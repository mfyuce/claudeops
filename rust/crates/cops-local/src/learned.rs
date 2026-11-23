//! copsd'nin kendi yazdığı tablo: `rootrel_learned` (yol kökü öğrenme: ilk yol parçası -> mount kimliği).
//! `claudeops.db` içinde, Python göç listesinden BAĞIMSIZ (`CREATE TABLE IF NOT EXISTS`); yazan tek taraf copsd.
//! WAL + busy_timeout; Python `docs` tablosuna dokunulmaz.

use rusqlite::{params, Connection};
use std::collections::HashMap;
use std::path::Path;

fn open(db: &Path) -> rusqlite::Result<Connection> {
    let c = Connection::open(db)?;
    c.busy_timeout(std::time::Duration::from_secs(5))?;
    let _ = c.pragma_update(None, "journal_mode", "WAL");
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS rootrel_learned (
            seg TEXT PRIMARY KEY,
            mount_id TEXT NOT NULL,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )",
    )?;
    Ok(c)
}

/// Tüm satırlar (seg -> mount_id).
pub fn load(db: &Path) -> rusqlite::Result<HashMap<String, String>> {
    let c = open(db)?;
    let mut st = c.prepare("SELECT seg, mount_id FROM rootrel_learned")?;
    let rows = st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
    rows.collect()
}

/// Tek satır yaz/güncelle.
pub fn upsert(db: &Path, seg: &str, id: &str) -> rusqlite::Result<()> {
    let c = open(db)?;
    c.execute(
        "INSERT INTO rootrel_learned (seg, mount_id) VALUES (?1, ?2)
         ON CONFLICT(seg) DO UPDATE SET mount_id=excluded.mount_id, updated_at=strftime('%s','now')",
        params![seg, id],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_and_update() {
        let d = tempfile::tempdir().unwrap();
        let f = d.path().join("t.db");
        assert!(load(&f).unwrap().is_empty());
        upsert(&f, "api", "gw").unwrap();
        upsert(&f, "v1", "rancher").unwrap();
        upsert(&f, "api", "grafana").unwrap();
        let m = load(&f).unwrap();
        assert_eq!(m.len(), 2);
        assert_eq!(m["api"], "grafana");
    }
}
