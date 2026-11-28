//! `claudeops.db` (Python `store.py`): `docs` belgeleri ve `tsv_rows` gölgesi. Rust DB OLUŞTURMAZ ve GÖÇ ÇALIŞTIRMAZ:
//! sürüm [`SCHEMA_VERSION`] değilse yazma açılışı reddedilir; yazım işlemi içinde sürüm yeniden denetlenir. Salt okuma
//! açılışı daha yeni sürümü de kabul eder (göçler yalnız sona eklenir; `check_read`). Yalnız SQLite
//! (`CLAUDEOPS_DB_URL` Postgres ise [`StoreError::Unsupported`]; yanlış DB'ye sessizce yazılmaz).
use crate::json::{Json, Map};
use rusqlite::{
    params, Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior,
};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// Bu kodun bildiği şema sürümü = Python `len(store.MIGRATIONS)` (parite testi denetler).
pub const SCHEMA_VERSION: i64 = 2;
/// Python `BUSY_TIMEOUT_MS`.
pub const BUSY_TIMEOUT_MS: u64 = 5000;
const BACKUP_RETRIES: usize = 120;

#[derive(Debug)]
pub enum StoreError {
    /// DB dosyası yok (Rust oluşturmaz).
    Missing(PathBuf),
    /// Şema sürümü bilinenden farklı.
    Schema {
        found: i64,
    },
    /// SQLite dışı `db_url`.
    Unsupported(String),
    Sqlite(rusqlite::Error),
    /// Belge gövdesi JSON değil.
    BadDoc(String),
    /// `import_all` girdisi Python'un istisna verdiği biçimde.
    Import(String),
    /// Dosya işlemi (yedek).
    Io(String),
}

impl StoreError {
    /// Geçici olmayan hata: bu süreç bu DB'ye hiç yazamaz.
    pub fn is_permanent(&self) -> bool {
        matches!(
            self,
            StoreError::Missing(_) | StoreError::Schema { .. } | StoreError::Unsupported(_)
        )
    }
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StoreError::Missing(p) => write!(f, "DB yok: {}", p.display()),
            StoreError::Schema { found } => write!(
                f,
                "DB sürümü {found}, bu kod {SCHEMA_VERSION} biliyor (göç Python'da)"
            ),
            StoreError::Unsupported(u) => write!(f, "desteklenmeyen db_url ({u})"),
            StoreError::Sqlite(e) => write!(f, "sqlite: {e}"),
            StoreError::BadDoc(n) => write!(f, "bozuk belge: {n}"),
            StoreError::Import(m) => write!(f, "içe aktarım: {m}"),
            StoreError::Io(m) => write!(f, "dosya: {m}"),
        }
    }
}
impl std::error::Error for StoreError {}
impl From<rusqlite::Error> for StoreError {
    fn from(e: rusqlite::Error) -> Self {
        StoreError::Sqlite(e)
    }
}

type Result<T> = std::result::Result<T, StoreError>;

/// `log` satırı.
#[derive(Debug, Clone, PartialEq)]
pub struct LogRow {
    pub id: i64,
    pub ts: f64,
    pub body: Json,
}

/// `import_all` sayıları.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ImportCounts {
    pub docs: usize,
    pub tsv: usize,
    pub logs: usize,
    pub logs_skipped: usize,
}

/// `int(x)` (JSON değeri; `TypeError`/`ValueError`/`OverflowError` = `None`).
fn py_int_of(v: &Json) -> Option<i64> {
    match v {
        Json::Bool(b) => Some(i64::from(*b)),
        Json::Int(i) => Some(*i),
        Json::Float(f) if f.is_finite() => Some(f.trunc() as i64),
        Json::Str(s) => crate::pycompat::parse_int(s).and_then(|n| n.as_i64()),
        _ => None,
    }
}

/// `float(x)`.
fn py_float_of(v: &Json) -> Option<f64> {
    match v {
        Json::Bool(b) => Some(f64::from(u8::from(*b))),
        Json::Int(_) | Json::BigInt(_) | Json::Float(_) => v.as_f64(),
        Json::Str(s) => crate::pycompat::parse_float(s),
        _ => None,
    }
}

/// Python'da yinelenebilen (liste, dize karakterleri, sözlük anahtarları değil: burada yalnız liste kabul).
fn py_iter(v: &Json) -> Option<Vec<&Json>> {
    v.as_array().map(|a| a.iter().collect())
}

/// `tsv_rows` satırı (yalnız `kind='row'`).
#[derive(Debug, Clone, PartialEq)]
pub struct TsvShadowRow {
    pub seq: i64,
    pub active: bool,
    pub name: String,
    pub rest: Vec<String>,
}

/// `CLAUDEOPS_DB_URL` -> SQLite yolu (Python `dbapi.backend_of`/`sqlite_path`).
pub fn sqlite_path_from_url(url: &str, default: &Path) -> Result<PathBuf> {
    let u = py_strip(url);
    if u.is_empty() {
        return Ok(default.to_path_buf());
    }
    if u.get(..7)
        .is_some_and(|p| p.eq_ignore_ascii_case("sqlite:"))
    {
        let rest = &u[7..];
        let rest = rest.strip_prefix("//").unwrap_or(rest);
        let rest = rest.split('?').next().unwrap_or("");
        return Ok(if rest.is_empty() {
            default.to_path_buf()
        } else {
            rest.into()
        });
    }
    // URL parola taşıyabilir: yalnız şema yazılır.
    let scheme = u.split(':').next().unwrap_or("?");
    Err(StoreError::Unsupported(scheme.to_string()))
}

fn version(c: &Connection) -> rusqlite::Result<i64> {
    let user: i64 = c.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    let has: Option<i64> = c
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    let tab: i64 = match has {
        Some(_) => c
            .query_row("SELECT version FROM schema_version WHERE id=1", [], |r| {
                r.get(0)
            })
            .optional()?
            .unwrap_or(0),
        None => 0,
    };
    Ok(user.max(tab))
}

