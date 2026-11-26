//! Proje kartları (grup C): ham kart alanları, kart prompt'u, model yanıtının ayrıştırılması, yenileme/duraklatma kararları.
//! Belge/`git` okuması, model çağrısı ve kart deposu çağırandadır.

use crate::consts_gen::*;
use crate::identity::{self, InvalidStewardId, PathsArg};
use crate::pyc;
use crate::types::Project;
use indexmap::IndexMap;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fmt;
use std::sync::LazyLock;

// Python `\s` U+001C..U+001F'i de boşluk sayar.
static FENCED_JSON_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(?s)```(?:json)?[\s\x1c-\x1f]*(\{.*\})[\s\x1c-\x1f]*```").ok());

/// Bozuk tipte/değerde alan (Python `float()`/`int()`/dilimleme istisnası fırlatırdı).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BadValue(pub String);

impl fmt::Display for BadValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "bad value: {}", self.0)
    }
}

impl std::error::Error for BadValue {}

/// `str(v or "")`
pub(crate) fn str_or_empty(v: Option<&Value>) -> String {
    v.filter(|v| pyc::truthy(v)).map(pyc::str_of).unwrap_or_default()
}

/// `float(v or 0.0)`
fn float_or_zero(v: Option<&Value>) -> Result<f64, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(0.0),
        Some(v) => pyc::to_float(v).ok_or_else(|| BadValue(v.to_string())),
    }
}

fn list_cap() -> usize {
    usize::try_from(CARD_LIST_ITEMS).unwrap_or(0)
}

fn text_cap() -> usize {
    usize::try_from(CARD_TEXT_CHARS).unwrap_or(0)
}

/// py: card_path
pub fn card_path(base: &str, name: &str, paths: PathsArg<'_>) -> Result<String, InvalidStewardId> {
    Ok(pyc::path_join(&identity::pp(base, paths)?.cards, &format!("{name}.json")))
}

/// Modelsiz ham kart (`build_raw_card` / `raw_card_from_docs` çıktısı).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct RawCard {
    pub docs: IndexMap<String, String>,
    pub git_log: Vec<String>,
    pub last_commit: f64,
    /// Yalnız uzak projede (yerel kartta anahtar hiç yok).
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub git_unknown: bool,
    pub source_hash: String,
}

/// UZAK projenin ham kartı: yalnız belge başları, git bilgisi yok.
///
/// py: raw_card_from_docs
pub fn raw_card_from_docs(docs: &IndexMap<String, String>) -> RawCard {
    let mut data = Vec::new();
    for d in CARD_DOCS {
        if let Some(body) = docs.get(*d) {
            data.extend_from_slice(format!("\0{d}\0{body}").as_bytes());
        }
    }
    let hash = pyc::sha1_hex(&data);
    RawCard {
        docs: docs.clone(),
        git_log: Vec::new(),
        last_commit: 0.0,
        git_unknown: true,
        source_hash: pyc::head(&hash, 16).to_string(),
    }
}

/// `_short(text, n)`: boşluklar teke iner, `n` kod noktasında `…` ile kesilir. `n` verilmezse Python'daki `CARD_TEXT_CHARS`.
///
/// py: _short
pub fn short(text: &Value, n: Option<usize>) -> String {
    short_str(&str_or_empty(Some(text)), n.unwrap_or_else(text_cap))
}

fn short_str(text: &str, n: usize) -> String {
    crate::prompts::clip(&pyc::collapse_ws(text), n)
}

/// py: _str_list
pub fn str_list(v: &Value) -> Vec<String> {
    let items: &[Value] = match v {
        Value::String(_) => std::slice::from_ref(v),
        Value::Array(a) => a,
        _ => return Vec::new(),
    };
    items
        .iter()
        .filter(|x| !pyc::strip(&str_or_empty(Some(x))).is_empty())
        .take(list_cap())
        .map(|x| short(x, None))
        .collect()
}

/// TOBEDECIDED başından `TBD`'li satırlar.
///
/// py: _tbd_lines
pub fn tbd_lines(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    for ln in pyc::splitlines(text) {
        let t = pyc::strip(pyc::strip(ln).trim_start_matches(|c| "-*#• ".contains(c)));
        if t.contains("TBD") {
            out.push(short_str(t, text_cap()));
        }
        if out.len() >= list_cap() {
            break;
        }
    }
    out
}

/// py: _goal_from_docs
pub fn goal_from_docs(docs: &IndexMap<String, String>) -> String {
    pyc::splitlines(docs.get("GOAL.md").map_or("", String::as_str))
        .into_iter()
        .map(pyc::strip)
        .find(|t| !t.is_empty() && !t.starts_with('#'))
        .map(|t| short_str(t, text_cap()))
        .unwrap_or_default()
}

