//! Olay günlüğünde tekrar bastırma kararı (grup 1). Bellek içi durum çağırandadır (Python `_LOG_SEEN`); günlük yazımı yok.

use crate::consts_gen::{LOG_DEDUP_EXEMPT, LOG_DEDUP_SECONDS};
use crate::pyc;
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Konunun son yazımı: içerik özeti, zaman, bastırılan sayısı.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Seen {
    pub hash: String,
    pub at: f64,
    pub suppressed: i64,
}

/// (log yolu, olay, konu) -> son yazım.
pub type LogSeen = IndexMap<(String, String, String), Seen>;

/// Bellek sınırı: bu kadar konudan sonra penceresi geçmiş kayıtlar atılır.
const MAX_SUBJECTS: usize = 4000;

/// Anahtar sırasından bağımsız içerik metni (`json.dumps(sort_keys=True)` karşılığı; yalnız eşitlik için).
fn canonical(v: &Value, out: &mut String) {
    match v {
        Value::Array(a) => {
            out.push('[');
            for x in a {
                canonical(x, out);
                out.push(',');
            }
            out.push(']');
        }
        Value::Object(o) => {
            let mut keys: Vec<&String> = o.keys().collect();
            keys.sort();
            out.push('{');
            for k in keys {
                out.push_str(&pyc::json_str_ascii(k));
                out.push(':');
                if let Some(x) = o.get(k) {
                    canonical(x, out);
                }
                out.push(',');
            }
            out.push('}');
        }
        Value::String(s) => out.push_str(&pyc::json_str_ascii(s)),
        _ => out.push_str(&v.to_string()),
    }
}

/// `None` = yazma (aynı konunun ardışık aynı içeriği, pencere içinde); `Some` = yaz, dönen sayaç alanlarını
/// (`repeated` / `repeated_prev`) kayda ekle.
///
/// py: _log_dedup
pub fn log_dedup(
    seen: &mut LogSeen,
    log: &str,
    event: &str,
    data: &Map<String, Value>,
    now: f64,
) -> Option<Map<String, Value>> {
    let mut extra = Map::new();
    if LOG_DEDUP_EXEMPT.contains(&event) || event.ends_with("denied") {
        return Some(extra);
    }
    let mut text = String::new();
    canonical(&Value::Object(data.clone()), &mut text);
    let hash = pyc::head(&pyc::sha1_hex(text.as_bytes()), 16).to_string();
    let subject = ["name", "project"]
        .iter()
        .find_map(|k| data.get(*k).filter(|v| pyc::truthy(v)))
        .map(pyc::str_of)
        .unwrap_or_default();
    let key = (log.to_string(), event.to_string(), subject);
    if let Some(rec) = seen.get_mut(&key) {
        let same = rec.hash == hash;
        if same && now - rec.at < LOG_DEDUP_SECONDS {
            rec.suppressed += 1;
            return None;
        }
        if rec.suppressed != 0 {
            let field = if same { "repeated" } else { "repeated_prev" };
            extra.insert(field.to_string(), Value::from(rec.suppressed));
        }
    }
    seen.insert(key, Seen { hash, at: now, suppressed: 0 });
    if seen.len() > MAX_SUBJECTS {
        seen.retain(|_, v| now - v.at < LOG_DEDUP_SECONDS);
    }
    Some(extra)
}
