//! "Neden ilerlemiyor" açıklaması (grup 3): motorun karar sırasıyla proje başına TEK neden. SAF.

use crate::cards::{str_or_empty, BadValue};
use crate::consts_gen::*;
use crate::identity::project_key;
use crate::idle::{recorded_open, IdleInput};
use crate::idletext::*;
use crate::markers::marker_next_work;
use crate::prompts::object_of;
use crate::pyc;
use crate::recovery::{dict_of, doc, float_of, int_of, truthy_at};
use crate::tour::OpenWork;
use crate::types::{Action, Config, Project, Question, SessionView, World};
use crate::world::bg_blocks_message;
use indexmap::IndexMap;
use serde_json::{json, Map, Value};

type Doc = Map<String, Value>;

/// py: _why
pub fn why(code: &str, lang: &str, detail: &str, extra: Doc) -> Doc {
    let table = if lang == "en" { &*P_WHY_EN } else { &*P_WHY_TR };
    let text = table.get(code).and_then(Value::as_str).unwrap_or(code);
    let mut d = doc(json!({"code": code, "text": text, "detail": detail}));
    d.extend(extra);
    d
}

/// `explain_idle` girdisi. `actions` = bu tick'in nihai eylemleri.
#[derive(Clone, Copy)]
pub struct ExplainInput<'a> {
    pub views: &'a [SessionView],
    pub projects: &'a IndexMap<String, Project>,
    pub state: &'a Doc,
    pub cfg: &'a Config,
    pub now: f64,
    pub questions: &'a [Question],
    pub actions: &'a [Action],
    pub world: Option<&'a World>,
    pub open_work: Option<OpenWork<'a>>,
}

impl<'a> ExplainInput<'a> {
    /// Boşta planlarıyla ortak alanlardan kurar (`planned` = nihai eylemler).
    pub fn from_idle(input: IdleInput<'a>, questions: &'a [Question], open_work: Option<OpenWork<'a>>) -> Self {
        let IdleInput { views, projects, state, cfg, now, planned, world } = input;
        ExplainInput { views, projects, state, cfg, now, questions, actions: planned, world, open_work }
    }
}

fn stamp(ts: f64) -> String {
    pyc::localtime(ts).format("%d.%m %H:%M").to_string()
}

/// `(d or {}).get(key)`
fn entry<'a>(state: &'a Doc, section: &str, key: &str) -> Result<Option<&'a Value>, BadValue> {
    Ok(object_of(state.get(section))?.and_then(|o| o.get(key)))
}

/// `name in (v or [])`
fn contains(v: Option<&Value>, name: &str) -> Result<bool, BadValue> {
    Ok(match v.filter(|v| pyc::truthy(v)) {
        None => false,
        Some(Value::Array(a)) => a.iter().any(|x| x.as_str() == Some(name)),
        Some(Value::String(s)) => s.contains(name),
        Some(Value::Object(o)) => o.contains_key(name),
        Some(other) => return Err(BadValue(other.to_string())),
    })
}

fn plain(code: &str, lang: &str) -> Doc {
    why(code, lang, "", Map::new())
}

