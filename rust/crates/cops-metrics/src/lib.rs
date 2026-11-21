//! Metrik deposu: kendi `metrics.db` (WAL, 0600, `user_version` göçleri). Tek yazım yolu copsd (`POST /api/metrics/points`).
//! Şema: `series(id, name, key, owner, unit)` + `points(series_id, ts, value, meta_json)`. `owner` çok kullanıcı için baştan var
//! (bugün hep ''). Depo erişimi `Store` arkasındadır: PG'ye geçiş yalnız bu kutuyu değiştirir (uç ve çağıranlar aynı kalır).
//! NOT (sqlx yerine rusqlite): sahibin "sqlx" tercihi, `cops-local` ile AYNI `libsqlite3-sys` bağlantısı gerektiği için ertelendi
//! (sqlx 0.8 libsqlite3-sys 0.30, rusqlite 0.37 ise 0.35 ister; Cargo bir graf içinde iki sqlite3 bağlantısını reddeder). TBD'de.

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Mutex;

const MIGRATIONS: [&str; 1] = ["
CREATE TABLE series(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  key TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  UNIQUE(name, key, owner));
CREATE TABLE points(
  series_id INTEGER NOT NULL REFERENCES series(id),
  ts REAL NOT NULL,
  value REAL NOT NULL,
  meta_json TEXT);
CREATE INDEX points_series_ts ON points(series_id, ts);
"];

pub struct Store {
    conn: Mutex<Connection>,
}

/// Bir nokta: `POST /api/metrics/points` gövdesindeki dizi elemanı.
pub struct Point {
    pub name: String,
    pub key: String,
    pub owner: String,
    pub unit: String,
    pub ts: f64,
    pub value: f64,
    pub meta: Option<String>,
}

fn s(v: &Value, k: &str) -> String {
    v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string()
}

/// JSON nesnesi -> Point. `name` zorunlu (<=120 kar.), `value` sayı, `ts` yoksa `now`.
pub fn parse_point(v: &Value, now: f64) -> Result<Point, String> {
    let name = s(v, "name");
    if name.is_empty() || name.len() > 120 {
        return Err("bad name".into());
    }
    let value = v.get("value").and_then(|x| x.as_f64()).filter(|x| x.is_finite()).ok_or("bad value")?;
    let ts = match v.get("ts") {
        None | Some(Value::Null) => now,
        Some(t) => t.as_f64().filter(|x| x.is_finite() && *x > 0.0).ok_or("bad ts")?,
    };
    let key = s(v, "key");
    if key.len() > 200 {
        return Err("bad key".into());
    }
    let meta = match v.get("meta") {
        None | Some(Value::Null) => None,
        Some(m) => Some(Some(m.to_string()).filter(|m| m.len() <= 4096).ok_or("meta too large")?),
    };
    Ok(Point { name, key, owner: s(v, "owner"), unit: s(v, "unit"), ts, value, meta })
}

impl Store {
    pub fn open(path: &Path) -> Result<Store, String> {
        let existed = path.exists();
        let conn = Connection::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
        if !existed {
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        }
        conn.pragma_update(None, "journal_mode", "WAL").map_err(|e| e.to_string())?;
        conn.pragma_update(None, "synchronous", "NORMAL").map_err(|e| e.to_string())?;
        conn.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e| e.to_string())?;
        let ver: usize = conn.pragma_query_value(None, "user_version", |r| r.get(0)).map_err(|e| e.to_string())?;
        for (i, sql) in MIGRATIONS.iter().enumerate().skip(ver) {
            conn.execute_batch(&format!("BEGIN; {sql} PRAGMA user_version = {}; COMMIT;", i + 1)).map_err(|e| format!("göç {}: {e}", i + 1))?;
        }
        for ext in ["-wal", "-shm"] {
            let p = format!("{}{ext}", path.display());
            let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600));
        }
        Ok(Store { conn: Mutex::new(conn) })
    }

    /// Tek işlemde yazar; eklenen nokta sayısını döndürür.
    pub fn insert(&self, pts: &[Point]) -> Result<usize, String> {
        let mut c = self.conn.lock().map_err(|_| "kilit")?;
        let tx = c.transaction().map_err(|e| e.to_string())?;
        for p in pts {
            tx.execute(
                "INSERT INTO series(name,key,owner,unit) VALUES(?1,?2,?3,?4) ON CONFLICT(name,key,owner) DO UPDATE SET unit=CASE WHEN excluded.unit!='' THEN excluded.unit ELSE unit END",
                params![p.name, p.key, p.owner, p.unit],
            )
            .map_err(|e| e.to_string())?;
            let id: i64 = tx.query_row("SELECT id FROM series WHERE name=?1 AND key=?2 AND owner=?3", params![p.name, p.key, p.owner], |r| r.get(0)).map_err(|e| e.to_string())?;
            tx.execute("INSERT INTO points(series_id,ts,value,meta_json) VALUES(?1,?2,?3,?4)", params![id, p.ts, p.value, p.meta]).map_err(|e| e.to_string())?;
        }
        tx.commit().map_err(|e| e.to_string())?;
        Ok(pts.len())
    }

    /// `GET /api/metrics/series?name=&key=&owner=&from=&to=&limit=`: seri başına noktalar (ts artan). `name` zorunlu; `key` boşsa tüm anahtarlar.
    pub fn series(&self, name: &str, key: Option<&str>, owner: &str, from: f64, to: f64, limit: usize) -> Result<Value, String> {
        let c = self.conn.lock().map_err(|_| "kilit")?;
        let mut st = c.prepare("SELECT id,key,unit FROM series WHERE name=?1 AND owner=?2 AND (?3 IS NULL OR key=?3) ORDER BY key").map_err(|e| e.to_string())?;
        let rows: Vec<(i64, String, String)> = st.query_map(params![name, owner, key], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?))).map_err(|e| e.to_string())?.filter_map(|r| r.ok()).collect();
        let mut out = vec![];
        for (id, k, unit) in rows {
            let mut ps = c.prepare("SELECT ts,value,meta_json FROM (SELECT ts,value,meta_json FROM points WHERE series_id=?1 AND ts>=?2 AND ts<=?3 ORDER BY ts DESC LIMIT ?4) ORDER BY ts").map_err(|e| e.to_string())?;
            let pts: Vec<Value> = ps
                .query_map(params![id, from, to, limit as i64], |r| {
                    let m: Option<String> = r.get(2)?;
                    Ok(json!({"ts": r.get::<_, f64>(0)?, "value": r.get::<_, f64>(1)?, "meta": m.and_then(|m| serde_json::from_str::<Value>(&m).ok())}))
                })
                .map_err(|e| e.to_string())?
                .filter_map(|r| r.ok())
                .collect();
            out.push(json!({"name": name, "key": k, "unit": unit, "points": pts}));
        }
        Ok(json!({"series": out}))
    }

    /// `GET /api/metrics/names`: {name, keys, points, last_ts}.
    pub fn names(&self, owner: &str) -> Result<Value, String> {
        let c = self.conn.lock().map_err(|_| "kilit")?;
        let mut st = c
            .prepare("SELECT s.name, COUNT(DISTINCT s.id), COUNT(p.ts), MAX(p.ts) FROM series s LEFT JOIN points p ON p.series_id=s.id WHERE s.owner=?1 GROUP BY s.name ORDER BY s.name")
            .map_err(|e| e.to_string())?;
        let v: Vec<Value> = st
            .query_map([owner], |r| Ok(json!({"name": r.get::<_, String>(0)?, "keys": r.get::<_, i64>(1)?, "points": r.get::<_, i64>(2)?, "last_ts": r.get::<_, Option<f64>>(3)?})))
            .map_err(|e| e.to_string())?
            .filter_map(|r| r.ok())
            .collect();
        Ok(json!({"names": v}))
    }

    /// Son noktanın değeri (günlük işin "bugün zaten koştu mu" denetimi için).
    pub fn last_ts(&self, name: &str, key: &str) -> Result<Option<f64>, String> {
        let c = self.conn.lock().map_err(|_| "kilit")?;
        c.query_row("SELECT MAX(p.ts) FROM points p JOIN series s ON s.id=p.series_id WHERE s.name=?1 AND s.key=?2", params![name, key], |r| r.get::<_, Option<f64>>(0)).optional().map(|o| o.flatten()).map_err(|e| e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pt(name: &str, key: &str, ts: f64, v: f64) -> Point {
        parse_point(&json!({"name": name, "key": key, "ts": ts, "value": v, "unit": "n"}), 0.0).unwrap()
    }

    #[test]
    fn roundtrip_perms_and_migration_idempotent() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("metrics.db");
        let st = Store::open(&p).unwrap();
        assert_eq!(std::fs::metadata(&p).unwrap().permissions().mode() & 0o777, 0o600);
        st.insert(&[pt("project.todo_open", "a", 10.0, 3.0), pt("project.todo_open", "a", 20.0, 2.0), pt("project.todo_open", "b", 10.0, 9.0)]).unwrap();
        drop(st);
        let st = Store::open(&p).unwrap(); // ikinci açılış göçü yeniden koşmaz
        let r = st.series("project.todo_open", Some("a"), "", 0.0, 1e12, 100).unwrap();
        let pts = r["series"][0]["points"].as_array().unwrap();
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[0]["value"], 3.0);
        assert_eq!(st.series("project.todo_open", None, "", 0.0, 1e12, 100).unwrap()["series"].as_array().unwrap().len(), 2);
        assert_eq!(st.series("project.todo_open", Some("a"), "", 15.0, 1e12, 100).unwrap()["series"][0]["points"].as_array().unwrap().len(), 1);
        let n = st.names("").unwrap();
        assert_eq!(n["names"][0]["keys"], 2);
        assert_eq!(n["names"][0]["points"], 3);
        assert_eq!(st.last_ts("project.todo_open", "a").unwrap(), Some(20.0));
    }

    #[test]
    fn owner_isolates_series() {
        let d = tempfile::tempdir().unwrap();
        let st = Store::open(&d.path().join("m.db")).unwrap();
        let mut a = pt("x", "k", 1.0, 1.0);
        a.owner = "u1".into();
        st.insert(&[a, pt("x", "k", 2.0, 2.0)]).unwrap();
        assert_eq!(st.series("x", None, "", 0.0, 9.0, 10).unwrap()["series"][0]["points"].as_array().unwrap().len(), 1);
        assert_eq!(st.series("x", None, "u1", 0.0, 9.0, 10).unwrap()["series"][0]["points"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn parse_rejects_bad() {
        assert!(parse_point(&json!({"value": 1}), 0.0).is_err());
        assert!(parse_point(&json!({"name": "a", "value": "x"}), 0.0).is_err());
        assert!(parse_point(&json!({"name": "a", "value": 1, "ts": -1}), 0.0).is_err());
        assert_eq!(parse_point(&json!({"name": "a", "value": 1}), 5.0).unwrap().ts, 5.0);
    }
}
