//! Günlük/aylık kota, kapasite, agy/copilot engelleri.
use crate::badrec;
use crate::clock;
use crate::error::{Error, Result};
use crate::planner::{agy_pool, key_model, pairs};
use crate::py;
use crate::targets::{ci, decimal};
use chrono::{Datelike, NaiveDate, TimeZone, Utc};
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::BTreeSet;
use std::sync::LazyLock;

macro_rules! re {
    ($name:ident, $pat:expr) => {
        static $name: LazyLock<Regex> = LazyLock::new(|| Regex::new($pat).unwrap());
    };
}

re!(LIMIT_RE, r"(?i)daily_token_limit_exceeded|daily token limit|exceeded your monthly quota");
re!(MONTHLY_RE, r"(?i)monthly");
re!(QUOTA_RE, r"(?i)RESOURCE_EXHAUSTED|Individual quota reached|quota reached|hit your usage limit");
re!(USAGE_LIMIT_RE, r"(?i)hit your usage limit");
re!(TRY_AT_RE, r"(?i)try again at[\s\x1c-\x1f]+([A-Za-z]{3})[a-z]*[\s\x1c-\x1f]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\x1c-\x1f]+(\d{4})[\s\x1c-\x1f]+(\d{1,2}):(\d{2})[\s\x1c-\x1f]*([AP]M)");
re!(RESET_RE, r"(?i)resets?[\s\x1c-\x1f]+in[\s\x1c-\x1f]+((?:\d+[\s\x1c-\x1f]*[dhms][\s\x1c-\x1f]*)+)");
re!(UNIT_RE, r"(\d+)[\s\x1c-\x1f]*([dhmsDHMS])");

pub const BANNER_MAX_CHARS: usize = 600;
pub const QUOTA_FALLBACK_SECONDS: f64 = 1800.0;
pub const QUOTA_MAX_SECONDS: f64 = 14.0 * 86400.0;
pub const COPILOT_BLOCK_REASON: &str = "copilot usage_state";
pub const COPILOT_FALLBACK_SECONDS: f64 = 24.0 * 3600.0;
pub const AGY_BLOCK_GRACE: f64 = 600.0;
pub const MODEL_TEXT_KEYS: [&str; 5] = ["partial_turn", "answer", "result", "text", "messages"];

fn any(re: &Regex, texts: &[&str]) -> bool {
    texts.iter().any(|t| re.is_match(&ci(t)))
}

pub fn is_daily_limit(texts: &[&str]) -> bool {
    any(&LIMIT_RE, texts)
}

pub fn next_utc_midnight(now: f64) -> f64 {
    ((now.trunc() as i64).div_euclid(86400) + 1) as f64 * 86400.0
}

/// Sonraki ayın 1'i 00:00 UTC. Aralık dışı zamanda `None` (Python hata verir).
pub fn next_utc_month_start(now: f64) -> Option<f64> {
    if !now.is_finite() {
        return None;
    }
    let t = Utc.timestamp_opt(now.floor() as i64, 0).single()?;
    let (y, m) = if t.month() == 12 { (t.year() + 1, 1) } else { (t.year(), t.month() + 1) };
    Some(NaiveDate::from_ymd_opt(y, m, 1)?.and_hms_opt(0, 0, 0)?.and_utc().timestamp() as f64)
}

pub fn block_until_for_limit(now: f64, texts: &[&str]) -> f64 {
    if any(&MONTHLY_RE, texts) {
        if let Some(t) = next_utc_month_start(now) {
            return t;
        }
    }
    next_utc_midnight(now)
}

pub fn is_short_banner(text: &str) -> bool {
    let t = py::strip(text);
    let n = t.chars().count();
    n > 0 && n < BANNER_MAX_CHARS && !t.contains("## R-")
}

