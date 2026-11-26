//! Boşta kararlarının metin okuyucuları (grup 3): son cevabın bitti/kapı/hata hükmü, sahip cevabının olumlu/olumsuzluğu,
//! projenin sıradaki işi ve bayat not. Hepsi SAF.

use crate::consts_gen::*;
use crate::markers::{bare_marker, clip_words, is_conditional_note, is_no_work, rfh_marker_in, scan_markers};
use crate::pyc;
use crate::tour::OpenWork;
use crate::types::{Config, Project, Question};
use std::borrow::Cow;
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static NEXT_NOTE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_NOTE_RE.as_str()));
static NEXT_NONE_LINE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_NONE_LINE_RE.as_str()));
static TURN_FAILED_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TURN_FAILED_RE.as_str()));
static TURN_STATUS_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TURN_FAILED_STATUS_RE.as_str()));
static TURN_WORD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TURN_FAILED_WORD_RE.as_str()));
static GATE_WAIT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_GATE_WAIT_RE.as_str()));
static NEG_ANSWER_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEG_ANSWER_RE.as_str()));
static OPEN_LEAD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_OPEN_LEAD_RE.as_str()));
static OPEN_ANY_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_OPEN_ANY_RE.as_str()));
static HOLD_ANY_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_HOLD_ANY_RE.as_str()));
static OPT_NUM_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_OPT_NUM_RE.as_str()));
static FABLE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_FABLE_POLISH_RE.as_str()));
static NOTE_WORD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NOTE_WORD_RE.as_str()));
static TODO_ITEM_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TODO_ITEM_RE.as_str()));
static DONE_BULLET_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DONE_BULLET_RE.as_str()));
static REASON_SPLIT_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"(?i)[;.,]?\s*(?:neden|reason)\s*:"));
static NOTE_MENTION_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"(?i)s[ıi]radaki|siradaki"));
static NOTE_SCRUB_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"(?i)s[ıi]radaki|next\s*:"));
static NEXT_LINE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_LINE_RE.as_str()));
static NEXT_NONE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEXT_NONE_RE.as_str()));
static STATED_NEXT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_STATED_NEXT_RE.as_str()));
static DONE_TEXT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DONE_TEXT_RE.as_str()));
static NEGATED_TAIL_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_NEGATED_TAIL_RE.as_str()));

/// `re.search` büyük/küçük harf duyarsız desende (girdi `ci_input`tan geçer).
fn ci_search(re: &Fancy, text: &str) -> bool {
    pyc::is_match(re, &pyc::ci_input(text))
}

/// Eşleşmenin `group`una özgün metinde karşılık gelen dilim.
fn group_of<'a>(original: &'a str, folded: &str, caps: &fancy_regex::Captures<'_>, group: usize) -> Option<&'a str> {
    caps.get(group).map(|m| pyc::ci_span(original, folded, m.start(), m.end()))
}

/// İlk eşleşmenin `group`u (özgün metinden).
fn ci_group<'a>(re: &Fancy, text: &'a str, group: usize) -> Option<&'a str> {
    let folded = pyc::ci_input(text);
    let caps = re.as_ref()?.captures(&folded).ok()??;
    group_of(text, &folded, &caps, group)
}

/// Son cevap "sıradaki: yok" (ya da `STEWARD-NEXT: yok`) diyor mu.
///
/// py: next_none_stated
pub fn next_none_stated(text: &str) -> bool {
    scan_markers(text).next.as_deref().is_some_and(is_no_work) || ci_search(&NEXT_NONE_LINE_RE, text)
}

/// Son asistan metni (son 600 karakter) başarısız bir tur izi taşıyor mu.
///
/// py: turn_failed
pub fn turn_failed(text: &str) -> bool {
    let tail = pyc::tail(text, 600);
    ci_search(&TURN_FAILED_RE, tail)
        || pyc::splitlines(tail).iter().any(|l| ci_search(&TURN_STATUS_RE, l) && ci_search(&TURN_WORD_RE, l))
}

