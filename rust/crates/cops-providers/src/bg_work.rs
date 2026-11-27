//! Arka plan işi tespiti (`py/claudeops/bg_work.py`): ekran işaretleri ve transkriptte bildirimi gelmemiş iş. SAF
//! işlevler; dosya okuma `live` modülündedir.
//!
//! İki tarafta da beklenmeyen tipte bir satır (nesne olmayan belge, nesne olmayan `message`/`input`/`payload`/`item`,
//! anahtar olamayan kimlik) yalnız o satırı/bloğu atlatır.

use crate::pyfmt::{decimal_value, strip};
use crate::pyjson::Py;
use crate::usage::d_in;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

pub const SCREEN_TAIL_LINES: usize = 14;
pub const TRANSCRIPT_TAIL_BYTES: u64 = 8 * 1024 * 1024;
/// Bildirimi hiç gelmemiş iş bu yaştan sonra sayılmaz (saniye).
pub const PENDING_MAX_AGE_SECONDS: f64 = 6.0 * 3600.0;

/// Saat: Python `time.time()` ve saat dilimsiz zaman damgasının yorumlandığı yerel UTC farkı (saniye).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Clock {
    pub now: f64,
    pub utc_offset_secs: i64,
}

/// Python `\w` (harf, rakam, `_`) sınıfının içi.
const W_IN: &str = r"\p{L}\p{N}_";

/// `{W}` -> Python `\w` sınıfı, `{D}` -> Python `\d` sınıfı. `re.I`nin `i` ↔ `İ`/`ı` eşlemesi desende açık yazılır.
///
/// Python'un geriye bakışı `(?<![..])` burada "satır başı ya da sınıf dışı bir karakter" olarak TÜKETİLİR, sondaki `\b`
/// ise eşleşmeden sonra elle bakılır: `regex` doğrusal zamanlıdır (geri izlemeli motor uzun satırda sınıra takılıp
/// sessizce "eşleşme yok" diyordu).
fn rx(pat: &str) -> Regex {
    let p = pat
        .replace("{W}", W_IN)
        .replace("{D}", &format!("[{}]", d_in()));
    Regex::new(&p).expect("sabit desen")
}

static COUNT: LazyLock<Regex> = LazyLock::new(|| {
    rx(r"(?i)(?:^|[^{W}.])([1-9]{D}*) (?:background tasks?|shells?|agents?|mon[iİı]tors?)")
});
static WORD_CHAR: LazyLock<Regex> = LazyLock::new(|| rx(r"^[{W}]"));
static HINT: LazyLock<Regex> =
    LazyLock::new(|| rx(r"(?i)to manage|esc to [iİı]nterrupt|to v[iİı]ew|ctrl\+b"));
static WAIT: LazyLock<Regex> = LazyLock::new(|| {
    rx(
        r"(?i)(?:^|[^{W}])wa[iİı]t[iİı]ng on (?:[iİı]ts own background work|[1-9]{D}* (?:shells?|agents?|background tasks?|mon[iİı]tors?))",
    )
});
static CODEX_BG: LazyLock<Regex> =
    LazyLock::new(|| rx(r"(?i)(?:^|[^{W}.])([1-9]{D}*) background term[iİı]nals? runn[iİı]ng"));
static NOTIF_ID: LazyLock<Regex> = LazyLock::new(|| rx(r"<tool-use-id>([^<]+)</tool-use-id>"));
static TASK_ID: LazyLock<Regex> = LazyLock::new(|| rx(r"<task-id>([^<]+)</task-id>"));
static STATUS: LazyLock<Regex> = LazyLock::new(|| rx(r"<status>([^<]+)</status>"));
static RUNNING_ID: LazyLock<Regex> = LazyLock::new(|| rx(r"(?:^|[^{W}])ID: ([A-Za-z0-9]+)"));
const DONE_STATUSES: [&str; 6] = [
    "completed",
    "failed",
    "killed",
    "cancelled",
    "canceled",
    "stopped",
];

/// `(text).rstrip("\n").split("\n")[-SCREEN_TAIL_LINES:]`.
fn screen_tail(text: &str) -> impl Iterator<Item = &str> {
    let lines: Vec<&str> = text.trim_end_matches('\n').split('\n').collect();
    let skip = lines.len().saturating_sub(SCREEN_TAIL_LINES);
    lines.into_iter().skip(skip)
}

