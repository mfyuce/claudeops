//! Soru deposunun SAF okumaları (grup 1): seçenek/cevap normalleştirme, tekrar ve konu benzerliği, süzgeçler.
//! Depo okuma ve saat çağırandadır; "açık/cevaplanmış/iletilmemiş" süzgeçlerinin tek kopyası burasıdır.

use crate::consts_gen::*;
use crate::pyc;
use crate::types::Question;
use regex::Regex;
use serde_json::Value;
use std::collections::BTreeSet;
use std::fmt;
use std::sync::LazyLock;

// `_WORD_RE` (`\w+`): Python `\w` birleşen işaretleri saymaz.
static WORD_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"[\p{L}\p{N}_]+").ok());
type Fancy = LazyLock<Option<fancy_regex::Regex>>;
static DEFER_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DEFER_ANSWER_RE.as_str()));
static SALIENT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_SALIENT_RE.as_str()));
static TOPIC_CODE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_TOPIC_CODE_RE.as_str()));
static PAUSED_SWEEP_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_PAUSED_SWEEP_RE.as_str()));
static COUNT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_COUNT_RE.as_str()));
static HOLD_RE: Fancy = LazyLock::new(|| pyc::py_regex(HOLD_ANSWER_RE.as_str()));
// `(?<=[.!?;:])\s+|\n`
static SENTENCE_SPLIT_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"(?<=[.!?;:])\s+|\n"));

// ── seçenekler ve cevap ───────────────────────────────────────────────────────

/// Seçenek listesi: boşluk kırpılır, boş/yinelenen atılır, en çok `QUESTION_MAX_OPTIONS`; liste ya da dize değilse boş.
///
/// py: normalize_options
pub fn normalize_options(options: &Value) -> Vec<String> {
    let items: &[Value] = match options {
        Value::String(_) => std::slice::from_ref(options),
        Value::Array(a) => a,
        _ => return Vec::new(),
    };
    let mut out: Vec<String> = Vec::new();
    for o in items {
        if matches!(o, Value::Bool(_) | Value::Null) {
            continue;
        }
        let collapsed = pyc::collapse_ws(&pyc::str_of(o));
        let t = pyc::head(&collapsed, P_MAX_OPTION_CHARS as usize);
        if !t.is_empty() && !out.iter().any(|x| x == t) {
            out.push(t.to_string());
        }
        if out.len() >= QUESTION_MAX_OPTIONS as usize {
            break;
        }
    }
    out
}

/// `resolve_answer`ın Python'da istisna fırlattığı girdiler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ResolveError {
    /// `isdigit()` doğru ama `int()` kabul etmiyor (ör. "²"): Python `ValueError`
    NotAnInt(String),
    /// tek harfin büyük hâli birden çok karakter (ör. "ß"): Python `TypeError`
    MultiCharUpper(String),
}

impl fmt::Display for ResolveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ResolveError::NotAnInt(s) => {
                write!(f, "invalid literal for int() with base 10: {}", pyc::repr_str(s))
            }
            ResolveError::MultiCharUpper(s) => {
                write!(f, "ord() expected a character, but string of length {} found", pyc::len(s))
            }
        }
    }
}

impl std::error::Error for ResolveError {}

