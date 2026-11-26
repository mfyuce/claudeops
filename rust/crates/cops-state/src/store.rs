//! `claudeops.db` (Python `store.py`): `docs` belgeleri ve `tsv_rows` gölgesi. Rust DB OLUŞTURMAZ ve GÖÇ ÇALIŞTIRMAZ:
//! sürüm [`SCHEMA_VERSION`] değilse açılış reddedilir; yazım işlemi içinde sürüm yeniden denetlenir. Yalnız SQLite
//! (`CLAUDEOPS_DB_URL` Postgres ise [`StoreError::Unsupported`]; yanlış DB'ye sessizce yazılmaz).
use crate::json::{Json, Map};
use rusqlite::{
    params, Connection, OpenFlags, OptionalExtension, Transaction, TransactionBehavior,
};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// Bu kodun bildiği şema sürümü = Python `len(store.MIGRATIONS)` (parite testi denetler).
pub const SCHEMA_VERSION: i64 = 2;
const BUSY_TIMEOUT_MS: u64 = 5000;
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
    let u = url.trim();
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

fn check(c: &Connection) -> Result<()> {
    match version(c)? {
        SCHEMA_VERSION => Ok(()),
        found => Err(StoreError::Schema { found }),
    }
}

/// Süreç içinde paylaşılabilir (`Arc<Store>`); tek bağlantı, kilitli. Süreçler arası sıralama SQLite kilidiyle.
pub struct Store {
    path: PathBuf,
    conn: Mutex<Connection>,
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
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
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
        Ok(self
            .conn()
            .query_row("SELECT body FROM docs WHERE name=?1", [name], |r| r.get(0))
            .optional()?)
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
        let c = self.conn();
        let mut st =
            c.prepare("SELECT name FROM docs WHERE name LIKE ?1 ESCAPE '\\' ORDER BY name")?;
        let rows = st.query_map([like], |r| r.get(0))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn doc_version(&self, name: &str) -> Result<i64> {
        Ok(self
            .conn()
            .query_row("SELECT version FROM docs WHERE name=?1", [name], |r| {
                r.get(0)
            })
            .optional()?
            .unwrap_or(0))
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
            Ok(lines.len().max(1))
        })
    }

    pub fn delete_tsv(&self, file: &str) -> Result<()> {
        self.write(|tx| {
            tx.execute("DELETE FROM tsv_rows WHERE file=?1", [file])?;
            Ok(())
        })
    }

    pub fn tsv_text(&self, file: &str) -> Result<Option<String>> {
        let c = self.conn();
        let mut st = c.prepare("SELECT raw FROM tsv_rows WHERE file=?1 ORDER BY seq")?;
        let rows: Vec<String> = st
            .query_map([file], |r| r.get(0))?
            .collect::<rusqlite::Result<_>>()?;
        Ok((!rows.is_empty()).then(|| rows.concat()))
    }

    /// `tsv_rows(file, active=None)`: yalnız `kind='row'`; `active` verilirse süzülür.
    pub fn tsv_rows(&self, file: &str, active: Option<bool>) -> Result<Vec<TsvShadowRow>> {
        let c = self.conn();
        let mut q =
            "SELECT seq,active,name,cols FROM tsv_rows WHERE file=?1 AND kind='row'".to_string();
        if active.is_some() {
            q.push_str(" AND active=?2");
        }
        q.push_str(" ORDER BY seq");
        let mut st = c.prepare(&q)?;
        let map = |r: &rusqlite::Row<'_>| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
            ))
        };
        let rows: Vec<_> = match active {
            Some(a) => st.query_map(params![file, i64::from(a)], map)?,
            None => st.query_map(params![file], map)?,
        }
        .collect::<rusqlite::Result<_>>()?;
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
        let c = self.conn();
        let mut st = c.prepare("SELECT DISTINCT file FROM tsv_rows ORDER BY file")?;
        let rows = st.query_map([], |r| r.get(0))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// `schema_version()`.
    pub fn schema_version(&self) -> Result<i64> {
        Ok(version(&self.conn())?)
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

    fn log_rows(&self, sql: &str, args: impl rusqlite::Params) -> Result<Vec<LogRow>> {
        let c = self.conn();
        let mut st = c.prepare(sql)?;
        let rows: Vec<(i64, f64, String)> = st
            .query_map(args, |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .collect::<rusqlite::Result<_>>()?;
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
        let c = self.conn();
        let mut st = c.prepare("SELECT DISTINCT stream FROM log ORDER BY stream")?;
        let rows = st.query_map([], |r| r.get(0))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    // ---- dışa/içe aktarım, yedek ---------------------------------------------------------------------------------

    /// `export_all` (`cops db export`): `{"format":1, "schema_version", "exported", "docs", "tsv", "logs"}`. Yalnız okur.
    pub fn export_all(&self) -> Result<Json> {
        let mut logs = Map::new();
        for st in self.list_streams()? {
            let c = self.conn();
            let mut q = c.prepare("SELECT ts, body FROM log WHERE stream=?1 ORDER BY id")?;
            let rows: Vec<(f64, String)> = q
                .query_map([&st], |r| Ok((r.get(0)?, r.get(1)?)))?
                .collect::<rusqlite::Result<_>>()?;
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
