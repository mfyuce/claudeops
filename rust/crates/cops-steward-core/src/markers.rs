//! `STEWARD-*` işaret taraması ve yanıt dili yardımcıları (grup B). `scan_markers` güvenlik açısından kritiktir:
//! düzyazıda anma, kod bloğu, alıntı ve yer tutucu işaret SAYILMAZ.

use crate::consts_gen::*;
use crate::pyc;
use crate::types::{Action, Config, Project};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fmt;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static NEXT_DONE_VALUE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_DONE_VALUE_RE.as_str()));
static NEXT_DONE_THEN_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_DONE_THEN_RE.as_str()));
static CONFIRM_DENIAL_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CONFIRM_DENIAL_RE.as_str()));
static NEXT_IDLE_REST_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_IDLE_REST_RE.as_str()));

/// `needs_ho._RFH`
const RFH: &str = "READY FOR HANDOVER";

// Python `\s` U+001C..U+001F'i de boşluk sayar.
static OPEN_HDR_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"(?m)^##[\s\x1c-\x1f]+Açık").ok());
static NEW_TBD_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"TBD#\d").ok());
static ITEM_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^###[\s\x1c-\x1f]+\d+[).]").ok());
static LANG_WORD_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"[\p{L}\p{Nl}\p{No}]+").ok()); // `[^\W\d_]+`

fn hit(re: &Option<Regex>, s: &str) -> bool {
    re.as_ref().is_some_and(|r| r.is_match(s))
}

/// Devir işareti YALNIZ satır BAŞINDA sayılır (baştaki boşluk/`#`/`*` hariç); kod bloğu içi sayılmaz.
///
/// py: rfh_marker_in, needs_ho.rfh_marker_in
pub fn rfh_marker_in(text: &str) -> bool {
    let mut fenced = false;
    for raw in pyc::splitlines(text) {
        if pyc::strip(raw).starts_with("```") {
            fenced = !fenced;
            continue;
        }
        if !fenced && raw.trim_start_matches(|c| pyc::is_space(c) || c == '#' || c == '*').starts_with(RFH) {
            return true;
        }
    }
    false
}

/// İşaretin etrafındaki biçimlendirme backtick'ini at, gövdenin KENDİ backtick'ine dokunma.
///
/// py: _unwrap_ticks
pub fn unwrap_ticks<'a>(prefix: &str, body: &'a str) -> &'a str {
    let mut body = body;
    if prefix.matches('`').count() % 2 == 1 {
        if let Some(b) = body.strip_suffix('`') {
            body = pyc::rstrip(b);
        }
    }
    if body.matches('`').count() == 2 {
        if let Some(inner) = body.strip_prefix('`').and_then(|b| b.strip_suffix('`')) {
            body = inner;
        }
    }
    pyc::strip(body)
}

fn closed_mark(line: &str) -> bool {
    line.contains("~~") || line.contains("KAPANDI") || pyc::contains_word(line, "KARAR") || line.contains('✅')
}

/// TOBEDECIDED.md'deki AÇIK karar sayısı.
///
/// py: count_open_tbd
pub fn count_open_tbd(text: &str) -> usize {
    let (mut n, mut in_open) = (0, false);
    let has_open_hdr = hit(&OPEN_HDR_RE, text);
    for ln in pyc::splitlines(text) {
        if ln.starts_with("## ") {
            in_open = ln.starts_with("## Açık");
            if hit(&NEW_TBD_RE, ln) && pyc::contains_word(ln, "AÇIK") && !closed_mark(ln) {
                n += 1;
            }
            continue;
        }
        if has_open_hdr && !in_open {
            continue;
        }
        if hit(&ITEM_RE, ln) && !closed_mark(ln) {
            n += 1;
        }
    }
    n
}

/// Proje notunda `NO_DONE_TAG` varsa `STEWARD-DONE` işlenmez.
///
/// py: done_blocked
pub fn done_blocked(project: Option<&Project>) -> bool {
    project.is_some_and(|p| p.notes.contains(NO_DONE_TAG))
}

/// `mark` satırda ANILMAYA değil İŞARET olarak yazılmış mı.
///
/// py: _bare_marker
pub fn bare_marker(line: &str, mark: &str) -> bool {
    let Some((before, tail)) = line.split_once(mark) else {
        return false;
    };
    if before.chars().next_back().is_some_and(|c| pyc::is_alnum(c) || c == '-') {
        return false;
    }
    let head = pyc::strip_chars(before, "` ");
    if !head.is_empty() && !head.ends_with(':') {
        return false;
    }
    if tail.chars().next().is_some_and(|c| pyc::is_alnum(c) || c == '-') {
        return false;
    }
    let rest = pyc::strip_chars(tail, "` ");
    rest.is_empty() || rest.starts_with(':')
}

