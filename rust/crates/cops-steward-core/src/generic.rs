//! `generic` rolü (grup 2): üst model onay kapısı ve otonom iş listesi.

use crate::cards::{self, BadValue};
use crate::consts_gen::*;
use crate::gates::owner_only;
use crate::prompts::{items_of, phase_model_effort};
use crate::pyc;
use crate::types::{Config, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static NUMBERED_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"^\d+[.)]\s"));
static BULLET_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"^(?:[-*+]|\d+[.)])\s+"));
static EMPTY_BOX_RE: Fancy = LazyLock::new(|| pyc::py_regex(r"^\[ \]\s*"));
static TODO_DONE: Fancy = LazyLock::new(|| pyc::py_regex(P_TODO_DONE_RE.as_str()));
static TBD_DECIDED: Fancy = LazyLock::new(|| pyc::py_regex(P_TBD_DECIDED_RE.as_str()));

/// py: is_generic
pub fn is_generic(cfg: &Config) -> bool {
    cfg.role == "generic"
}

/// Ana oturum için üst kademe mi: Opus/Fable modeli ya da high/xhigh/max effort.
///
/// py: is_upper_tier
pub fn is_upper_tier(model: &str, effort: &str) -> bool {
    UPPER_MODEL_RE.is_match(model) || UPPER_EFFORTS.contains(&pyc::strip(effort).to_lowercase().as_str())
}

/// py: is_claude_model
pub fn is_claude_model(model: &str) -> bool {
    pyc::strip(model).to_lowercase().starts_with("claude-")
}

/// Fiilen üst kademede çalışan proje ana oturumları (sahibin bilinçli seçimi hariç).
///
/// py: upper_main_views
pub fn upper_main_views<'a>(
    views: &'a [SessionView],
    projects: &IndexMap<String, Project>,
    cfg: &Config,
    world: Option<&World>,
) -> Vec<&'a SessionView> {
    if cfg.role == "reviewer" {
        return Vec::new();
    }
    let own = world.map(|w| w.own_projects(projects));
    let projects = own.as_ref().unwrap_or(projects);
    views
        .iter()
        .filter(|v| v.running && v.blueprint.as_deref().is_none_or(str::is_empty))
        .filter(|v| {
            let Some(project) = projects.get(&v.name) else {
                return false;
            };
            let (model, effort) = phase_model_effort(project, cfg);
            is_claude_model(&v.live_model)
                && is_upper_tier(&v.live_model, &v.live_effort)
                && !is_upper_tier(&model, &effort)
        })
        .collect()
}

fn or_dash(s: &str) -> &str {
    if s.is_empty() {
        "-"
    } else {
        s
    }
}

/// Üst kademede çalışan ana oturuma hatırlatma metni.
///
/// py: upper_main_text
pub fn upper_main_text(project: &str, model: &str, effort: &str, lang: &str) -> String {
    let (m, e) = (or_dash(model), or_dash(effort));
    if lang == "en" {
        return format!(
            "Reminder (steward audit): this MAIN session of '{project}' is currently running on {m} / {e}. The \
             owner's rule is that the main session stays on {GENERIC_MODEL} + {GENERIC_EFFORT}; an upper tier is only \
             for a deliberate heavy step. If that step is done, switch back with `/model {GENERIC_MODEL}` and effort \
             {GENERIC_EFFORT}, and put heavy work in a sub-agent. If you raised it on purpose, finish the step and \
             ignore this reminder."
        );
    }
    format!(
        "Hatırlatma (değnekçi denetimi): '{project}' ANA oturumu şu an {m} / {e} ile çalışıyor. Sahibin kuralı: ana \
         oturum {GENERIC_MODEL} + {GENERIC_EFFORT}; üst kademe yalnız bilinçli ağır bir adım için geçici. O adım \
         bittiyse `/model {GENERIC_MODEL}` ve effort {GENERIC_EFFORT} ile geri dön, ağır işi alt ajana ver. Bilerek \
         yükselttiysen adımı bitir, bu hatırlatmayı yok say."
    )
}

