//! Durum belgeleri sınırı ([`DocStore`]) ve gerçek [`AgySidStore`].
//!
//! Belge deposu (claudeops.db + ayna, `store_backend` kipi) `rs/state` `statedocs`undur ve bu dalda YOKTUR. Buradaki
//! [`FileDocs`] yalnız dosyanın doğruluk kaynağı olduğu durumları karşılar (`files` ve `dual`; Python `dual` okurken
//! dosya imzası değişince DB'yi dosyaya uydurur). Belge `db` kipinde DB doğruluk kaynağıysa [`FileDocs`] okumaz ve
//! yazmaz (bayat aynadan karar verilmez, yalnız aynaya yazıp başarı sayılmaz): birleştirmede [`DocStore`] `statedocs`
//! ile uygulanmalı.

use crate::agy_resume::AgySidStore;
use crate::probe::Paths;
use crate::pyfmt::strip;
use crate::pyjson::Py;
use crate::real::lock::{FileLock, LOCK_TIMEOUT};
use crate::real::{effects, fsio, Env};
use std::sync::Arc;
use std::time::Duration;

/// Belge okuma sınırı (Python sınırsız).
pub const DOC_MAX_BYTES: u64 = 16 << 20;

/// `statedocs.DB_READY` içinden bu crate'in kullandığı belgeler.
const DB_READY: [&str; 2] = ["agy_sids", "claude_models"];

pub trait DocStore: Send + Sync {
    /// `statedocs.read_json(name, path, ..)`: yok, bozuk ya da okunamıyorsa None.
    fn read(&self, name: &str, path: &str) -> Option<Py>;
    /// `statedocs.write_json(name, path, doc, writer=atomic_write_json)`.
    fn write(&self, name: &str, path: &str, doc: &Py) -> Result<(), String>;
}

/// Dosya doğruluk kaynağıyken belge deposu.
#[derive(Debug, Clone)]
pub struct FileDocs {
    settings_json: String,
    env: Env,
}

impl FileDocs {
    pub fn new(paths: &Paths, env: Env) -> FileDocs {
        FileDocs { settings_json: format!("{}/settings.json", paths.claudeops_dir), env }
    }

    /// `statedocs.backend()`: ortam, yoksa `settings.json` `store_backend`, yoksa `files`. Her çağrıda yeniden okunur.
    fn backend_is_db(&self) -> bool {
        let word = |s: &str| strip(s).to_lowercase();
        let env = word(&self.env.get("CLAUDEOPS_STORE_BACKEND").unwrap_or_default());
        if matches!(env.as_str(), "files" | "dual" | "db") {
            return env == "db";
        }
        fsio::read_bytes(&self.settings_json, DOC_MAX_BYTES)
            .and_then(|b| Py::parse(std::str::from_utf8(&b).ok()?))
            .and_then(|d| d.get("store_backend").and_then(Py::as_str).map(word))
            .is_some_and(|m| m == "db")
    }

    fn db_only(&self, name: &str) -> bool {
        DB_READY.contains(&name) && self.backend_is_db()
    }
}

impl DocStore for FileDocs {
    fn read(&self, name: &str, path: &str) -> Option<Py> {
        if self.db_only(name) {
            return None;
        }
        let data = fsio::read_bytes(path, DOC_MAX_BYTES)?;
        Py::parse(std::str::from_utf8(&data).ok()?)
    }

    fn write(&self, name: &str, path: &str, doc: &Py) -> Result<(), String> {
        if self.db_only(name) {
            return Err(format!("{name}: store_backend=db, belge deposu (rs/state) gerekli; yazılmadı"));
        }
        effects::atomic_write_text(path, &doc.dumps_pretty(), None).map_err(|e| format!("{name}: {e}"))
    }
}

/// `agy_sids` belgesinin yazım yolu: Python ile aynı `flock` dosyası (`agy_sids.json.lock`) + atomik yazım.
#[derive(Clone)]
pub struct DocAgySidStore {
    docs: Arc<dyn DocStore>,
    path: String,
    cwd: String,
    timeout: Duration,
}

impl DocAgySidStore {
    pub fn new(paths: &Paths, docs: Arc<dyn DocStore>) -> DocAgySidStore {
        let cwd = std::env::current_dir().map_or_else(|_| "/".into(), |p| p.to_string_lossy().into_owned());
        DocAgySidStore { docs, path: paths.agy_sids_json(), cwd, timeout: LOCK_TIMEOUT }
    }

    pub fn with_lock_timeout(mut self, timeout: Duration) -> DocAgySidStore {
        self.timeout = timeout;
        self
    }
}

impl AgySidStore for DocAgySidStore {
    fn load(&self) -> Option<Py> {
        self.docs.read("agy_sids", &self.path)
    }

    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        let _lock = FileLock::acquire(&self.path, &self.cwd, self.timeout)
            .map_err(|e| format!("agy_sids kilidi alınamadı: {e}"))?;
        f()
    }

    fn save(&self, doc: &Py) -> Result<(), String> {
        self.docs.write("agy_sids", &self.path, doc)
    }
}
