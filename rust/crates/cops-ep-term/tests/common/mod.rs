//! Ortak test ortamı. Durum: geçici kök (`TestEnv`) altında `state/` (CLAUDEOPS_DIR) ve `home/` (HOME). tmux: geçici
//! `TMUX_TMPDIR` + benzersiz soket adı + `-f /dev/null`; her çağrı soketi açıkça verir, `TMUX` ortamı silinir, `Drop`ta
//! YALNIZ kendi sunucusu kapatılır. Kullanıcının tmux sunucusuna ve `-L cops` soketine dokunulmaz.
#![allow(dead_code)]
use cops_state::{Backend, StateDir, StateDocs, TestEnv};
use cops_tmux::Tmux;
use std::io::Write;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub struct Env {
    _tmp: TestEnv,
    pub root: PathBuf,
    pub state: PathBuf,
    pub home: PathBuf,
}

impl Env {
    pub fn new() -> Env {
        let tmp = TestEnv::new().unwrap();
        let root = tmp.root().to_path_buf();
        let state = tmp.dir().root().to_path_buf();
        let home = root.join("home");
        std::fs::create_dir_all(&home).unwrap();
        Env {
            _tmp: tmp,
            root,
            state,
            home,
        }
    }
    pub fn dir(&self) -> StateDir {
        StateDir::at(&self.state)
    }
    pub fn ro(&self, b: Backend) -> StateDocs {
        StateDocs::isolated(self.dir(), Some(b), "").into_read_only()
    }
    pub fn write(&self, rel: &str, data: impl AsRef<[u8]>) {
        let p = self.state.join(rel);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, data).unwrap();
    }
    /// Python alt süreci: geçici HOME/CLAUDEOPS_DIR, tmux soketi `T_SOCK` + `TMUX_TMPDIR` (Python `TMUX_SOCKET` yamalanır).
    pub fn py(&self, srv: Option<&Server>, code: &str, stdin: &str) -> String {
        let py = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../py")
            .canonicalize()
            .unwrap();
        let mut prelude = String::from("import sys, json, os\nsys.path.insert(0, sys.argv[1])\n");
        if srv.is_some() {
            prelude.push_str(
                "from claudeops import tmux_backend\nassert os.environ['T_SOCK'].startswith('cxet')\n\
                 tmux_backend.TMUX_SOCKET = os.environ['T_SOCK']\n",
            );
        }
        let userbase = std::env::var_os("PYTHONUSERBASE")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local")))
            .unwrap_or_default();
        let mut c = Command::new("python3");
        c.args(["-B", "-c", &format!("{prelude}{code}")])
            .arg(py)
            .env_clear()
            .env("PATH", std::env::var_os("PATH").unwrap_or_default())
            .env("LANG", "C.UTF-8")
            .env("HOME", &self.home)
            .env("CLAUDEOPS_DIR", &self.state)
            .env("CLAUDEOPS_EXTENSIONS", "")
            .env("PYTHONUSERBASE", userbase)
            .env("CLAUDEOPS_STORE_BACKEND", "files")
            .current_dir(&self.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(s) = srv {
            c.env("T_SOCK", s.tmux.socket())
                .env("TMUX_TMPDIR", s.path());
        }
        let mut child = c.spawn().expect("python3");
        child
            .stdin
            .take()
            .unwrap()
            .write_all(stdin.as_bytes())
            .unwrap();
        let o = child.wait_with_output().unwrap();
        assert!(
            o.status.success(),
            "python hata:\n{}",
            String::from_utf8_lossy(&o.stderr)
        );
        String::from_utf8(o.stdout).unwrap()
    }
}

/// Testin tmux sunucusu.
pub struct Server {
    pub tmux: Tmux,
    pub dir: tempfile::TempDir,
}

impl Server {
    pub fn new() -> Server {
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .subsec_nanos();
        let socket = format!(
            "cxet{nanos}-{}-{}",
            SEQ.fetch_add(1, Ordering::Relaxed),
            std::process::id()
        );
        let dir = tempfile::tempdir().unwrap();
        let tmux = Tmux::with_socket(socket).tmpdir(dir.path());
        Server { tmux, dir }
    }

