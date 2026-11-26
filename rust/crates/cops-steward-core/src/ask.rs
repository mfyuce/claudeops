//! ASK kapısının belirlenimci kısmı (`steward_ask`, grup 2): hangi sahip sorusu her zaman sahibe kalır, hangisi beynin
//! turuna girer.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::gates::owner_only;
use crate::prompts::{bad, object_of};
use crate::pyc;
use crate::types::{Config, Project, Question};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

/// Aynı soru en çok bu kadar turda beyne gösterilir (`steward_ask.SEEN_MAX_TOURS`).
pub const SEEN_MAX_TOURS: i64 = 2;
/// `steward_ask.SEEN_GAP_SECONDS`
pub const SEEN_GAP_SECONDS: f64 = 1800.0;
/// Sahibe kalan kaynaklar (`steward_ask.OWNER_SOURCES`).
pub const OWNER_SOURCES: &[&str] = &["reviewer-where", "upper_model", "dry-report", "job-red"];

/// `steward_ask._CLASSES`: sıra önemlidir, ilk eşleşen sınıf döner.
const CLASSES: [(&str, &str); 5] = [
    (
        "credentials",
        concat!(
            r"parola|şifre|password|credential|kimlik|api[\s_-]*(?:key|anahtar)|\banahtar|secret|\btoken|",
            r"giriş yap|\blog[\s-]?in\b|\bsign[\s-]?(?:in|up)\b|hesap aç|oturum aç(?:ar|abilir)\s*m[ıi]s[ıi]n|",
            r"\b2fa\b|captcha"
        ),
    ),
    (
        "spend",
        concat!(
            r"harca|\bspend|kredi|ücretli|satın|\bbuy\b|purchase|\bpaid\b|licen[cs]e|lisans|abonelik|subscri|ödeme|",
            r"ödey|\busd\b|\$\s?\d|\bdolar|\beuro?\b|€|\d\s?tl\b|fatura"
        ),
    ),
    ("destructive", r"sıfırla|\bwipe\b|\bdrop\b|reset --hard|kalıcı olarak kald|geri alınamaz|irreversib"),
    (
        "external",
        concat!(
            r"\bform(?:u|un|unu|a|da|lar\w*)?\b|e-?posta|e-?mail|\bmail|yay[ıi]n|yay[ıi]ml|publi(?:sh|c)|",
            r"submi(?:t|ssion)|arxiv|zenodo|başvur|dergiye|editöre|yazara|dışarı(?:ya)? (?:beyan|gönder)"
        ),
    ),
    (
        "owner_hands",
        concat!(
            r"dene(?:r|yebilir)\s*m[ıi]s[ıi]n|sen(?:in)? dene|elle dene|fiziksel|telefon(?:da|dan|unda)|",
            r"okur\s*musun|okuyup|okuma onay|okuduktan|bakar\s*m[ıi]s[ıi]n|can you (?:try|test|read|check)"
        ),
    ),
];

static CLASS_RES: LazyLock<Vec<(&'static str, Option<fancy_regex::Regex>)>> =
    LazyLock::new(|| CLASSES.iter().map(|(n, rx)| (*n, pyc::py_regex(&format!("(?i){rx}")))).collect());
static ASK_OWNER_NOTE: Fancy = LazyLock::new(|| pyc::py_regex("(?i)sahibe sor|sahibine sor|ask the owner"));

/// Soru HER ZAMAN sahibe kalıyorsa sınıf adı, beyne gidebiliyorsa "". `owner_projects` virgüllü proje listesi,
/// `note` proje notu.
///
/// py: owner_class
pub fn owner_class(q: &Question, owner_projects: &str, note: &str, now: f64) -> &'static str {
    if q.project.is_empty() {
        return "no_project";
    }
    if OWNER_SOURCES.contains(&q.source.as_str()) {
        return "source";
    }
    if q.text.starts_with(JOB_REQUEST_PREFIX) {
        return "job_request";
    }
    if !q.extra_texts.is_empty() {
        return "combined";
    }
    if q.deferred_until != 0.0 && q.deferred_until > now {
        return "deferred";
    }
    if owner_projects.split(',').map(pyc::strip).any(|x| !x.is_empty() && x == q.project)
        || pyc::is_match(&ASK_OWNER_NOTE, &pyc::ci_input(note))
    {
        return "owner_project";
    }
    let mut parts: Vec<&str> = vec![&q.text];
    parts.extend(q.options.iter().map(String::as_str));
    parts.push(&q.detail);
    parts.extend(q.prev_texts.iter().map(String::as_str));
    let blob = parts.join("\n");
    if owner_only(&blob) {
        return "owner_only";
    }
    let blob = pyc::ci_input(&blob);
    // desen aranamazsa soru sahibe kalır
    CLASS_RES
        .iter()
        .find(|(_, re)| re.as_ref().and_then(|r| r.is_match(&blob).ok()).unwrap_or(true))
        .map_or("", |(name, _)| name)
}

/// `owner_class` + proje durumu (kayıtsız ya da bitmiş/duraklatılmış proje sahibindir).
///
/// py: blocked_reason
pub fn blocked_reason(q: &Question, projects: &IndexMap<String, Project>, cfg: &Config, now: f64) -> &'static str {
    let Some(p) = projects.get(&q.project) else {
        return "no_project";
    };
    if p.phase == "done" || p.phase == "paused" {
        return "paused";
    }
    owner_class(q, &cfg.ask_gate_owner_projects, &p.notes, now)
}

/// Açık sahip sorusu bu turda beyne gösterilsin mi. `state`: `ask_gated`, `ask_seen`.
///
/// py: tour_eligible, steward_ask.tour_eligible
pub fn tour_eligible(
    q: &Question,
    projects: &IndexMap<String, Project>,
    cfg: &Config,
    state: &Map<String, Value>,
    now: f64,
) -> Result<bool, BadValue> {
    if q.status != "open" || q.routine {
        return Ok(false);
    }
    // `q.id in (state.get("ask_gated") or {})`
    let gated = match state.get("ask_gated").filter(|v| pyc::truthy(v)) {
        None => false,
        Some(Value::Object(o)) => o.contains_key(&q.id),
        Some(Value::Array(a)) => a.iter().any(|x| x.as_str() == Some(q.id.as_str())),
        Some(Value::String(s)) => s.contains(&q.id),
        Some(other) => return Err(bad(other)),
    };
    if gated {
        return Ok(false);
    }
    let empty = Map::new();
    let seen = object_of(object_of(state.get("ask_seen"))?.and_then(|m| m.get(&q.id)))?.unwrap_or(&empty);
    let n = match seen.get("n").filter(|v| pyc::truthy(v)) {
        None => 0,
        Some(v) => pyc::to_int(v).ok_or_else(|| bad(v))?,
    };
    if n >= SEEN_MAX_TOURS {
        return Ok(false);
    }
    if !seen.is_empty() {
        let at = match seen.get("at").filter(|v| pyc::truthy(v)) {
            None => 0.0,
            Some(v) => pyc::to_float(v).ok_or_else(|| bad(v))?,
        };
        if now - at < SEEN_GAP_SECONDS {
            return Ok(false);
        }
    }
    Ok(blocked_reason(q, projects, cfg, now).is_empty())
}
