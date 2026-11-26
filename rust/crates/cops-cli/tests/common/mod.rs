//! Ortak test ortamı: yalıtık HOME + CLAUDEOPS_DIR, eklenti kapalı, `PATH` başında sahte `systemctl` (çağrıları günlüğe
//! yazar, `FAKE_SC_FAIL` içindeki komutta 1 döner; `is-active`/`is-enabled` `FAKE_SC_STATE`, varsayılan 3 = durmuş). Gerçek `systemctl`e ulaşılamaz: sahte olan PATH'te ilk sıradadır ve
//! testler yalnız salt okuma yollarında Python'u koşar.
#![allow(dead_code)]

use std::ffi::OsStr;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap()
}

pub fn py_cops() -> PathBuf {
    repo().join("py/cops")
}

pub fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_cops-rs"))
}

/// Gerçek kullanıcının Python site tabanı (sahte HOME altında `websockets` vb. bulunsun; yalnız okunur).
pub fn user_base() -> String {
    static B: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    B.get_or_init(|| {
        let o = Command::new("/usr/bin/python3")
            .args(["-c", "import site; print(site.getuserbase())"])
            .output()
            .unwrap();
        String::from_utf8(o.stdout).unwrap().trim().to_string()
    })
    .clone()
}

pub struct Sandbox {
    pub t: tempfile::TempDir,
}

impl Sandbox {
    pub fn new() -> Sandbox {
        let t = tempfile::tempdir().unwrap();
        for d in ["home/.config/systemd/user", "state", "fakebin"] {
            std::fs::create_dir_all(t.path().join(d)).unwrap();
        }
        let sc = t.path().join("fakebin/systemctl");
        std::fs::write(
            &sc,
            "#!/bin/sh\necho \"$*\" >> \"$FAKE_SC_LOG\"\ncase \"$2\" in is-active|is-enabled) exit \"${FAKE_SC_STATE:-3}\";; esac\ncase \" $FAKE_SC_FAIL \" in *\" $2 \"*) exit 1;; esac\nexit 0\n",
        )
        .unwrap();
        std::fs::set_permissions(&sc, std::fs::Permissions::from_mode(0o755)).unwrap();
        Sandbox { t }
    }

    pub fn home(&self) -> PathBuf {
        self.t.path().join("home")
    }
    pub fn state(&self) -> PathBuf {
        self.t.path().join("state")
    }
    pub fn unit_dir(&self) -> PathBuf {
        self.home().join(".config/systemd/user")
    }
    pub fn sc_log(&self) -> PathBuf {
        self.t.path().join("sc.log")
    }

    pub fn cmd(&self, prog: &Path) -> Command {
        let mut c = Command::new(prog);
        c.env_clear()
            .env("HOME", self.home())
            .env("CLAUDEOPS_DIR", self.state())
            .env("CLAUDEOPS_EXTENSIONS", "off")
            .env(
                "PATH",
                format!("{}:/usr/bin:/bin", self.t.path().join("fakebin").display()),
            )
            .env("LANG", "C.UTF-8")
            .env("FAKE_SC_LOG", self.sc_log())
            .env("COPS_PY", py_cops())
            .env("PYTHONUSERBASE", user_base())
            .current_dir(self.t.path());
        c
    }

    pub fn run<I, S>(&self, prog: &Path, args: I) -> Output
    where
        I: IntoIterator<Item = S>,
        S: AsRef<OsStr>,
    {
        self.cmd(prog).args(args).output().unwrap()
    }

    pub fn exe(&self, p: &Path) {
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, "#!/bin/sh\n").unwrap();
        std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
}

pub fn same(a: &Output, b: &Output, what: &str) {
    assert_eq!(
        (
            a.status.code(),
            String::from_utf8_lossy(&a.stdout),
            String::from_utf8_lossy(&a.stderr)
        ),
        (
            b.status.code(),
            String::from_utf8_lossy(&b.stdout),
            String::from_utf8_lossy(&b.stderr)
        ),
        "{what}"
    );
}

/// Bağlı (dolu) ve boş iki loopback portu.
pub fn ports() -> (std::net::TcpListener, String, String) {
    let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let busy = l.local_addr().unwrap().to_string();
    let free = {
        let x = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        x.local_addr().unwrap().to_string()
    };
    (l, busy, free)
}