/// Salt okunur açılışın biçimi ([`Store::open_read_only`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RoOpen {
    Plain,
    Immutable,
    Refuse,
}

/// DB başlığı (bayt 18/19 = 2: WAL) ve `-wal`/`-shm` varlığından salt okunur açılış biçimi. Başlık okunamazsa (kısa/boş
/// dosya) `Plain`: SQLite kendisi karar verir (WAL değilse yan dosya yaratmaz). Yol sembolik bağlantıysa HEDEFİN yanına
/// bakılır: SQLite yan dosyaları çözülmüş yolun yanına koyar (R-B1-2).
pub fn wal_open_mode(path: &Path) -> RoOpen {
    let real = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    match Stamp::take(&real) {
        Some(s) => s.mode(),
        None => RoOpen::Plain,
    }
}

/// immutable okumanın yarış denetimi (R-B1-1): açılıştan ÖNCE ve her sorgudan SONRA alınır; farklıysa sonuç atılır.
/// Çekirdek zaman damgası kaba olabilir (aynı adımda boyutu değiştirmeyen tek yazım kaçabilir); yazarın açılışı yan
/// dosyaları, kapanışı ana dosyayı değiştirdiğinden yan dosya varlığıyla birlikte pratikte yeterli.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Stamp {
    dev: u64,
    ino: u64,
    size: u64,
    mtime_ns: i128,
    ctime_ns: i128,
    wal_header: bool,
    wal: bool,
    shm: bool,
}

impl Stamp {
    fn take(real: &Path) -> Option<Stamp> {
        use std::io::Read;
        use std::os::unix::fs::MetadataExt;
        let side = |sfx: &str| {
            let mut p = real.as_os_str().to_owned();
            p.push(sfx);
            std::fs::symlink_metadata(PathBuf::from(p)).is_ok()
        };
        let mut f = std::fs::File::open(real).ok()?;
        let m = f.metadata().ok()?;
        let mut head = [0u8; 20];
        let wal_header = f.read_exact(&mut head).is_ok()
            && head.starts_with(b"SQLite format 3\0")
            && (head[18] == 2 || head[19] == 2);
        Some(Stamp {
            dev: m.dev(),
            ino: m.ino(),
            size: m.size(),
            mtime_ns: i128::from(m.mtime()) * 1_000_000_000 + i128::from(m.mtime_nsec()),
            ctime_ns: i128::from(m.ctime()) * 1_000_000_000 + i128::from(m.ctime_nsec()),
            wal_header,
            wal: side("-wal"),
            shm: side("-shm"),
        })
    }

    fn mode(&self) -> RoOpen {
        if !self.wal_header {
            return RoOpen::Plain;
        }
        match (self.wal, self.shm) {
            (true, true) => RoOpen::Plain,
            (false, false) => RoOpen::Immutable,
            _ => RoOpen::Refuse,
        }
    }
}

/// Damgası değişen immutable okumanın en çok kaç kez yeniden açılacağı (sonra hata: çağıran dosyaya düşer).
const RO_RETRIES: usize = 4;

/// `file:` URI (RFC 3986 yüzde kaçışı: SQLite yolda `%`yi çözer, `?`/`#` ayıraçtır).
fn sqlite_uri(path: &Path, immutable: bool) -> String {
    use std::os::unix::ffi::OsStrExt;
    // mutlak yol boş yetkiliyle (`file:///a`): `//x` biçimli yol yetkili (host) sanılmasın
    let mut s = String::from(if path.is_absolute() {
        "file://"
    } else {
        "file:"
    });
    for &b in path.as_os_str().as_bytes() {
        if b.is_ascii_alphanumeric() || b"/-._~".contains(&b) {
            s.push(char::from(b));
        } else {
            s.push_str(&format!("%{b:02X}"));
        }
    }
    s.push_str(if immutable {
        "?mode=ro&immutable=1"
    } else {
        "?mode=ro"
    });
    s
}

fn check(c: &Connection) -> Result<()> {
    match version(c)? {
        SCHEMA_VERSION => Ok(()),
        found => Err(StoreError::Schema { found }),
    }
}

/// Salt okuma açılışının şema denetimi: bilinen sürüm ya da DAHA YENİSİ. Python göçleri yalnız sona eklenir, var olan tablo
/// ve sütun değiştirilmez (`store.py` sözleşmesi); bu yüzden yeni bir göç eski okuma sorgularını bozmaz. Yine de okunan
/// `docs` sütunları açılışta hazırlanarak sınanır: yoksa `Schema` (çağıran dosya aynasına düşer ve günlüğe yazar). Daha ESKİ
/// sürüm reddedilir (göç Python'da). YAZMA açılışı ([`Store::open`]) tam eşleşme ister: bilinmeyen şemaya yazılmaz.
fn check_read(c: &Connection) -> Result<i64> {
    let found = version(c)?;
    if found == SCHEMA_VERSION || (found > SCHEMA_VERSION && c.prepare(READ_CONTRACT).is_ok()) {
        return Ok(found);
    }
    Err(StoreError::Schema { found })
}

/// Salt okuma yolunun `docs` sözleşmesi ([`check_read`]).
const READ_CONTRACT: &str = "SELECT name, body, version, updated FROM docs LIMIT 0";

/// Süreç içinde paylaşılabilir (`Arc<Store>`); tek bağlantı, kilitli. Süreçler arası sıralama SQLite kilidiyle.
pub struct Store {
    path: PathBuf,
    conn: Mutex<Connection>,
    /// Açılışta okunan şema sürümü (salt okumada [`SCHEMA_VERSION`]ten büyük olabilir).
    schema: i64,
    /// Salt okumada çözülmüş yol ve (yalnız `immutable=1` bağlantıdayken) açılış öncesi damga ([`Store::read`]).
    ro: Option<(PathBuf, Mutex<Option<Stamp>>)>,
}

