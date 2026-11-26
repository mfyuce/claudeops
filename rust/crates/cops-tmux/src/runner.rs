use std::ffi::{OsStr, OsString};
use std::io::{ErrorKind, Read, Write};
use std::os::fd::{AsRawFd, RawFd};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use crate::diag::{swallow, Swallowed};
use crate::TmuxError;

/// claudeops'un ayrı tmux soketi.
pub const TMUX_SOCKET: &str = "cops";

/// Python `_TIMEOUT`.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(5);

/// `-t` hedefini TAM eşleşmeye zorlar (Python `_exact`). `=ad` tek başına yalnız oturum hedefli komutlarda çalışır;
/// pane hedefli komutlar (`capture-pane`, `send-keys`, `list-panes`, `display-message`) sondaki `:` ister.
///
/// [`addressable`] olmayan ad `BadArgument("name")`: tmux onu BAŞKA bir oturuma çözer (TBD#366 P1-P3); çağıran işlev
/// hiçbir tmux komutu çalıştırmadan döner.
pub fn exact_target(name: &str) -> Result<String, TmuxError> {
    if !addressable(name) {
        return Err(TmuxError::BadArgument("name"));
    }
    Ok(format!("={name}:"))
}

/// `=ad:` hedefi tmux'ta YALNIZ bu oturuma çözülür mü (Python `_addressable`; tmux 3.2a ölçümü): boş ad (`=:` en son
/// oturum), `$` ile başlayan ad (`=$0:` oturum KİMLİĞİ) ve `:` içeren ad (`=zeta:0:` display-message'ta zeta; tmux
/// adlarda `:` bırakmaz) başka oturumu hedefler.
pub fn addressable(name: &str) -> bool {
    !name.is_empty() && !name.starts_with('$') && !name.contains(':')
}

/// `;` ile biten argv elemanını literal yapar (`\;`; tmux ters bölüyü soyar). Diğer metin aynen kalır.
pub fn escape_arg(arg: &str) -> String {
    match arg.strip_suffix(';') {
        Some(head) => format!(r"{head}\;"),
        None => arg.to_string(),
    }
}

/// Bir tmux sunucusuna (soket adıyla) bağlanan istemci.
#[derive(Debug, Clone)]
pub struct Tmux {
    socket: String,
    program: OsString,
    tmpdir: Option<PathBuf>,
    pub(crate) timeout: Duration,
}

/// Bir süreç çevresi (tamamı: miras alınan çevrenin yerine geçer).
pub(crate) type Env = [(OsString, OsString)];

pub(crate) struct Call<'a> {
    pub utf8: bool,
    pub args: &'a [&'a str],
    pub input: Option<&'a [u8]>,
    pub env: Option<&'a Env>,
}

impl<'a> Call<'a> {
    pub fn new(args: &'a [&'a str]) -> Self {
        Self {
            utf8: false,
            args,
            input: None,
            env: None,
        }
    }
}

pub(crate) struct Output {
    pub stdout: Vec<u8>,
}

impl Output {
    /// Python `subprocess.run(text=True)` ile aynı: UTF-8 çözme + evrensel satır sonu (`\r\n`, `\r` -> `\n`).
    pub fn text(self) -> Result<String, TmuxError> {
        let s = String::from_utf8(self.stdout).map_err(|_| TmuxError::BadOutput)?;
        if s.contains('\r') {
            Ok(s.replace("\r\n", "\n").replace('\r', "\n"))
        } else {
            Ok(s)
        }
    }
}

impl Tmux {
    /// Canlı filonun soketi (`tmux -L cops`).
    pub fn cops() -> Self {
        Self::with_socket(TMUX_SOCKET)
    }

    pub fn with_socket(socket: impl Into<String>) -> Self {
        Self {
            socket: socket.into(),
            program: "tmux".into(),
            tmpdir: None,
            timeout: DEFAULT_TIMEOUT,
        }
    }

