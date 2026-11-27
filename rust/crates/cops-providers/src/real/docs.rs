//! Durum belgeleri sınırı ([`DocStore`]) ve gerçek [`AgySidStore`].
//!
//! Gerçek belge deposu [`StateDocStore`]: rs/state `StateDocs` (claudeops.db + ayna, `store_backend` = files | dual | db)
//! üstünde ince sarmal. Kip, DB okuma/yazma, ayna ve `statedocs ..` günlükleri tamamen oradadır; burada yalnız bu crate'in
//! sınır kuralları var: FIFO / aygıt / soket ya da [`DOC_MAX_BYTES`]i aşan dosya hiç açılmaz, okunamayan
//! belge yazılmaz. rs/state'ten miras bilinen fark: `db` kipinde DB kalıcı olarak yazılamıyorsa (DB yok, şema farklı)
//! Rust hiçbir yere yazmaz ve hata döner (Python DB'yi yaratır ya da dosyaya düşer).

use crate::agy_resume::{AgySidStore, AGY_SIDS_UNREADABLE};
use crate::probe::Paths;
use crate::pyjson::Py;
use crate::real::diaglog::Mirror;
use crate::real::lock::{FileLock, LOCK_TIMEOUT};
use crate::spawn_exec::DiagSink;
use cops_state::json::{Json, Map};
use cops_state::statedocs::Read;
use cops_state::StateDocs;
use std::cell::Cell;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

/// Belge dosyası boyut sınırı (Python sınırsız).
pub const DOC_MAX_BYTES: u64 = 16 << 20;

pub trait DocStore: Send + Sync {
    /// `statedocs.read_json(name, path, ..)`: yok, bozuk ya da okunamıyorsa None.
    fn read(&self, name: &str, path: &str) -> Option<Py>;
    /// Yazımdan önce okuma: yoksa `Ok(None)`; var ama okunamıyor, UTF-8 değil ya da JSON değilse `Err`
    /// ([`crate::agy_resume::AGY_SIDS_UNREADABLE`]).
    fn read_checked(&self, name: &str, path: &str) -> Result<Option<Py>, String> {
        Ok(self.read(name, path))
    }
    /// `statedocs.write_json(name, path, doc, writer=atomic_write_json)`.
    fn write(&self, name: &str, path: &str, doc: &Py) -> Result<(), String>;
}

fn to_json(v: &Py) -> Json {
    match v {
        Py::Null => Json::Null,
        Py::Bool(b) => Json::Bool(*b),
        Py::Int(i) => Json::Int(*i),
        Py::BigInt(s) => Json::BigInt(s.clone()),
        Py::Float(f) => Json::Float(*f),
        Py::Str(s) => Json::Str(s.clone()),
        Py::Array(a) => Json::Array(a.iter().map(to_json).collect()),
        Py::Object(o) => {
            let mut m = Map::new();
            for (k, v) in o {
                m.insert(k.clone(), to_json(v));
            }
            Json::Object(m)
        }
    }
}

fn to_py(v: &Json) -> Py {
    match v {
        Json::Null => Py::Null,
        Json::Bool(b) => Py::Bool(*b),
        Json::Int(i) => Py::Int(*i),
        Json::BigInt(s) => Py::BigInt(s.clone()),
        Json::Float(f) => Py::Float(*f),
        Json::Str(s) => Py::Str(s.clone()),
        Json::Array(a) => Py::Array(a.iter().map(to_py).collect()),
        Json::Object(m) => Py::Object(m.iter().map(|(k, v)| (k.clone(), to_py(v))).collect()),
    }
}

/// Dosya yoksa, dizinse (okuma hemen düşer: Python gibi DB'ye bakılır) ya da sınır içinde normal dosyaysa true.
/// `StateDocs` dosyayı sınırsız ve bloke ederek okuduğundan FIFO, aygıt ve soket hiç açılmaz.
fn openable(path: &str) -> bool {
    std::fs::metadata(path).map_or(true, |m| {
        m.is_dir() || (m.is_file() && m.len() <= DOC_MAX_BYTES)
    })
}