impl Store {
    /// Var olan DB'yi aç (oluşturmaz, göç yapmaz).
    pub fn open(path: &Path) -> Result<Store> {
        crate::paths::guard_write(path); // açılış -wal/-shm yazar
        if !path.is_file() {
            return Err(StoreError::Missing(path.to_path_buf()));
        }
        let c = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        c.busy_timeout(std::time::Duration::from_millis(BUSY_TIMEOUT_MS))?;
        check(&c)?; // yanlış DB'ye pragma bile yazılmadan
        c.query_row("PRAGMA journal_mode=WAL", [], |_| Ok(()))?;
        c.execute_batch("PRAGMA synchronous=NORMAL")?;
        Ok(Store {
            path: path.to_path_buf(),
            conn: Mutex::new(c),
            schema: SCHEMA_VERSION,
            ro: None,
        })
    }

    /// Salt okunur açılış: DB dosyasına yazmaz, pragma değiştirmez, kapanışta WAL'ı ana dosyaya aktarmaz, YENİ DOSYA
    /// YARATMAZ. Yazma yöntemleri hata verir.
    ///
    /// WAL kipindeki DB'de SQLite'ın salt okunur bağlantısı eksik `-shm`/`-wal` dosyalarını YARATIR (unix VFS `-shm`i
    /// `O_CREAT` ile açar; ölçüldü, `wal_files_absent_creates_nothing`). Bu yüzden ([`wal_open_mode`]):
    /// - WAL değil ya da `-wal` ile `-shm` ikisi de var (açık bir yazar var): olağan `mode=ro`;
    /// - WAL ve ikisi de yok (DB'yi açık tutan yok, tüm veri ana dosyada): `immutable=1` (kilit ve yan dosya yok);
    /// - yalnız biri var (çökme artığı; kurtarma yazım ister): [`StoreError::Io`], çağıran dosyaya düşer.
    pub fn open_read_only(path: &Path) -> Result<Store> {
        if !path.is_file() {
            return Err(StoreError::Missing(path.to_path_buf()));
        }
        let real = std::fs::canonicalize(path).map_err(|e| StoreError::Io(e.to_string()))?;
        let (c, stamp, schema) = Self::ro_connect(&real)?;
        Ok(Store {
            path: path.to_path_buf(),
            conn: Mutex::new(c),
            schema,
            ro: Some((real, Mutex::new(stamp))),
        })
    }

    /// Salt okunur bağlantı + (immutable ise) açılış öncesi damga + şema. Şema denetimi de bir sorgudur: damga sonra
    /// yeniden alınır, değiştiyse güncel biçimle yeniden açılır.
    fn ro_connect(real: &Path) -> Result<(Connection, Option<Stamp>, i64)> {
        for _ in 0..RO_RETRIES {
            let s0 = Stamp::take(real);
            let immutable = match s0.map_or(RoOpen::Plain, |s| s.mode()) {
                RoOpen::Plain => false,
                RoOpen::Immutable => true,
                RoOpen::Refuse => {
                    return Err(StoreError::Io(format!(
                        "{}: WAL yan dosyalarından yalnız biri var (salt okunur açılış dosya yaratırdı)",
                        real.display()
                    )))
                }
            };
            let uri = sqlite_uri(real, immutable);
            let c = Connection::open_with_flags(
                &uri,
                OpenFlags::SQLITE_OPEN_READ_ONLY
                    | OpenFlags::SQLITE_OPEN_URI
                    | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            )?;
            c.busy_timeout(std::time::Duration::from_millis(BUSY_TIMEOUT_MS))?;
            let schema = check_read(&c);
            if !immutable {
                return Ok((c, None, schema?));
            }
            if Stamp::take(real) == s0 {
                return Ok((c, s0, schema?));
            }
        }
        Err(StoreError::Io(format!(
            "{}: salt okuma sırasında DB sürekli değişti",
            real.display()
        )))
    }