    /// Soket dizinini (`TMUX_TMPDIR`) değiştirir; testlerin kullanıcının sunucusundan yalıtımı için.
    pub fn tmpdir(mut self, dir: impl Into<PathBuf>) -> Self {
        self.tmpdir = Some(dir.into());
        self
    }

    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// tmux ikilisinin yolu (varsayılan `PATH`teki `tmux`).
    pub fn program(mut self, program: impl AsRef<OsStr>) -> Self {
        self.program = program.as_ref().to_os_string();
        self
    }

    pub fn socket(&self) -> &str {
        &self.socket
    }

    /// Python `_base_argv`.
    pub fn base_argv(&self) -> Vec<String> {
        vec!["tmux".into(), "-L".into(), self.socket.clone()]
    }

    fn command(&self, utf8: bool, env: Option<&Env>) -> Command {
        let mut cmd = Command::new(&self.program);
        if let Some(env) = env {
            cmd.env_clear().envs(env.iter().map(|(k, v)| (k, v)));
        }
        if utf8 {
            cmd.arg("-u");
        }
        cmd.arg("-L").arg(&self.socket);
        if let Some(dir) = &self.tmpdir {
            cmd.env("TMUX_TMPDIR", dir);
        }
        cmd
    }

    /// tmux'u çalıştırır; yalnız çıkış kodu 0 ise `Ok`.
    pub(crate) fn run(&self, args: &[&str]) -> Result<Output, TmuxError> {
        self.exec(Call::new(args), self.timeout)
    }

    /// [`Tmux::run`] + Python `text=True` çözümü.
    pub(crate) fn text(&self, args: &[&str]) -> Result<String, TmuxError> {
        self.run(args)?.text()
    }

    /// Yalnız Python karşılığı OLMAYAN liste sorguları için `-u`: UTF-8 olmayan yerelde `-F` çıktısındaki sekme ve
    /// Türkçe harfler `_` olur. `-u` ASLA sunucu başlatan komuta verilmez (sunucu argv'sini [`Tmux::is_tmux_backed`]
    /// okur).
    pub(crate) fn text_utf8(&self, args: &[&str]) -> Result<String, TmuxError> {
        self.exec(
            Call {
                utf8: true,
                ..Call::new(args)
            },
            self.timeout,
        )?
        .text()
    }

    pub(crate) fn exec(&self, call: Call<'_>, timeout: Duration) -> Result<Output, TmuxError> {
        let Call {
            utf8,
            args,
            input,
            env,
        } = call;
        let deadline = Instant::now() + timeout.min(MAX_TIMEOUT);
        let mut child = self
            .command(utf8, env)
            .args(args)
            .stdin(if input.is_some() {
                Stdio::piped()
            } else {
                Stdio::null()
            })
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let io = match communicate(&mut child, input.unwrap_or(&[]), deadline) {
            Ok(io) => io,
            Err(e) => {
                kill(child);
                return Err(e);
            }
        };
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(1)),
                Ok(None) => {
                    kill(child);
                    return Err(TmuxError::Timeout);
                }
                Err(e) => {
                    kill(child);
                    return Err(e.into());
                }
            }
        };
        if !status.success() {
            if let Some(e) = &io.write_err {
                // Asıl sonuç tmux'un hatası; girdinin yarım kalması onun sonucu.
                swallow(Swallowed::StdinWrite, e);
            }
            return Err(TmuxError::Failed {
                code: status.code(),
                stderr: String::from_utf8_lossy(&io.stderr).into_owned(),
            });
        }
        // tmux "oldu" dedi ama girdinin tamamını almadı: yarım tamponu başarı sayma (kapalı yön).
        if let Some(e) = io.write_err {
            return Err(e.into());
        }
        Ok(Output { stdout: io.stdout })
    }
}

/// Bir çağrının en uzun süresi: daha uzun istenen süre buna kırpılır (`Instant` taşması panik atmasın).
pub const MAX_TIMEOUT: Duration = Duration::from_secs(3600);

/// Öldürülen tmux istemcisinin toplanması için bekleme; aşılırsa arka planda beklenir (zombi kalmaz).
pub const REAP_GRACE: Duration = Duration::from_secs(1);