/// Onay sorusunun metnine gömülen imza.
///
/// py: upper_tier_tag
pub fn upper_tier_tag(project: &str, model: &str, effort: &str) -> String {
    format!("[upper-model project={project} model={} effort={}]", or_dash(model), or_dash(effort))
}

/// py: upper_tier_question_text
pub fn upper_tier_question_text(project: &str, model: &str, effort: &str, lang: &str) -> String {
    let tag = upper_tier_tag(project, model, effort);
    let (m, e) = (or_dash(model), or_dash(effort));
    if lang == "en" {
        return format!(
            "{tag} The steward wants to run the MAIN session of '{project}' with model {m} / effort {e} (above Sonnet \
             medium). Approve? Until approved it stays on Sonnet medium."
        );
    }
    format!(
        "{tag} Değnekçi '{project}' ANA oturumunu {m} / {e} ile çalıştırmak istiyor (Sonnet medium üstü). Onaylıyor \
         musun? Onaya kadar Sonnet medium sürer."
    )
}

/// Sahip bu proje + model + effort için üst kademeyi onayladı mı.
///
/// py: upper_tier_approved
pub fn upper_tier_approved(questions: &[Question], project: &str, model: &str, effort: &str) -> bool {
    let tag = upper_tier_tag(project, model, effort);
    questions.iter().any(|q| {
        q.status == "answered" && q.source == UPPER_MODEL_SOURCE && q.text.contains(&tag) && {
            let a = pyc::strip(&q.answer).to_lowercase();
            APPROVE_WORDS.contains(&a.trim_end_matches(['.', '!']))
        }
    })
}

/// `generic_backlog` sonucu: `auto` otonom ilerletilebilir, `decide` karar gerektiren.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Backlog {
    pub auto: Vec<String>,
    pub decide: Vec<String>,
}

impl Backlog {
    fn add(&mut self, decide: bool, text: &str) {
        let t = cards::short(&Value::from(text), None);
        let cap = usize::try_from(GENERIC_BACKLOG_ITEMS).unwrap_or(0);
        if t.is_empty() || self.auto.contains(&t) || self.decide.contains(&t) {
            return;
        }
        let list = if decide { &mut self.decide } else { &mut self.auto };
        if list.len() < cap {
            list.push(t);
        }
    }
}

/// `re.sub` (desen `^` ile başlar: yalnız baştaki eşleşme atılır).
fn drop_lead<'a>(re: &Fancy, s: &'a str) -> &'a str {
    let end = re.as_ref().and_then(|r| r.find(s).ok().flatten()).map_or(0, |m| m.end());
    s.get(end..).unwrap_or(s)
}

/// TODO.md, TOBEDECIDED.md ve kartın `open_tbds`inden iş listesi.
///
/// py: generic_backlog
pub fn generic_backlog(
    todo_text: &str,
    tbd_text: &str,
    card: Option<&Map<String, Value>>,
) -> Result<Backlog, BadValue> {
    let mut out = Backlog::default();
    for ln in pyc::splitlines(todo_text) {
        let raw = pyc::strip(ln);
        let bullet = ["- ", "* ", "+ "].iter().any(|p| raw.starts_with(p));
        if !bullet && !pyc::is_match(&NUMBERED_RE, raw) {
            continue;
        }
        let t = pyc::strip(drop_lead(&BULLET_RE, raw));
        if t.is_empty() || pyc::is_match(&TODO_DONE, t) {
            continue;
        }
        let t = drop_lead(&EMPTY_BOX_RE, t);
        out.add(owner_only(t), t);
    }
    let mut tbds: Vec<String> = pyc::splitlines(tbd_text)
        .into_iter()
        .filter(|ln| ln.contains("TBD") && !pyc::lstrip(ln).starts_with('#')) // başlık satırı madde değil
        .map(|ln| {
            let t = pyc::strip(ln).trim_start_matches(['-', '*', '+', '•', ' ']);
            pyc::strip(t).to_string()
        })
        .collect();
    tbds.extend(items_of(card.and_then(|c| c.get("open_tbds")))?.iter().map(pyc::str_of));
    for t in &tbds {
        let decided = pyc::is_match(&TBD_DECIDED, &pyc::ci_input(t)) && !owner_only(t);
        out.add(!decided, t);
    }
    Ok(out)
}
