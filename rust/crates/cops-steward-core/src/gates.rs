//! İş ve cevap kapıları (grup 2): beynin hangi soruyu/işi kapatabileceği, direktif erteleme, iş işareti doğrulaması,
//! beyin araç denetimi, acil durdurma yolu. Dosya okuması/yazması çağırandadır.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::identity::{self, InvalidStewardId, StewardPaths};
use crate::prompts::bad;
use crate::pyc;
use crate::types::{Config, Question};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static OWNER_ONLY: Fancy = LazyLock::new(|| pyc::py_regex(OWNER_ONLY_RE.as_str()));
static JOB_RED: Fancy = LazyLock::new(|| pyc::py_regex(P_JOB_RED_RE.as_str()));
static JOB_STATUS_NOTE: Fancy = LazyLock::new(|| pyc::py_regex(P_JOB_STATUS_NOTE_RE.as_str()));
// Python `[\W\w]` = her karakter; `py_pattern` sınıf içinde `\W` desteklemez
static ASK_STATUS: Fancy = LazyLock::new(|| pyc::py_regex(&P_ASK_STATUS_RE.as_str().replace(r"[\W\w]", r"(?s:.)")));
static NO_TOOLS: Fancy = LazyLock::new(|| pyc::py_regex(P_NO_TOOLS_RE.as_str()));

/// Metin sahibin kararına ait bir konu (force-push, kurulum, silme, harcama, parola/token/yetki) içeriyor mu.
/// Desen aranamazsa KAPALI yöne düşer (`true`).
pub(crate) fn owner_only(text: &str) -> bool {
    OWNER_ONLY.as_ref().and_then(|r| r.is_match(&pyc::ci_input(text)).ok()).unwrap_or(true)
}

/// Acil durdurma bayrağının yolu; `base` = `STEWARD_DIR`.
///
/// py: panic_path
pub fn panic_path(base: &str) -> Result<String, InvalidStewardId> {
    Ok(pyc::path_join(&identity::paths_for(base, None)?.root, "PANIC"))
}

/// `float(d.get(key) or 0)`
fn float_or_zero(v: Option<&Value>) -> Result<f64, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(0.0),
        Some(v) => pyc::to_float(v).ok_or_else(|| bad(v)),
    }
}

/// İŞ İSTEĞİ maddesine beynin cevabı: (izin, neden, ret gerekçesi). `jobs` = kimliğin iş kayıtları.
///
/// py: job_request_gate
pub fn job_request_gate(
    q: &Question,
    answer: &str,
    jobs: &[Map<String, Value>],
) -> Result<(bool, String, String), BadValue> {
    let allow = |red: &str| Ok((true, String::new(), red.to_string()));
    if !q.text.starts_with(JOB_REQUEST_PREFIX) {
        return allow("");
    }
    for j in jobs {
        let project = j.get("project").filter(|v| pyc::truthy(v)).map(pyc::str_of).unwrap_or_default();
        if project == q.project && float_or_zero(j.get("created_at"))? >= q.created_at - 5.0 {
            return allow("");
        }
    }
    if let Some(m) = JOB_RED.as_ref().and_then(|r| r.captures(answer).ok().flatten()) {
        let reason = pyc::strip(m.get(1).map_or("", |g| g.as_str()));
        if pyc::len(reason) >= usize::try_from(JOB_RED_MIN_CHARS).unwrap_or(0) {
            return allow(reason);
        }
    }
    let why = format!(
        "job request: close it only after steward_job_submit for this project (then answer with the job id) or with \
         'RED: <reason, >= {JOB_RED_MIN_CHARS} chars>'; a bare 'devam' would lose the request"
    );
    Ok((false, why, String::new()))
}

/// İŞ İSTEĞİ metni salt okunur bir iş türü mü.
///
/// py: is_readonly_job_request
pub fn is_readonly_job_request(text: &str) -> bool {
    let Some(rest) = text.strip_prefix(JOB_REQUEST_PREFIX) else {
        return false;
    };
    let kind = pyc::split_ws(rest).next().unwrap_or("").to_lowercase();
    READONLY_JOB_KINDS.contains(&kind.as_str())
}