/// Son asistan cevabı kapıdan onay/karar beklediğini söylüyor mu (son 800 karakter).
///
/// py: waiting_for_gate
pub fn waiting_for_gate(text: &str) -> bool {
    ci_search(&GATE_WAIT_RE, pyc::tail(text, 800))
}

/// Metni TEK satıra katlar ve `limit` kod noktasında keser.
///
/// py: one_line
pub fn one_line(text: &str, limit: usize) -> String {
    pyc::head(&pyc::collapse_ws(text), limit).to_string()
}

/// Proje notu `BEKLEME` ile başlıyorsa motor onu cadence ile BAŞLATMAZ.
///
/// py: notes_wait
pub fn notes_wait(proj: &Project) -> bool {
    proj.notes
        .trim_start_matches([' ', '\t', '\r', '\n', '-', '*', '#', '>', ':', '[', '('])
        .to_lowercase()
        .starts_with("bekleme")
}

/// Boşluk eşiği (sn): `--cache-ttl 1h` oturumda ayrı eşik. 0 = kapalı.
///
/// py: ucli_idle_threshold
pub fn ucli_idle_threshold(cfg: &Config, cache_ttl: &str) -> i64 {
    if pyc::strip(cache_ttl).to_lowercase() == "1h" {
        cfg.ucli_idle_nudge_secs_1h
    } else {
        cfg.ucli_idle_nudge_secs
    }
}

fn neg_max() -> usize {
    usize::try_from(NEG_ANSWER_MAX_CHARS).unwrap_or(0)
}

/// Sahip cevabı KISA ve olumsuz/bekle mi.
///
/// py: is_negative_answer
pub fn is_negative_answer(text: &str) -> bool {
    let t = pyc::strip(text);
    !t.is_empty() && pyc::len(t) <= neg_max() && ci_search(&NEG_ANSWER_RE, t)
}

/// paused/done projede sahip cevabı açıkça olumlu iş verici mi.
///
/// py: is_open_answer
pub fn is_open_answer(text: &str) -> bool {
    let all = pyc::collapse_ws(text);
    let skip = OPT_NUM_RE.as_ref().and_then(|r| r.find(&all).ok().flatten()).map_or(0, |m| m.end());
    let t = all.get(skip..).unwrap_or("");
    !t.is_empty() && (ci_search(&OPEN_LEAD_RE, t) || (!ci_search(&HOLD_ANY_RE, t) && ci_search(&OPEN_ANY_RE, t)))
}

/// done/paused projeyi AÇMAYAN uzun sahip cevabının beyne gidecek rutin madde metni ("" = gitmez).
///
/// py: _held_instruction_item
pub fn held_instruction_item(q: &Question) -> String {
    let mut text = pyc::strip(&q.answer);
    text = text.strip_prefix(ON_BEHALF_PREFIX).unwrap_or(text);
    if q.routine || matches!(q.answered_by.as_str(), "brain" | "motor") || pyc::len(text) <= neg_max() {
        return String::new();
    }
    format!(
        "{P_HELD_ANSWER_PREFIX} {} projesi done/paused, sahibin cevabı ({}) açıkça 'aç' demediği için oturum açılmadı. \
         İş istiyorsa projeyi aç ya da işi uygun oturuma ver; yalnız 'beklet' diyorsa maddeyi 'atla' diye kapat. \
         Cevap: {text}",
        q.project, q.id
    )
}

/// Devir süresi READY FOR HANDOVER gelmeden dolunca ilk direktife eklenen eski son mesaj. Metin yoksa "".
///
/// py: expired_handover_note
pub fn expired_handover_note(last_assistant: &str, lang: &str) -> String {
    let mut t = pyc::collapse_ws(last_assistant);
    if t.is_empty() {
        return t;
    }
    let max = usize::try_from(CARD_NOTE_MAX_CHARS).unwrap_or(0);
    if pyc::len(&t) > max {
        t = format!("…{}", pyc::tail(&t, max));
    }
    if lang == "en" {
        return format!(
            "The previous session ended its handover window without a READY FOR HANDOVER note. Its last message \
             (verify against TODO.md/git before relying on it): {t}"
        );
    }
    format!(
        "Önceki oturum devir süresi READY FOR HANDOVER notu yazmadan doldu. Son mesajı (güvenmeden önce TODO.md/git \
         ile doğrula): {t}"
    )
}