/// Kota taramasına girecek metinler: sağlayıcı kanalları; modelin kendi metni hariç.
pub fn limit_scan_texts(out: &str, err: &str, jerr: &str, err_has_model_text: bool) -> Vec<String> {
    let e = if !err_has_model_text || is_short_banner(err) { err } else { "" };
    let mut parts = vec![e.to_string(), jerr.to_string()];
    match Json::parse(out) {
        Ok(Json::Object(m)) => {
            let kept: Map = m.into_iter().filter(|(k, _)| !MODEL_TEXT_KEYS.contains(&k.as_str())).collect();
            parts.push(Json::Object(kept).to_compact());
        }
        _ => {
            if is_short_banner(out) {
                parts.push(out.to_string());
            }
        }
    }
    parts
}

pub fn is_quota_exhausted(texts: &[&str]) -> bool {
    any(&QUOTA_RE, texts)
}

pub fn is_usage_limit(texts: &[&str]) -> bool {
    any(&USAGE_LIMIT_RE, texts)
}

const MONTHS: [&str; 12] = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/// "try again at Nov 20th, 2026 6:37 PM" -> yerel epoch.
pub fn reset_at(texts: &[&str]) -> Option<f64> {
    for t in texts {
        let folded = ci(t);
        let Some(m) = TRY_AT_RE.captures(&folded) else { continue };
        let parsed = (|| {
            let month = MONTHS.iter().position(|x| *x == m[1].to_lowercase())? as u32 + 1;
            // `int()` sonrası `%d` 1-31, yıl `%Y` (4 rakam), saat `%I` 1-12, dakika 00-59.
            let day = decimal(&m[2]) as u32;
            let year = decimal(&m[3]) as i32;
            let hour = decimal(&m[4]) as u32;
            let minute = decimal(&m[5]) as u32;
            if !(1..=12).contains(&hour) || year < 1 || !m[5].is_ascii() || !m[3].is_ascii() {
                return None;
            }
            let h24 = hour % 12 + if m[6].eq_ignore_ascii_case("pm") { 12 } else { 0 };
            clock::mktime(NaiveDate::from_ymd_opt(year, month, day)?.and_hms_opt(h24, minute, 0)?)
        })();
        if parsed.is_some() {
            return parsed;
        }
    }
    None
}

fn unit_seconds(u: &str) -> f64 {
    match u.to_ascii_lowercase().as_str() {
        "d" => 86400.0,
        "h" => 3600.0,
        "m" => 60.0,
        _ => 1.0,
    }
}

/// "Resets in 107h49m47s" -> saniye (üst sınır `QUOTA_MAX_SECONDS`).
pub fn reset_seconds(texts: &[&str]) -> Option<f64> {
    for t in texts {
        let folded = ci(t);
        let Some(m) = RESET_RE.captures(&folded) else { continue };
        let total: f64 = UNIT_RE.captures_iter(&m[1]).map(|c| decimal(&c[1]) * unit_seconds(&c[2])).sum();
        if total > 0.0 {
            return Some(total.min(QUOTA_MAX_SECONDS));
        }
    }
    None
}

pub fn quota_block_until(now: f64, texts: &[&str]) -> f64 {
    if let Some(at) = reset_at(texts) {
        if at > now {
            return at.min(now + QUOTA_MAX_SECONDS);
        }
    }
    now + reset_seconds(texts).unwrap_or(QUOTA_FALLBACK_SECONDS)
}

