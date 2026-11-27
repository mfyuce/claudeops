//! Ortak test ortamı: geçici kök (`TestEnv`), altında `state/` (CLAUDEOPS_DIR) ve `home/` (HOME); Python alt süreci aynı
//! geçici dizinlerle (gerçek durum dizinine ve `~/.claude`a dokunmaz).
#![allow(dead_code)]
use cops_state::{Backend, StateDir, StateDocs, TestEnv};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

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
    /// Salt okuma kipindeki belge erişimi (copsd'nin kullandığı biçim).
    pub fn ro(&self, b: Backend) -> StateDocs {
        StateDocs::isolated(self.dir(), Some(b), "").into_read_only()
    }
    pub fn write(&self, rel: &str, data: impl AsRef<[u8]>) {
        let p = self.state.join(rel);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, data).unwrap();
    }
    fn command(&self, backend: &str, code: &str, extra: &[(&str, &Path)]) -> Command {
        let py = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../py")
            .canonicalize()
            .unwrap();
        let prelude = "import sys, json, os\nsys.path.insert(0, sys.argv[1])\n";
        // HOME geçici olsa da kullanıcı site-packages'i bulunsun (psutil, websockets)
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
            .env("CLAUDEOPS_STORE_BACKEND", backend)
            .current_dir(&self.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for (k, v) in extra {
            c.env(k, v);
        }
        c
    }
    /// `(başarılı mı, stdout, stderr)`.
    pub fn py_try(
        &self,
        backend: &str,
        code: &str,
        stdin: &str,
        extra: &[(&str, &Path)],
    ) -> (bool, String, String) {
        let mut child = self.command(backend, code, extra).spawn().expect("python3");
        child
            .stdin
            .take()
            .unwrap()
            .write_all(stdin.as_bytes())
            .unwrap();
        let o = child.wait_with_output().unwrap();
        (
            o.status.success(),
            String::from_utf8(o.stdout).unwrap(),
            String::from_utf8_lossy(&o.stderr).into_owned(),
        )
    }
    pub fn py(&self, backend: &str, code: &str) -> String {
        let (ok, out, err) = self.py_try(backend, code, "", &[]);
        assert!(ok, "python hata:\n{err}");
        out
    }
}

/// Python şemalı DB'yi kurar (`default_store()`), sonra verilen kodu çalıştırır (`st` = depo). Süreç çıkınca yan dosyalar
/// silinir (kapalı WAL DB).
pub fn py_db(e: &Env, code: &str) {
    e.py(
        "db",
        &format!("from claudeops.store import default_store\nst = default_store()\n{code}"),
    );
}