/// `scan_markers` sonucu.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Markers {
    pub asks: Vec<String>,
    pub routines: Vec<String>,
    pub ideas: Vec<String>,
    pub blocked: Vec<String>,
    pub jobs: Vec<String>,
    pub nexts: Vec<String>,
    pub next: Option<String>,
    pub lessons: Vec<String>,
    pub details: Vec<String>,
    pub plan_ready: bool,
    pub done: bool,
    pub confirmed: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Key {
    Routines,
    Asks,
    Ideas,
    Blocked,
    Jobs,
    Nexts,
    Lessons,
    Details,
}

impl Markers {
    fn list(&mut self, key: Key) -> &mut Vec<String> {
        match key {
            Key::Routines => &mut self.routines,
            Key::Asks => &mut self.asks,
            Key::Ideas => &mut self.ideas,
            Key::Blocked => &mut self.blocked,
            Key::Jobs => &mut self.jobs,
            Key::Nexts => &mut self.nexts,
            Key::Lessons => &mut self.lessons,
            Key::Details => &mut self.details,
        }
    }
}

/// Sıra önemlidir: satırda ilk bulunan işaret kazanır.
const BODY_MARKS: [(&str, Key); 8] = [
    (MARK_ROUTINE, Key::Routines),
    (MARK_ASK, Key::Asks),
    (MARK_IDEA, Key::Ideas),
    (MARK_BLOCKED, Key::Blocked),
    (MARK_JOB, Key::Jobs),
    (MARK_NEXT, Key::Nexts),
    (MARK_LESSON, Key::Lessons),
    (MARK_DETAIL, Key::Details),
];

fn is_placeholder(body: &str) -> bool {
    // U+001F: Python `\s` boşluk sayar, `regex` saymaz.
    pyc::match_dollar(&P_PLACEHOLDER_BODY_RE, &body.replace('\u{1f}', " "))
}

fn odd_ticks(s: &str) -> bool {
    s.matches('`').count() % 2 == 1
}

/// `STEWARD-DONE-CONFIRMED` satırı teyit mi, düzyazıda anma mı? Açık inkâr anmadır; yoksa `:` varsa teyit; yoksa işaret satır başında (ya da `…:`
/// ardında) olmalı ve ardından commit hash'i gelmeli ya da hiçbir şey gelmemeli.
///
/// py: _is_confirm_line
pub fn is_confirm_line(prefix: &str, tail: &str) -> bool {
    // U+001F: Python `\s` boşluk sayar, `regex` saymaz.
    let spaced = tail.replace('\u{1f}', " ");
    // Python `match`: yalnız baştaki eşleşme
    let leads = |re: &Regex| re.find(&spaced).is_some_and(|m| m.start() == 0);
    // desen `^` taşımaz: Python `match` gibi yalnız baştaki eşleşme sayılır
    let denial =
        CONFIRM_DENIAL_RE.as_ref().and_then(|re| re.find(&pyc::ci_input(&spaced)).ok().flatten().map(|m| m.start()));
    if denial == Some(0) {
        return false;
    }
    if leads(&P_CONFIRM_COLON_RE) {
        return true;
    }
    let head = pyc::strip_chars(prefix, "`*_#.) 0123456789✅✔");
    if !head.is_empty() && !head.ends_with(':') {
        return false;
    }
    leads(&P_CONFIRM_LEAD_HASH_RE) || pyc::strip_chars(tail, "`*_ .!").is_empty()
}