/// Çalışan oturumu olmayan proje: uğrama/başlatma kararının nedeni.
fn without_session(proj: &Project, input: &ExplainInput<'_>) -> Result<Doc, BadValue> {
    let ExplainInput { projects, state, cfg, now, actions, .. } = *input;
    let (lang, name) = (cfg.lang.as_str(), proj.name.as_str());
    if let Some(a) = actions.iter().find(|a| a.kind == "start" && a.name == name) {
        return Ok(why("starting", lang, &a.reason, Map::new()));
    }
    let cooldown = BRAIN_STOP_COOLDOWN_SECONDS as f64;
    for (k, v) in dict_of(state.get("brain_stopped"))? {
        let keys = projects.keys().map(String::as_str);
        if project_key(&k, keys) != name {
            continue;
        }
        let at = float_of(Some(&v))?;
        if now - at < cooldown {
            let until = pyc::to_float(&v).ok_or_else(|| BadValue(v.to_string()))? + cooldown;
            return Ok(why("brain_stopped", lang, &stamp(until), doc(json!({"until": until}))));
        }
    }
    if proj.cadence_minutes <= 0 {
        return Ok(why("cadence_off", lang, "cadence_minutes=0", Map::new()));
    }
    if !cfg.auto_start {
        return Ok(plain("auto_start_off", lang));
    }
    let observed = float_of(dict_of(state.get("observed_visit"))?.get(name))?;
    // `max(a, b)`: eşitlikte ilk
    let last = if observed > proj.last_visit { observed } else { proj.last_visit };
    let cadence = proj.cadence_minutes.saturating_mul(60) as f64;
    if last != 0.0 && now - last < cadence {
        let left = pyc::floor_div(cadence - (now - last), 60.0) as i64;
        let detail = if lang != "en" { format!("{left} dk sonra") } else { format!("in {left} min") };
        return Ok(why("cadence_wait", lang, &detail, doc(json!({"minutes_left": left}))));
    }
    let blocked = object_of(state.get("start_blocked"))?;
    if contains(blocked.and_then(|b| b.get("projects")), name)? {
        let reason = str_or_empty(blocked.and_then(|b| b.get("reason")));
        let detail = match P_START_BLOCK_TR.get(&reason).and_then(Value::as_str) {
            Some(tr) if lang != "en" => tr,
            _ => &reason,
        };
        return Ok(why("start_blocked", lang, detail, doc(json!({"reason": reason}))));
    }
    let detail = if lang != "en" { "sıra bekliyor" } else { "waiting for its turn" };
    Ok(why("start_blocked", lang, detail, doc(json!({"reason": "queue"}))))
}