/// Desenin her eşleşmesinin birinci grubu.
fn groups<'a>(re: &'a Regex, s: &'a str) -> impl Iterator<Item = &'a str> + 'a {
    re.captures_iter(s)
        .filter_map(|c| c.get(1).map(|m| m.as_str()))
}

/// Satırdaki iş sayıları (sözcüğün hemen ardından harf/rakam gelmeyen eşleşmeler).
fn counts(line: &str) -> impl Iterator<Item = &str> {
    COUNT
        .captures_iter(line)
        .filter(|c| {
            c.get(0)
                .is_some_and(|m| !WORD_CHAR.is_match(&line[m.end()..]))
        })
        .filter_map(|c| c.get(1).map(|m| m.as_str()))
}

/// `int()` (Unicode ondalık rakamlar); `u64`e sığmayan değer `u64::MAX`.
fn count_value(digits: &str) -> u64 {
    digits
        .chars()
        .filter_map(decimal_value)
        .fold(0u64, |acc, d| {
            acc.saturating_mul(10).saturating_add(u64::from(d))
        })
}

fn sum_counts<'a>(found: impl Iterator<Item = &'a str>) -> u64 {
    found.fold(0u64, |acc, g| acc.saturating_add(count_value(g)))
}

/// Ekrandaki arka plan işi sayısı (alt durum satırındaki N'lerin toplamı; yalnız "waiting on" görünürse en az 1).
pub fn screen_bg_count(text: &str) -> u64 {
    let mut total = 0u64;
    let mut waiting = false;
    for line in screen_tail(text) {
        waiting |= WAIT.is_match(line);
        if HINT.is_match(line) {
            total = total.saturating_add(sum_counts(counts(line)));
        }
    }
    if total > 0 || waiting {
        total.max(1)
    } else {
        0
    }
}

/// ANSI'si ayıklanmış ekranda arka plan işi göstergesi var mı.
pub fn screen_bg_work(text: &str) -> bool {
    screen_tail(text)
        .any(|line| WAIT.is_match(line) || (HINT.is_match(line) && counts(line).next().is_some()))
}

/// codex alt durum satırı: `N background terminal(s) running`.
pub fn codex_screen_count(text: &str) -> u64 {
    screen_tail(text).fold(0u64, |acc, line| {
        acc.saturating_add(sum_counts(groups(&CODEX_BG, line)))
    })
}

/// Python'da sözlük/küme anahtarı olabilen kimlik (`True == 1 == 1.0`).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum Key {
    Str(String),
    Num(String),
}

fn key(v: &Py) -> Option<Key> {
    match v {
        Py::Str(s) => Some(Key::Str(s.clone())),
        Py::Bool(b) => Some(Key::Num(u8::from(*b).to_string())),
        Py::Int(i) => Some(Key::Num(i.to_string())),
        Py::BigInt(s) => Some(Key::Num(s.clone())),
        Py::Float(f) if f.fract() == 0.0 && f.abs() < 9.0e18 => {
            Some(Key::Num((*f as i64).to_string()))
        }
        Py::Float(f) => Some(Key::Num(f.to_string())),
        Py::Null | Py::Array(_) | Py::Object(_) => None,
    }
}

/// `(v or {})`: falsy değer boş sözlük, truthy ama sözlük olmayan değer None (satır/blok atlanır).
fn dict_or_empty(v: Option<&Py>) -> Option<&Py> {
    static EMPTY: Py = Py::Object(Vec::new());
    match v {
        Some(v) if v.truthy() => v.is_object().then_some(v),
        _ => Some(&EMPTY),
    }
}

/// Araç sonucunun metni: listede yalnız metin blokları, gerçek satır sonlarıyla; diğer biçimlerde `str()`.
fn result_text(content: &Py) -> String {
    match content {
        Py::Array(blocks) => blocks
            .iter()
            .filter(|b| b.get("type").and_then(Py::as_str) == Some("text"))
            .filter_map(|b| b.get("text").and_then(Py::as_str))
            .collect::<Vec<_>>()
            .join("\n"),
        other => other.py_str(),
    }
}