    /// Okuma sorgusu. `immutable=1` bağlantıda sorgudan sonra damga yeniden alınır; değiştiyse sonuç atılır, bağlantı güncel
    /// biçimle yeniden açılır ve sorgu yinelenir (R-B1-1). Diğer bağlantılarda doğrudan.
    fn read<T>(&self, f: impl Fn(&Connection) -> Result<T>) -> Result<T> {
        let mut c = self.conn();
        let Some((real, stamp)) = &self.ro else {
            return f(&c);
        };
        let mut stamp = stamp.lock().unwrap_or_else(|e| e.into_inner());
        for _ in 0..RO_RETRIES {
            let out = f(&c);
            let Some(s0) = *stamp else {
                return out;
            };
            if Stamp::take(real) == Some(s0) {
                return out;
            }
            let (nc, ns, _) = Self::ro_connect(real)?;
            *c = nc;
            *stamp = ns;
        }
        Err(StoreError::Io(format!(
            "{}: salt okuma sırasında DB sürekli değişti",
            real.display()
        )))
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Açılışta görülen şema sürümü.
    pub fn schema(&self) -> i64 {
        self.schema
    }

    fn conn(&self) -> std::sync::MutexGuard<'_, Connection> {
        // Zehirli kilit: bağlantı durumu SQLite'ta tutarlı (işlem düşünce ROLLBACK), devam edilir.
        self.conn.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn write<T>(&self, f: impl FnOnce(&Transaction<'_>) -> Result<T>) -> Result<T> {
        let mut c = self.conn();
        let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
        check(&tx)?;
        let out = f(&tx)?;
        tx.commit()?;
        Ok(out)
    }

    /// Ham gövde (JSON metni).
    pub fn get_doc_raw(&self, name: &str) -> Result<Option<String>> {
        self.read(|c| {
            Ok(
                c.query_row("SELECT body FROM docs WHERE name=?1", [name], |r| r.get(0))
                    .optional()?,
            )
        })
    }

    pub fn get_doc(&self, name: &str) -> Result<Option<Json>> {
        self.get_doc_raw(name)?
            .map(|b| Json::parse(&b).map_err(|_| StoreError::BadDoc(name.to_string())))
            .transpose()
    }

    fn put(c: &Connection, name: &str, body: &str) -> Result<i64> {
        c.execute(
            "INSERT INTO docs(name, body, version, updated) VALUES(?1,?2,1,?3) \
             ON CONFLICT(name) DO UPDATE SET body=excluded.body, version=docs.version+1, updated=excluded.updated",
            params![name, body, crate::now()],
        )?;
        Ok(
            c.query_row("SELECT version FROM docs WHERE name=?1", [name], |r| {
                r.get(0)
            })?,
        )
    }

    /// Belgeyi tümden değiştirir; yeni sürüm numarası.
    pub fn set_doc(&self, name: &str, obj: &Json) -> Result<i64> {
        let body = obj.to_compact();
        self.write(|tx| Self::put(tx, name, &body))
    }

    /// Atomik oku-değiştir-yaz (tek `BEGIN IMMEDIATE`). `f` `None` dönerse yazılmaz. `f` içinde uzun iş / başka DB çağrısı YOK.
    pub fn update_doc(
        &self,
        name: &str,
        default: Json,
        f: impl FnOnce(Json) -> Option<Json>,
    ) -> Result<Json> {
        self.write(|tx| {
            let body: Option<String> = tx
                .query_row("SELECT body FROM docs WHERE name=?1", [name], |r| r.get(0))
                .optional()?;
            let cur = match body {
                Some(b) => Json::parse(&b).map_err(|_| StoreError::BadDoc(name.to_string()))?,
                None => default,
            };
            match f(cur.clone()) {
                None => Ok(cur),
                Some(new) => {
                    Self::put(tx, name, &new.to_compact())?;
                    Ok(new)
                }
            }
        })
    }

    pub fn delete_doc(&self, name: &str) -> Result<bool> {
        self.write(|tx| Ok(tx.execute("DELETE FROM docs WHERE name=?1", [name])? > 0))
    }

    pub fn list_docs(&self, prefix: &str) -> Result<Vec<String>> {
        let like = prefix
            .replace('\\', "\\\\")
            .replace('%', "\\%")
            .replace('_', "\\_")
            + "%";
        self.read(|c| {
            let mut st =
                c.prepare("SELECT name FROM docs WHERE name LIKE ?1 ESCAPE '\\' ORDER BY name")?;
            let rows = st.query_map([&like], |r| r.get(0))?;
            Ok(rows.collect::<rusqlite::Result<_>>()?)
        })
    }

    /// `_doc_stamp`: (sürüm, yazım anının bitleri); satır yoksa `None`. Sil + yeniden yaz sürümü 1'den başlatır:
    /// yazım anı ayırır.
    pub(crate) fn doc_stamp(&self, name: &str) -> Result<Option<(i64, u64)>> {
        self.read(|c| {
            Ok(c.query_row(
                "SELECT version, updated FROM docs WHERE name=?1",
                [name],
                |r| Ok((r.get(0)?, r.get::<_, f64>(1)?.to_bits())),
            )
            .optional()?)
        })
    }

    pub fn doc_version(&self, name: &str) -> Result<i64> {
        self.read(|c| {
            Ok(
                c.query_row("SELECT version FROM docs WHERE name=?1", [name], |r| {
                    r.get(0)
                })
                .optional()?
                .unwrap_or(0),
            )
        })
    }

    /// Dosyanın TÜM satırlarını tek işlemde değiştirir (Python `replace_tsv` ile aynı satır ayrıştırma).
    pub fn replace_tsv(&self, file: &str, text: &str) -> Result<usize> {
        let lines = split_lines_keepends(text);
        self.write(|tx| {
            tx.execute("DELETE FROM tsv_rows WHERE file=?1", [file])?;
            let mut ins = tx.prepare(
                "INSERT INTO tsv_rows(file,seq,kind,active,name,c1,c2,c3,c4,cols,raw) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
            )?;
            let none: Option<&str> = None;
            for (seq, line) in lines.iter().enumerate() {
                let stripped = py_strip(line);
                let active = !stripped.starts_with('#');
                let bare = if active { stripped } else { &stripped[1..] };
                let parts: Vec<&str> = py_strip(bare).split('\t').collect();
                let kind = if stripped.is_empty() {
                    "blank"
                } else if parts[0].is_empty() {
                    "comment"
                } else {
                    "row"
                };
                if kind == "row" {
                    let rest = &parts[1..];
                    let cols = Json::Array(rest.iter().map(|s| Json::from(*s)).collect()).to_compact();
                    let c = |i: usize| rest.get(i).copied();
                    ins.execute(params![file, seq as i64, kind, i64::from(active), parts[0], c(0), c(1), c(2), c(3), cols, line])?;
                } else {
                    ins.execute(params![file, seq as i64, kind, none, none, none, none, none, none, none, line])?;
                }
            }
            if lines.is_empty() {
                // boş dosya "hiç eşitlenmemiş" ile karışmasın
                ins.execute(params![file, 0i64, "empty", none, none, none, none, none, none, none, ""])?;
            }
            Ok(lines.len()) // "empty" satırı sayılmaz (Python `n_rows`)
        })
    }

    pub fn delete_tsv(&self, file: &str) -> Result<()> {
        self.write(|tx| {
            tx.execute("DELETE FROM tsv_rows WHERE file=?1", [file])?;
            Ok(())
        })
    }

    pub fn tsv_text(&self, file: &str) -> Result<Option<String>> {
        let rows: Vec<String> = self.read(|c| {
            let mut st = c.prepare("SELECT raw FROM tsv_rows WHERE file=?1 ORDER BY seq")?;
            let rows = st
                .query_map([file], |r| r.get(0))?
                .collect::<rusqlite::Result<_>>()?;
            Ok(rows)
        })?;
        Ok((!rows.is_empty()).then(|| rows.concat()))
    }

    /// `tsv_rows(file, active=None)`: yalnız `kind='row'`; `active` verilirse süzülür.
    pub fn tsv_rows(&self, file: &str, active: Option<bool>) -> Result<Vec<TsvShadowRow>> {
        let mut q =
            "SELECT seq,active,name,cols FROM tsv_rows WHERE file=?1 AND kind='row'".to_string();
        if active.is_some() {
            q.push_str(" AND active=?2");
        }
        q.push_str(" ORDER BY seq");
        let map = |r: &rusqlite::Row<'_>| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
            ))
        };
        let rows: Vec<_> = self.read(|c| {
            let mut st = c.prepare(&q)?;
            let rows = match active {
                Some(a) => st.query_map(params![file, i64::from(a)], map)?,
                None => st.query_map(params![file], map)?,
            }
            .collect::<rusqlite::Result<_>>()?;
            Ok(rows)
        })?;
        let mut out = Vec::new();
        for (seq, active, name, cols) in rows {
            let bad = || StoreError::BadDoc(file.to_string());
            let rest = match Json::parse(&cols).map_err(|_| bad())? {
                Json::Array(a) => a
                    .into_iter()
                    .map(|x| match x {
                        Json::Str(s) => Ok(s),
                        _ => Err(bad()),
                    })
                    .collect::<Result<Vec<_>>>()?,
                _ => return Err(bad()),
            };
            out.push(TsvShadowRow {
                seq,
                active: active != 0,
                name,
                rest,
            });
        }
        Ok(out)
    }

    /// `tsv_files`.
    pub fn tsv_files(&self) -> Result<Vec<String>> {
        self.read(|c| {
            let mut st = c.prepare("SELECT DISTINCT file FROM tsv_rows ORDER BY file")?;
            let rows = st.query_map([], |r| r.get(0))?;
            Ok(rows.collect::<rusqlite::Result<_>>()?)
        })
    }

    /// `schema_version()`.
    pub fn schema_version(&self) -> Result<i64> {
        self.read(|c| Ok(version(c)?))
    }

    // ---- log (ekleme günlüğü) ----------------------------------------------------------------------------------

    /// `append_log`: yeni satırın kimliği.
    pub fn append_log(&self, stream: &str, obj: &Json) -> Result<i64> {
        let body = obj.to_compact();
        self.write(|tx| {
            tx.execute(
                "INSERT INTO log(stream, ts, body) VALUES(?1,?2,?3)",
                params![stream, crate::now(), body],
            )?;
            Ok(tx.last_insert_rowid())
        })
    }

    fn log_rows(&self, sql: &str, args: impl rusqlite::Params + Copy) -> Result<Vec<LogRow>> {
        let rows: Vec<(i64, f64, String)> = self.read(|c| {
            let mut st = c.prepare(sql)?;
            let rows = st
                .query_map(args, |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
                .collect::<rusqlite::Result<_>>()?;
            Ok(rows)
        })?;
        rows.into_iter()
            .map(|(id, ts, body)| {
                let v = Json::parse(&body).map_err(|_| StoreError::BadDoc(format!("log#{id}")))?;
                Ok(LogRow { id, ts, body: v })
            })
            .collect()
    }

    /// `read_log(stream, limit=100, after_id=0)`: en eskiden yeniye.
    pub fn read_log(&self, stream: &str, limit: i64, after_id: i64) -> Result<Vec<LogRow>> {
        self.log_rows(
            "SELECT id, ts, body FROM log WHERE stream=?1 AND id>?2 ORDER BY id LIMIT ?3",
            params![stream, after_id, limit],
        )
    }

    /// `tail_log(stream, n=100)`: son `n` satır, en eskiden yeniye.
    pub fn tail_log(&self, stream: &str, n: i64) -> Result<Vec<LogRow>> {
        let mut rows = self.log_rows(
            "SELECT id, ts, body FROM log WHERE stream=?1 ORDER BY id DESC LIMIT ?2",
            params![stream, n],
        )?;
        rows.reverse();
        Ok(rows)
    }

    /// `trim_log(stream, keep)`: en yeni `keep` satır kalır; silinen sayı.
    pub fn trim_log(&self, stream: &str, keep: i64) -> Result<usize> {
        self.write(|tx| {
            Ok(tx.execute(
                "DELETE FROM log WHERE stream=?1 AND id <= COALESCE((SELECT id FROM log WHERE stream=?2 ORDER BY id DESC LIMIT 1 OFFSET ?3), 0)",
                params![stream, stream, keep],
            )?)
        })
    }

    /// `list_streams`.
    pub fn list_streams(&self) -> Result<Vec<String>> {
        self.read(|c| {
            let mut st = c.prepare("SELECT DISTINCT stream FROM log ORDER BY stream")?;
            let rows = st.query_map([], |r| r.get(0))?;
            Ok(rows.collect::<rusqlite::Result<_>>()?)
        })
    }

    // ---- dışa/içe aktarım, yedek ---------------------------------------------------------------------------------

    /// `export_all` (`cops db export`): `{"format":1, "schema_version", "exported", "docs", "tsv", "logs"}`. Yalnız okur.
    pub fn export_all(&self) -> Result<Json> {
        let mut logs = Map::new();
        for st in self.list_streams()? {
            let rows: Vec<(f64, String)> = self.read(|c| {
                let mut q = c.prepare("SELECT ts, body FROM log WHERE stream=?1 ORDER BY id")?;
                let rows = q
                    .query_map([&st], |r| Ok((r.get(0)?, r.get(1)?)))?
                    .collect::<rusqlite::Result<_>>()?;
                Ok(rows)
            })?;
            let mut arr = Vec::with_capacity(rows.len());
            for (ts, body) in rows {
                let v = Json::parse(&body).map_err(|_| StoreError::BadDoc(format!("log:{st}")))?;
                arr.push(Json::Array(vec![Json::Float(ts), v]));
            }
            logs.insert(st, Json::Array(arr));
        }
        let mut tsv = Map::new();
        for f in self.tsv_files()? {
            let t = self.tsv_text(&f)?.map_or(Json::Null, Json::from);
            tsv.insert(f, t);
        }
        let mut m = Map::new();
        m.insert("format".into(), Json::Int(1));
        m.insert("schema_version".into(), Json::Int(self.schema_version()?));
        m.insert("exported".into(), Json::Float(crate::now()));
        m.insert("docs".into(), Json::Object(self.export_docs()?));
        m.insert("tsv".into(), Json::Object(tsv));
        m.insert("logs".into(), Json::Object(logs));
        Ok(Json::Object(m))
    }

    /// `import_all(data)`: belgeler ve tsv TAMAMEN değişir; günlük akışı yalnız boşsa eklenir. Python gibi adım adım yazar:
    /// ortada hata olursa önceki adımlar yazılmış kalır (Python istisnasıyla aynı yerde [`StoreError::Import`]).
    pub fn import_all(&self, data: &Json) -> Result<ImportCounts> {
        let imp = |m: &str| StoreError::Import(m.to_string());
        let get = |k: &str| data.get(k).filter(|v| v.truthy());
        let format = match get("format") {
            None => 0,
            Some(v) => py_int_of(v).ok_or_else(|| imp("format"))?,
        };
        if data.as_object().is_none() {
            return Err(imp("nesne değil"));
        }
        if format != 1 {
            return Err(imp("desteklenmeyen dışa aktarım biçimi"));
        }
        let mut n = ImportCounts::default();
        let items = |k: &str| -> Result<Vec<(String, Json)>> {
            match get(k) {
                None => Ok(Vec::new()),
                Some(Json::Object(m)) => {
                    Ok(m.iter().map(|(a, b)| (a.clone(), b.clone())).collect())
                }
                Some(_) => Err(imp(k)),
            }
        };
        for (name, obj) in items("docs")? {
            self.set_doc(&name, &obj)?;
            n.docs += 1;
        }
        for (f, text) in items("tsv")? {
            match text {
                Json::Null => {}
                Json::Str(t) => {
                    self.replace_tsv(&f, &t)?;
                    n.tsv += 1;
                }
                _ => return Err(imp("tsv")),
            }
        }
        for (st, rows) in items("logs")? {
            let exists: Option<i64> = self
                .conn()
                .query_row("SELECT 1 FROM log WHERE stream=?1 LIMIT 1", [&st], |r| {
                    r.get(0)
                })
                .optional()?;
            if exists.is_some() {
                n.logs_skipped += 1;
                continue;
            }
            let rows = py_iter(&rows).ok_or_else(|| imp("logs"))?;
            let mut parsed = Vec::with_capacity(rows.len());
            for r in rows {
                let pair = py_iter(r)
                    .filter(|p| p.len() == 2)
                    .ok_or_else(|| imp("logs"))?;
                let ts = py_float_of(pair[0]).ok_or_else(|| imp("logs ts"))?;
                parsed.push((ts, pair[1].to_compact()));
            }
            self.write(|tx| {
                let mut ins = tx.prepare("INSERT INTO log(stream, ts, body) VALUES(?1,?2,?3)")?;
                for (ts, body) in &parsed {
                    ins.execute(params![st, ts, body])?;
                }
                Ok(())
            })?;
            n.logs += parsed.len();
        }
        Ok(n)
    }

    /// `backup(dest)`: SQLite yedek API'siyle tutarlı anlık kopya; hedef 0600, aynı dizinde geçici dosya + fsync + rename.
    pub fn backup(&self, dest: &Path) -> Result<()> {
        crate::paths::guard_write(dest);
        let dir = match dest.parent() {
            Some(p) if !p.as_os_str().is_empty() => p.to_path_buf(),
            _ => PathBuf::from("."),
        };
        let base = dest
            .file_name()
            .map_or_else(|| "db".into(), |f| f.to_string_lossy().into_owned());
        let tmp = crate::fsutil::create_unique(&dir, &format!("{base}."), ".tmp")
            .map_err(|e| StoreError::Io(e.to_string()))?;
        let res = (|| -> Result<()> {
            {
                let mut out = Connection::open(&tmp)?;
                let src = self.conn();
                let b = rusqlite::backup::Backup::new(&src, &mut out)?;
                // Python `backup(pages=-1, sleep=0.25)`: tek adım; meşgul/kilitliyse bekleyip yeniden (burada SINIRLI: 30 sn)
                let mut done = false;
                for _ in 0..BACKUP_RETRIES {
                    match b.step(-1)? {
                        rusqlite::backup::StepResult::Done => {
                            done = true;
                            break;
                        }
                        _ => std::thread::sleep(std::time::Duration::from_millis(250)),
                    }
                }
                if !done {
                    return Err(StoreError::Io("yedek: DB 30 sn meşgul".into()));
                }
            }
            let f = std::fs::File::open(&tmp).map_err(|e| StoreError::Io(e.to_string()))?;
            f.sync_all().map_err(|e| StoreError::Io(e.to_string()))?;
            std::fs::rename(&tmp, dest).map_err(|e| StoreError::Io(e.to_string()))?;
            Ok(())
        })();
        if res.is_err() {
            // geçici dosya sızmasın; silme hatası asıl hatayı örtmesin
            let _ = std::fs::remove_file(&tmp);
        }
        res
    }

    /// `{ad: belge}` (tanı ve parite testleri).
    pub fn export_docs(&self) -> Result<Map> {
        let mut m = Map::new();
        for n in self.list_docs("")? {
            if let Some(v) = self.get_doc(&n)? {
                m.insert(n, v);
            }
        }
        Ok(m)
    }
}