/// Tek çalışan oturumu olan projenin nedeni.
fn with_session(proj: &Project, v: &SessionView, input: &ExplainInput<'_>) -> Result<Doc, BadValue> {
    let ExplainInput { state, cfg, now, actions, open_work, .. } = *input;
    let (lang, name) = (cfg.lang.as_str(), proj.name.as_str());
    let en = lang == "en";
    let txt = v.last_assistant.as_str();
    if v.busy == Some(true) {
        return Ok(plain("working", lang));
    }
    if let Some(ds) = entry(state, "dialog_stuck", &v.name)?.and_then(Value::as_object) {
        let show = |k: &str| ds.get(k).map(pyc::str_of).unwrap_or_default();
        let detail = format!("{}: {}", show("kind"), show("head"));
        let kind = ds.get("kind").cloned().unwrap_or_else(|| json!(""));
        let extra = doc(json!({"kind": kind, "since": float_of(ds.get("since"))?}));
        return Ok(why("dialog_stuck", lang, pyc::head(&detail, 200), extra));
    }
    if let Some(sf) = entry(state, "send_fail", &v.name)?.and_then(Value::as_object) {
        let n = int_of(sf.get("n"))?;
        if n >= 3 {
            let count = pyc::str_of(sf.get("n").unwrap_or(&Value::Null));
            let error = sf.get("error").map(pyc::str_of).unwrap_or_default();
            let detail = format!("{count}x {error}");
            let extra = doc(json!({"n": n, "since": float_of(sf.get("since"))?}));
            return Ok(why("send_failed", lang, pyc::head(&detail, 200), extra));
        }
    }
    let claude = v.cli == "claude";
    if claude && !txt.is_empty() {
        if P_ASK_MARKERS.iter().any(|m| txt.contains(m)) {
            return Ok(why("session_asked", lang, &one_line(txt, 160), Map::new()));
        }
        if turn_failed(txt) {
            return Ok(plain("turn_failed", lang));
        }
        if waiting_for_gate(txt) {
            return Ok(plain("gate", lang));
        }
        let marker = idle_finish_marker(txt).0;
        if !marker.is_empty() {
            return Ok(why("finished", lang, marker, Map::new()));
        }
        if owner_wait(txt) {
            return Ok(plain("owner_wait", lang));
        }
    }
    if bg_blocks_message(v) {
        // alt ajan/arka plan işi çalışıyor ya da bilinmiyor: yönerge/dürtü/teslim gitmez
        let detail = if v.subagent_unknown { "?" } else { "" };
        return Ok(why("bg_running", lang, detail, Map::new()));
    }
    if let Some(a) = actions.iter().find(|a| a.kind == "idle_nudge" && a.name == v.name) {
        let next = str_or_empty(a.payload.get("next"));
        return Ok(why("nudging", lang, pyc::head(&next, 160), Map::new()));
    }
    if !claude {
        return Ok(plain("running", lang));
    }
    let secs = cfg.claude_idle_nudge_secs;
    if cfg.claude_idle == "off" || secs <= 0 {
        return Ok(plain("idle_off", lang));
    }
    let since = v.last_activity;
    if since <= 0.0 || now - since < secs as f64 {
        let remaining = secs as f64 - (now - since);
        let left = if since > 0.0 && remaining > 0.0 { pyc::floor_div(remaining, 60.0) as i64 } else { 0 };
        let unit = if lang == "en" { "min" } else { "dk" };
        let detail = if since > 0.0 { format!("{left} {unit}") } else { "?".to_string() };
        return Ok(why("idle_wait", lang, &detail, doc(json!({"minutes_left": left}))));
    }
    let chains = dict_of(state.get("claude_idle"))?;
    let rec = dict_of(chains.get(&v.name))?;
    let mut chain = if since > float_of(rec.get("at"))? { 0 } else { int_of(rec.get("n"))? };
    if rec.get("mode").map_or(cfg.claude_idle != "dry", |m| m.as_str() != Some(cfg.claude_idle.as_str())) {
        chain = 0;
    }
    if chain >= cfg.ucli_idle_max_consecutive {
        let detail = format!("{chain}/{}", cfg.ucli_idle_max_consecutive);
        return Ok(why("nudge_exhausted", lang, &detail, Map::new()));
    }
    let n_open = open_work.and_then(|f| f(name)).unwrap_or(0);
    let note_hint = next_work_hint(proj, None, true);
    if n_open <= 0 && note_hint.is_empty() && marker_next_work(txt).is_empty() {
        return Ok(plain("no_next_work", lang));
    }
    let count = if en { format!("{n_open} open in TODO") } else { format!("TODO'da {n_open} açık") };
    let triaged = dict_of(state.get("todo_triage"))?.get(name).is_some_and(pyc::truthy);
    if triaged && (next_none_stated(txt) || owner_wait(txt)) {
        return Ok(why("todo_triage", lang, &count, Map::new()));
    }
    let nones = dict_of(state.get("next_none"))?;
    let nn = nones.get(name).filter(|v| pyc::truthy(v));
    if next_none_stated(txt) {
        if let Some(nn) = nn {
            if recorded_open(&dict_of(Some(nn))?)? == n_open {
                return Ok(why("next_none", lang, &count, Map::new()));
            }
        }
    }
    let detail = match (n_open > 0, en) {
        (true, false) => format!("TODO'da {n_open} açık sahipsiz madde"),
        (true, true) => format!("{n_open} open ownerless items"),
        (false, _) => note_hint,
    };
    let code = if cfg.claude_idle == "dry" { "idle_dry" } else { "nudging" };
    Ok(why(code, lang, &one_line(&detail, 160), Map::new()))
}

