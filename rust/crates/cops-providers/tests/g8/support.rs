//! G8 testlerinin ortak düzeni: her şey geçici dizinde; ikililer sahte kabuk betiği; gerçek HOME/ağ YOK.

#![allow(dead_code)]

use cops_providers::real::docs::FileDocs;
use cops_providers::real::help::HelpCache;
use cops_providers::cost::CostRefusal;
use cops_providers::real::probe::{CostGate, ProjectDirs, SearchUrl};
use cops_providers::real::{Env, RealDeps, RealProbe};
use cops_providers::Paths;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;
use tempfile::TempDir;

/// Betik yazımı ile süreç başlatma çakışmasın: başka iş parçacığının `fork`u yazım tanıtıcısını taşırsa `ETXTBSY`.
pub fn spawn_guard() -> MutexGuard<'static, ()> {
    static LOCK: Mutex<()> = Mutex::new(());
    LOCK.lock().unwrap_or_else(PoisonError::into_inner)
}

pub struct Tmp {
    _dir: TempDir,
    pub root: String,
}

impl Tmp {
    pub fn new() -> Tmp {
        let dir = tempfile::Builder::new().prefix("cops-g8-").tempdir().unwrap();
        let root = fs::canonicalize(dir.path()).unwrap().to_string_lossy().into_owned();
        for d in ["home", "state", "bin", "work"] {
            fs::create_dir(format!("{root}/{d}")).unwrap();
        }
        Tmp { _dir: dir, root }
    }

    pub fn path(&self, rel: &str) -> String {
        format!("{}/{rel}", self.root)
    }

    pub fn write(&self, rel: &str, content: impl AsRef<[u8]>, mode: u32) -> String {
        let p = self.path(rel);
        fs::create_dir_all(Path::new(&p).parent().unwrap()).unwrap();
        fs::write(&p, content).unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
        p
    }

    /// `#!/bin/sh` betiği.
    pub fn script(&self, rel: &str, body: &str) -> String {
        self.write(rel, format!("#!/bin/sh\n{body}\n"), 0o755)
    }

    pub fn paths(&self) -> Paths {
        Paths { claudeops_dir: self.path("state"), home: self.path("home"), repo_dir: self.path("repo") }
    }

    /// Yalıtılmış ortam: PATH sahte `bin` + temel araçlar.
    pub fn env(&self, extra: &[(&str, &str)]) -> Env {
        let mut vars = vec![
            ("HOME".to_string(), self.path("home")),
            ("CLAUDEOPS_DIR".to_string(), self.path("state")),
            ("PATH".to_string(), format!("{}:/usr/bin:/bin", self.path("bin"))),
        ];
        vars.extend(extra.iter().map(|(k, v)| (k.to_string(), v.to_string())));
        Env::fixed(vars)
    }

    pub fn probe_with(&self, env: Env, help: Arc<HelpCache>) -> RealProbe {
        let paths = self.paths();
        let deps = RealDeps {
            docs: Arc::new(FileDocs::new(&paths, env.clone())),
            projects: Arc::new(Projects(paths.home.clone())),
            cost: Arc::new(OpenGate),
            search: Arc::new(NoSearch),
            help,
            panel_port: Some(8765),
        };
        RealProbe::new(paths, env, deps).with_cwd(self.root.clone())
    }

    pub fn probe(&self) -> RealProbe {
        self.probe_with(self.env(&[]), Arc::new(HelpCache::with_timeout(Duration::from_secs(5))))
    }
}

/// Maliyet kapısı ve arama yöneticisi kendi testlerinde (`real_ledger`, `real_searxng`) sınanır.
pub struct OpenGate;

impl CostGate for OpenGate {
    fn check_and_reserve(&self, _session: &str) -> Result<(), CostRefusal> {
        Ok(())
    }
    fn release(&self, _session: &str) {}
}

pub struct NoSearch;

impl SearchUrl for NoSearch {
    fn search_url(&self, _session: &str, _preview: bool) -> Option<String> {
        None
    }
}

pub struct Projects(pub String);

impl ProjectDirs for Projects {
    fn claude_project_dir(&self, cwd: &str) -> String {
        let enc: String = cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect();
        format!("{}/.claude/projects/{enc}", self.0)
    }
}

pub fn mode(path: &str) -> u32 {
    fs::symlink_metadata(path).unwrap().permissions().mode() & 0o7777
}

pub fn mkfifo(path: &str) {
    let c = std::ffi::CString::new(path).unwrap();
    // SAFETY: geçerli, NUL ile biten yol.
    assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o600) }, 0);
}