/// rs/state belge deposu. Süreç başına TEK `StateDocs` paylaşılır (kirli/eşitlendi kayıtları ondadır).
#[derive(Clone)]
pub struct StateDocStore {
    docs: Arc<StateDocs>,
}

impl StateDocStore {
    pub fn new(docs: Arc<StateDocs>) -> StateDocStore {
        StateDocStore { docs }
    }

    /// `diag_log`un DB `log` aynası (`statedocs.mirror_log`): [`crate::real::diaglog::DiagLog::with_mirror`]e verilir.
    /// `log_path` günlük dosyasının yoludur (durum dizini dışındaysa DB'ye eklenmez).
    pub fn diag_mirror(&self, log_path: impl Into<String>) -> Mirror {
        let docs = self.docs.clone();
        let path = log_path.into();
        Arc::new(move |stream: &str, entry: &Py| {
            docs.mirror_log(stream, Path::new(&path), &to_json(entry));
        })
    }
}

impl DocStore for StateDocStore {
    fn read(&self, name: &str, path: &str) -> Option<Py> {
        if !openable(path) {
            return None;
        }
        let read = self.docs.read(name, Path::new(path));
        read.into_option().map(|v| to_py(&v))
    }

    fn read_checked(&self, name: &str, path: &str) -> Result<Option<Py>, String> {
        let refused = || Err(AGY_SIDS_UNREADABLE.to_string());
        if !openable(path) {
            return refused();
        }
        // `dual` kipte bozuk dosyanın yerine DB değeri döner: bozukluk yine de yazımı durdurur (Python `on_corrupt`)
        let corrupt = Cell::new(false);
        let mark = |_: &Path| corrupt.set(true);
        let read = self
            .docs
            .read_with(name, Path::new(path), true, Some(&mark));
        if corrupt.get() {
            return refused();
        }
        match read {
            Read::Value(v) => Ok(Some(to_py(&v))),
            Read::Missing if std::fs::symlink_metadata(path).is_err() => Ok(None),
            // eşlenmemiş vekil geri yazılamaz; var ama açılamayan dosya "yok" değildir
            Read::Lossy(_) | Read::Missing | Read::Corrupt => refused(),
        }
    }

    fn write(&self, name: &str, path: &str, doc: &Py) -> Result<(), String> {
        self.docs
            .write(name, Path::new(path), &to_json(doc), None)
            .map(|_| ())
            .map_err(|e| format!("{name}: {e}"))
    }
}

/// `agy_sids` belgesinin yazım yolu: Python ile aynı `flock` dosyası (`agy_sids.json.lock`) + atomik yazım.
#[derive(Clone)]
pub struct DocAgySidStore {
    docs: Arc<dyn DocStore>,
    path: String,
    cwd: String,
    timeout: Duration,
    diag: Option<Arc<dyn DiagSink>>,
}

impl DocAgySidStore {
    pub fn new(paths: &Paths, docs: Arc<dyn DocStore>) -> DocAgySidStore {
        let cwd = std::env::current_dir()
            .map_or_else(|_| "/".into(), |p| p.to_string_lossy().into_owned());
        DocAgySidStore {
            docs,
            path: paths.agy_sids_json(),
            cwd,
            timeout: LOCK_TIMEOUT,
            diag: None,
        }
    }

    /// Reddedilen kilidin (`file_lock_refused`) yazılacağı günlük.
    pub fn with_diag(mut self, diag: Arc<dyn DiagSink>) -> DocAgySidStore {
        self.diag = Some(diag);
        self
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

    fn load_for_write(&self) -> Result<Option<Py>, String> {
        self.docs.read_checked("agy_sids", &self.path)
    }

    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        let _lock =
            FileLock::acquire_logged(&self.path, &self.cwd, self.timeout, self.diag.as_deref())
                .map_err(|e| format!("agy_sids kilidi alınamadı: {e}"))?;
        f()
    }

    fn save(&self, doc: &Py) -> Result<(), String> {
        self.docs.write("agy_sids", &self.path, doc)
    }
}
