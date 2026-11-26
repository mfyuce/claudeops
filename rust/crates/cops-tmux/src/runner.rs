use std::ffi::{OsStr, OsString};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use crate::TmuxError;

/// claudeops'un ayrı tmux soketi.
pub const TMUX_SOCKET: &str = "cops";

/// Python `_TIMEOUT`.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(5);

/// `-t` hedefini TAM eşleşmeye zorlar (Python `_exact`). `=ad` tek başına yalnız oturum hedefli komutlarda çalışır;
/// pane hedefli komutlar (`capture-pane`, `send-keys`, `list-panes`, `display-message`) sondaki `:` ister.
///
/// Python gibi hiçbir adı reddetmez. Bilinen açıklar (docs/rs-tmux.md, "Python hatası?"): boş ad, `$N` ve `:` içeren
/// ad tmux'ta BAŞKA bir oturuma çözülebilir.
pub fn exact_target(name: &str) -> String {
    format!("={name}:")
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
        let deadline = Instant::now() + timeout;
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
        // Borular ayrı iş parçacıklarında: büyük girdi/çıktı süre sınırını kilitlemesin.
        if let (Some(data), Some(mut pipe)) = (input, child.stdin.take()) {
            let data = data.to_vec();
            // Yazım hatası (tmux erken çıktı) çıkış kodunda zaten görünür.
            thread::spawn(move || {
                let _ = pipe.write_all(&data);
            });
        }
        let stdout = drain(child.stdout.take());
        let stderr = drain(child.stderr.take());
        let (Some(out), Some(err)) = (receive(&stdout, deadline), receive(&stderr, deadline))
        else {
            kill(&mut child);
            return Err(TmuxError::Timeout);
        };
        let status = loop {
            if let Some(status) = child.try_wait()? {
                break status;
            }
            if Instant::now() >= deadline {
                kill(&mut child);
                return Err(TmuxError::Timeout);
            }
            thread::sleep(Duration::from_millis(1));
        };
        if !status.success() {
            return Err(TmuxError::Failed {
                code: status.code(),
                stderr: String::from_utf8_lossy(&err?).into_owned(),
            });
        }
        Ok(Output { stdout: out? })
    }
}

type Drained = mpsc::Receiver<std::io::Result<Vec<u8>>>;

fn drain<R: Read + Send + 'static>(pipe: Option<R>) -> Drained {
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut buf = Vec::new();
        let res = match pipe {
            Some(mut p) => p.read_to_end(&mut buf).map(|_| buf),
            None => Ok(buf),
        };
        let _ = tx.send(res);
    });
    rx
}

/// `None` = süre doldu.
fn receive(rx: &Drained, deadline: Instant) -> Option<Result<Vec<u8>, TmuxError>> {
    let left = deadline.saturating_duration_since(Instant::now());
    rx.recv_timeout(left)
        .ok()
        .map(|r| r.map_err(TmuxError::from))
}

/// Yalnız KENDİ başlattığımız tmux istemci süreci (sunucu ya da pane süreci değil).
fn kill(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_target_wraps_any_name_like_python() {
        assert_eq!(exact_target("dccl20260917"), "=dccl20260917:");
        assert_eq!(exact_target("we'ird name;"), "=we'ird name;:");
        assert_eq!(exact_target(""), "=:");
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
        // Paralel testlerin fork'u yazılan betiği kısa süre açık tutabilir (ETXTBSY): yeniden dene.
        let err = loop {
            match t.run(&["ls"]) {
                Err(TmuxError::Io(e)) if e.raw_os_error() == Some(libc::ETXTBSY) => continue,
                other => break other.err(),
            }
        };
        assert!(matches!(err, Some(TmuxError::Timeout)), "{err:?}");
        assert!(start.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn missing_program_is_io_error() {
        let t = Tmux::with_socket("x").program("/nonexistent/tmux");
        assert!(matches!(t.run(&["ls"]), Err(TmuxError::Io(_))));
    }
}