/// Okuma tamponu (tur başına fd başına tek okuma: sonsuz çıktı süre sınırını aşamaz).
const CHUNK: usize = 64 * 1024;

struct Collected {
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    write_err: Option<std::io::Error>,
}

fn set_nonblocking(fd: RawFd) -> std::io::Result<()> {
    // SAFETY: `fd` çağıranın sahip olduğu açık bir boru ucu; fcntl yalnız bayrak okur/yazar.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

/// Girdiyi yazar, iki çıktıyı EOF'a dek okur; hepsi TEK iş parçacığında `poll` ile, `deadline`a dek. İş parçacığı
/// açılmaz: süre dolunca borular burada kapanır (torun süreç boruyu açık tutsa bile hiçbir şey geride kalmaz).
fn communicate(child: &mut Child, input: &[u8], deadline: Instant) -> Result<Collected, TmuxError> {
    let mut stdin = child.stdin.take();
    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();
    let fds = [
        stdin.as_ref().map(AsRawFd::as_raw_fd),
        stdout.as_ref().map(AsRawFd::as_raw_fd),
        stderr.as_ref().map(AsRawFd::as_raw_fd),
    ];
    for fd in fds.into_iter().flatten() {
        set_nonblocking(fd)?;
    }
    if input.is_empty() {
        stdin = None;
    }
    let mut io = Collected {
        stdout: Vec::new(),
        stderr: Vec::new(),
        write_err: None,
    };
    let mut written = 0;
    let mut buf = vec![0u8; CHUNK];
    loop {
        let mut polled: Vec<libc::pollfd> = Vec::with_capacity(3);
        if let Some(p) = &stdin {
            polled.push(pollfd(p.as_raw_fd(), libc::POLLOUT));
        }
        for p in [
            stdout.as_ref().map(AsRawFd::as_raw_fd),
            stderr.as_ref().map(AsRawFd::as_raw_fd),
        ]
        .into_iter()
        .flatten()
        {
            polled.push(pollfd(p, libc::POLLIN));
        }
        if polled.is_empty() {
            return Ok(io);
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(TmuxError::Timeout);
        }
        let ms = i32::try_from(left.as_millis().max(1)).unwrap_or(i32::MAX);
        // SAFETY: `polled` geçerli, uzunluğu doğru verilen bir dizi; fd'ler bu işlev boyunca açık.
        let n = unsafe { libc::poll(polled.as_mut_ptr(), polled.len() as libc::nfds_t, ms) };
        if n < 0 {
            let e = std::io::Error::last_os_error();
            if e.kind() == ErrorKind::Interrupted {
                continue;
            }
            return Err(e.into());
        }
        let ready = |fd: Option<RawFd>| {
            fd.is_some_and(|fd| polled.iter().any(|p| p.fd == fd && p.revents != 0))
        };
        if ready(stdin.as_ref().map(AsRawFd::as_raw_fd)) {
            if let Some(pipe) = stdin.as_mut() {
                match pipe.write(&input[written..]) {
                    Ok(0) => {
                        io.write_err = Some(ErrorKind::WriteZero.into());
                        stdin = None;
                    }
                    Ok(k) => {
                        written += k;
                        if written == input.len() {
                            // Kapatma = EOF: tmux girdinin bittiğini görür.
                            stdin = None;
                        }
                    }
                    Err(e)
                        if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::Interrupted) => {}
                    Err(e) => {
                        io.write_err = Some(e);
                        stdin = None;
                    }
                }
            }
        }
        if ready(stdout.as_ref().map(AsRawFd::as_raw_fd))
            && read_some(&mut stdout, &mut buf, &mut io.stdout)?
        {
            stdout = None;
        }
        if ready(stderr.as_ref().map(AsRawFd::as_raw_fd))
            && read_some(&mut stderr, &mut buf, &mut io.stderr)?
        {
            stderr = None;
        }
    }
}