pub(crate) use crate::pycompat::strip as py_strip;

/// Python `str.splitlines(keepends=True)`.
pub(crate) fn split_lines_keepends(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = text.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if !matches!(
            c,
            '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}'
                ..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
        ) {
            continue;
        }
        let mut end = i + c.len_utf8();
        if c == '\r' && it.peek().is_some_and(|&(_, n)| n == '\n') {
            it.next();
            end += 1;
        }
        out.push(&text[start..end]);
        start = end;
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Python `dbapi.connect`: WAL, `synchronous=NORMAL`, `busy_timeout`. Bağlantı ayarları dışarıdan görülemediği için
    /// birim testi; Python tarafının aynı üç değeri `tests/parity_store.rs::connection_pragmas_python`ta.
    #[test]
    fn open_sets_pragmas() {
        let env = crate::paths::TestEnv::new().unwrap();
        let path = env.dir().db();
        Connection::open(&path)
            .unwrap()
            .execute_batch("PRAGMA user_version=2")
            .unwrap();
        let s = Store::open(&path).unwrap();
        let c = s.conn();
        let get = |q: &str| -> String {
            c.query_row(q, [], |r| r.get::<_, rusqlite::types::Value>(0))
                .map(|v| format!("{v:?}"))
                .unwrap()
        };
        assert_eq!(get("PRAGMA journal_mode"), "Text(\"wal\")");
        assert_eq!(get("PRAGMA synchronous"), "Integer(1)");
        assert_eq!(
            get("PRAGMA busy_timeout"),
            format!("Integer({BUSY_TIMEOUT_MS})")
        );
    }

    fn listing(dir: &Path) -> Vec<String> {
        let mut v: Vec<String> = std::fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        v.sort();
        v
    }

    /// Kapalı (yan dosyasız) WAL DB: `docs` satırı olan, sürümü doğru.
    fn closed_wal_db(dir: &Path) -> PathBuf {
        let path = dir.join("claudeops.db");
        let c = Connection::open(&path).unwrap();
        c.query_row("PRAGMA journal_mode=WAL", [], |_| Ok(()))
            .unwrap();
        c.execute_batch(
            "CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL);
             INSERT INTO docs VALUES('a', '{\"x\": 1}', 1, 2.5);
             PRAGMA user_version=2;",
        )
        .unwrap();
        drop(c);
        path
    }

    /// B1 salt okuma kipi: yan dosyası olmayan WAL DB'yi okumak DİZİNE dosya eklemez. Karşılaştırma: SQLite'ın olağan
    /// `mode=ro` açılışı aynı durumda `-shm`/`-wal` YARATIR (bu kanıt kırmızıya dönerse SQLite davranışı değişmiştir ve
    /// `immutable` dalı gereksizdir; test ikisini birlikte gösterir).
    #[test]
    fn wal_files_absent_creates_nothing() {
        let env = crate::paths::TestEnv::new().unwrap();
        let dir = env.root().join("ro");
        std::fs::create_dir_all(&dir).unwrap();
        let path = closed_wal_db(&dir);
        assert_eq!(listing(&dir), vec!["claudeops.db"]);
        assert_eq!(wal_open_mode(&path), RoOpen::Immutable);
        let s = Store::open_read_only(&path).unwrap();
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("{\"x\": 1}"));
        assert!(s.set_doc("a", &Json::Int(2)).is_err());
        drop(s);
        assert_eq!(listing(&dir), vec!["claudeops.db"]);

        // ham salt okunur açılış (eski davranış) aynı DB'de yan dosya yaratır
        let raw = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        let _: i64 = raw
            .query_row("SELECT count(*) FROM docs", [], |r| r.get(0))
            .unwrap();
        drop(raw);
        assert_ne!(
            listing(&dir),
            vec!["claudeops.db"],
            "olağan mode=ro artık yan dosya yaratmıyor: immutable dalını yeniden değerlendir"
        );
    }

    /// R-B1-1: `immutable=1` bağlantısı açıkken bir yazar gelip yazar, kapanışta WAL'ı ana dosyaya aktarıp yan dosyaları
    /// siler. immutable bağlantı değişikliği görmez (kilit/değişiklik denetimi yok): sorgu sonrası damga farklıysa sonuç
    /// atılmalı ve güncel biçimde yeniden okunmalı. Yan dosya yaratmama sözleşmesi korunur.
    #[test]
    fn immutable_read_detects_writer_that_came_and_went() {
        let env = crate::paths::TestEnv::new().unwrap();
        let dir = env.root().join("ro3");
        std::fs::create_dir_all(&dir).unwrap();
        let path = closed_wal_db(&dir);
        let s = Store::open_read_only(&path).unwrap();
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("{\"x\": 1}"));
        std::thread::sleep(std::time::Duration::from_millis(20)); // çekirdek zaman damgası adımı
        let w = Connection::open(&path).unwrap();
        w.execute("UPDATE docs SET body='{\"x\": 2}'", []).unwrap();
        drop(w);
        assert_eq!(listing(&dir), vec!["claudeops.db"]);
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("{\"x\": 2}"));
        drop(s);
        assert_eq!(listing(&dir), vec!["claudeops.db"]);
    }

    /// R-B1-1 doğal yarış (gözden geçirme deneyi e7 benzeri): yazar sürekli açıp yazıp kapanırken her salt okunur
    /// okuma ya tutarlı bir nesil görür ya da hata verir (çağıran dosyaya düşer); karışık nesil YOK.
    #[test]
    fn immutable_reads_never_mix_generations_under_writer() {
        let env = crate::paths::TestEnv::new().unwrap();
        let dir = env.root().join("ro4");
        std::fs::create_dir_all(&dir).unwrap();
        let path = closed_wal_db(&dir);
        let body = |g: usize| {
            let v: Vec<String> = (0..3000).map(|_| g.to_string()).collect();
            format!("[{}]", v.join(","))
        };
        {
            let w = Connection::open(&path).unwrap();
            w.execute("UPDATE docs SET body=?1", [body(0)]).unwrap();
        }
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let wp = path.clone();
        let st = stop.clone();
        let writer = std::thread::spawn(move || {
            let mut g = 1;
            while !st.load(std::sync::atomic::Ordering::Relaxed) {
                let w = Connection::open(&wp).unwrap();
                w.busy_timeout(std::time::Duration::from_secs(5)).unwrap();
                w.execute("UPDATE docs SET body=?1", [body(g)]).unwrap();
                drop(w);
                g += 1;
            }
        });
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(1500);
        let (mut ok, mut mixed) = (0, 0);
        while std::time::Instant::now() < deadline {
            let Ok(s) = Store::open_read_only(&path) else {
                continue;
            };
            let Ok(Some(raw)) = s.get_doc_raw("a") else {
                continue;
            };
            let mut it = raw.trim_matches(['[', ']']).split(',');
            let first = it.next().unwrap_or_default().to_string();
            if raw.matches(',').count() == 2999 && it.all(|x| x == first) {
                ok += 1;
            } else {
                mixed += 1;
            }
        }
        stop.store(true, std::sync::atomic::Ordering::Relaxed);
        writer.join().unwrap();
        assert_eq!(mixed, 0, "karışık nesil okundu ({ok} tutarlı)");
        assert!(ok > 0);
    }

    /// R-B1-2: DB yolu sembolik bağlantıysa SQLite yan dosyaları HEDEFİN yanına koyar; açılış biçimi hedefe bakmalı. Aksi
    /// hâlde açık yazar varken `Immutable` seçilir ve yazarın WAL'daki işlemi görülmez (kalıcı bayat okuma).
    #[test]
    fn symlinked_db_checks_side_files_next_to_target() {
        let env = crate::paths::TestEnv::new().unwrap();
        let a = env.root().join("sa");
        let b = env.root().join("sb");
        std::fs::create_dir_all(&a).unwrap();
        std::fs::create_dir_all(&b).unwrap();
        let real = closed_wal_db(&a);
        let link = b.join("link.db");
        std::os::unix::fs::symlink(&real, &link).unwrap();
        let w = Connection::open(&link).unwrap();
        w.execute("UPDATE docs SET body='2'", []).unwrap();
        assert_eq!(
            listing(&a),
            vec!["claudeops.db", "claudeops.db-shm", "claudeops.db-wal"]
        );
        assert_eq!(listing(&b), vec!["link.db"]);
        assert_eq!(wal_open_mode(&link), RoOpen::Plain);
        let s = Store::open_read_only(&link).unwrap();
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("2"));
        drop(s);
        drop(w);
        assert_eq!(listing(&b), vec!["link.db"]);
    }

    /// Açık yazar varken (yan dosyalar mevcut) olağan salt okunur bağlantı; yazarın son işlemi görülür, dosya listesi
    /// değişmez. Yan dosyalardan yalnız biri varsa açılış reddedilir (dosya yaratmamak için).
    #[test]
    fn wal_with_live_writer_reads_latest_and_half_state_refuses() {
        let env = crate::paths::TestEnv::new().unwrap();
        let dir = env.root().join("ro2");
        std::fs::create_dir_all(&dir).unwrap();
        let path = closed_wal_db(&dir);
        let w = Connection::open(&path).unwrap();
        w.execute("UPDATE docs SET body='2'", []).unwrap();
        let before = listing(&dir);
        assert_eq!(
            before,
            vec!["claudeops.db", "claudeops.db-shm", "claudeops.db-wal"]
        );
        assert_eq!(wal_open_mode(&path), RoOpen::Plain);
        let s = Store::open_read_only(&path).unwrap();
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("2"));
        drop(s);
        assert_eq!(listing(&dir), before);
        drop(w);
        std::fs::write(dir.join("claudeops.db-wal"), b"").unwrap();
        assert_eq!(wal_open_mode(&path), RoOpen::Refuse);
        assert!(matches!(
            Store::open_read_only(&path),
            Err(StoreError::Io(_))
        ));
        assert_eq!(listing(&dir), vec!["claudeops.db", "claudeops.db-wal"]);
    }

    /// Şema sürümü: salt okuma daha yeni sürümü (okunan `docs` sütunları yerindeyse) kabul eder, eskisini ve sütunu
    /// eksik yenisini reddeder; yazma açılışı yalnız tam eşleşme.
    #[test]
    fn read_only_accepts_newer_schema_with_the_docs_contract() {
        let env = crate::paths::TestEnv::new().unwrap();
        let db = |sub: &str, ver: i64, docs: &str| {
            let dir = env.root().join(sub);
            std::fs::create_dir_all(&dir).unwrap();
            let path = dir.join("claudeops.db");
            let c = Connection::open(&path).unwrap();
            c.execute_batch(&format!(
                "CREATE TABLE docs({docs}); INSERT INTO docs(name, body) VALUES('a', '{{\"x\": 1}}');
                 CREATE TABLE yeni(x); PRAGMA user_version={ver};"
            ))
            .unwrap();
            drop(c);
            path
        };
        let full = "name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL";
        let newer = db("yeni", SCHEMA_VERSION + 1, full);
        let s = Store::open_read_only(&newer).unwrap();
        assert_eq!(s.schema(), SCHEMA_VERSION + 1);
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("{\"x\": 1}"));
        assert!(
            matches!(Store::open(&newer), Err(StoreError::Schema { found }) if found == SCHEMA_VERSION + 1)
        );
        let older = db("eski", SCHEMA_VERSION - 1, full);
        assert!(matches!(
            Store::open_read_only(&older),
            Err(StoreError::Schema { .. })
        ));
        let broken = db(
            "bozuk",
            SCHEMA_VERSION + 1,
            "name TEXT PRIMARY KEY, body TEXT",
        );
        assert!(matches!(
            Store::open_read_only(&broken),
            Err(StoreError::Schema { .. })
        ));
        let same = db("ayni", SCHEMA_VERSION, full);
        assert_eq!(
            Store::open_read_only(&same).unwrap().schema(),
            SCHEMA_VERSION
        );
    }

    /// Yolda `%`, `?`, `#`, boşluk ve UTF-8: URI kaçışı doğru dosyayı açar.
    #[test]
    fn read_only_uri_escapes_path() {
        let env = crate::paths::TestEnv::new().unwrap();
        let dir = env.root().join("a %2F?b#ç");
        std::fs::create_dir_all(&dir).unwrap();
        let path = closed_wal_db(&dir);
        let s = Store::open_read_only(&path).unwrap();
        assert_eq!(s.get_doc_raw("a").unwrap().as_deref(), Some("{\"x\": 1}"));
        assert!(sqlite_uri(Path::new("//x/y"), false).starts_with("file:////x/y"));
    }
}