/// Bir oturum yanıtındaki `STEWARD-*` satırlarını çıkar.
///
/// py: scan_markers
pub fn scan_markers(text: &str) -> Markers {
    let mut out = Markers::default();
    let mut fenced = false;
    let mut cont: Option<(Key, usize)> = None; // `:` ile biten soru/engel gövdesi alt satırlarla sürer
    for raw in pyc::splitlines(text) {
        if pyc::strip(raw).starts_with("```") {
            fenced = !fenced;
            cont = None;
            continue;
        }
        if fenced || pyc::lstrip(raw).starts_with('>') {
            continue;
        }
        let line = pyc::strip(pyc::strip(raw).trim_start_matches(['-', '*', '•', ' ']));
        if line.is_empty() {
            cont = None;
            continue;
        }
        if let Some((k, i)) = cont {
            if !line.contains("STEWARD-") {
                if let Some(item) = out.list(k).get_mut(i) {
                    if k == Key::Details {
                        item.push('\n');
                        item.push_str(pyc::strip(raw));
                    } else {
                        item.push(' ');
                        item.push_str(line);
                    }
                }
                continue;
            }
        }
        cont = None;
        let found = BODY_MARKS.iter().find_map(|&(mark, key)| line.split_once(mark).map(|(p, rest)| (p, rest, key)));
        let Some((prefix, rest, key)) = found else {
            scan_state_marks(line, &mut out);
            continue;
        };
        let raw_body = pyc::strip(rest);
        if odd_ticks(prefix) && raw_body.contains('`') && !raw_body.ends_with('`') {
            continue; // düzyazıda satır içi kodla anma
        }
        let body = unwrap_ticks(prefix, raw_body);
        if is_placeholder(body) {
            continue;
        }
        let at_start = prefix.is_empty() || prefix == "`";
        if key == Key::Nexts && !at_start {
            continue;
        }
        if key == Key::Jobs && (!at_start || !body.chars().next().is_some_and(pyc::is_alpha)) {
            continue;
        }
        if body.is_empty() {
            continue;
        }
        let list = out.list(key);
        list.push(body.to_string());
        let last = list.len() - 1;
        let open_ended =
            matches!(key, Key::Asks | Key::Routines | Key::Blocked) && body.trim_end_matches(['`', ' ']).ends_with(':');
        if open_ended || key == Key::Details {
            cont = Some((key, last));
        }
        if key == Key::Nexts {
            out.next = Some(body.to_string()); // en SONDAKİ satır kazanır
        }
    }
    out
}

/// Gövdesiz durum işaretleri (PLAN-READY / DONE-CONFIRMED / DONE).
fn scan_state_marks(line: &str, out: &mut Markers) {
    if bare_marker(line, MARK_PLAN_READY) {
        out.plan_ready = true;
    } else if let Some((prefix, rest)) = line.split_once(MARK_DONE_CONFIRMED) {
        let body = unwrap_ticks(prefix, pyc::strip(rest.trim_start_matches(':')));
        if is_confirm_line(prefix, rest) && !is_placeholder(body) && !body.contains('<') && !odd_ticks(prefix) {
            out.confirmed = Some(body.to_string()); // boş gövde de bir teyit denemesi
        }
    } else if bare_marker(line, MARK_DONE) && !line.contains(MARK_END) {
        out.done = true;
    }
}

// ── yanıt dili ────────────────────────────────────────────────────────────────

/// py: reply_language_line
pub fn reply_language_line(lang: &str) -> &'static str {
    if lang == "en" {
        REPLY_LANG_EN
    } else {
        REPLY_LANG_TR
    }
}

/// SAF sezgi: `text` beklenen dilde DEĞİL mi (yalnız açık ise true).
///
/// py: text_lang_mismatch
pub fn text_lang_mismatch(text: &str, lang: &str) -> bool {
    let lower = text.to_lowercase();
    let words: Vec<&str> =
        LANG_WORD_RE.as_ref().map(|r| r.find_iter(&lower).map(|m| m.as_str()).collect()).unwrap_or_default();
    if words.len() < 6 {
        return false;
    }
    let hits = |set: &[&str]| words.iter().filter(|w| set.contains(*w)).count();
    let tr_chars = words.iter().filter(|w| w.chars().any(|c| "çğıöşü".contains(c))).count();
    let (tr_hits, en_hits, de_hits) = (hits(P_TR_WORDS), hits(P_EN_WORDS), hits(P_DE_WORDS));
    if lang == "en" {
        ((tr_chars + tr_hits) >= 3 || de_hits >= 3) && en_hits == 0
    } else {
        tr_chars == 0 && tr_hits == 0 && (en_hits + de_hits) >= 3
    }
}

/// `scan_markers` sonucundaki görünen metinler (soru, rutin, engel, sıradaki iş, fikir) tek dizgede.
///
/// py: marker_texts
pub fn marker_texts(m: &Markers) -> String {
    let mut parts: Vec<&str> =
        [&m.asks, &m.routines, &m.blocked, &m.nexts, &m.ideas].into_iter().flatten().map(String::as_str).collect();
    if let Some(next) = m.next.as_deref().filter(|n| !n.is_empty()) {
        parts.push(next);
    }
    parts.join(" ")
}

/// `state["lang_fix_at"]` bozuk (Python `dict()`/`float()` istisnası).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BadLangFixState(pub String);