/// `sıradaki` değeri bir Fable/üslup cilası mı.
///
/// py: is_fable_polish
pub fn is_fable_polish(text: &str) -> bool {
    ci_search(&FABLE_RE, text)
}

/// Projenin sıradaki işi ("" = iş yok/bilinmiyor). `real_only`: yalnız notta açık `sıradaki: <iş>` değeri.
/// `open_work`in `None` dönüşü = bilinmiyor (Python istisnası dahil).
///
/// py: next_work_hint
pub fn next_work_hint(proj: &Project, open_work: Option<OpenWork<'_>>, real_only: bool) -> String {
    let notes = proj.notes.as_str();
    let lines = pyc::splitlines(notes);
    for line in &lines {
        let Some(value) = ci_group(&NEXT_NOTE_RE, line, 1) else { continue };
        let val = clip_words(value, 160);
        if is_no_work(&val) || is_conditional_note(&val) {
            return String::new();
        }
        if !is_fable_polish(&val) && !val.is_empty() {
            return val;
        }
    }
    if real_only {
        return String::new();
    }
    if ci_search(&NOTE_MENTION_RE, notes) {
        if lines.iter().any(|l| ci_search(&NOTE_MENTION_RE, l) && is_conditional_note(l)) {
            return String::new();
        }
        return "notlardaki sıradaki iş".to_string();
    }
    match open_work.and_then(|f| f(&proj.name)) {
        Some(n) if n != 0 => "TODO.md'deki ilk açık iş".to_string(),
        _ => String::new(),
    }
}

/// py: _note_words
pub fn note_words(text: &str) -> BTreeSet<String> {
    let folded = pyc::casefold(text);
    let Some(re) = NOTE_WORD_RE.as_ref() else { return BTreeSet::new() };
    re.find_iter(&folded)
        .map_while(Result::ok)
        .map(|m| m.as_str())
        .filter(|w| !P_NOTE_STOPWORDS.contains(w) && !pyc::str_is_digit(w))
        .map(str::to_string)
        .collect()
}

fn captures<'t>(re: &Fancy, line: &'t str) -> Option<fancy_regex::Captures<'t>> {
    re.as_ref()?.captures(line).ok().flatten()
}

/// Notun `sıradaki:` işi TODO.md'de/DONE.md'de kapanmışsa o notun iş metni, yoksa "".
///
/// py: stale_next_note
pub fn stale_next_note(notes: &str, todo_text: &str, done_text: &str) -> String {
    for line in pyc::splitlines(notes) {
        let Some(value) = ci_group(&NEXT_NOTE_RE, line, 1) else { continue };
        let folded = pyc::ci_input(value);
        let cut = REASON_SPLIT_RE.as_ref().and_then(|r| r.find(&folded).ok().flatten());
        let what = pyc::strip(cut.map_or(value, |m| pyc::ci_span(value, &folded, 0, m.start())));
        let words = note_words(what);
        if (words.len() as i64) < STALE_NOTE_MIN_WORDS {
            return String::new();
        }
        let score = |item: &str| words.intersection(&note_words(item)).count() as f64 / words.len() as f64;
        let (mut open, mut closed, mut done) = (0.0_f64, 0.0_f64, 0.0_f64);
        for ln in pyc::splitlines(todo_text) {
            let Some(it) = captures(&TODO_ITEM_RE, ln) else { continue };
            let s = score(it.get(2).map_or("", |m| m.as_str()));
            if matches!(it.get(1).map(|m| m.as_str()), Some("x" | "X")) {
                closed = closed.max(s);
            } else {
                open = open.max(s);
            }
        }
        for ln in pyc::splitlines(done_text) {
            let text = if let Some(it) = captures(&TODO_ITEM_RE, ln) {
                let body = it.get(2).map_or("", |m| m.as_str());
                if !matches!(it.get(1).map(|m| m.as_str()), Some("x" | "X")) {
                    open = open.max(score(body));
                    continue;
                }
                body
            } else if let Some(b) = captures(&DONE_BULLET_RE, ln) {
                b.get(1).map_or("", |m| m.as_str())
            } else {
                continue;
            };
            done = done.max(score(text));
        }
        let stale = [(closed, STALE_NOTE_CLOSED_MIN), (done, STALE_NOTE_DONE_MIN)]
            .iter()
            .any(|&(s, need)| s >= need && s - open >= STALE_NOTE_MARGIN);
        // yalnız İLK `sıradaki:` satırı
        return if stale { clip_words(what, 160) } else { String::new() };
    }
    String::new()
}