/// Ham cevap -> kaydedilecek metin: `1`..`n` / `A`.. / seçenek metni (harf duyarsız) kanonik seçenek, gerisi serbest metin.
///
/// py: resolve_answer
pub fn resolve_answer(q: &Question, raw: &str) -> Result<String, ResolveError> {
    let raw = pyc::collapse_ws(raw);
    if q.options.is_empty() || raw.is_empty() {
        return Ok(raw);
    }
    if pyc::str_is_digit(&raw) {
        if !raw.chars().all(pyc::is_decimal) {
            return Err(ResolveError::NotAnInt(raw));
        }
        // taşan sayı seçenek sayısından büyüktür: doymalı çarpma yeter
        let n = raw.chars().fold(0i64, |acc, c| acc.saturating_mul(10).saturating_add(pyc::decimal_value(c)));
        if let Some(o) = usize::try_from(n - 1).ok().and_then(|i| q.options.get(i)) {
            return Ok(o.clone());
        }
    }
    if pyc::len(&raw) == 1 {
        let upper = raw.to_uppercase();
        if !upper.is_empty() && upper.chars().all(pyc::is_alpha) {
            let mut chars = upper.chars();
            let (Some(c), None) = (chars.next(), chars.next()) else {
                return Err(ResolveError::MultiCharUpper(upper));
            };
            let idx = i64::from(u32::from(c)) - 65;
            // Python negatif indeks: harfler 65'ten küçük olamaz
            if let Some(o) = usize::try_from(idx).ok().and_then(|i| q.options.get(i)) {
                return Ok(o.clone());
            }
        }
    }
    let folded = pyc::casefold(&raw);
    Ok(q.options.iter().find(|o| pyc::casefold(o) == folded).cloned().unwrap_or(raw))
}

/// D19: cevap gerçek bir karar değil, erteleme.
///
/// py: is_defer_answer
pub fn is_defer_answer(raw: &str) -> bool {
    pyc::is_match(&DEFER_RE, &pyc::ci_input(&pyc::collapse_ws(raw)))
}

// ── benzerlik ve konu ─────────────────────────────────────────────────────────

/// `_WORD_RE.findall(text)`
fn find_words(text: &str) -> impl Iterator<Item = &str> {
    WORD_RE.iter().flat_map(move |r| r.find_iter(text).map(|m| m.as_str()))
}

/// py: _words
pub fn words(text: &str) -> BTreeSet<String> {
    find_words(&text.to_lowercase()).filter(|w| pyc::len(w) > 2).map(str::to_string).collect()
}

/// Sorunun konusunu belirleyen kısa jetonlar (G8, A3-5, opus, high...).
///
/// py: _salient
pub fn salient(text: &str) -> BTreeSet<String> {
    // eşleşme `İ`/`ı` -> `i` kopyasında aranır, jeton özgün metinden (aynı karakter konumları) alınır
    let mapped = pyc::ci_input(text);
    let chars: Vec<char> = text.chars().collect();
    let mut out = BTreeSet::new();
    let (mut at_byte, mut at_char) = (0, 0);
    let mut advance = |to: usize| {
        at_char += mapped.get(at_byte..to).map_or(0, pyc::len);
        at_byte = to;
        at_char
    };
    for m in SALIENT_RE.iter().flat_map(|r| r.find_iter(&mapped)).map_while(Result::ok) {
        let from = advance(m.start());
        let to = advance(m.end());
        let token: String = chars.get(from..to).unwrap_or_default().iter().collect();
        out.insert(token.to_lowercase());
    }
    out
}

/// Sorunun KONUSU: backtick'li adlar (yolun son parçası), iş/madde kodları ve cümle ortasındaki özel adlar.
///
/// py: topic_tokens
pub fn topic_tokens(text: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for c in P_TOPIC_BT_RE.captures_iter(text) {
        let inner = c.get(1).map_or("", |m| m.as_str());
        if let Some(first) = pyc::split_ws(inner).next() {
            let trimmed = first.trim_end_matches(|c| ".,;:".contains(c));
            out.insert(trimmed.rsplit('/').next().unwrap_or(trimmed).to_lowercase());
        }
    }
    let rest = P_TOPIC_BT_RE.replace_all(text, " ");
    for m in TOPIC_CODE_RE.iter().flat_map(|r| r.find_iter(&rest)).map_while(Result::ok) {
        out.insert(m.as_str().to_lowercase());
    }
    for c in P_TOPIC_CAP_RE.captures_iter(&rest).map_while(Result::ok) {
        let m = c.get(1).map_or("", |m| m.as_str());
        if !P_TOPIC_CAP_STOP.contains(&m) {
            out.insert(m.to_lowercase());
        }
    }
    out.remove("");
    out
}

/// py: _strong_topic
pub fn strong_topic(tok: &str) -> bool {
    tok.chars().any(pyc::is_digit) || tok.chars().any(|c| "._-".contains(c))
}

