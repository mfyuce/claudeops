//! Atlanan bozuk kayıtların tek günlük noktası (`review._log_bad` / `_field`). Aynı (tür, anahtar) süreç başına bir kez
//! bildirilir; bozuk DEĞER yazılmaz (sır taşıyabilir). Koşucu [`set_sink`] ile kendi günlüğüne bağlar; yoksa stderr.
use crate::py;
use cops_state::json::{Json, Map};
use std::collections::HashSet;
use std::sync::{LazyLock, Mutex, OnceLock, PoisonError};

const BAD_SEEN_MAX: usize = 1000;
static BAD_SEEN: LazyLock<Mutex<HashSet<(String, String)>>> = LazyLock::new(Mutex::default);
static SINK: OnceLock<fn(&str, &str)> = OnceLock::new();

/// Günlük hedefi (yalnız ilk çağrı geçerli).
pub fn set_sink(sink: fn(&str, &str)) {
    let _ = SINK.set(sink);
}

pub fn log_bad(what: &str, key: &str) {
    let key = py::head(key, 200).to_string();
    {
        let mut seen = BAD_SEEN.lock().unwrap_or_else(PoisonError::into_inner);
        let mark = (what.to_string(), key.clone());
        if seen.contains(&mark) {
            return;
        }
        if seen.len() >= BAD_SEEN_MAX {
            seen.clear();
        }
        seen.insert(mark);
    }
    match SINK.get() {
        Some(f) => f(what, &key),
        None => eprintln!("review_bad_record what={what} key={key:?}"),
    }
}

/// Kayıttaki sayı alanı; yok/boş = 0, sayıya çevrilemiyorsa `None` (loglanır, çağıran kaydı atlar).
pub fn field(rec: &Map, name: &str, what: &str, key: &str) -> Option<f64> {
    let v: Option<&Json> = rec.get(name);
    let r = py::float_or_zero(v).ok().filter(|f| f.is_finite());
    if r.is_none() {
        log_bad(&format!("{what}.{name}"), key);
    }
    r
}