/// Kartın model/ham alanları.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct CardFields {
    pub goal: String,
    pub phase_guess: String,
    pub next_step: String,
    pub open_tbds: Vec<String>,
    pub blockers: Vec<String>,
    pub recent_done: Vec<String>,
}

/// Modele gidilemeyen/yanıtı bozuk durumda kartın içi: ham veriden türetilir.
///
/// py: raw_card_fields
pub fn raw_card_fields(raw: &RawCard, project: Option<&Project>) -> CardFields {
    let goal = match project.map(|p| p.goal.as_str()).filter(|g| !g.is_empty()) {
        Some(g) => g.to_string(),
        None => goal_from_docs(&raw.docs),
    };
    CardFields {
        goal: short_str(&goal, text_cap()),
        phase_guess: project.map(|p| p.phase.as_str()).filter(|p| PHASES.contains(p)).unwrap_or("").to_string(),
        next_step: String::new(),
        open_tbds: tbd_lines(raw.docs.get("TOBEDECIDED.md").map_or("", String::as_str)),
        blockers: Vec::new(),
        recent_done: raw
            .git_log
            .iter()
            .filter_map(|ln| ln.splitn(3, ' ').nth(2))
            .take(3)
            .map(|s| short_str(s, text_cap()))
            .collect(),
    }
}

/// Modelin yanıtından kart alanları; ayrıştırılamıyor ya da tanınan alan yoksa `None`.
///
/// py: parse_card_json
pub fn parse_card_json(text: &str) -> Option<CardFields> {
    if text.is_empty() {
        return None;
    }
    let t = pyc::strip(text);
    let fenced = FENCED_JSON_RE.as_ref().and_then(|r| r.captures(t)).and_then(|c| c.get(1));
    let cand = match fenced {
        Some(m) => m.as_str(),
        None => {
            let (i, j) = (t.find('{')?, t.rfind('}')?);
            if j <= i {
                return None;
            }
            t.get(i..=j)?
        }
    };
    let Ok(Value::Object(d)) = serde_json::from_str::<Value>(cand) else {
        return None;
    };
    const KNOWN: [&str; 6] = ["goal", "phase_guess", "next_step", "open_tbds", "blockers", "recent_done"];
    if !KNOWN.iter().any(|k| d.contains_key(*k)) {
        return None;
    }
    let field = |k: &str| d.get(k).unwrap_or(&Value::Null);
    let phase = pyc::strip(&str_or_empty(d.get("phase_guess"))).to_lowercase();
    Some(CardFields {
        goal: short(field("goal"), None),
        phase_guess: if PHASES.contains(&phase.as_str()) { phase } else { String::new() },
        next_step: short(field("next_step"), None),
        open_tbds: str_list(field("open_tbds")),
        blockers: str_list(field("blockers")),
        recent_done: str_list(field("recent_done")),
    })
}

/// Kart özeti için tek seferlik prompt.
///
/// py: build_card_prompt
pub fn build_card_prompt(name: &str, raw: &RawCard, project: Option<&Project>, lang: &str) -> String {
    let tr = lang != "en";
    let mut parts: Vec<String> = Vec::new();
    let n = CARD_LIST_ITEMS;
    parts.push(if tr {
        format!(
            "Aşağıda '{name}' adlı bir projenin belge başları ve son commit'leri var. Bunlardan projenin durum kartını \
             çıkar. YALNIZ tek bir JSON nesnesi yaz (açıklama, markdown çiti yok), şu anahtarlarla:\n\
             {{\"goal\": \"tek cümle amaç\", \"phase_guess\": \"idea|planning|planned|paused|done\", \
             \"next_step\": \"sıradaki tek somut iş\", \"open_tbds\": [\"açık karar maddeleri\"], \
             \"blockers\": [\"engeller\"], \"recent_done\": [\"son biten işler\"]}}\n\
             Listeler en çok {n} madde, her alan kısa ve Türkçe olsun. Bilmediğin alanı boş bırak \
             (\"\" ya da []); uydurma. 'blockers' YALNIZ belgelerde ŞU AN açık görünen engelleri içersin; geçmiş/çözülmüş \
             olabilecek ya da doğrulayamadığın engeli yazma (bayat engel satırı yanlış alarm üretir)."
        )
    } else {
        format!(
            "Below are the document heads and recent commits of a project called '{name}'. Produce its status card. \
             Write ONLY a single JSON object (no prose, no markdown fence) with these keys:\n\
             {{\"goal\": \"one-sentence goal\", \"phase_guess\": \"idea|planning|planned|paused|done\", \
             \"next_step\": \"the single next concrete task\", \"open_tbds\": [\"open decision items\"], \
             \"blockers\": [\"blockers\"], \"recent_done\": [\"recently finished work\"]}}\n\
             At most {n} items per list, every field short. Leave unknown fields empty (\"\" or []); do not invent. 'blockers' must list ONLY blockers the documents show as open NOW; omit any that may be past/\
             resolved or that you cannot verify (a stale blocker line causes false alarms)."
        )
    });
    if let Some(p) = project {
        if !p.goal.is_empty() {
            let label = if tr { "Kayıtlı amaç: " } else { "Registered goal: " };
            parts.push(format!("{label}{}", short_str(&p.goal, 600)));
        }
        let label = if tr { "Kayıtlı faz: " } else { "Registered phase: " };
        parts.push(format!("{label}{}", p.phase));
    }
    for (d, body) in &raw.docs {
        parts.push(format!("=== {d} ===\n{body}"));
    }
    if !raw.git_log.is_empty() {
        parts.push(format!("=== git log -5 ===\n{}", raw.git_log.join("\n")));
    }
    if raw.git_unknown {
        parts.push(if tr { "=== git ===\nremote: bilinmiyor" } else { "=== git ===\nremote: unknown" }.to_string());
    }
    if raw.docs.is_empty() && raw.git_log.is_empty() {
        parts.push(if tr { "(belge ya da commit yok)" } else { "(no documents or commits)" }.to_string());
    }
    parts.join("\n\n")
}

