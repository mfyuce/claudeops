//! `time` modülü karşılıkları (yerel saat dilimi).
use chrono::{DateTime, Local, NaiveDateTime, TimeZone};

pub fn now() -> f64 {
    cops_state::now()
}

/// `time.localtime(ts)`; aralık dışı/sonsuz/NaN -> `None` (Python hata verir).
pub fn local(ts: f64) -> Option<DateTime<Local>> {
    if !ts.is_finite() || ts.abs() > 2.5e11 {
        return None;
    }
    Local.timestamp_opt(ts.floor() as i64, 0).single()
}

/// `time.strftime(fmt, time.localtime(ts))`.
pub fn format_local(ts: f64, fmt: &str) -> Option<String> {
    local(ts).map(|d| d.format(fmt).to_string())
}

/// `time.mktime`: yerel saat -> epoch. Yaz saati boşluğundaki saat bir saat ileri alınır, çift saatte ilki.
pub fn mktime(n: NaiveDateTime) -> Option<f64> {
    match Local.from_local_datetime(&n).earliest() {
        Some(d) => Some(d.timestamp() as f64),
        None => Local
            .from_local_datetime(&(n + chrono::Duration::hours(1)))
            .earliest()
            .map(|d| d.timestamp() as f64),
    }
}