/// İki konu kümesinin eşleşme skoru (0 = eşleşmez).
///
/// py: topic_match
pub fn topic_match(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    let common: Vec<&String> = a.intersection(b).collect();
    if common.is_empty() {
        return 0.0;
    }
    let strong = common.iter().filter(|t| strong_topic(t)).count();
    if !(strong >= 2 || (strong >= 1 && common.len() >= 4)) {
        return 0.0;
    }
    let score = common.len() as f64 / a.len().min(b.len()).max(1) as f64;
    if score >= TOPIC_MIN_OVERLAP {
        score
    } else {
        0.0
    }
}

/// `len(a & b) / len(a | b)`; ikisi de boşsa 0.
fn jaccard(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    a.intersection(b).count() as f64 / a.union(b).count().max(1) as f64
}

/// Python `seq[:limit]` (negatif `limit` sondan keser).
fn slice_to<T>(mut v: Vec<T>, limit: i64) -> Vec<T> {
    let n = usize::try_from(limit.unsigned_abs()).unwrap_or(usize::MAX);
    let keep = if limit >= 0 { n } else { v.len().saturating_sub(n) };
    v.truncate(keep);
    v
}

/// Karar hafızası: `text`e en çok benzeyen cevaplanmış sorular (en benzer önce).
///
/// py: similar_answers
pub fn similar_answers<'a>(
    text: &str,
    questions: &'a [Question],
    project: &str,
    exclude_id: &str,
    limit: i64,
) -> Vec<&'a Question> {
    let (mine, mine_sal) = (words(text), salient(text));
    if mine.is_empty() {
        return Vec::new();
    }
    let mut scored: Vec<(f64, &Question)> = Vec::new();
    for q in questions {
        if q.status != "answered" || pyc::strip(&q.answer).is_empty() || q.id == exclude_id {
            continue;
        }
        let theirs = words(&q.text);
        if theirs.is_empty() {
            continue;
        }
        let mut score = jaccard(&mine, &theirs);
        let sal = salient(&q.text);
        if !mine_sal.is_empty() && !sal.is_empty() {
            score += 0.3 * mine_sal.intersection(&sal).count() as f64 / mine_sal.union(&sal).count() as f64;
        }
        if !project.is_empty() && q.project == project {
            score += 0.1;
        }
        if score >= SIMILAR_MIN_SCORE {
            scored.push((score, q));
        }
    }
    scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| b.1.answered_at.total_cmp(&a.1.answered_at)));
    slice_to(scored, limit).into_iter().map(|(_, q)| q).collect()
}

/// En yüksek skorlu ilk soru (skor 0'dan büyükse).
fn best_of<'a>(scored: impl Iterator<Item = (f64, &'a Question)>) -> Option<&'a Question> {
    let mut best: (f64, Option<&Question>) = (0.0, None);
    for (score, q) in scored {
        if score > best.0 {
            best = (score, Some(q));
        }
    }
    best.1
}

/// Kelime Jaccard'ı; eşik altındaysa konu jetonları birebir aynı olan soru eşik değerini alır. Eşik altı `None`.
fn reask_similarity(mine: &BTreeSet<String>, theirs: &BTreeSet<String>, text: &str, other: &str) -> Option<f64> {
    let mut sim = jaccard(mine, theirs);
    if sim < REASK_MIN_SIMILARITY {
        let (sal, sal_q) = (salient(text), salient(other));
        if sal.len() >= SALIENT_MIN_TOKENS as usize && sal == sal_q {
            sim = REASK_MIN_SIMILARITY;
        }
    }
    (sim >= REASK_MIN_SIMILARITY).then_some(sim)
}

fn asks_for_detail(answer: &str) -> bool {
    let low = answer.to_lowercase();
    low.contains("anlamad") || low.contains("understand")
}