/// Beyin bu soruya cevap verebilir mi: (izin, neden).
///
/// py: brain_may_answer
pub fn brain_may_answer(q: &Question) -> (bool, &'static str) {
    if !q.routine {
        return (false, "owner question (STEWARD-ASK): only the owner answers it");
    }
    if owner_only(&q.text) && !is_readonly_job_request(&q.text) {
        return (false, "owner decision (force-push/install/delete/spend/credentials): only the owner answers it");
    }
    (true, "")
}

/// Beynin reddedilmiş (`denied`) ve hâlâ açık sorusu aynı projeye/oturuma direktifi engelliyorsa o soru.
///
/// py: owner_pending_block
pub fn owner_pending_block<'a>(
    keys: &BTreeSet<String>,
    questions: &'a [Question],
    denied: &Map<String, Value>,
) -> Option<&'a Question> {
    let hit = |k: &String| !k.is_empty() && keys.contains(k);
    questions.iter().find(|q| q.status == "open" && denied.contains_key(&q.id) && (hit(&q.project) || hit(&q.source)))
}

/// Beyin direktifi şimdi gönderilmemeli mi: "busy" / "recent" / "".
///
/// py: directive_defer_reason
pub fn directive_defer_reason(busy: Option<bool>, last_directive_at: f64, now: f64, gap: f64) -> &'static str {
    if busy == Some(true) {
        "busy"
    } else if last_directive_at != 0.0 && now - last_directive_at < gap {
        "recent"
    } else {
        ""
    }
}

/// `STEWARD-JOB` gövdesi gerçek bir servis iş isteği mi: (ok, neden). `known_kinds` `None` = katalog bilinmiyor.
///
/// py: job_marker_verdict
pub fn job_marker_verdict(
    body: &str,
    known_kinds: Option<&[Value]>,
    services_registered: bool,
) -> (bool, &'static str) {
    if !services_registered {
        return (false, "no_service");
    }
    let body = pyc::strip(body);
    let (first, rest) = body.split_once(pyc::is_space).unwrap_or((body, ""));
    let kind = pyc::strip_chars(first, "`");
    if !pyc::match_dollar(&P_JOB_KIND_RE, kind) {
        return (false, "status_note");
    }
    if pyc::is_match(&JOB_STATUS_NOTE, &pyc::ci_input(pyc::lstrip(rest))) {
        return (false, "status_note");
    }
    if let Some(known) = known_kinds {
        if !known.is_empty() && !known.iter().any(|k| pyc::str_of(k) == kind) {
            return (false, "unknown_kind");
        }
    }
    (true, "")
}

/// STEWARD-ASK gövdesi gerçek soru değil, kısa bir "yok/hayır" durum cümlesi mi.
///
/// py: _ask_is_status_line
pub fn ask_is_status_line(q: &str) -> bool {
    let t = pyc::strip(q);
    !t.is_empty() && !t.contains('?') && pyc::len(t) <= 70 && pyc::is_match(&ASK_STATUS, &pyc::ci_input(t))
}

// ── beyin araçları ────────────────────────────────────────────────────────────

/// py: brain_mcp_path
pub fn brain_mcp_path(paths: &StewardPaths) -> String {
    pyc::path_join(&paths.root, BRAIN_MCP_FILE)
}

/// Beynin son cevabı "araçlar yok / karar veremedim" diyor mu.
///
/// py: brain_tools_missing_text
pub fn brain_tools_missing_text(text: &str) -> bool {
    pyc::is_match(&NO_TOOLS, &pyc::ci_input(text))
}

/// Tur gönderilmeden önce önceki turun hükmü: (yeni çağrısız tur sayacı, yeniden açma gerekçesi ya da "").
///
/// py: brain_notools_verdict
pub fn brain_notools_verdict(
    prev_tour: f64,
    mcp: &IndexMap<String, f64>,
    last_text: &str,
    nocall: i64,
    cfg: &Config,
    now: f64,
) -> (i64, String) {
    if prev_tour == 0.0 || now - prev_tour < BRAIN_NOTOOLS_MIN_AGE {
        return (nocall, String::new());
    }
    if brain_tools_missing_text(last_text) {
        return (0, "beyin 'araçlar yok' dedi".to_string());
    }
    if mcp.get("call_at").copied().unwrap_or(0.0) >= prev_tour {
        return (0, String::new());
    }
    let nocall = nocall.saturating_add(1);
    if cfg.brain_nocall_tours > 0 && nocall >= cfg.brain_nocall_tours {
        return (0, format!("art arda {nocall} turda hiç steward_* çağrısı yok"));
    }
    (nocall, String::new())
}