impl fmt::Display for BadLangFixState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "bad state.lang_fix_at: {}", self.0)
    }
}

impl std::error::Error for BadLangFixState {}

/// Yanlış dilde `STEWARD-*` metni: oturum başına günde BİR düzeltme notu. `state["lang_fix_at"]` yerinde güncellenir.
///
/// py: lang_fix_action
pub fn lang_fix_action(
    name: &str,
    proj: &str,
    text: &str,
    cfg: &Config,
    state: &mut Map<String, Value>,
    now: f64,
) -> Result<Option<Action>, BadLangFixState> {
    if name.is_empty() || !text_lang_mismatch(text, &cfg.lang) {
        return Ok(None);
    }
    let mut last = match state.get("lang_fix_at").filter(|v| pyc::truthy(v)) {
        None => Map::new(),
        Some(Value::Object(o)) => o.clone(),
        Some(other) => return Err(BadLangFixState(other.to_string())),
    };
    let at = match last.get(name).filter(|v| pyc::truthy(v)) {
        None => 0.0,
        Some(v) => pyc::to_float(v).ok_or_else(|| BadLangFixState(v.to_string()))?,
    };
    if now - at < LANG_FIX_COOLDOWN_SECONDS {
        return Ok(None);
    }
    last.insert(name.to_string(), Value::from(now));
    state.insert("lang_fix_at".to_string(), Value::Object(last));
    let en = cfg.lang == "en";
    let mut payload = Map::new();
    payload.insert("text".into(), Value::from(if en { LANG_FIX_TEXT_EN } else { LANG_FIX_TEXT_TR }));
    payload.insert("project".into(), Value::from(proj));
    payload.insert("lang_fix".into(), Value::Bool(true));
    Ok(Some(Action {
        kind: "nudge".into(),
        name: name.into(),
        reason: if en { "STEWARD-* text not in panel language" } else { "STEWARD-* metni panel dilinde değil" }.into(),
        payload,
    }))
}

// ── sıradaki iş bildirimi (tur maddeleri ve `project_next` kaydı) ─────────────

static COND_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_COND_RE.as_str()));

/// Metni tek satıra katlar; `limit` kod noktasını aşıyorsa son TAM kelimede keser (sonuna `…`).
///
/// py: clip_words
pub fn clip_words(text: &str, limit: usize) -> String {
    let t = pyc::collapse_ws(text);
    if pyc::len(&t) <= limit {
        return t;
    }
    let mut cut = pyc::head(&t, limit);
    if !pyc::skip(&t, limit).starts_with(' ') {
        if let Some((before, _)) = cut.rsplit_once(' ') {
            cut = before;
        }
    }
    format!("{}…", cut.trim_end_matches([' ', ',', ';', ':', '.', '-']))
}

/// Not "X olursa Y" gibi koşullu mu.
///
/// py: is_conditional_note
pub fn is_conditional_note(text: &str) -> bool {
    pyc::is_match(&COND_RE, &pyc::ci_input(text))
}

/// "sıradaki" değeri "iş yok" anlamında mı (yok/none/-/n/a/bitti/done).
///
/// py: _is_no_work_value
pub fn is_no_work(value: &str) -> bool {
    if P_NO_WORK_VALUES.contains(&pyc::strip_chars(value, " .`*_,;:!").to_lowercase().as_str()) {
        return true;
    }
    let folded = pyc::ci_input(value);
    if !pyc::is_match(&NEXT_DONE_VALUE_RE, &folded) {
        return false;
    }
    // "bitti, şimdi X": devamı (`rest`) sıradaki iştir
    let then = NEXT_DONE_THEN_RE.as_ref().and_then(|re| re.captures(&folded).ok().flatten());
    let Some(m) = then.and_then(|c| c.name("rest")) else { return true };
    pyc::is_match(&NEXT_IDLE_REST_RE, &pyc::ci_input(m.as_str()))
        || is_no_work(pyc::ci_span(value, &folded, m.start(), m.end()))
}

/// Son yanıttaki `STEWARD-NEXT: <iş>` gerçek (koşulsuz) bir işse o iş, değilse "".
///
/// py: marker_next_work
pub fn marker_next_work(text: &str) -> String {
    if !text.contains("STEWARD-NEXT") {
        return String::new();
    }
    let next = scan_markers(text).next.unwrap_or_default();
    let val = pyc::strip(&next);
    if val.is_empty() || is_no_work(val) || is_conditional_note(val) {
        return String::new();
    }
    clip_words(val, 200)
}