/// `card_model` doluysa o; boşsa `choices` içinde "haiku" geçen en büyük (sıralamada son) ad, yoksa `fallback`.
///
/// py: pick_card_model
pub fn pick_card_model(configured: &str, choices: &[String], fallback: &str) -> String {
    let c = pyc::strip(configured);
    if !c.is_empty() {
        return c.to_string();
    }
    choices
        .iter()
        .filter(|c| c.to_lowercase().contains("haiku"))
        .max()
        .map_or_else(|| fallback.to_string(), Clone::clone)
}

/// Beynin `phase=paused` isteği için karar: (kabul mü, ret gerekçesi).
///
/// py: brain_pause_verdict
pub fn brain_pause_verdict(
    card: Option<&Map<String, Value>>,
    running: bool,
    reason: &str,
    now: f64,
) -> Result<(bool, &'static str), BadValue> {
    if pyc::strip(reason).is_empty() {
        return Ok((false, "a reason is required for pause"));
    }
    if running {
        return Ok((false, "a session is running for this project"));
    }
    let Some(card) = card.filter(|c| !c.is_empty()) else {
        return Ok((false, "no project card yet (state unknown)"));
    };
    let last = float_or_zero(card.get("last_activity"))?;
    if last != 0.0 && now - last < BRAIN_PAUSE_RECENT_SECONDS as f64 {
        return Ok((false, "a commit landed in the last 24 hours"));
    }
    let open_work =
        !pyc::strip(&str_or_empty(card.get("next_step"))).is_empty() || card.get("open_tbds").is_some_and(pyc::truthy);
    if open_work && !card.get("blockers").is_some_and(pyc::truthy) {
        return Ok((false, "open work with no blocker (next step / open TBD): the project should continue"));
    }
    Ok((true, ""))
}

/// "" = yenileme gerekmez; aksi halde neden: missing | stale | changed | old.
///
/// py: card_refresh_reason
pub fn card_refresh_reason(
    card: Option<&Map<String, Value>>,
    source_hash: &str,
    now: f64,
    max_age_hours: i64,
) -> Result<&'static str, BadValue> {
    let Some(card) = card else {
        return Ok("missing");
    };
    let max_age = max_age_hours.saturating_mul(3600) as f64;
    let attempt_at = float_or_zero(card.get("attempt_at"))?;
    let same = |key: &str| card.get(key).and_then(Value::as_str) == Some(source_hash);
    if same("attempt_hash") && (max_age == 0.0 || now - attempt_at < max_age) {
        return Ok("");
    }
    if card.get("stale").is_some_and(pyc::truthy) {
        return Ok("stale");
    }
    if !same("source_hash") {
        return Ok("changed");
    }
    if max_age != 0.0 {
        let updated = float_or_zero(card.get("updated_at"))?;
        let newest = if attempt_at > updated { attempt_at } else { updated };
        if now - newest >= max_age {
            return Ok("old");
        }
    }
    Ok("")
}

/// py: card_one_liner
pub fn card_one_liner(card: Option<&Map<String, Value>>) -> String {
    str_or_empty(card.and_then(|c| c.get("next_step")))
}
