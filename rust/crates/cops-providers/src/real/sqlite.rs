//! Salt okunur SQLite okuyucuları ([`crate::LiveProbe::sqlite_cell`]/[`crate::LiveProbe::sqlite_rows`] sözleşmesi).
//!
//! Yol URI diye AYRIŞTIRILMAZ (`SQLITE_OPEN_URI` yok): `#`/`?` taşıyan yol başka dosyaya gitmez, hiçbir dosya
//! yaratılmaz. Bağlantı her sorguda açılıp kapanır; meşgul beklemesi 2 sn.

use crate::live::SqlCell;
use rusqlite::types::{Value as Sql, ValueRef};
use rusqlite::{Connection, OpenFlags};
use std::path::Path;
use std::time::Duration;

const BUSY_TIMEOUT: Duration = Duration::from_secs(2);

fn open(db: &str) -> Option<Connection> {
    // normal dosya şartı: FIFO/aygıt açılışta bloklamasın
    if !Path::new(db).is_file() {
        return None;
    }
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
    let conn = Connection::open_with_flags(db, flags).ok()?;
    conn.busy_timeout(BUSY_TIMEOUT).ok()?;
    Some(conn)
}

/// UTF-8 olmayan metin hücresi hatadır (Python `sqlite3` de düşer).
fn cell(value: ValueRef<'_>) -> Option<SqlCell> {
    Some(match value {
        ValueRef::Null => SqlCell::Null,
        ValueRef::Integer(i) => SqlCell::Int(i),
        ValueRef::Real(f) => SqlCell::Real(f),
        ValueRef::Text(t) => SqlCell::Text(std::str::from_utf8(t).ok()?.into()),
        ValueRef::Blob(b) => SqlCell::Blob(b.into()),
    })
}

pub fn sqlite_cell(db: &str, sql: &str, param: &str) -> Option<SqlCell> {
    let conn = open(db)?;
    let mut statement = conn.prepare(sql).ok()?;
    let mut rows = statement.query([param]).ok()?;
    let first = rows.next().ok()??;
    cell(first.get_ref(0).ok()?)
}

pub fn sqlite_rows(db: &str, sql: &str, params: &[SqlCell], row: &mut dyn FnMut(Vec<SqlCell>) -> bool) -> bool {
    let mut run = || -> Option<()> {
        let conn = open(db)?;
        let mut statement = conn.prepare(sql).ok()?;
        let columns = statement.column_count();
        let params = params.iter().map(|p| match p {
            SqlCell::Null => Sql::Null,
            SqlCell::Int(i) => Sql::Integer(*i),
            SqlCell::Real(f) => Sql::Real(*f),
            SqlCell::Text(s) => Sql::Text(s.clone()),
            SqlCell::Blob(b) => Sql::Blob(b.clone()),
        });
        let mut rows = statement.query(rusqlite::params_from_iter(params)).ok()?;
        while let Some(r) = rows.next().ok()? {
            let mut cells = Vec::with_capacity(columns);
            for i in 0..columns {
                cells.push(cell(r.get_ref(i).ok()?)?);
            }
            if !row(cells) {
                break;
            }
        }
        Some(())
    };
    run().is_some()
}
