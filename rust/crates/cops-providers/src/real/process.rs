//! Alt süreç koşucusu: kabuk YOK, stdin boş, TOPLAM süre sınırı (`Instant` = `CLOCK_MONOTONIC`), sınırlı boru okuma,
//! ayrı süreç grubu, her çıkış yolunda öldür + bekle. İş parçacığı açılmaz: borular `poll` ile tek yerden boşaltılır.
//!
//! Python `subprocess.run(timeout=..)` farkı: zaman aşımında Python yalnız doğrudan çocuğu öldürür; burada çocuğun
//! süreç grubu (torunlar dahil) öldürülür.

use crate::real::Env;
use std::io::{self, Read};
use std::os::fd::{AsRawFd, RawFd};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Bir çıktı akışının nasıl toplanacağı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Capture {
    /// `/dev/null`.
    Discard,
    /// En çok bu kadar bayt; aşılırsa [`RunError::Overflow`].
    Bounded(u64),
    /// Hep okunur, yalnız SON bu kadar bayt tutulur.
    Tail(usize),
}

#[derive(Debug, Clone, Copy)]
pub struct Spec<'a> {
    /// `argv[0]` eğik çizgisizse `PATH`te aranır.
    pub argv: &'a [String],
    pub cwd: Option<&'a str>,
    pub env: &'a Env,
    pub timeout: Duration,
    pub stdout: Capture,
    pub stderr: Capture,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Output {
    /// Python `returncode`: sinyalle bitişte eksi sinyal numarası.
    pub code: i32,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

#[derive(Debug)]
pub enum RunError {
    /// Başlatılamadı (boş argv dahil).
    Spawn(io::Error),
    Timeout,
    Overflow,
    Io(io::Error),
}

/// Çocuk beklenmeden bırakılırsa (hata, panik) süreç grubunu öldürür ve bekler.
struct Guard {
    child: Child,
    reaped: bool,
}

impl Drop for Guard {
    fn drop(&mut self) {
        if self.reaped {
            return;
        }
        // Çocuk henüz beklenmedi: kimliği (ve grup kimliği) yeniden kullanılamaz, sinyal yalnız bizim sürecimize gider.
        if let Ok(pid) = libc::pid_t::try_from(self.child.id()) {
            if pid > 1 {
                // SAFETY: yalnız `kill` sistem çağrısı; negatif kimlik, bu koşucunun açtığı süreç grubudur.
                unsafe { libc::kill(-pid, libc::SIGKILL) };
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

struct Stream {
    pipe: Option<Box<dyn Read>>,
    fd: RawFd,
    capture: Capture,
    data: Vec<u8>,
}

impl Stream {
    fn new<R: Read + AsRawFd + 'static>(pipe: Option<R>, capture: Capture) -> io::Result<Stream> {
        let fd = pipe.as_ref().map_or(-1, AsRawFd::as_raw_fd);
        if fd >= 0 {
            // SAFETY: `fd` az önce alınan, bu yapının sahip olduğu boru ucudur.
            let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
            // SAFETY: aynı tanıtıcı; yalnız `O_NONBLOCK` eklenir.
            if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0
            {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(Stream {
            pipe: pipe.map(|p| Box::new(p) as Box<dyn Read>),
            fd,
            capture,
            data: Vec::new(),
        })
    }

    /// Hazır veriyi okur (en çok bir parça: süre denetimi aç kalmasın).
    fn drain(&mut self) -> Result<(), RunError> {
        let Some(pipe) = self.pipe.as_mut() else {
            return Ok(());
        };
        let mut buf = [0u8; 65536];
        match pipe.read(&mut buf) {
            Ok(0) => self.pipe = None,
            Ok(n) => {
                self.data.extend_from_slice(&buf[..n]);
                match self.capture {
                    Capture::Bounded(max) if self.data.len() as u64 > max => {
                        return Err(RunError::Overflow)
                    }
                    Capture::Tail(keep) if self.data.len() > keep => {
                        self.data.drain(..self.data.len() - keep);
                    }
                    _ => {}
                }
            }
            Err(e)
                if matches!(
                    e.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) => {}
            Err(e) => return Err(RunError::Io(e)),
        }
        Ok(())
    }
}

fn stdio(capture: Capture) -> Stdio {
    match capture {
        Capture::Discard => Stdio::null(),
        _ => Stdio::piped(),
    }
}

/// Süreci koşturur. Başarı = süreç bitti VE yakalanan borular kapandı (Python `communicate` gibi: boruyu açık tutan
/// torun süre sınırına yol açar). Çıkış kodu çağırana kalır.
pub fn run(spec: &Spec<'_>) -> Result<Output, RunError> {
    let Some((program, args)) = spec.argv.split_first() else {
        return Err(RunError::Spawn(io::Error::from_raw_os_error(libc::ENOENT)));
    };
    let mut cmd = Command::new(program);
    cmd.args(args)
        .stdin(Stdio::null())
        .stdout(stdio(spec.stdout))
        .stderr(stdio(spec.stderr))
        .process_group(0);
    if let Some(cwd) = spec.cwd {
        cmd.current_dir(cwd);
    }
    spec.env.apply(&mut cmd);
    let deadline = Instant::now().checked_add(spec.timeout);
    let mut guard = Guard {
        child: cmd.spawn().map_err(RunError::Spawn)?,
        reaped: false,
    };
    let mut out = Stream::new(guard.child.stdout.take(), spec.stdout).map_err(RunError::Io)?;
    let mut err = Stream::new(guard.child.stderr.take(), spec.stderr).map_err(RunError::Io)?;
    let mut nap = Duration::from_micros(200);
    loop {
        let left = deadline.map_or(Duration::from_secs(3600), |d| {
            d.saturating_duration_since(Instant::now())
        });
        if out.pipe.is_none() && err.pipe.is_none() {
            if let Some(status) = guard.child.try_wait().map_err(RunError::Io)? {
                guard.reaped = true;
                let code = status
                    .code()
                    .unwrap_or_else(|| -status.signal().unwrap_or(0));
                return Ok(Output {
                    code,
                    stdout: out.data,
                    stderr: err.data,
                });
            }
            if left.is_zero() {
                return Err(RunError::Timeout);
            }
            std::thread::sleep(nap.min(left));
            nap = (nap * 2).min(Duration::from_millis(10));
            continue;
        }
        if left.is_zero() {
            return Err(RunError::Timeout);
        }
        // kapanan akışın tanıtıcısı -1 olur (`poll` yok sayar)
        let mut fds = [&out, &err].map(|s| libc::pollfd {
            fd: if s.pipe.is_some() { s.fd } else { -1 },
            events: libc::POLLIN,
            revents: 0,
        });
        let wait_ms = i32::try_from(left.as_millis().clamp(1, 1000)).unwrap_or(1000);
        // SAFETY: `fds` iki öğeli geçerli bir dizi; sayı doğru veriliyor.
        let ready = unsafe { libc::poll(fds.as_mut_ptr(), 2, wait_ms) };
        if ready < 0 {
            let e = io::Error::last_os_error();
            if e.kind() != io::ErrorKind::Interrupted {
                return Err(RunError::Io(e));
            }
            continue;
        }
        if fds[0].revents != 0 {
            out.drain()?;
        }
        if fds[1].revents != 0 {
            err.drain()?;
        }
    }
}