/// `re.sub(desen, "", text)` büyük/küçük harf duyarsız desende.
fn ci_remove(re: &Fancy, text: &str) -> String {
    let folded = pyc::ci_input(text);
    let Some(re) = re.as_ref() else { return text.to_string() };
    let (mut out, mut from) = (String::new(), 0);
    for m in re.find_iter(&folded).map_while(Result::ok) {
        out.push_str(pyc::ci_span(text, &folded, from, m.start()));
        from = m.end();
    }
    out.push_str(pyc::ci_span(text, &folded, from, folded.len()));
    out
}

/// `sıradaki:` işi kapanmışsa o not satırı uyarıyla değiştirilmiş KOPYA, yoksa aynı proje.
///
/// py: without_stale_note
pub fn without_stale_note<'a>(proj: &'a Project, todo_text: &str, lang: &str, done_text: &str) -> Cow<'a, Project> {
    let what = stale_next_note(&proj.notes, todo_text, done_text);
    if what.is_empty() {
        return Cow::Borrowed(proj);
    }
    let warn = if lang != "en" {
        format!(
            "Değnekçi notundaki iş TODO.md/DONE.md'de KAPALI görünüyor, onu yapma: «{what}». TODO.md'deki açık işi al."
        )
    } else {
        format!(
            "The job in the steward note looks CLOSED in TODO.md/DONE.md, do not redo it: «{what}». Take an open \
             TODO.md item."
        )
    };
    let warn = ci_remove(&NOTE_SCRUB_RE, &warn); // uyarı yeni bir `sıradaki:` işi sanılmasın
    let mut lines: Vec<&str> = pyc::splitlines(&proj.notes);
    if let Some(slot) = lines.iter_mut().find(|l| ci_search(&NEXT_NOTE_RE, l)) {
        *slot = &warn;
    }
    let mut copy = proj.clone();
    copy.notes = lines.join("\n");
    Cow::Owned(copy)
}

/// SON "sıradaki:" satırı: (aynı satırdaki değer, sonraki satırlar). Değer satır sonunu GEÇMEZ.
///
/// py: _last_next_line
pub fn last_next_line(text: &str) -> Option<(&str, Vec<&str>)> {
    let lines = pyc::splitlines(text);
    let (i, what) =
        lines.iter().enumerate().rev().find_map(|(i, line)| ci_group(&NEXT_LINE_RE, line, 1).map(|w| (i, w)))?;
    Some((pyc::strip(what), lines.get(i + 1..).unwrap_or_default().to_vec()))
}

/// Değer boş mu (yalnız biçim işaretleri dahil).
fn blank_value(what: &str) -> bool {
    pyc::strip_chars(what, "`*_ ").is_empty()
}

/// Cevaptaki SON "sıradaki: <iş>" satırı: (var_mı, iş). "sıradaki: yok" ve boş satır -> (true, "").
///
/// py: next_line
pub fn next_line(text: &str) -> (bool, String) {
    let Some((what, _)) = last_next_line(text) else { return (false, String::new()) };
    if blank_value(what) || ci_search(&NEXT_NONE_RE, what) || is_no_work(what) {
        return (true, String::new());
    }
    (true, clip_words(what, 220))
}