fn pollfd(fd: RawFd, events: libc::c_short) -> libc::pollfd {
    libc::pollfd {
        fd,
        events,
        revents: 0,
    }
}

/// Tek okuma. `Ok(true)` = EOF.
fn read_some<R: Read>(
    pipe: &mut Option<R>,
    buf: &mut [u8],
    out: &mut Vec<u8>,
) -> Result<bool, TmuxError> {
    let Some(p) = pipe.as_mut() else {
        return Ok(true);
    };
    match p.read(buf) {
        Ok(0) => Ok(true),
        Ok(k) => {
            out.extend_from_slice(&buf[..k]);
            Ok(false)
        }
        Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::Interrupted) => Ok(false),
        Err(e) => Err(e.into()),
    }
}

/// [`kill`]in süreçten istediği üç işlem; testler toplanamayan (D durumundaki) süreci sahtesiyle kurar.
trait Reapable {
    fn kill(&mut self) -> std::io::Result<()>;
    /// `true` = süreç toplandı.
    fn try_reap(&mut self) -> std::io::Result<bool>;
    fn reap(&mut self) -> std::io::Result<()>;
}

impl Reapable for Child {
    fn kill(&mut self) -> std::io::Result<()> {
        Child::kill(self)
    }
    fn try_reap(&mut self) -> std::io::Result<bool> {
        Ok(self.try_wait()?.is_some())
    }
    fn reap(&mut self) -> std::io::Result<()> {
        self.wait().map(drop)
    }
}

