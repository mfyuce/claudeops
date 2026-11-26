//! Zaman aşımlı alt süreç (`subprocess.run(..., capture_output=True, timeout=)`).
//!
//! Sahiplik: başlatılan her çocuk [`ChildGuard`] içindedir; hangi yoldan çıkılırsa çıkılsın (zaman aşımı, hata, panik)
//! `Drop` öldürür ve `wait` ile biçer (zombi kalmaz). Crate'te süreç öldürmenin TEK yeri burasıdır ve yalnız kendi
//! başlattığı çocuğa (ve onun kendi süreç grubuna) uygulanır (`clippy.toml` `disallowed-methods`).
//!
//! Torun (birleştirme kapısı): [`run`] çocuğu `process_group(0)` ile AYRI bir süreç grubunda başlatır ve grubun gerçekten
//! kurulduğunu (`getpgid(çocuk) == çocuk`, grup 0/1 ya da bizim grubumuz değil) doğrular; çocuk zaman aşımında ya da
//! hatada öldürülürken bu grup da `SIGKILL` alır (stdout'u tutan torun dahil). Doğrulanamazsa yalnız çocuk öldürülür.
//! stdout iş parçacığı olmadan, son tarihe kadar `poll` ile okunur: gruptan kaçan (`setsid`) bir torun boruyu tutsa bile
//! çağrı sürede döner, sızan okuyucu yoktur. Başarılı çıkışta torunlara dokunulmaz (Python `subprocess.run` gibi).