/// Transkript satırlarında bildirimi gelmemiş `run_in_background` işi var mı.
pub fn transcript_pending<'a>(lines: impl IntoIterator<Item = &'a str>, clock: Clock) -> bool {
    // tool_use_id -> (epoch, task_id)
    let mut pending: HashMap<Key, (f64, Option<String>)> = HashMap::new();
    let mut done_use: HashSet<Key> = HashSet::new();
    let mut done_task: HashSet<String> = HashSet::new();
    for line in lines {
        if !line.contains("run_in_background")
            && !line.contains("task-notification")
            && !line.contains("ackground")
            && !line.contains("\"is_error\"")
        {
            continue;
        }
        let Some(o) = Py::parse(line).filter(Py::is_object) else {
            continue;
        };
        let ts = o
            .get("timestamp")
            .and_then(|v| iso_epoch(v, clock.utc_offset_secs));
        let Some(message) = dict_or_empty(o.get("message")) else {
            continue;
        };
        match message.get("content") {
            Some(Py::Str(c)) => {
                if !c.contains("<task-notification>") {
                    continue;
                }
                let Some(status) = groups(&STATUS, c).next() else {
                    continue;
                };
                if DONE_STATUSES.contains(&strip(status).to_lowercase().as_str()) {
                    done_use.extend(groups(&NOTIF_ID, c).map(|s| Key::Str(s.to_string())));
                    done_task.extend(groups(&TASK_ID, c).map(str::to_string));
                }
            }
            Some(Py::Array(blocks)) => {
                for b in blocks.iter().filter(|b| b.is_object()) {
                    let kind = b.get("type").and_then(Py::as_str);
                    let background = || {
                        dict_or_empty(b.get("input"))
                            .is_some_and(|i| i.get("run_in_background") == Some(&Py::Bool(true)))
                    };
                    let id = b.get("id").filter(|v| v.truthy());
                    if kind == Some("tool_use") && background() && id.is_some() {
                        if let Some(k) = id.and_then(key) {
                            let at = ts.filter(|t| *t != 0.0).unwrap_or(clock.now);
                            pending.insert(k, (at, None));
                        }
                    } else if kind == Some("tool_result") {
                        let Some(k) = b.get("tool_use_id").and_then(key) else {
                            continue;
                        };
                        if !pending.contains_key(&k) {
                            continue;
                        }
                        if b.get("is_error") == Some(&Py::Bool(true)) {
                            // çağrı reddedildi/düştü: iş hiç başlamadı, bildirim de gelmeyecek
                            pending.remove(&k);
                            continue;
                        }
                        let text: String = result_text(b.get("content").unwrap_or(&Py::Null))
                            .chars()
                            .take(400)
                            .collect();
                        let task = groups(&RUNNING_ID, &text).next().map(str::to_string);
                        if let (Some(task), Some(slot)) = (task, pending.get_mut(&k)) {
                            slot.1 = Some(task);
                        }
                    }
                }
            }
            _ => {}
        }
    }
    pending.iter().any(|(id, (at, task))| {
        !done_use.contains(id)
            && !task.as_ref().is_some_and(|t| done_task.contains(t))
            && clock.now - at < PENDING_MAX_AGE_SECONDS
    })
}

/// codex rollout: `SubAgentActivity` `started` olup aynı `agent_thread_id` için bitiş gelmemiş ajan sayısı.
pub fn codex_subagents_pending<'a>(lines: impl IntoIterator<Item = &'a str>, clock: Clock) -> u64 {
    let mut started: HashMap<String, f64> = HashMap::new();
    let mut done: HashSet<String> = HashSet::new();
    for line in lines {
        if !line.contains("SubAgentActivity") {
            continue;
        }
        let Some(o) = Py::parse(line).filter(Py::is_object) else {
            continue;
        };
        let Some(item) = dict_or_empty(o.get("payload")).and_then(|p| dict_or_empty(p.get("item")))
        else {
            continue;
        };
        if item.get("type").and_then(Py::as_str) != Some("SubAgentActivity") {
            continue;
        }
        let Some(agent) = item
            .get("agent_thread_id")
            .filter(|v| v.truthy())
            .map(Py::py_str)
        else {
            continue;
        };
        match item.get("kind").and_then(Py::as_str) {
            Some("started") => {
                let at = o
                    .get("timestamp")
                    .and_then(|v| iso_epoch(v, clock.utc_offset_secs))
                    .filter(|t| *t != 0.0);
                started.insert(agent, at.unwrap_or(clock.now));
            }
            Some("completed" | "failed" | "cancelled" | "canceled" | "closed") => {
                done.insert(agent);
            }
            _ => {}
        }
    }
    started
        .iter()
        .filter(|(a, at)| !done.contains(*a) && clock.now - **at < PENDING_MAX_AGE_SECONDS)
        .count() as u64
}