/// Yalnız KENDİ başlattığımız tmux istemci süreci (sunucu ya da pane süreci değil): SIGKILL + toplama. Toplama
/// [`REAP_GRACE`]i aşarsa arka plan iş parçacığı bekler; çağıran bloklanmaz, zombi kalmaz.
fn kill<C: Reapable + Send + 'static>(mut child: C) {
    if let Err(e) = child.kill() {
        swallow(Swallowed::KillChild, &e);
    }
    let until = Instant::now() + REAP_GRACE;
    loop {
        match child.try_reap() {
            Ok(true) => return,
            Ok(false) if Instant::now() < until => thread::sleep(Duration::from_millis(1)),
            Ok(false) => break,
            Err(e) => {
                swallow(Swallowed::ReapChild, &e);
                return;
            }
        }
    }
    swallow(Swallowed::ReapChild, &"süre doldu, arka planda bekleniyor");
    let reaper = thread::Builder::new()
        .name("cops-tmux-reap".into())
        .spawn(move || {
            if let Err(e) = child.reap() {
                swallow(Swallowed::ReapChild, &e);
            }
        });
    if let Err(e) = reaper {
        swallow(Swallowed::ReapChild, &e);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_target_wraps_any_name_like_python() {
        assert_eq!(exact_target("dccl20260917").unwrap(), "=dccl20260917:");
        assert_eq!(exact_target("we'ird name;").unwrap(), "=we'ird name;:");
        for name in ["=eq", "@1", "%1", "a.b"] {
            assert_eq!(exact_target(name).unwrap(), format!("={name}:"));
        }
    }

    #[test]
    fn exact_target_refuses_names_tmux_resolves_to_another_session() {
        for name in ["", "$0", "$x", "zeta:0", "alpha:0.0", "a:b"] {
            assert!(!addressable(name), "{name:?}");
            assert!(
                matches!(exact_target(name), Err(TmuxError::BadArgument("name"))),
                "{name:?}"
            );
        }
        assert_eq!(Tmux::cops().base_argv(), ["tmux", "-L", "cops"]);
    }

    #[test]
    fn escape_only_trailing_semicolon() {
        assert_eq!(escape_arg("foo;"), r"foo\;");
        assert_eq!(escape_arg(r"bar\;"), r"bar\\;");
        assert_eq!(escape_arg(";"), r"\;");
        assert_eq!(escape_arg("a;b"), "a;b");
        assert_eq!(escape_arg(""), "");
    }

    #[test]
    fn universal_newlines_like_python_text_mode() {
        let out = Output {
            stdout: b"a\r\nb\rc\n".to_vec(),
        };
        assert_eq!(out.text().unwrap(), "a\nb\nc\n");
        assert!(matches!(
            Output { stdout: vec![0xff] }.text(),
            Err(TmuxError::BadOutput)
        ));
    }

    #[test]
    fn hung_program_times_out() {
        let dir = tempfile::tempdir().unwrap();
        let fake = dir.path().join("tmux");
        std::fs::write(&fake, "#!/bin/sh\nexec sleep 30\n").unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        let t = Tmux::with_socket("x")
            .program(&fake)
            .timeout(Duration::from_millis(200));
        let start = Instant::now();
        // Paralel testlerin fork'u yazılan betiği kısa süre açık tutabilir (ETXTBSY): sınırlı yeniden deneme.
        let mut err = None;
        for _ in 0..200 {
            match t.run(&["ls"]) {
                Err(TmuxError::Io(e)) if e.raw_os_error() == Some(libc::ETXTBSY) => {
                    thread::sleep(Duration::from_millis(5));
                }
                other => {
                    err = other.err();
                    break;
                }
            }
        }
        assert!(matches!(err, Some(TmuxError::Timeout)), "{err:?}");
        assert!(start.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn huge_timeout_is_clamped_not_a_panic() {
        // `Instant + Duration::MAX` taşardı.
        let t = Tmux::with_socket("x")
            .program("/bin/true")
            .timeout(Duration::MAX);
        assert!(t.run(&["ls"]).is_ok());
        let zero = Tmux::with_socket("x")
            .program("/bin/true")
            .timeout(Duration::ZERO);
        assert!(matches!(zero.run(&["ls"]), Err(TmuxError::Timeout)));
    }

    #[test]
    fn missing_program_is_io_error() {
        let t = Tmux::with_socket("x").program("/nonexistent/tmux");
        assert!(matches!(t.run(&["ls"]), Err(TmuxError::Io(_))));
    }

    /// Asla toplanmayan süreç: kill ve (isteğe göre) try_reap hata verir, bekleyen `reap` kanala haber verir.
    struct Stuck {
        try_fails: bool,
        reaped: std::sync::mpsc::Sender<String>,
    }

    impl Reapable for Stuck {
        fn kill(&mut self) -> std::io::Result<()> {
            Err(std::io::Error::other("sahte kill"))
        }
        fn try_reap(&mut self) -> std::io::Result<bool> {
            if self.try_fails {
                return Err(std::io::Error::other("sahte try_wait"));
            }
            Ok(false)
        }
        fn reap(&mut self) -> std::io::Result<()> {
            let name = thread::current().name().unwrap_or("").to_string();
            self.reaped.send(name).map_err(std::io::Error::other)
        }
    }

    #[test]
    fn unreapable_child_is_counted_and_waited_in_background() {
        use crate::swallowed_count;
        let kills = swallowed_count(Swallowed::KillChild);
        let reaps = swallowed_count(Swallowed::ReapChild);
        let (tx, rx) = std::sync::mpsc::channel();
        let start = Instant::now();
        kill(Stuck {
            try_fails: false,
            reaped: tx,
        });
        assert!(start.elapsed() >= REAP_GRACE);
        assert!(start.elapsed() < REAP_GRACE + Duration::from_secs(5));
        let waiter = rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(waiter, "cops-tmux-reap");
        assert!(swallowed_count(Swallowed::KillChild) > kills);
        assert!(swallowed_count(Swallowed::ReapChild) > reaps);

        // try_wait hatası: sayılır, arka plan toplayıcısı açılmaz.
        let reaps = swallowed_count(Swallowed::ReapChild);
        let (tx, rx) = std::sync::mpsc::channel();
        kill(Stuck {
            try_fails: true,
            reaped: tx,
        });
        assert!(rx.recv_timeout(Duration::from_secs(5)).is_err());
        assert!(swallowed_count(Swallowed::ReapChild) > reaps);
    }
}