/// Aynı projede yakın zamanda cevaplanmış, `text`e çok benzeyen soru (en benzeri).
///
/// py: find_answered_duplicate
pub fn find_answered_duplicate<'a>(
    questions: impl IntoIterator<Item = &'a Question>,
    project: &str,
    text: &str,
    now: f64,
) -> Option<&'a Question> {
    let mine = words(text);
    if mine.is_empty() {
        return None;
    }
    best_of(questions.into_iter().filter_map(|q| {
        if q.status != "answered" || q.project != project || q.answered_at == 0.0 {
            return None;
        }
        if now - q.answered_at > REASK_WINDOW_SECONDS as f64 || asks_for_detail(&q.answer) {
            return None;
        }
        let theirs = words(&q.text);
        if theirs.is_empty() {
            return None;
        }
        reask_similarity(&mine, &theirs, text, &q.text).map(|s| (s, q))
    }))
}

/// Aynı projede hâlâ AÇIK, yakın zamanda açılmış ve `text`e çok benzeyen soru (en benzeri).
///
/// py: find_open_similar
pub fn find_open_similar<'a>(
    questions: impl IntoIterator<Item = &'a Question>,
    project: &str,
    text: &str,
    now: f64,
) -> Option<&'a Question> {
    let mine = words(text);
    let min = OPEN_MERGE_MIN_WORDS as usize;
    if mine.len() < min {
        return None;
    }
    best_of(questions.into_iter().filter_map(|q| {
        if q.status != "open" || q.project != project || now - q.created_at > OPEN_MERGE_WINDOW_SECONDS as f64 {
            return None;
        }
        let theirs = words(&q.text);
        if theirs.len() < min {
            return None;
        }
        reask_similarity(&mine, &theirs, text, &q.text).map(|s| (s, q))
    }))
}

/// L7: aynı projede AÇIK ve KONUSU `text`inkiyle eşleşen soru (en iyi skor).
///
/// py: find_open_topic
pub fn find_open_topic<'a>(
    questions: impl IntoIterator<Item = &'a Question>,
    project: &str,
    text: &str,
    now: f64,
) -> Option<&'a Question> {
    let mine = topic_tokens(text);
    if mine.is_empty() {
        return None;
    }
    best_of(questions.into_iter().filter_map(|q| {
        if q.status != "open" || q.project != project || now - q.created_at > TOPIC_OPEN_WINDOW_SECONDS as f64 {
            return None;
        }
        Some((topic_match(&mine, &topic_tokens(&q.text)), q))
    }))
}

/// py: paused_sweep_text
pub fn paused_sweep_text(project: &str, open_items: &Value) -> String {
    format!("{project} duraklatılmış, TODO.md'sinde {} açık madde var. Açayım mı?", pyc::str_of(open_items))
}

/// Soru işaretiyle biten, en az 3 anlamlı kelimeli cümleler (kelime dizisi olarak).
///
/// py: _question_sentences
pub fn question_sentences(text: &str) -> BTreeSet<Vec<String>> {
    let mut parts = Vec::new();
    let mut start = 0;
    for m in SENTENCE_SPLIT_RE.iter().flat_map(|r| r.find_iter(text)).map_while(Result::ok) {
        parts.push(text.get(start..m.start()).unwrap_or_default());
        start = m.end();
    }
    parts.push(text.get(start..).unwrap_or_default());
    parts
        .into_iter()
        .filter(|p| p.trim_end_matches(|c| " \"'`*_)".contains(c)).ends_with('?'))
        .filter_map(|p| {
            let low = p.to_lowercase();
            let words: Vec<String> = find_words(&low).map(str::to_string).collect();
            (words.iter().filter(|w| pyc::len(w) > 2).count() >= 3).then_some(words)
        })
        .collect()
}

pub(crate) fn is_paused_sweep(text: &str) -> bool {
    // `match` + `$`: sondaki tek satır sonu geçer
    pyc::is_match(&PAUSED_SWEEP_RE, text.strip_suffix('\n').unwrap_or(text))
}

/// `_COUNT_RE.sub("#", " ".join(text.split()).lower())`
fn mask_counts(text: &str) -> String {
    let low = pyc::collapse_ws(text).to_lowercase();
    match COUNT_RE.as_ref() {
        Some(r) => r.replace_all(&low, "#").into_owned(),
        None => low,
    }
}