/// Oturumun SON cevabında kendi söylediği sıradaki iş cümlesi; yoksa "".
///
/// py: stated_next_work
pub fn stated_next_work(text: &str) -> String {
    let (has, what) = next_line(text);
    if has {
        return what; // açık "sıradaki:" satırı her şeyden önce gelir
    }
    let folded = pyc::ci_input(text);
    // en SONDAKİ ifade
    let last = STATED_NEXT_RE.as_ref().and_then(|r| r.find_iter(&folded).map_while(Result::ok).last());
    let Some(m) = last else { return String::new() };
    let before = pyc::ci_span(text, &folded, 0, m.start());
    let end_of_match = pyc::ci_span(text, &folded, 0, m.end()).len();
    let start = before.rfind('\n').unwrap_or(0).max(before.rfind(". ").map_or(0, |i| i + 1));
    let seg = text.get(start..).unwrap_or("");
    // `seg.find("\n\n", 1)`
    let second = seg.chars().next().map_or(0, char::len_utf8);
    let paragraph = seg.get(second..).and_then(|s| s.find("\n\n")).map(|i| i + second);
    let from = end_of_match.saturating_sub(start);
    let sentence = seg.get(from..).and_then(|s| s.find(". ")).map(|i| i + from);
    let cut = [paragraph, sentence].into_iter().flatten().filter(|&i| i > 0).min();
    let seg = cut.and_then(|i| seg.get(..=i)).unwrap_or(seg);
    clip_words(seg, 220)
}

/// Son cevap işin sahipte/sahip kararında olduğunu söylüyor mu.
///
/// py: owner_wait
pub fn owner_wait(text: &str) -> bool {
    let low = text.to_lowercase();
    P_OWNER_WAIT_PHRASES.iter().any(|ph| low.contains(ph))
}

/// "işler bitti STEWARD-DONE" biçimi: işaret satırın SONUNDA.
///
/// py: _done_at_line_end
pub fn done_at_line_end(line: &str) -> bool {
    let found = DONE_TEXT_RE.as_ref().and_then(|r| r.find(line).ok().flatten());
    found.is_some_and(|m| line.get(m.end()..).unwrap_or("").chars().all(|c| pyc::is_space(c) || "`.!:;)]".contains(c)))
}

/// (işaret, ready): işaret = "" | READY FOR HANDOVER | STEWARD-DONE | "yapacak iş yok" kalıbı.
///
/// py: idle_finish_marker
pub fn idle_finish_marker(text: &str) -> (&'static str, bool) {
    let (has, what) = next_line(text);
    if has && !what.is_empty() {
        return ("", false);
    }
    // boş "sıradaki:" ardında metin: iş listesi olabilir (belirsiz), bitti sayılıp oturum kapatılmaz
    if last_next_line(text).is_some_and(|(w, tail)| blank_value(w) && tail.iter().any(|l| !pyc::strip(l).is_empty())) {
        return ("", false);
    }
    if rfh_marker_in(text) {
        return (READY_FOR_HANDOVER, true);
    }
    let mut fenced = false;
    for raw in pyc::splitlines(text) {
        if pyc::strip(raw).starts_with("```") {
            fenced = !fenced;
            continue;
        }
        if fenced || pyc::lstrip(raw).starts_with('>') {
            continue;
        }
        let line = pyc::strip(pyc::strip(raw).trim_start_matches(['-', '*', '•', ' ']));
        if bare_marker(line, MARK_DONE) || done_at_line_end(line) {
            return (MARK_DONE, false);
        }
        let low = line.to_lowercase();
        for ph in P_NO_WORK_PHRASES {
            if let Some((_, after)) = low.split_once(ph) {
                // `_NEGATED_TAIL_RE.match`: yalnız kalıbın hemen ardında
                let folded = pyc::ci_input(after);
                let negated = NEGATED_TAIL_RE
                    .as_ref()
                    .and_then(|r| r.find(&folded).ok().flatten())
                    .is_some_and(|m| m.start() == 0);
                if !negated {
                    return (ph, false);
                }
            }
        }
    }
    ("", false)
}
