//! Python `statedocs.py`: `store_backend` = files | dual | db.
//!
//! * files: yalnız dosya.
//! * dual: yaz = DB + dosya; oku = DOSYA doğruluk kaynağı, DB gölge (fark varsa DB dosyaya uydurulur).
//! * db: yalnız [`StateDocs::db_ready`] belgelerde DB doğruluk kaynağı, dosya AYNA; diğerleri `dual` davranır.
//!
//! Süreç başına TEK [`StateDocs`] paylaş (`Arc`): kirli/eşitlendi kayıtları ve DB bağlantısı onda.
//! Python'dan sapma: db kipinde KALICI DB hatasında (DB yok, şema farklı, Postgres) yazım HİÇBİR yere yapılmaz ve hata döner
//! (Python tarafı DB'yi okuyacağı için yalnız dosyaya yazmak sessiz kayıp olurdu).
use crate::fsutil::atomic_write_json;
use crate::json::Json;
use crate::paths::{realpath, StateDir};
use crate::store::{sqlite_path_from_url, Store, StoreError};
use std::collections::{HashMap, HashSet};
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

/// Python `DB_READY`.
pub const DB_READY: [&str; 6] = [
    "hosts",
    "steward/quota",
    "claude_models",
    "agy_sids",
    "snapshots",
    "instances",
];
/// Python `DB_READY_PREFIXES`.
pub const DB_READY_PREFIXES: [&str; 2] = ["steward/", "orchestration/"];
/// Python `_MIRROR_KEEP`.
pub const MIRROR_KEEP: i64 = 200_000;
/// Python `_MIRROR_EVERY`.
pub const MIRROR_EVERY: u64 = 2000;
const BACKEND_TTL: Duration = Duration::from_secs(5);
const TSV_FILES: [&str; 2] = ["roster.tsv", "models.tsv"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend {
    Files,
    Dual,
    Db,
}

impl Backend {
    pub fn parse(s: &str) -> Option<Backend> {
        match s.trim().to_lowercase().as_str() {
            "files" => Some(Backend::Files),
            "dual" => Some(Backend::Dual),
            "db" => Some(Backend::Db),
            _ => None,
        }
    }
}

/// Okuma sonucu; yazıcılar `Corrupt` üstüne yazmamalı.
#[derive(Debug, Clone, PartialEq)]
pub enum Read {
    Value(Json),
    Missing,
    /// Dosya var ama JSON/UTF-8 değil.
    Corrupt,
}

impl Read {
    pub fn into_option(self) -> Option<Json> {
        match self {
            Read::Value(v) => Some(v),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WriteOutcome {
    /// Doğruluk kaynağına yazıldı.
    Written,
    /// db kipinde DB geçici olarak yazılamadı: yalnız dosyaya yazıldı, BU süreçteki sonraki okuma DB'ye geri alır.
    DbDeferred,
}

#[derive(Debug)]
pub enum WriteError {
    Io(io::Error),
    Db(StoreError),
}
impl std::fmt::Display for WriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WriteError::Io(e) => write!(f, "durum yazımı: {e}"),
            WriteError::Db(e) => write!(f, "durum yazımı: {e}"),
        }
    }
}
impl std::error::Error for WriteError {}
impl From<io::Error> for WriteError {
    fn from(e: io::Error) -> Self {
        WriteError::Io(e)
    }
}

type Sig = Option<(i64, i64, u64)>; // (mtime sn, nsn, boyut)

fn sig(path: &Path) -> Sig {
    std::fs::metadata(path)
        .ok()
        .map(|m| (m.mtime(), m.mtime_nsec(), m.size()))
}

/// Dosya okuma (UTF-8 + JSON).
pub fn read_file(path: &Path) -> Read {
    match std::fs::read(path) {
        Err(_) => Read::Missing,
        Ok(b) => match std::str::from_utf8(&b)
            .ok()
            .and_then(|t| Json::parse(t).ok())
        {
            Some(v) => Read::Value(v),
            None => Read::Corrupt,
        },
    }
}

#[derive(Default)]
struct State {
    backend: Option<(Instant, Backend)>,
    store: Option<Arc<Store>>,
    dirty: HashSet<String>,
    synced: HashMap<String, Sig>,
    ext_prefixes: Vec<String>,
    mirror_n: HashMap<String, u64>,
}

type Logger = Box<dyn Fn(&str) + Send + Sync>;

pub struct StateDocs {
    dir: StateDir,
    forced: Option<Backend>,
    db_url: String,
    state: Mutex<State>,
    logger: Logger,
}

impl StateDocs {
    /// Ortam: `CLAUDEOPS_STORE_BACKEND` (kip), `CLAUDEOPS_DB_URL`.
    pub fn new(dir: StateDir) -> StateDocs {
        let forced = std::env::var("CLAUDEOPS_STORE_BACKEND")
            .ok()
            .and_then(|v| Backend::parse(&v));
        let db_url = std::env::var("CLAUDEOPS_DB_URL").unwrap_or_default();
        StateDocs {
            dir,
            forced,
            db_url,
            state: Mutex::new(State::default()),
            logger: Box::new(|m| eprintln!("statedocs {m}")),
        }
    }
    /// Ortamdan bağımsız kurulum (testler): kip ve `db_url` açık; `None` = settings.json.
    pub fn isolated(dir: StateDir, backend: Option<Backend>, db_url: &str) -> StateDocs {
        let mut s = StateDocs::new(dir);
        s.forced = backend;
        s.db_url = db_url.to_string();
        s
    }
    pub fn with_logger(mut self, f: impl Fn(&str) + Send + Sync + 'static) -> StateDocs {
        self.logger = Box::new(f);
        self
    }
    pub fn dir(&self) -> &StateDir {
        &self.dir
    }

    fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }
    fn log(&self, msg: &str) {
        (self.logger)(msg)
    }

    /// Ortam > settings.json `store_backend` (5 sn önbellek) > files.
    pub fn backend(&self) -> Backend {
        if let Some(b) = self.forced {
            return b;
        }
        let mut st = self.lock();
        if let Some((at, b)) = st.backend {
            if at.elapsed() < BACKEND_TTL {
                return b;
            }
        }
        let b = read_file(&self.dir.settings_json())
            .into_option()
            .and_then(|v| {
                v.get("store_backend")
                    .and_then(Json::as_str)
                    .and_then(Backend::parse)
            })
            .unwrap_or(Backend::Files);
        st.backend = Some((Instant::now(), b));
        b
    }

    /// K8: eklentinin DB-doğruluk-kaynağı öneki. Boş, `/` ile başlayan ya da bitmeyen önek reddedilir.
    pub fn register_doc_prefix(&self, prefix: &str) -> bool {
        let ok = prefix.len() >= 3 && prefix.ends_with('/') && !prefix.starts_with('/');
        if ok {
            self.lock().ext_prefixes.push(prefix.to_string());
        }
        ok
    }

    pub fn db_ready(&self, name: &str) -> bool {
        DB_READY.contains(&name)
            || DB_READY_PREFIXES.iter().any(|p| name.starts_with(p))
            || self.lock().ext_prefixes.iter().any(|p| name.starts_with(p))
    }

    fn effective(&self, name: &str) -> Backend {
        match self.backend() {
            Backend::Db if !self.db_ready(name) => Backend::Dual,
            m => m,
        }
    }

    /// Durum dizini altındaki yoldan belge adı (`steward/quota.json` -> `steward/quota`).
    pub fn name_for(&self, path: &Path) -> String {
        let root = realpath(self.dir.root());
        let p = realpath(path);
        let rel = p.strip_prefix(&root).unwrap_or(&p).to_string_lossy();
        rel.strip_suffix(".json").unwrap_or(&rel).to_string()
    }

    /// DB yalnız durum dizini altındaki yollar için kullanılır.
    fn db_ok(&self, path: &Path) -> bool {
        realpath(path).starts_with(realpath(self.dir.root()))
    }

    /// Paylaşılan DB bağlantısı (ilk kullanımda açılır; başarısız açılış önbelleklenmez).
    pub fn store(&self) -> Result<Arc<Store>, StoreError> {
        if let Some(s) = &self.lock().store {
            return Ok(s.clone());
        }
        let path = sqlite_path_from_url(&self.db_url, &self.dir.db())?;
        let s = Arc::new(Store::open(&path)?);
        Ok(self.lock().store.get_or_insert(s).clone())
    }

    /// `read_json(name, path)` (`file_truth=True`).
    pub fn read(&self, name: &str, path: &Path) -> Read {
        self.read_opts(name, path, true)
    }

    /// `file_truth=false`: dual kipte de DB önce.
    pub fn read_opts(&self, name: &str, path: &Path, file_truth: bool) -> Read {
        self.read_with(name, path, file_truth, None)
    }

    /// `read_json(..., on_corrupt=f)`: dosya her bozuk okunduğunda `f(path)` çağrılır (Python `_file_read` gibi: bir okuma
    /// içinde dosya birden çok kez okunursa birden çok kez). Kanıt yedeği çağıranın işi (ör. [`crate::fsutil::write_corrupt_copy`]).
    pub fn read_with(
        &self,
        name: &str,
        path: &Path,
        file_truth: bool,
        on_corrupt: Option<&dyn Fn(&Path)>,
    ) -> Read {
        let rf = |p: &Path| {
            let r = read_file(p);
            if let (Read::Corrupt, Some(f)) = (&r, on_corrupt) {
                f(p);
            }
            r
        };
        let mode = self.effective(name);
        if mode == Backend::Files || !self.db_ok(path) {
            return rf(path);
        }
        match self.read_db(name, path, mode == Backend::Dual && file_truth, &rf) {
            Ok(r) => r,
            Err(e) => {
                self.log(&format!("read {name}: {e} -> dosya"));
                rf(path)
            }
        }
    }

    fn read_db(
        &self,
        name: &str,
        path: &Path,
        file_first: bool,
        read_file: &dyn Fn(&Path) -> Read,
    ) -> Result<Read, StoreError> {
        if file_first {
            // DB açılamasa da dosya (doğruluk kaynağı) döner: hata üst katta dosyaya düşer
            let st = self.store()?;
            let r = read_file(path);
            if let Read::Value(v) = &r {
                let sg = sig(path);
                if self.lock().synced.get(name) != Some(&sg) {
                    let have = st.get_doc(name)?;
                    if !have.as_ref().is_some_and(|h| h.py_eq(v)) {
                        self.log(&if have.is_none() {
                            format!("import {name}: DB'de yoktu, dosyadan alındı")
                        } else {
                            format!("drift {name}: DB dosyaya uyduruldu")
                        });
                        st.set_doc(name, v)?;
                    }
                    self.lock().synced.insert(name.to_string(), sg);
                }
                return Ok(r);
            }
            return Ok(match st.get_doc(name)? {
                Some(v) => Read::Value(v),
                None => r,
            });
        }
        let st = self.store()?;
        if self.lock().dirty.contains(name) {
            // son DB yazımı başarısızdı: dosya daha yeni
            if let Read::Value(v) = read_file(path) {
                st.set_doc(name, &v)?;
                self.lock().dirty.remove(name);
                self.log(&format!("recover {name}: DB dosyadan yeniden yazıldı"));
                return Ok(Read::Value(v));
            }
        }
        if let Some(v) = st.get_doc(name)? {
            return Ok(Read::Value(v));
        }
        let r = read_file(path); // tembel içe aktarma
        if let Read::Value(v) = &r {
            st.set_doc(name, v)?;
        }
        Ok(r)
    }

    /// `write_json`. `mode`: dosya izni (`None` = var olan korunur).
    pub fn write(
        &self,
        name: &str,
        path: &Path,
        obj: &Json,
        mode: Option<u32>,
    ) -> Result<WriteOutcome, WriteError> {
        let be = if self.db_ok(path) {
            self.effective(name)
        } else {
            Backend::Files
        };
        let mut db_failed = false;
        if be != Backend::Files {
            match self.store().and_then(|s| s.set_doc(name, obj)) {
                Ok(_) => {
                    self.lock().dirty.remove(name);
                }
                Err(e) => {
                    self.log(&format!("write {name}: {e}"));
                    if be == Backend::Db {
                        if e.is_permanent() {
                            return Err(WriteError::Db(e));
                        }
                        atomic_write_json(path, obj, mode)?;
                        self.lock().dirty.insert(name.to_string());
                        return Ok(WriteOutcome::DbDeferred);
                    }
                    db_failed = true;
                }
            }
        }
        if be == Backend::Db {
            // dosya AYNA: hata yutulur
            if let Err(e) = atomic_write_json(path, obj, mode) {
                self.log(&format!("mirror {name}: {e}"));
            }
            return Ok(WriteOutcome::Written);
        }
        atomic_write_json(path, obj, mode)?;
        if be == Backend::Dual {
            let mut st = self.lock();
            if db_failed {
                st.synced.remove(name);
            } else {
                st.synced.insert(name.to_string(), sig(path));
            }
        }
        Ok(WriteOutcome::Written)
    }

    /// `mirror_log`: dosya günlüğüne yazılan satırı DB `log` akışına da ekle (dual/db). SESSİZ (Python gibi: günlük
    /// best-effort; hata yalnız sayılır, loglanmaz: günlük -> mirror -> log döngüsü olmasın). Akış her
    /// [`MIRROR_EVERY`] eklemede [`MIRROR_KEEP`] satıra kırpılır. Dönüş: eklendi mi.
    pub fn mirror_log(&self, stream: &str, path: &Path, entry: &Json) -> bool {
        if self.backend() == Backend::Files || !self.db_ok(path) {
            return false;
        }
        let Ok(st) = self.store() else {
            return false;
        };
        if st.append_log(stream, entry).is_err() {
            return false;
        }
        let n = {
            let mut g = self.lock();
            let c = g.mirror_n.entry(stream.to_string()).or_insert(0);
            *c += 1;
            *c
        };
        if n % MIRROR_EVERY == 0 {
            // kırpma hatası bir sonraki eşikte yeniden denenir (Python ile aynı)
            let _ = st.trim_log(stream, MIRROR_KEEP);
        }
        true
    }

    /// `shadow_tsv`: roster/models dosyasının güncel içeriğini `tsv_rows`a eşitle. Sessiz (hata yalnız loglanır).
    pub fn shadow_tsv(&self, path: &Path, force: bool) {
        let is_tsv = path
            .file_name()
            .and_then(|f| f.to_str())
            .is_some_and(|f| TSV_FILES.contains(&f));
        if self.backend() == Backend::Files || !is_tsv || !self.db_ok(path) {
            return;
        }
        if let Err(e) = self.shadow_tsv_inner(path, force) {
            self.log(&format!("shadow_tsv {}: {e}", path.display()));
        }
    }

    fn shadow_tsv_inner(&self, path: &Path, force: bool) -> Result<(), Box<dyn std::error::Error>> {
        let sg = sig(path);
        let name = self.name_for(path);
        let key = format!("tsv:{name}");
        if !force && self.lock().synced.get(&key) == Some(&sg) {
            return Ok(());
        }
        match crate::roster::read_text(path)? {
            None => {
                let st = self.store()?;
                if st.tsv_text(&name)?.is_some() {
                    st.delete_tsv(&name)?;
                }
            }
            Some(text) => {
                let st = self.store()?;
                if st.tsv_text(&name)?.unwrap_or_default() != text {
                    st.replace_tsv(&name, &text)?;
                }
            }
        }
        self.lock().synced.insert(key, sg);
        Ok(())
    }
}