/// `usage_state` copilot girdileri -> (kullanılan %, reset epoch, detay).
pub fn parse_copilot_entries(entries: &Json, now: f64, base: Option<f64>) -> Option<(f64, f64, String)> {
    re!(RESETS_IN, r"(?i)resets?[\s\x1c-\x1f]+[iİı]n[\s\x1c-\x1f]+(.+)\n?$");
    re!(SPAN, r"(?i)(\d+)[\s\x1c-\x1f]*(day|d|hour|hr|h|m[iİı]nute|m[iİı]n|m)\w*");
    for e in entries.as_array().unwrap_or(&[]) {
        let Some(e) = e.as_object() else { continue };
        let label = py::str_or_empty(e.get("label")).to_lowercase();
        if !label.contains("credit") && !label.contains("plan") {
            continue;
        }
        let pct_text = e.get("percent").map_or_else(|| "None".to_string(), py::to_str);
        let Some(pct) = py::float_str(pct_text.trim_end_matches('%')) else { continue };
        let detail = py::str_or_empty(e.get("detail"));
        let mut secs = 0.0;
        if let Some(m) = RESETS_IN.captures(&detail) {
            for c in SPAN.captures_iter(&m[1]) {
                let unit = c[2].chars().next().map(|c| c.to_ascii_lowercase());
                secs += decimal(&c[1])
                    * match unit {
                        Some('d') => 86400.0,
                        Some('h') => 3600.0,
                        _ => 60.0,
                    };
            }
        }
        let start = base.filter(|b| *b != 0.0).unwrap_or(now);
        let reset = if secs != 0.0 { start + secs } else { now + COPILOT_FALLBACK_SECONDS };
        return Some((pct, reset, detail));
    }
    None
}

/// `history.setdefault("blocks", {})`; nesne değilse Python gibi HATA.
pub(crate) fn blocks_mut(hist: &mut Map) -> Result<&mut Map> {
    hist.entry("blocks".to_string())
        .or_insert_with(Json::object)
        .as_object_mut()
        .ok_or_else(|| Error::Value("history[\"blocks\"] nesne değil".into()))
}

/// `blocks.<key>.until`; sayıya çevrilemiyorsa `None` (loglanır).
fn until_of(e: &Map, key: &str) -> Option<f64> {
    badrec::field(e, "until", "blocks", key)
}

fn block_entry(until: f64, set_at: f64, reason: String) -> Json {
    let mut m = Map::new();
    m.insert("until".into(), Json::Float(until));
    m.insert("set_at".into(), Json::Float(set_at));
    m.insert("reason".into(), Json::Str(reason));
    Json::Object(m)
}

/// `%g` biçimi.
pub fn fmt_g(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.into();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0" } else { "0" }.into();
    }
    let sci = format!("{:.5e}", x);
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let trim = |s: String| {
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s
        }
    };
    if !(-4..6).contains(&exp) {
        format!("{}e{}{:02}", trim(mant.to_string()), if exp < 0 { '-' } else { '+' }, exp.unsigned_abs())
    } else {
        trim(format!("{:.*}", (5 - exp) as usize, x))
    }
}

/// Copilot MOD engelini kullanım yüzdesine çeker. Değişen anahtarlar.
pub fn reconcile_copilot_blocks(
    hist: &mut Map,
    info: Option<&(f64, f64, String)>,
    stop_pct: f64,
    now: f64,
) -> Result<Vec<String>> {
    let Some((pct, reset, detail)) = info else { return Ok(Vec::new()) };
    if stop_pct <= 0.0 {
        return Ok(Vec::new());
    }
    let blocks = blocks_mut(hist)?;
    let cur = blocks.get("copilot").and_then(Json::as_object);
    // Python `if cur and ...`: boş sözlük yok sayılır.
    let cur = cur.filter(|c| !c.is_empty());
    if *pct >= stop_pct {
        if let Some(c) = cur {
            if until_of(c, "copilot").unwrap_or(0.0) >= reset - 60.0 {
                return Ok(Vec::new());
            }
        }
        let when = clock::format_local(*reset, "%Y-%m-%d %H:%M").unwrap_or_default();
        let reason = format!(
            "{COPILOT_BLOCK_REASON}: %{} kullanıldı (eşik %{}), {detail}; yenilenme {when}",
            fmt_g(*pct),
            fmt_g(stop_pct)
        );
        blocks.insert("copilot".into(), block_entry(*reset, now, reason));
        return Ok(vec!["copilot".into()]);
    }
    if cur.is_some_and(|c| py::str_or_empty(c.get("reason")).starts_with(COPILOT_BLOCK_REASON)) {
        blocks.shift_remove("copilot");
        return Ok(vec!["copilot".into()]);
    }
    Ok(Vec::new())
}