use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::process::{Child, ChildStdout, Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

/// Öldürülebilecek süreç grubu: yalnız çocuğun KENDİ grubu (`pgid == pid`), asla 0, 1 ya da bizim grubumuz.
fn safe_group(child: i32, pgid: i32, ours: i32) -> Option<i32> {
    (pgid == child && pgid > 1 && pgid != ours).then_some(pgid)
}

/// Kendi başlattığımız çocuk: düşerken (biçilmemişse) kill+wait; grubu doğrulandıysa önce grubu öldürür.
pub(crate) struct ChildGuard {
    child: Child,
    reaped: bool,
    group: Option<i32>,
}

impl ChildGuard {
    pub(crate) fn spawn(cmd: &mut Command) -> std::io::Result<Self> {
        Ok(ChildGuard {
            child: cmd.spawn()?,
            reaped: false,
            group: None,
        })
    }

    /// Çocuğu kendi süreç grubunda başlatır; grup ancak doğrulanırsa öldürülebilir olarak işaretlenir.
    pub(crate) fn spawn_group(cmd: &mut Command) -> std::io::Result<Self> {
        let mut g = ChildGuard::spawn(cmd.process_group(0))?;
        // `spawn` exec sonrası döner: setpgid çocukta exec'ten önce yapıldı. Çocuk biçilmediği için pid'i (ve grup
        // numarası) başka sürece geçemez.
        g.group = i32::try_from(g.id()).ok().and_then(|pid| {
            // SAFETY: yan etkisiz sorgular.
            let (pgid, ours) = unsafe { (libc::getpgid(pid), libc::getpgrp()) };
            safe_group(pid, pgid, ours)
        });
        Ok(g)
    }

    pub(crate) fn id(&self) -> u32 {
        self.child.id()
    }

    fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> {
        let st = self.child.try_wait()?;
        self.reaped |= st.is_some();
        Ok(st)
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if !self.reaped {
            if let Some(g) = self.group {
                // Yalnız `spawn_group`un doğruladığı, çocuğun kendi grubu (çocuk henüz biçilmedi: numara bize ait).
                #[allow(clippy::disallowed_methods)]
                // SAFETY: sinyal gönderimi; `g` > 1 ve bizim grubumuz değil (`safe_group`).
                let _ = unsafe { libc::killpg(g, libc::SIGKILL) };
            }
            // Yalnız kendi çocuğumuz; zaten çıkmışsa kill hata döner, wait yine biçer.
            #[allow(clippy::disallowed_methods)]
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

/// Boruyu EOF'a ya da son tarihe kadar okur (iş parçacığı yok). Süre dolarsa ya da hata olursa `None`.
fn read_until(mut pipe: ChildStdout, deadline: Instant) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    let mut chunk = [0u8; 65536];
    loop {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return None;
        }
        let ms = i32::try_from(left.as_millis().max(1)).unwrap_or(i32::MAX);
        let mut pfd = libc::pollfd {
            fd: pipe.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: tek geçerli pollfd.
        let r = unsafe { libc::poll(&mut pfd, 1, ms) };
        if r < 0 {
            if std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return None;
        }
        if r == 0 {
            continue; // son tarih döngü başında denetlenir
        }
        match pipe.read(&mut chunk) {
            Ok(0) => return Some(out),
            Ok(n) => out.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
            Err(_) => return None,
        }
    }
}

/// Çıkış durumu ve stdout; başlatılamazsa ya da süre dolarsa (süreç ve kendi grubu öldürülür) `None`.
pub(crate) fn run(cmd: Command, timeout: Duration) -> Option<(ExitStatus, Vec<u8>)> {
    run_observed(cmd, timeout, |_| {})
}

/// [`run`]; `spawned` çocuğun pid'iyle çağrılır (testler biçildiğini doğrular).
#[doc(hidden)]
pub fn run_observed(mut cmd: Command, timeout: Duration, spawned: impl FnOnce(u32)) -> Option<(ExitStatus, Vec<u8>)> {
    let deadline = Instant::now() + timeout;
    let mut child = ChildGuard::spawn_group(cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())).ok()?;
    spawned(child.id());
    let pipe = child.child.stdout.take()?;
    let out = read_until(pipe, deadline)?; // `child` düşer: grup + çocuk kill, wait
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some((status, out)),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(2)),
            _ => return None, // `child` düşer: kill+wait
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sh(s: &str) -> Command {
        let mut c = Command::new("sh");
        c.args(["-c", s]);
        c
    }

    #[test]
    fn output_status_and_timeout() {
        let (st, out) = run(sh("echo hi; exit 3"), Duration::from_secs(5)).unwrap();
        assert_eq!((st.code(), out.as_slice()), (Some(3), b"hi\n".as_slice()));
        let t = Instant::now();
        assert!(run(sh("exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(run(sh("exec >&-; exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(t.elapsed() < Duration::from_secs(3));
        assert!(run(Command::new("/nonexistent/x"), Duration::from_secs(1)).is_none());
    }

    #[test]
    fn group_kill_only_for_childs_own_verified_group() {
        assert_eq!(safe_group(500, 500, 10), Some(500));
        assert_eq!(safe_group(500, 10, 10), None, "çocuk bizim grubumuzda: grup kurulmadı");
        assert_eq!(safe_group(500, 0, 10), None);
        assert_eq!(safe_group(1, 1, 10), None);
        assert_eq!(safe_group(500, 501, 10), None);
        assert_eq!(safe_group(500, -1, 10), None, "getpgid hatası");
        assert_eq!(safe_group(10, 10, 10), None, "kendi grubumuz asla");
        // gerçek çocuk: ayrı grup kuruldu ve doğrulandı
        let g = ChildGuard::spawn_group(sh("exec sleep 30").stdin(Stdio::null())).unwrap();
        assert_eq!(g.group, i32::try_from(g.id()).ok());
        let plain = ChildGuard::spawn(sh("exec sleep 30").stdin(Stdio::null())).unwrap();
        assert_eq!(plain.group, None);
    }

    #[test]
    fn guard_reaps_on_drop() {
        let mut c = sh("exec sleep 30");
        let g = ChildGuard::spawn(c.stdin(Stdio::null())).unwrap();
        let pid = g.id();
        let start = |pid: u32| {
            let raw = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
            crate::procfs::parse_stat(&raw).map(|s| s.starttime)
        };
        let before = start(pid).unwrap();
        drop(g);
        // biçilmiş çocuğun /proc girdisi kalmaz (zombi olsaydı `State: Z` ile dururdu); pid yeniden kullanıldıysa başka süreç
        assert_ne!(start(pid), Some(before));
    }
}