    pub fn path(&self) -> &Path {
        self.dir.path()
    }

    /// Ham tmux. `-u` YOK: sunucu argv'si `tmux -L <soket>` ile başlamalı (`is_tmux_backed` buna bakar).
    pub fn raw(&self, args: &[&str]) -> String {
        let out = Command::new("tmux")
            .args(["-L", self.tmux.socket(), "-f", "/dev/null"])
            .args(args)
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "tmux {args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        String::from_utf8(out.stdout).unwrap()
    }

    /// `session` tmux oturumunda (100x30) `command` (kabuk satırı).
    pub fn spawn(&self, session: &str, command: &str) {
        self.raw(&[
            "new-session",
            "-d",
            "-s",
            session,
            "-x",
            "100",
            "-y",
            "30",
            command,
        ]);
    }

    pub fn screen(&self, session: &str) -> String {
        self.raw(&["capture-pane", "-p", "-t", &format!("={session}:")])
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", self.tmux.socket(), "kill-server"])
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output();
    }
}

pub fn wait_until(mut done: impl FnMut() -> bool, what: &str) {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !done() {
        assert!(Instant::now() < deadline, "beklenen durum oluşmadı: {what}");
        std::thread::sleep(Duration::from_millis(30));
    }
}

/// Durağan içerikli sahte CLI (pane zamanla DEĞİŞMEZ). argv: ad satır mod bayrak; bayrak `mask` (ICANON açık, ECHO kapalı:
/// getpass), `alt` (alternatif ekran), `-` (yok). Sonda `DONE` basar.
pub const FAKE_CLI: &str = r#"
import sys, time, termios
name, n, mode, flag = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
if flag == "alt":
    sys.stdout.write("\x1b[?1049h\x1b[H")
out = []
for i in range(n):
    out.append(f"\x1b[38;5;{i % 200}m{name} satır {i:04d}\x1b[0m çğüşıö https://example.test/{i}. yol ./src/{i}.rs ~/x/{i} /tmp/a{i}),")
out.append("\x1b[2m╭──────╮\x1b[0m")
if mode != "-":
    out.append(f"  \x1b[38;5;220m⏵⏵ {mode}\x1b[39m (shift+tab to cycle)")
out.append("DONE")
sys.stdout.write("\r\n".join(out))
sys.stdout.flush()
if flag == "mask":
    a = termios.tcgetattr(0)
    a[3] = (a[3] | termios.ICANON) & ~termios.ECHO
    termios.tcsetattr(0, termios.TCSANOW, a)
while True:
    time.sleep(3600)
"#;

pub fn fake_script(dir: &Path) -> PathBuf {
    let p = dir.join("fake_cli.py");
    std::fs::write(&p, FAKE_CLI).unwrap();
    p
}

/// Kabuk tek tırnağı.
pub fn sq(s: &str) -> String {
    format!("'{}'", s.replace('\'', r"'\''"))
}

/// tmux pane'inde çalışacak sahte CLI komutu: `cli` adıyla (`exec -a`) ve CLI'ın ad kuralıyla.
pub fn cli_command(
    script: &Path,
    cli: &str,
    name: &str,
    lines: usize,
    mode: &str,
    flag: &str,
) -> String {
    let base = format!(
        "{} {} {lines} {} {flag}",
        sq(script.to_str().unwrap()),
        sq(name),
        sq(mode)
    );
    match cli {
        "claude" => format!(
            "exec -a claude python3 -I {base} --remote-control {}",
            sq(name)
        ),
        "ucli" => format!(
            "exec -a ucli python3 -I {base} --repl --session {}",
            sq(name)
        ),
        other => format!("COPS_NAME={} exec -a {other} python3 -I {base}", sq(name)),
    }
}

/// tmux DIŞINDA sahte claude (eski/bare oturum). Çağıran `kill` + `wait` eder.
pub fn bare_claude(script: &Path, name: &str) -> Child {
    Command::new("python3")
        .arg0("claude")
        .args([
            "-I",
            script.to_str().unwrap(),
            name,
            "3",
            "-",
            "-",
            "--remote-control",
            name,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap()
}