/// havuz -> {"weekly"|"five": (kalan %, reset epoch)}.
pub type AgyUsage = Vec<(String, Vec<(String, (f64, f64))>)>;

fn usage_set(out: &mut AgyUsage, pool: &str, kind: &str, v: (f64, f64)) {
    let i = match out.iter().position(|(p, _)| p == pool) {
        Some(i) => i,
        None => {
            out.push((pool.to_string(), Vec::new()));
            out.len() - 1
        }
    };
    match out[i].1.iter_mut().find(|(k, _)| k == kind) {
        Some(slot) => slot.1 = v,
        None => out[i].1.push((kind.to_string(), v)),
    }
}

pub fn parse_agy_usage(text: &str) -> AgyUsage {
    re!(ISO, r"(?i)^(\d{4})-(1[0-2]|0[1-9]|[1-9])-(3[01]|[12]\d|0[1-9]|[1-9]| [1-9])T(2[0-3]|[01]\d|\d):([0-5]\d|\d):(6[01]|[0-5]\d|\d)Z$");
    let mut out = AgyUsage::new();
    for line in py::splitlines(text) {
        let parts: Vec<&str> = line.split('\t').map(py::strip).collect();
        if parts.len() != 4 {
            continue;
        }
        let pct_digits = parts[2].trim_end_matches('%');
        if pct_digits.is_empty() || !pct_digits.chars().all(|c| c.is_numeric()) {
            continue;
        }
        let (g, m) = (parts[0].to_lowercase(), parts[1].to_lowercase());
        let pool = if g.contains("argon") {
            "argon"
        } else if g.starts_with("gemini") {
            "gemini"
        } else if g.starts_with("claude") {
            "claude_gpt"
        } else {
            ""
        };
        let kind = if m.contains("weekly") {
            "weekly"
        } else if m.contains("five hour") || m.contains("5 hour") {
            "five"
        } else {
            ""
        };
        if pool.is_empty() || kind.is_empty() {
            continue;
        }
        let ts = (|| {
            let c = ISO.captures(parts[3])?;
            let n = |i: usize| decimal(py::strip(&c[i])) as u32;
            let sec = n(6);
            // `timegm` 60/61 saniyeyi sonraki dakikaya taşır.
            let base = NaiveDate::from_ymd_opt(decimal(&c[1]) as i32, n(2), n(3))?.and_hms_opt(n(4), n(5), 0)?;
            Some(base.and_utc().timestamp() as f64 + f64::from(sec))
        })();
        let (Some(ts), Some(pct)) = (ts, py::float_str(pct_digits)) else { continue };
        usage_set(&mut out, pool, kind, (pct, ts));
    }
    out
}

/// `usage_state`teki agy girdileri -> [`parse_agy_usage`] biçimi.
pub fn parse_agy_entries(entries: &Json) -> AgyUsage {
    let mut lines = Vec::new();
    for e in entries.as_array().unwrap_or(&[]) {
        let Some(e) = e.as_object() else { continue };
        let label = py::str_or_empty(e.get("label"));
        let (group, metric) = label.split_once(" — ").unwrap_or((&label, ""));
        let reset = py::str_or_empty(e.get("detail")).replacen("Resets ", "", 1);
        let pct = e.get("percent").map_or_else(|| "None".to_string(), py::to_str);
        lines.push([group.to_string(), metric.to_string(), format!("{pct}%"), reset].join("\t"));
    }
    parse_agy_usage(&lines.join("\n"))
}

/// Havuz kapalıysa açılış zamanı (`Some(Some)`), açıksa `Some(None)`, havuz bilinmiyorsa `None` (Python `-1`).
pub fn agy_pool_blocked_until(usage: &AgyUsage, pool: &str, now: f64) -> Option<Option<f64>> {
    let u = usage.iter().find(|(p, _)| p == pool).map(|(_, u)| u).filter(|u| !u.is_empty())?;
    let mut until = 0.0;
    for kind in ["weekly", "five"] {
        if let Some((_, (left, reset))) = u.iter().find(|(k, _)| k == kind) {
            if *left <= 0.0 && *reset > now {
                until = f64::max(until, *reset);
            }
        }
    }
    Some((until != 0.0).then_some(until))
}