/// Aynı projede AÇIK ve AYNI soruyu soran kayıt (en yenisi).
///
/// py: find_open_same_ask
pub fn find_open_same_ask<'a>(
    questions: impl IntoIterator<Item = &'a Question>,
    project: &str,
    text: &str,
    now: f64,
) -> Option<&'a Question> {
    let sweep = is_paused_sweep(text);
    let masked = mask_counts(text);
    let (mine, sentences) = (words(text), question_sentences(text));
    let mut newest: Option<&Question> = None;
    for q in questions {
        if q.status != "open" || q.project != project {
            continue;
        }
        let hit = if sweep && is_paused_sweep(&q.text) {
            true
        } else if now - q.created_at > TOPIC_OPEN_WINDOW_SECONDS as f64 {
            false
        } else {
            (masked.contains('#') && mine.len() >= OPEN_MERGE_MIN_WORDS as usize && masked == mask_counts(&q.text))
                || (!sentences.is_disjoint(&question_sentences(&q.text))
                    && jaccard(&mine, &words(&q.text)) >= SAME_SENTENCE_MIN_SIMILARITY)
        };
        // `max()`: eşitlikte ilk görülen kalır
        if hit && newest.is_none_or(|n| q.created_at > n.created_at) {
            newest = Some(q);
        }
    }
    newest
}

/// L7: aynı konuya "bekle / sonra / yeniden sorma" diye cevaplanmış soru.
///
/// py: find_answered_hold
pub fn find_answered_hold<'a>(
    questions: impl IntoIterator<Item = &'a Question>,
    project: &str,
    text: &str,
    now: f64,
) -> Option<&'a Question> {
    let mine = topic_tokens(text);
    if mine.is_empty() {
        return None;
    }
    best_of(questions.into_iter().filter_map(|q| {
        if q.status != "answered" || q.project != project || q.answered_at == 0.0 {
            return None;
        }
        if now - q.answered_at > TOPIC_HOLD_WINDOW_SECONDS as f64
            || !pyc::is_match(&HOLD_RE, &pyc::ci_input(&q.answer))
            || asks_for_detail(&q.answer)
        {
            return None;
        }
        Some((topic_match(&mine, &topic_tokens(&q.text)), q))
    }))
}

// ── süzgeçler ─────────────────────────────────────────────────────────────────

/// Projenin en son `limit` cevaplanmış sorusu (eskiden yeniye); `exclude_id` hariç. Python `qs[-limit:]`: `limit` 0
/// hepsini verir, negatif `limit` baştan o kadarını atar.
///
/// py: recent_answers
pub fn recent_answers<'a>(project: &str, exclude_id: &str, limit: i64, questions: &'a [Question]) -> Vec<&'a Question> {
    let mut qs: Vec<&Question> = questions
        .iter()
        .filter(|q| {
            q.status == "answered" && q.project == project && q.id != exclude_id && !pyc::strip(&q.answer).is_empty()
        })
        .collect();
    qs.sort_by(|a, b| a.answered_at.partial_cmp(&b.answered_at).unwrap_or(std::cmp::Ordering::Equal));
    let n = usize::try_from(limit.unsigned_abs()).unwrap_or(usize::MAX);
    let from = match limit {
        0 => 0,
        1.. => qs.len().saturating_sub(n),
        _ => n.min(qs.len()),
    };
    qs.split_off(from)
}

/// py: find_question
pub fn find_question<'a>(question_id: &str, questions: &'a [Question]) -> Option<&'a Question> {
    questions.iter().find(|q| q.id == question_id)
}

/// py: open_questions
pub fn open_questions(questions: &[Question]) -> Vec<&Question> {
    questions.iter().filter(|q| q.status == "open").collect()
}

/// py: undelivered_answers
pub fn undelivered_answers(questions: &[Question]) -> Vec<&Question> {
    questions.iter().filter(|q| q.status == "answered" && q.delivered_at == 0.0).collect()
}