/// Dosya kuyruğu baytlarının satırları (`decode("utf-8", "replace").split("\n")`).
pub fn decode_lines(data: &[u8]) -> Vec<String> {
    String::from_utf8_lossy(data)
        .split('\n')
        .map(str::to_string)
        .collect()
}

// ---------------------------------------------------------------------------------------------- zaman damgası

/// `datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()` (Python 3.10 sözdizimi); dize değilse ya da
/// ayrıştırılamazsa None. Saat dilimsiz damga `local_offset` ile yorumlanır (yaz saati geçişi hesaba katılmaz).
pub fn iso_epoch(v: &Py, local_offset: i64) -> Option<f64> {
    let s = v.as_str()?.replace('Z', "+00:00");
    let b = s.as_bytes();
    if b.len() < 10 || b[4] != b'-' || b[7] != b'-' {
        return None;
    }
    let year = digits(&b[0..4])?;
    let month = digits(&b[5..7])?;
    let day = digits(&b[8..10])?;
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days_in_month = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => 28 + i64::from(leap),
        _ => return None,
    };
    if year < 1 || day < 1 || day > days_in_month {
        return None;
    }
    let day_seconds = days_from_civil(year, month, day) * 86_400;
    let (mut seconds, mut micro, mut offset_micro) = (day_seconds, 0i64, None);
    if b.len() > 10 {
        // 10. konumda tek bir ayraç karakteri (herhangi bir kod noktası)
        let sep = s.get(10..)?.chars().next()?.len_utf8();
        let time = &b[10 + sep..];
        let zone_at = time.iter().position(|c| matches!(c, b'+' | b'-'));
        let (clock_part, zone) = match zone_at {
            Some(i) => (&time[..i], Some(&time[i..])),
            None => (time, None),
        };
        // saat dilimi izliyorsa saat kısmının sonundaki tek artık karakter Python'da kabul edilir
        let (t, trailing) = hms(clock_part, zone.map(|z| z[0]))?;
        if (trailing && zone.is_none()) || t[0] > 23 || t[1] > 59 || t[2] > 59 {
            return None;
        }
        seconds += t[0] * 3600 + t[1] * 60 + t[2];
        micro = t[3];
        if let Some(zone) = zone {
            if ![6, 9, 16].contains(&zone.len()) {
                return None;
            }
            let sign = if zone[0] == b'-' { -1 } else { 1 };
            let (z, trailing) = hms(&zone[1..], None)?;
            let whole = z[0] * 3600 + z[1] * 60 + z[2];
            let off = sign * (whole * 1_000_000 + if whole == 0 { 0 } else { z[3] });
            if trailing || off.abs() >= 86_400_000_000 {
                return None;
            }
            offset_micro = Some(off);
        }
    }
    // Python: dilimli damga mikro saniye farkı / 1e6, dilimsiz damga tam saniye + mikro / 1e6
    Some(match offset_micro {
        Some(off) => (seconds * 1_000_000 + micro - off) as f64 / 1e6,
        None => (seconds - local_offset) as f64 + micro as f64 / 1e6,
    })
}

fn digits(b: &[u8]) -> Option<i64> {
    b.iter().try_fold(0i64, |acc, c| {
        c.is_ascii_digit().then(|| acc * 10 + i64::from(c - b'0'))
    })
}

