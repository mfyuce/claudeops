//! Rust'un KENDİ cevapladığı salt okunur yerel uçlar (strangler Aşama 1). İlk uç: `GET /api/steward/questions` (Danış gölge kip okuması).
//! Kaynak `claudeops.db` `docs` tablosu (store_backend=db: tek doğruluk kaynağı; belge adı `steward/questions` ya da
//! `steward/stewards/<sid>/questions`, gövde = Python `Question` listesinin JSON'u). DB SALT OKUNUR açılır; yazım Python'da kalır.

pub mod learned;
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;

/// Yetki eylemi adı (Python `_ACTION_TABLE` ile eşitlik testi sonraki adım: plan bölüm 4).
pub const ACTION_STEWARD_READ: &str = "steward.read";

/// Python `STEWARD_ID_RE` (`^[a-z]{2,16}$`) + `default`.
pub fn valid_sid(sid: &str) -> bool {
    sid == "default"
        || ((2..=16).contains(&sid.len()) && sid.bytes().all(|b| b.is_ascii_lowercase()))
}

fn doc_name(sid: &str) -> String {
    if sid == "default" {
        "steward/questions".into()
    } else {
        format!("steward/stewards/{sid}/questions")
    }
}

const FIELDS: [&str; 10] = [
    "id",
    "project",
    "text",
    "options",
    "routine",
    "status",
    "created_at",
    "answered_at",
    "answer",
    "answered_by",
];

/// `GET /api/steward/questions?sid=&all=1&since=EPOCH` gövdesi: JSON dizisi (id, sid, project, text, options, routine, status,
/// created_at, answered_at, answer, answered_by). Varsayılan yalnız açık sorular; `all=1` ya da `since` hepsi.
/// `since` (epoch sn): `created_at` YA DA `answered_at` bu değerden büyük/eşit olanlar. Hata metni `Err`.
pub fn questions(db: &Path, query: &str) -> Result<Value, (u16, String)> {
    let get = |k: &str| {
        query
            .split('&')
            .filter_map(|kv| kv.split_once('='))
            .find(|(n, _)| *n == k)
            .map(|(_, v)| v.to_string())
    };
    let sid = get("sid")
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "default".into());
    if !valid_sid(&sid) {
        return Err((400, "bad sid".into()));
    }
    let all = matches!(get("all").as_deref(), Some("1") | Some("true"));
    let since: f64 = match get("since").filter(|s| !s.is_empty()) {
        None => 0.0,
        Some(s) => s
            .parse::<f64>()
            .map_err(|_| (400, "bad since".to_string()))?,
    };
    let conn = Connection::open_with_flags(
        db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| (503, format!("db: {e}")))?;
    let body: Option<String> = conn
        .query_row(
            "SELECT body FROM docs WHERE name = ?1",
            [doc_name(&sid)],
            |r| r.get(0),
        )
        .map(Some)
        .or_else(|e| {
            if matches!(e, rusqlite::Error::QueryReturnedNoRows) {
                Ok(None)
            } else {
                Err(e)
            }
        })
        .map_err(|e| (503, format!("db: {e}")))?;
    let list: Vec<Value> = match body {
        None => vec![],
        Some(b) => serde_json::from_str(&b).map_err(|e| (500, format!("bad doc: {e}")))?,
    };
    let num = |v: &Value, k: &str| v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
    let rows: Vec<Value> = list
        .iter()
        .filter(|q| q.get("id").and_then(|x| x.as_str()).is_some())
        .filter(|q| {
            if since > 0.0 {
                num(q, "created_at").max(num(q, "answered_at")) >= since
            } else {
                all || q.get("status").and_then(|x| x.as_str()) == Some("open")
            }
        })
        .map(|q| {
            let mut o = serde_json::Map::new();
            for k in FIELDS {
                o.insert(
                    k.into(),
                    q.get(k).cloned().unwrap_or_else(|| match k {
                        "options" => json!([]),
                        "routine" => json!(false),
                        "created_at" | "answered_at" => json!(0.0),
                        _ => json!(""),
                    }),
                );
            }
            o.insert("sid".into(), json!(sid));
            Value::Object(o)
        })
        .collect();
    Ok(Value::Array(rows))
}