/// Projenin neden ilerlemediğini TEK nedenle açıklar: `{code, text, detail, ...}` (ilk eşleşen kazanır).
///
/// py: explain_idle
pub fn explain_idle(proj: &Project, input: &ExplainInput<'_>) -> Result<Doc, BadValue> {
    let ExplainInput { views, projects, state, cfg, now, questions, world, .. } = *input;
    let (lang, name) = (cfg.lang.as_str(), proj.name.as_str());
    let mine: Vec<&SessionView> =
        views.iter().filter(|v| v.running && v.project() == name && v.name != cfg.brain_name).collect();
    if matches!(proj.phase.as_str(), "paused" | "done") {
        let code = if proj.phase == "paused" { "phase_paused" } else { "phase_done" };
        return Ok(why(code, lang, &format!("phase={}", proj.phase), Map::new()));
    }
    let qs: Vec<&Question> = questions.iter().filter(|q| q.project == name).collect();
    if let Some(q) = qs.iter().find(|q| q.status == "open" && !q.routine) {
        let detail = format!("[{}] {}", q.id, one_line(&q.text, 160));
        return Ok(why("ask_owner", lang, &detail, doc(json!({"question_id": q.id}))));
    }
    if let Some(q) = qs.iter().find(|q| q.status == "answered" && q.delivered_at == 0.0 && q.undeliverable.is_empty()) {
        return Ok(why("answer_pending", lang, &format!("[{}]", q.id), doc(json!({"question_id": q.id}))));
    }
    if notes_wait(proj) {
        return Ok(why("notes_wait", lang, &one_line(&proj.notes, 160), Map::new()));
    }
    if cfg.drain {
        return Ok(plain("drain", lang));
    }
    if let Some(w) = world {
        if w.unavailable.contains(name) {
            return Ok(why("host_down", lang, &proj.host, Map::new()));
        }
        if mine.iter().any(|v| w.session_class(&v.name, v.blueprint.as_deref()) == "manual") {
            let names: Vec<&str> = mine.iter().map(|v| v.name.as_str()).collect();
            return Ok(why("manual_session", lang, &names.join(", "), Map::new()));
        }
    }
    if mine.len() > 1 {
        let names: Vec<&str> = mine.iter().map(|v| v.name.as_str()).collect();
        return Ok(why("ambiguous", lang, &names.join(", "), Map::new()));
    }
    let mut guards: Vec<(String, Value)> = dict_of(state.get("loop_guard"))?.into_iter().collect();
    guards.sort_by(|a, b| a.0.cmp(&b.0));
    for (key, r) in guards {
        let (kind, target) = key.split_once('|').unwrap_or((&key, ""));
        let Some(r) = r.as_object() else { continue };
        let until = float_of(r.get("until"))?;
        if until > now && (target == name || project_key(target, projects.keys().map(String::as_str)) == name) {
            let detail = format!("{kind} -> {}", stamp(until));
            return Ok(why("loop_guard", lang, &detail, doc(json!({"until": until, "kind": kind}))));
        }
    }
    match mine.first() {
        None => without_session(proj, input),
        Some(v) => {
            // yalnız kabuk/Monitor 30 dk'dan eski (TBD#442 a): mesaj engeli yok, neden bunu `shell_only_stale` ile işaretler
            let stale = v.subagent_active && v.shell_only_stale && !v.subagent_unknown;
            let mut d = with_session(proj, v, input)?;
            if stale {
                d.insert("shell_only_stale".into(), Value::Bool(true));
            }
            Ok(d)
        }
    }
}

/// `{proje: explain_idle(...)}`; tek projenin hatası listeyi düşürmez. `owner_todo` -> `owner_in_todo` sayısı.
///
/// py: explain_idle_all
pub fn explain_idle_all(
    input: &ExplainInput<'_>,
    owner_todo: Option<OpenWork<'_>>,
) -> Result<IndexMap<String, Doc>, BadValue> {
    let mut out: IndexMap<String, Doc> = IndexMap::new();
    for (name, p) in input.projects {
        let Ok(mut d) = explain_idle(p, input) else { continue };
        let n = owner_todo.and_then(|f| f(name)).unwrap_or(0);
        if n > 0 {
            d.insert("owner_in_todo".into(), json!(n));
        }
        out.insert(name.clone(), d);
    }
    let next = object_of(input.state.get("project_next"))?;
    for (name, w) in &mut out {
        let Some(r) = next.and_then(|pn| pn.get(name)).and_then(Value::as_object) else { continue };
        if !truthy_at(r, "text") {
            continue;
        }
        let text = r.get("text").map(pyc::str_of).unwrap_or_default();
        let session = r.get("session").cloned().unwrap_or_else(|| json!(""));
        let work = json!({"text": pyc::head(&text, 200), "none": truthy_at(r, "none"),
            "at": float_of(r.get("at"))?, "session": session});
        w.insert("next_work".into(), work);
    }
    Ok(out)
}
