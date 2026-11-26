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

    pub fn tsv_rows(&self, file: &str) -> Result<Vec<TsvShadowRow>> {
        let c = self.conn();
        let mut st = c.prepare(
            "SELECT seq,active,name,cols FROM tsv_rows WHERE file=?1 AND kind='row' ORDER BY seq",
        )?;
        let rows = st.query_map([file], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (seq, active, name, cols) = row?;
            let rest = Json::parse(&cols)
                .ok()
                .and_then(|j| {
                    j.as_array().map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect()
                    })
                })
                .ok_or_else(|| StoreError::BadDoc(file.to_string()))?;
            out.push(TsvShadowRow {
                seq,
                active: active != 0,
                name,
                rest,
            });
        }
        Ok(out)
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

/// Python `str.isspace` kümesi: Unicode boşlukları + U+001C..U+001F.
fn py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `str.strip()`.
pub(crate) fn py_strip(s: &str) -> &str {
    s.trim_matches(py_space)
}

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