/// CPython 3.10 `parse_hh_mm_ss_ff`: `([saat, dk, sn, mikro], artık karakter var mı)`. `end` kısmı izleyen bayt
/// (saat dilimi işareti); dize sonu None. `.` herhangi bir alandan sonra kesir başlatır, saniyeden sonraki `:` de.
fn hms(b: &[u8], end: Option<u8>) -> Option<([i64; 4], bool)> {
    let mut v = [0i64; 4];
    let mut at = 0;
    for slot in 0..3 {
        v[slot] = digits(b.get(at..at + 2)?)?;
        at += 2;
        let c = b.get(at).copied().or(end);
        at += 1;
        if at >= b.len() {
            return Some((v, c.is_some()));
        }
        match c {
            Some(b':') => {}
            Some(b'.') => break,
            _ => return None,
        }
    }
    let fraction = b.get(at..)?;
    v[3] = match fraction.len() {
        3 => digits(fraction)? * 1000,
        6 => digits(fraction)?,
        _ => return None,
    };
    Some((v, false))
}

/// 1970-01-01'den gün sayısı (proleptik Gregoryen).
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iso_forms() {
        let at = |s: &str| iso_epoch(&Py::Str(s.into()), 3 * 3600);
        assert_eq!(at("1970-01-01T00:00:00Z"), Some(0.0));
        assert_eq!(at("1970-01-01T03:00:00"), Some(0.0));
        assert_eq!(at("1970-01-02"), Some(86_400.0 - 10_800.0));
        assert_eq!(at("2026-11-23T10:00:00.250+00:00"), Some(1_795_428_000.25));
        for bad in [
            "",
            "2026-11-23T",
            "2026-13-01",
            "2026-02-29",
            "2026-11-23T10:00:00.1Z",
            "ğğğğğğğğğğğ",
            "2026-11-23ğ",
        ] {
            assert_eq!(at(bad), None, "{bad}");
        }
    }

    #[test]
    fn very_long_screen_line_is_still_scanned() {
        // geri izlemeli motor bu uzunlukta sınıra takılıp sessizce 0 sayıyordu
        let line = "x ".repeat(2_000_000);
        assert_eq!(screen_bg_count(&format!("{line}2 shells · to manage")), 2);
        assert_eq!(screen_bg_count(&format!("{line}waiting on 1 shell")), 1);
        assert_eq!(
            codex_screen_count(&format!("{line}3 background terminals running")),
            3
        );
        assert!(screen_bg_work(&format!("{line}waiting on 1 shell")));
    }

    /// Her bayt konumunda kesilmiş ve bir baytı değiştirilmiş girdi: panik yok.
    #[test]
    fn truncated_and_mutated_input_never_panics() {
        let seed = "{\"timestamp\":\"2026-11-23ğ10:00:00.123+03:00\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"t\",\"input\":{\"run_in_background\":true}},-1.5e+3,NaN,\"\\ud83d\\ude00 background 🙂 SubAgentActivity\"]}}";
        let clock = Clock {
            now: 0.0,
            utc_offset_secs: 0,
        };
        let mut variants: Vec<String> = Vec::new();
        for (at, _) in seed.char_indices() {
            variants.push(seed[..at].to_string());
            variants.push(seed[at..].to_string());
            for c in ['"', '\\', '{', '[', '-', 'u', 'ğ', '\u{0}'] {
                variants.push(format!("{}{c}{}", &seed[..at], &seed[at..]));
            }
        }
        for v in &variants {
            let _ = Py::parse(v).map(|p| (p.py_repr(), p.dumps()));
            let _ = iso_epoch(&Py::Str(v.clone()), 0);
            let _ = transcript_pending([v.as_str()], clock);
            let _ = codex_subagents_pending([v.as_str()], clock);
            let _ = (screen_bg_count(v), screen_bg_work(v), codex_screen_count(v));
        }
        let stamp = "2026-11-23T10:00:00.123456+03:00:00.000001";
        for at in 0..=stamp.len() {
            for c in ["", "ğ", ":", "+", ".", "9"] {
                let _ = iso_epoch(&Py::Str(format!("{}{c}{}", &stamp[..at], &stamp[at..])), 0);
                let _ = iso_epoch(&Py::Str(format!("{}{c}", &stamp[..at])), 0);
            }
        }
        let deep = "[".repeat(100_000);
        assert_eq!(Py::parse(&deep), None);
    }
}
