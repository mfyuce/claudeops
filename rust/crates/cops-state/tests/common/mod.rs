//! Parite testlerinin ortak ortamı: geçici kök (`TestEnv`), Python alt süreci (`HOME` ve `CLAUDEOPS_DIR` geçici).
#![allow(dead_code)]
use cops_state::{Backend, Json, StateDir, StateDocs, TestEnv};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub struct Env {
    _tmp: TestEnv,
    pub root: PathBuf,
    pub state: PathBuf,
}

impl Env {
    pub fn new() -> Env {
        let tmp = TestEnv::new().unwrap();
        let root = tmp.root().to_path_buf();
        let state = tmp.dir().root().to_path_buf();
        std::fs::create_dir_all(root.join("home")).unwrap();
        Env {
            _tmp: tmp,
            root,
            state,
        }
    }
    pub fn dir(&self) -> StateDir {
        StateDir::at(&self.state)
    }
    pub fn docs(&self, b: Backend) -> StateDocs {
        StateDocs::isolated(self.dir(), Some(b), "").with_logger(|_| {})
    }
    pub fn command(&self, backend: &str, code: &str) -> Command {
        let py = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../py")
            .canonicalize()
            .unwrap();
        let prelude = "import sys, json, os\nsys.path.insert(0, sys.argv[1])\n";
        let mut c = Command::new("python3");
        // HOME geçici olsa da kullanıcı site-packages'i (websockets) bulunsun
        let userbase = std::env::var_os("PYTHONUSERBASE")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local")))
            .unwrap_or_default();
        c.args(["-B", "-c", &format!("{prelude}{code}")])
            .arg(py)
            .env_clear()
            .env("PATH", std::env::var_os("PATH").unwrap_or_default())
            .env("LANG", "C.UTF-8")
            .env("HOME", self.root.join("home"))
            .env("CLAUDEOPS_DIR", &self.state)
            .env("CLAUDEOPS_EXTENSIONS", "")
            .env("PYTHONUSERBASE", userbase)
            .env("CLAUDEOPS_STORE_BACKEND", backend)
            .current_dir(&self.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(tz) = std::env::var_os("TZ") {
            c.env("TZ", tz); // created_at_from_name yerel saat kullanır
        }
        c
    }
    /// Kodu çalıştır, stdout'u döndür.
    pub fn py_in(&self, backend: &str, code: &str, stdin: &str) -> String {
        let mut child = self.command(backend, code).spawn().expect("python3");
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
    pub fn py(&self, backend: &str, code: &str) -> String {
        self.py_in(backend, code, "")
    }
    pub fn read(&self, name: &str) -> String {
        std::fs::read_to_string(self.state.join(name)).unwrap()
    }
    pub fn write(&self, name: &str, text: &str) {
        let p = self.state.join(name);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, text).unwrap();
    }
    pub fn mode(&self, name: &str) -> u32 {
        std::fs::metadata(self.state.join(name))
            .unwrap()
            .permissions()
            .mode()
            & 0o777
    }
}

pub fn j(s: &str) -> Json {
    Json::parse(s).unwrap()
}
