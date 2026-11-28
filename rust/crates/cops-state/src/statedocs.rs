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
use crate::json::{Json, Map};
use crate::paths::{realpath, StateDir};
use crate::store::{sqlite_path_from_url, Store, StoreError};
use std::collections::{HashMap, HashSet};
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
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
/// Python `_TSV_FILES`.
pub const TSV_FILES: [&str; 2] = ["roster.tsv", "models.tsv"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend {
    Files,
    Dual,
    Db,
}

impl Backend {
    /// `s.strip().lower()` `files|dual|db` ise.
    pub fn parse(s: &str) -> Option<Backend> {
        match crate::pycompat::lower(crate::pycompat::strip(s)).as_str() {
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
    /// Dosyada eşlenmemiş vekil kaçışı vardı (U+FFFD ile okundu, [`Json::parse_lossy`]): okunabilir ama GERİ YAZILAMAZ
    /// (Python da yazamaz). DB'ye aktarılmaz.
    Lossy(Json),
    Missing,
    /// Dosya var ama JSON/UTF-8 değil.
    Corrupt,
}

impl Read {
    pub fn into_option(self) -> Option<Json> {
        match self {
            Read::Value(v) | Read::Lossy(v) => Some(v),
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
    /// [`StateDocs::into_read_only`] kipinde yazım istendi (hiçbir şeye dokunulmadı).
    ReadOnly,
}
impl std::fmt::Display for WriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WriteError::Io(e) => write!(f, "durum yazımı: {e}"),
            WriteError::Db(e) => write!(f, "durum yazımı: {e}"),
            WriteError::ReadOnly => write!(f, "durum yazımı: salt okuma kipi"),
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

/// Dosya okuma (UTF-8 + JSON; Python `json.load` gibi eşlenmemiş vekil kabul, bkz. [`Read::Lossy`]).
pub fn read_file(path: &Path) -> Read {
    match std::fs::read(path) {
        Err(_) => Read::Missing,
        Ok(b) => match std::str::from_utf8(&b)
            .ok()
            .and_then(|t| Json::parse_lossy(t).ok())
        {
            Some((v, false)) => Read::Value(v),
            Some((v, true)) => Read::Lossy(v),
            None => Read::Corrupt,
        },
    }
}

/// DB'ye aktarılacak dosya değeri: `Lossy` Python'daki `set_doc` kodlama istisnası gibi hata (üst kat dosyaya düşer).
fn for_db(r: &Read, name: &str) -> Result<Option<Json>, StoreError> {
    match r {
        Read::Value(v) => Ok(Some(v.clone())),
        Read::Lossy(_) => Err(StoreError::BadDoc(format!("{name}: eşlenmemiş vekil"))),
        _ => Ok(None),
    }
}

#[derive(Default)]
struct State {
    backend: Option<(Instant, Backend)>,
    /// Son başarılı okumadaki kip (ayar dosyası bozulursa korunur).
    good_backend: Option<Backend>,
    store: Option<Arc<Store>>,
    dirty: HashSet<String>,
    synced: HashMap<String, Sig>,
    ext_prefixes: Vec<String>,
    mirror_n: HashMap<String, u64>,
    /// Okuyucu önbellekleri (ör. `instances`): ad -> (dosya anahtarı, değer).
    reader_cache: HashMap<&'static str, (FileKey, Json)>,
    /// db kipi okuyucu önbellekleri: ad -> (DB damgası, değer).
    db_cache: HashMap<&'static str, (DbStamp, Json)>,
    /// ad -> db okuması hata verip dosyaya düşme sayısı (düşen okuma önbelleğe girmesin).
    fallbacks: HashMap<String, u64>,
}

/// Python `_db_stamp`: (DB yolu, (satır sürümü, yazım anı), dosyaya düşme sayısı).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct DbStamp(PathBuf, (i64, u64), u64);

/// Python `(st_ino, st_mtime_ns, st_size)`.
pub(crate) type FileKey = (u64, i128, u64);

/// Dosya anahtarı; dosya yoksa `Ok(None)`.
pub(crate) fn file_key(path: &Path) -> io::Result<Option<FileKey>> {
    match std::fs::metadata(path) {
        Ok(m) => Ok(Some((
            m.ino(),
            i128::from(m.mtime()) * 1_000_000_000 + i128::from(m.mtime_nsec()),
            m.size(),
        ))),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e),
    }
}

type Logger = Box<dyn Fn(&str) + Send + Sync>;

pub struct StateDocs {
    dir: StateDir,
    forced: Option<Backend>,
    /// `CLAUDEOPS_STORE_BACKEND` her çağrıda okunur (Python `backend()` gibi); `isolated` kapatır.
    read_env: bool,
    db_url: String,
    /// [`StateDocs::with_db_path`]: `db_url`den üstün açık SQLite yolu.
    db_path: Option<PathBuf>,
    state: Mutex<State>,
    /// `None` = [`StateDocs::diag_log`].
    logger: Option<Logger>,
    /// [`StateDocs::into_read_only`].
    read_only: bool,
}

impl std::fmt::Debug for StateDocs {
    /// `db_url` parola taşıyabilir: yazılmaz.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StateDocs")
            .field("dir", &self.dir.root())
            .field("read_only", &self.read_only)
            .finish_non_exhaustive()
    }
}

impl StateDocs {
    /// Ortam: `CLAUDEOPS_STORE_BACKEND` (kip), `CLAUDEOPS_DB_URL`, `CLAUDEOPS_DIAG_LOG`.
    pub fn new(dir: StateDir) -> StateDocs {
        let db_url = std::env::var("CLAUDEOPS_DB_URL").unwrap_or_default();
        StateDocs {
            dir,
            forced: None,
            read_env: true,
            db_url,
            db_path: None,
            state: Mutex::new(State::default()),
            logger: None,
            read_only: false,
        }
    }
    /// Ortamdan bağımsız kurulum (testler): kip ve `db_url` açık; `None` = settings.json.
    pub fn isolated(dir: StateDir, backend: Option<Backend>, db_url: &str) -> StateDocs {
        let mut s = StateDocs::new(dir);
        s.forced = backend;
        s.read_env = false;
        s.db_url = db_url.to_string();
        s
    }
    /// Açık SQLite yolu (`CLAUDEOPS_DB_URL` ve durum dizini varsayılanından üstün): copsd `--db` (R-B1-3).
    pub fn with_db_path(mut self, path: &Path) -> StateDocs {
        self.db_path = Some(path.to_path_buf());
        self
    }

    /// Kullanılacak SQLite yolu: [`StateDocs::with_db_path`], yoksa `db_url`, o da boşsa durum dizinindeki DB.
    pub fn db_path(&self) -> Result<PathBuf, StoreError> {
        match &self.db_path {
            Some(p) => Ok(p.clone()),
            None => sqlite_path_from_url(&self.db_url, &self.dir.db()),
        }
    }

    pub fn with_logger(mut self, f: impl Fn(&str) + Send + Sync + 'static) -> StateDocs {
        self.logger = Some(Box::new(f));
        self
    }

    /// SALT OKUMA kipi (B1, copsd: tek yazar Python). Okuma kararları Python `read_json` ile aynı kalır, ama:
    /// - içe aktarma (`db`: DB'de olmayan belge), uydurma (`dual`: drift/import), kirli kurtarma (`recover`) YOK;
    /// - DB her kullanımda [`Store::open_read_only`] ile açılır (yan dosya yaratmaz, pragma yazmaz; önbellek yok);
    /// - [`write`](Self::write) [`WriteError::ReadOnly`] döner; [`mirror_log`](Self::mirror_log),
    ///   [`shadow_tsv`](Self::shadow_tsv) hiçbir şey yapmaz; [`diag_log`](Self::diag_log) dosyaya YAZMAZ (günlükçü ya da stderr);
    /// - `Instances` bozuk ayna yedeği (`.corrupt-<sha8>`) yazmaz, `mutate` kilit dosyası açmadan reddeder; `Roster::lock`
    ///   reddeder.
    ///
    /// Dizin, dosya, izin yaratılmaz (`tests/read_only.rs` ham yolla karşılaştırarak kanıtlar).
    pub fn into_read_only(mut self) -> StateDocs {
        self.read_only = true;
        self
    }
    pub fn is_read_only(&self) -> bool {
        self.read_only
    }
    pub fn dir(&self) -> &StateDir {
        &self.dir
    }

    fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }
    /// Varsayılan günlükçü Python `_log` gibi: `diag.log`a `statedocs <ileti>` olayı.
    fn log(&self, msg: &str) {
        match &self.logger {
            Some(f) => f(msg),
            None if self.read_only => eprintln!("statedocs {msg}"),
            None => self.diag_log(&format!("statedocs {msg}")),
        }
    }

    /// `diaglog.diag_log_path()`: boş olmayan `CLAUDEOPS_DIAG_LOG` (`isolated` okumaz), yoksa `<dizin>/diag.log`.
    fn diag_log_path(&self) -> PathBuf {
        self.read_env
            .then(|| std::env::var_os("CLAUDEOPS_DIAG_LOG"))
            .flatten()
            .filter(|v| !v.is_empty())
            .map_or_else(|| self.dir.join("diag.log"), PathBuf::from)
    }

    /// `diaglog.diag_log(event)`: `{"ts": yerel saniye, "event": ..}` satırı + `log` akışı `diag` (dual/db). Best-effort:
    /// hiçbir hata çağırana dönmez; dosyaya yazılamazsa DB'ye de eklenmez (Python gibi).
    /// Alınamayan dosya kilidi (`atomic_json._log_lock_refused`, TBD#397): reddi yutan çağıranda da iz kalsın.
    pub fn log_lock_refused(&self, path: &Path) {
        let mut m = Map::new();
        m.insert("path".into(), path.to_string_lossy().into_owned().into());
        self.diag_log_with("file_lock_refused", m);
    }

    pub fn diag_log(&self, event: &str) {
        self.diag_log_with(event, Map::new());
    }

    /// `diaglog.diag_log(event, **data)`: alanlar `ts` ve `event`ten sonra (Python sözlük sırası).
    pub fn diag_log_with(&self, event: &str, data: Map) {
        if self.read_only {
            match &self.logger {
                Some(f) => f(event),
                None => eprintln!("{event}"),
            }
            return;
        }
        let Some(ts) = crate::pytime::local_isoformat_seconds(crate::now()) else {
            return;
        };
        let mut m = Map::new();
        m.insert("ts".into(), ts.into());
        m.insert("event".into(), event.into());
        m.extend(data);
        let entry = Json::Object(m);
        let path = self.diag_log_path();
        if crate::diaglog::append(&path, &entry).is_ok() {
            self.mirror_log("diag", &path, &entry);
        }
    }

    /// Ortam (her çağrıda) > settings.json `store_backend` (5 sn önbellek) > files.
    pub fn backend(&self) -> Backend {
        if let Some(b) = self.forced {
            return b;
        }
        if self.read_env {
            if let Some(b) = std::env::var_os("CLAUDEOPS_STORE_BACKEND")
                .and_then(|v| Backend::parse(&v.to_string_lossy()))
            {
                return b;
            }
        }
        let mut st = self.lock();
        if let Some((at, b)) = st.backend {
            if at.elapsed() < BACKEND_TTL {
                return b;
            }
        }
        let path = self.dir.settings_json();
        let parsed = |v: &Json| {
            v.get("store_backend")
                .and_then(Json::as_str)
                .and_then(Backend::parse)
                .unwrap_or(Backend::Files)
        };
        // bozuk/okunamayan ayar dosyası canlı `db` kipini sessizce `files`a çevirmesin (Python ile aynı)
        let read = match read_file(&path) {
            Read::Missing if matches!(path.try_exists(), Ok(false)) => None,
            r => Some(r.into_option().and_then(|v| match &v {
                Json::Object(_) => Some(parsed(&v)),
                other if !other.truthy() => Some(Backend::Files),
                _ => None,
            })),
        };
        let b = match read {
            None => Backend::Files,
            Some(Some(b)) => {
                st.good_backend = Some(b);
                b
            }
            Some(None) => st.good_backend.unwrap_or(Backend::Files),
        };
        st.backend = Some((Instant::now(), b));
        b
    }

    /// K8: eklentinin DB-doğruluk-kaynağı öneki. Boş, `/` ile başlayan ya da bitmeyen önek reddedilir.
    pub fn register_doc_prefix(&self, prefix: &str) -> bool {
        // Python `len` kod noktası sayar
        let ok = prefix.chars().count() >= 3 && prefix.ends_with('/') && !prefix.starts_with('/');
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

    pub(crate) fn cache_get(&self, name: &'static str, key: FileKey) -> Option<Json> {
        self.lock()
            .reader_cache
            .get(name)
            .filter(|(k, _)| *k == key)
            .map(|(_, v)| v.clone())
    }
    pub(crate) fn cache_put(&self, name: &'static str, key: Option<FileKey>, v: &Json) {
        let mut st = self.lock();
        match key {
            Some(k) => {
                st.reader_cache.insert(name, (k, v.clone()));
            }
            None => {
                st.reader_cache.remove(name);
            }
        }
    }
    /// db kipinde okuyucu önbelleğinin damgası. `None` = önbelleğe ALMA: kip db değil, yol durum dizini dışında,
    /// son DB yazımı başarısız (dosya daha yeni), satır yok ya da DB okunamıyor.
    pub(crate) fn db_stamp(&self, name: &str, path: &Path) -> Option<DbStamp> {
        if self.effective(name) != Backend::Db
            || !self.db_ok(path)
            || self.lock().dirty.contains(name)
        {
            return None;
        }
        let st = self.store().ok()?;
        let row = st.doc_stamp(name).ok()??;
        let fallbacks = self.lock().fallbacks.get(name).copied().unwrap_or(0);
        Some(DbStamp(st.path().to_path_buf(), row, fallbacks))
    }
    /// `db_truth`: AYNA dosya bozukken kullanılacak DB değeri. `None` = DB doğruluğu kesin değil (kip db değil, yol
    /// durum dizini dışında, son DB yazımı başarısız, satır yok ya da DB okunamıyor).
    pub(crate) fn db_truth(&self, name: &str, path: &Path) -> Option<Json> {
        if self.effective(name) != Backend::Db
            || !self.db_ok(path)
            || self.lock().dirty.contains(name)
        {
            return None;
        }
        match self.store().and_then(|s| s.get_doc(name)) {
            Ok(v) => v,
            Err(e) => {
                self.log(&format!("read {name}: {e} (ayna bozuk)"));
                None
            }
        }
    }
    pub(crate) fn db_cache_get(&self, name: &'static str, stamp: &DbStamp) -> Option<Json> {
        self.lock()
            .db_cache
            .get(name)
            .filter(|(s, _)| s == stamp)
            .map(|(_, v)| v.clone())
    }
    pub(crate) fn db_cache_put(&self, name: &'static str, stamp: DbStamp, v: &Json) {
        self.lock().db_cache.insert(name, (stamp, v.clone()));
    }
    /// Belgenin bu süreçteki etkin kipi (`db` istenip belge db-hazır değilse `dual`).
    pub fn effective_backend(&self, name: &str) -> Backend {
        self.effective(name)
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
        if self.read_only {
            return self.read_only_store().map(Arc::new);
        }
        if let Some(s) = &self.lock().store {
            return Ok(s.clone());
        }
        let path = self.db_path()?;
        let s = Arc::new(Store::open(&path)?);
        Ok(self.lock().store.get_or_insert(s).clone())
    }

    /// Yalnız okuyan komutlar için ayrı, önbelleklenmeyen salt okunur bağlantı ([`Store::open_read_only`]).
    ///
    /// DB şeması bu koddan YENİYSE (Python yeni göç ekledi, ikili güncellenmedi) okuma sürer; süreç başına sürüm başına BİR
    /// kez günlüğe yazılır (sessiz değil, ama her okumada da değil).
    pub fn read_only_store(&self) -> Result<Store, StoreError> {
        let st = Store::open_read_only(&self.db_path()?)?;
        static LOGGED: std::sync::atomic::AtomicI64 = std::sync::atomic::AtomicI64::new(0);
        let v = st.schema();
        if v > crate::store::SCHEMA_VERSION
            && LOGGED.swap(v, std::sync::atomic::Ordering::SeqCst) != v
        {
            self.log(&format!(
                "DB şema sürümü {v}, bu kod {} biliyor: salt okuma sürüyor (göçler yalnız sona eklenir; ikiliyi güncelleyin)",
                crate::store::SCHEMA_VERSION
            ));
        }
        Ok(st)
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
                *self.lock().fallbacks.entry(name.to_string()).or_insert(0) += 1;
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
        if self.read_only {
            return self.read_db_ro(name, path, file_first, read_file);
        }
        if file_first {
            // DB açılamasa da dosya (doğruluk kaynağı) döner: hata üst katta dosyaya düşer
            let st = self.store()?;
            let r = read_file(path);
            if matches!(r, Read::Value(_) | Read::Lossy(_)) {
                let sg = sig(path);
                if self.lock().synced.get(name) != Some(&sg) {
                    let have = st.get_doc(name)?;
                    let same = match (&have, &r) {
                        (Some(h), Read::Value(v)) => h.py_eq(v),
                        _ => false,
                    };
                    if !same {
                        let Some(v) = for_db(&r, name)? else {
                            return Ok(r); // erişilmez: r Value ya da Lossy (Lossy for_db'de hata)
                        };
                        self.log(&if have.is_none() {
                            format!("import {name}: DB'de yoktu, dosyadan alındı")
                        } else {
                            format!("drift {name}: DB dosyaya uyduruldu")
                        });
                        st.set_doc(name, &v)?;
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
            let r = read_file(path);
            if let Some(v) = for_db(&r, name)? {
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
        if let Some(v) = for_db(&r, name)? {
            st.set_doc(name, &v)?;
        }
        Ok(r)
    }

    /// [`read_db`](Self::read_db)in salt okuma karşılığı: aynı karar, DB'ye yazım yok. `dual`: dosya (doğruluk kaynağı) okunursa
    /// o, yoksa/bozuksa DB'deki değer; `db`: DB, satır yoksa dosya (içe AKTARILMAZ). DB açılamazsa hata (üst kat dosyaya düşer).
    fn read_db_ro(
        &self,
        name: &str,
        path: &Path,
        file_first: bool,
        read_file: &dyn Fn(&Path) -> Read,
    ) -> Result<Read, StoreError> {
        let st = self.store()?;
        if file_first {
            let r = read_file(path);
            if matches!(r, Read::Value(_) | Read::Lossy(_)) {
                return Ok(r);
            }
            return Ok(st.get_doc(name)?.map_or(r, Read::Value));
        }
        if let Some(v) = st.get_doc(name)? {
            return Ok(Read::Value(v));
        }
        Ok(read_file(path))
    }

    /// `write_json`. `mode`: dosya izni (`None` = var olan korunur).
    pub fn write(
        &self,
        name: &str,
        path: &Path,
        obj: &Json,
        mode: Option<u32>,
    ) -> Result<WriteOutcome, WriteError> {
        if self.read_only {
            return Err(WriteError::ReadOnly);
        }
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
        if self.read_only || self.backend() == Backend::Files || !self.db_ok(path) {
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
        if self.read_only || self.backend() == Backend::Files || !is_tsv || !self.db_ok(path) {
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

#[cfg(test)]
mod backend_tests {
    use super::*;

    /// Salt okunur açılış: temiz kapanmış ve yazarı açık WAL DB okunur, yazma reddedilir, ana dosya değişmez.
    #[test]
    fn read_only_store_reads_wal_and_never_writes() {
        let env = crate::paths::TestEnv::new().unwrap();
        let db = env.dir().db();
        let writer = || {
            let c = rusqlite::Connection::open(&db).unwrap();
            c.query_row("PRAGMA journal_mode=WAL", [], |_| Ok(()))
                .unwrap();
            c
        };
        let c = writer();
        c.execute_batch(
            "CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL);
             INSERT INTO docs VALUES('a', '1', 1, 2.5);",
        )
        .unwrap();
        c.pragma_update(None, "user_version", crate::store::SCHEMA_VERSION)
            .unwrap();
        drop(c);
        let docs = StateDocs::isolated(env.dir().clone(), Some(Backend::Db), "");
        let ro = docs.read_only_store().unwrap();
        assert_eq!(ro.get_doc_raw("a").unwrap().as_deref(), Some("1"));
        assert!(ro.set_doc("a", &Json::parse("2").unwrap()).is_err());
        drop(ro);

        let c = writer();
        c.execute("UPDATE docs SET body='3'", []).unwrap();
        let ro = docs.read_only_store().unwrap();
        assert_eq!(ro.get_doc_raw("a").unwrap().as_deref(), Some("3"));
        let before = std::fs::read(&db).unwrap();
        // yazar açık kaldığı için WAL beklemede; okuyucu kapanışı onu ana dosyaya aktarmamalı
        drop(ro);
        assert!(std::fs::read(&db).unwrap() == before);
        drop(c);
    }

    /// Son DB yazımı başarısız belge (dosya daha yeni) ve db dışı kip damga vermez.
    #[test]
    fn db_stamp_refused_when_dirty_or_not_db() {
        let env = crate::paths::TestEnv::new().unwrap();
        let db = env.dir().db();
        let c = rusqlite::Connection::open(&db).unwrap();
        c.execute_batch(
            "CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL);
             INSERT INTO docs VALUES('instances', '{}', 1, 2.5);",
        )
        .unwrap();
        c.pragma_update(None, "user_version", crate::store::SCHEMA_VERSION)
            .unwrap();
        let path = env.dir().instances_json();
        let docs = StateDocs::isolated(env.dir().clone(), Some(Backend::Db), "");
        assert!(docs.db_stamp("instances", &path).is_some());
        assert!(docs
            .db_stamp("instances", Path::new("/etc/hosts"))
            .is_none());
        assert!(docs
            .db_stamp("hosts", &env.dir().join("hosts.json"))
            .is_none());
        assert!(docs.db_truth("instances", &path).is_some());
        docs.lock().dirty.insert("instances".into());
        assert!(docs.db_stamp("instances", &path).is_none());
        assert!(docs.db_truth("instances", &path).is_none());
        let dual = StateDocs::isolated(env.dir().clone(), Some(Backend::Dual), "");
        assert!(dual.db_stamp("instances", &path).is_none());
    }

    /// TBD#374 S2/S7: bozuk ayar dosyası son iyi kipi korur; silinen dosya `files`.
    #[test]
    fn corrupt_settings_keeps_last_good_backend() {
        let env = crate::paths::TestEnv::new().unwrap();
        let mut docs = StateDocs::new(env.dir().clone());
        docs.read_env = false;
        let path = env.dir().settings_json();
        let backend = |raw: Option<&[u8]>| {
            match raw {
                Some(r) => std::fs::write(&path, r).unwrap(),
                None => std::fs::remove_file(&path).unwrap(),
            }
            docs.lock().backend = None; // 5 sn önbelleği
            docs.backend()
        };
        assert_eq!(backend(Some(b"{yarim")), Backend::Files);
        assert_eq!(backend(Some(br#"{"store_backend": "db"}"#)), Backend::Db);
        for bad in [&b"\xff"[..], b"{yarim", b"[1]"] {
            assert_eq!(backend(Some(bad)), Backend::Db);
        }
        assert_eq!(backend(None), Backend::Files);
    }
}