pub fn reconcile_agy_blocks(
    hist: &mut Map,
    usage: &AgyUsage,
    target_keys: &[String],
    now: f64,
) -> Result<Vec<String>> {
    let blocks = blocks_mut(hist)?;
    let mut changed = Vec::new();
    let keys: BTreeSet<String> = target_keys
        .iter()
        .cloned()
        .chain(blocks.keys().filter(|k| k.starts_with("agy/")).cloned())
        .collect();
    for key in keys {
        if !key.starts_with("agy/") {
            continue;
        }
        let pool = agy_pool(key_model(&key));
        let Some(until) = agy_pool_blocked_until(usage, &pool, now) else { continue };
        let cur = blocks.get(&key).and_then(Json::as_object);
        if let Some(until) = until {
            let stale = match cur.filter(|c| !c.is_empty()) {
                Some(c) => (until_of(c, &key).unwrap_or(0.0) - until).abs() > 60.0,
                None => true,
            };
            if stale {
                let when = clock::format_local(until, "%Y-%m-%d %H:%M").unwrap_or_default();
                let reason = format!("agy /usage: havuz kapalı ({pool}), yenilenme {when}");
                let mut e = Map::new();
                e.insert("until".into(), Json::Float(until));
                e.insert("set_at".into(), Json::Float(now));
                e.insert("reason".into(), Json::Str(reason));
                blocks.insert(key.clone(), Json::Object(e));
                changed.push(key);
            }
        } else if cur.is_some_and(|c| now - py::num(c.get("set_at")) > AGY_BLOCK_GRACE) {
            blocks.shift_remove(&key);
            changed.push(key);
        }
    }
    Ok(changed)
}

fn first_truthy<'a>(r: &'a Map, a: &str, b: &str) -> Option<&'a Json> {
    let x = r.get(a);
    if py::truthy(x) {
        x
    } else {
        r.get(b)
    }
}

fn agy_block_cleared(history: &Json, key: &str, entry: &Map) -> bool {
    let pool = agy_pool(key_model(key));
    let mut set_at = py::num(entry.get("set_at"));
    let empty = Map::new();
    let pairs = pairs(history).unwrap_or(&empty);
    let after_bar = |k: &str| k.split_once('|').map_or("", |(_, r)| r).to_string();
    if set_at == 0.0 {
        let lim: Vec<f64> = pairs
            .iter()
            .filter_map(|(k, r)| {
                let r = r.as_object()?;
                (py::is_str(r.get("status"), "limit") && after_bar(k) == key)
                    .then(|| py::num(first_truthy(r, "finished_at", "started_at")))
            })
            .collect();
        set_at = match lim.split_first() {
            Some((h, t)) => t.iter().fold(*h, |a, &b| if b > a { b } else { a }),
            None => py::num(entry.get("until")) - QUOTA_MAX_SECONDS,
        };
    }
    pairs.iter().any(|(k, r)| {
        let ms = after_bar(k);
        let Some(r) = r.as_object() else { return false };
        ms.starts_with("agy/")
            && py::is_str(r.get("status"), "done")
            && agy_pool(key_model(&ms)) == pool
            && py::num(r.get("finished_at")) > set_at
    })
}

/// Süresi dolmamış engellerin anahtarları (sıralı).
pub fn blocked_modes(history: &Json, now: f64) -> Result<Vec<String>> {
    let Some(b) = history.get("blocks").and_then(Json::as_object) else { return Ok(Vec::new()) };
    let mut set = BTreeSet::new();
    for (m, e) in b {
        let Some(e) = e.as_object() else { continue };
        let Some(until) = until_of(e, m) else { continue };
        if until > now && !(m.starts_with("agy/") && agy_block_cleared(history, m, e)) {
            set.insert(m.clone());
        }
    }
    Ok(set.into_iter().collect())
}
