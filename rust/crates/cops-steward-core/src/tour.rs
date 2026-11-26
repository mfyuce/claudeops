//! Tur maddeleri ve işaretlerin kayıt eylemleri (grup 2): beynin yargısını gerektiren maddeler, `STEWARD-*`
//! işaretlerinden `ask_user`/`idea` eylemleri, döngü kapalıyken salt kayıt taraması, başlatma kararı olayı.

use crate::ask::tour_eligible;
use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::gates::ask_is_status_line;
use crate::markers::{self, clip_words, marker_next_work, scan_markers, Markers};
use crate::prompts::{bad, clip, is_project_session, item_signature, items_of, object_of, stale_answers};
use crate::pyc;
use crate::questions::undelivered_answers;
use crate::types::{Action, Config, Idea, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

/// `proje -> yerel TODO'daki açık iş sayısı` (bilinmiyorsa `None`).
pub type OpenWork<'a> = &'a dyn Fn(&str) -> Option<i64>;
/// `proje -> not çelişkileri`.
pub type ClaimCheck<'a> = &'a dyn Fn(&str) -> Vec<String>;

/// `review_items` girdileri. `skip`: atlanacak oturum adları; `skip_seen`: {oturum: {at, sig}}; `sigs_out`: eklenen
/// oturum maddelerinin imzaları yazılır; `open_work(proje)`: yerel TODO'daki açık iş sayısı; `claim_check(proje)`:
/// proje notu çelişkileri; `state`: ASK kapısı sayaçları.
pub struct TourInput<'a> {
    pub views: &'a [SessionView],
    pub projects: &'a IndexMap<String, Project>,
    pub cfg: &'a Config,
    pub now: f64,
    pub questions: &'a [Question],
    pub ideas: &'a [Idea],
    pub skip: &'a BTreeSet<String>,
    pub last_directive_at: &'a IndexMap<String, f64>,
    pub reviewed_at: &'a IndexMap<String, f64>,
    pub world: Option<&'a World>,
    pub skip_seen: &'a Map<String, Value>,
    pub sigs_out: Option<&'a mut IndexMap<String, String>>,
    pub open_work: Option<OpenWork<'a>>,
    pub claim_check: Option<ClaimCheck<'a>>,
    pub state: &'a Map<String, Value>,
}

fn item(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(o) => o,
        _ => Map::new(),
    }
}

/// Python `max(a, b, ...)`: eşitlikte ilk.
fn max_of(values: &[f64]) -> f64 {
    values.iter().copied().reduce(|a, b| if b > a { b } else { a }).unwrap_or(0.0)
}

/// Oturum maddeleri (`idle` / `review`).
fn session_items(
    input: &mut TourInput<'_>,
    projects: &IndexMap<String, Project>,
    items: &mut Vec<Map<String, Value>>,
) -> Result<(), BadValue> {
    let (cfg, now) = (input.cfg, input.now);
    // sahibin cevabını bekleyen oturum/proje "boşta" sayılmaz
    let asked = || input.questions.iter().filter(|q| q.status == "open" && !q.routine);
    let waiting: BTreeSet<&str> =
        asked().flat_map(|q| [q.source.as_str(), q.project.as_str()]).filter(|s| !s.is_empty()).collect();
    for v in input.views {
        if !v.running || !is_project_session(v, projects) || input.skip.contains(&v.name) || v.name == cfg.brain_name {
            continue;
        }
        if input.world.is_some_and(|w| w.session_class(&v.name, v.blueprint.as_deref()) != "own") {
            continue;
        }
        let project = v.project();
        let halted = projects.get(project).is_some_and(|p| p.phase == "done" || p.phase == "paused");
        if waiting.contains(v.name.as_str()) || waiting.contains(project) || halted {
            continue;
        }
        let directed = input.last_directive_at.get(&v.name).copied().unwrap_or(0.0);
        let reviewed = input.reviewed_at.get(&v.name).copied().unwrap_or(0.0);
        let idle_since = max_of(&[v.last_activity, directed, v.started_at]);
        let due_idle = v.busy == Some(false)
            && idle_since != 0.0
            && now - idle_since >= cfg.idle_minutes.saturating_mul(60) as f64;
        let due_review = !due_idle
            && v.busy == Some(true)
            && now - max_of(&[directed, reviewed, v.started_at]) >= cfg.review_minutes.saturating_mul(60) as f64;
        if !(due_idle || due_review) {
            continue;
        }
        if due_idle && input.open_work.is_some_and(|f| f(project) == Some(0)) {
            continue; // yerel TODO.md'de açık iş yok
        }
        let sig = item_signature(v, projects, input.questions);
        if let Some(rec) = input.skip_seen.get(&v.name).and_then(Value::as_object) {
            if rec.get("sig").and_then(Value::as_str) == Some(sig.as_str()) {
                let at = match rec.get("at").filter(|x| pyc::truthy(x)) {
                    None => 0.0,
                    Some(x) => pyc::to_float(x).ok_or_else(|| bad(x))?,
                };
                if now - at < SKIP_QUIET_SECONDS {
                    continue; // beyin bu durumu gördü ve dokunmadı
                }
            }
        }
        if let Some(out) = input.sigs_out.as_deref_mut() {
            out.insert(v.name.clone(), sig);
        }
        let mut it = if due_idle {
            item(json!({"kind": "idle", "name": v.name, "idle_minutes": (now - idle_since) / 60.0}))
        } else {
            item(json!({"kind": "review", "name": v.name}))
        };
        let next = marker_next_work(&v.last_assistant);
        if !next.is_empty() {
            let warn = format!(
                "oturum STEWARD-NEXT ile SAHİPSİZ iş bildirdi: «{next}». 'Sahipsiz yeni iş yok' diye skip etme: \
                 steward_directive ile bu işe devam ettir (sahip cevabı bekleyen soru bunu engellemiyorsa)."
            );
            it.insert("stated_next".into(), Value::from(next));
            it.insert("contradictions".into(), json!([warn]));
        }
        if let Some(check) = input.claim_check {
            let found = check(project);
            if !found.is_empty() {
                let mut all = items_of(it.get("contradictions"))?;
                all.extend(found.into_iter().map(Value::from));
                it.insert("contradictions".into(), Value::Array(all));
            }
        }
        items.push(it);
    }
    Ok(())
}

/// Beynin yargısını gerektiren maddeler: `idle`, `review`, `idea`, `routine`, `ask`, `blocked`.
///
/// py: review_items
pub fn review_items(mut input: TourInput<'_>) -> Result<Vec<Map<String, Value>>, BadValue> {
    let own = input.world.map(|w| w.own_projects(input.projects));
    let projects = own.as_ref().unwrap_or(input.projects);
    let (cfg, now, questions) = (input.cfg, input.now, input.questions);
    let mut items = Vec::new();
    session_items(&mut input, projects, &mut items)?;
    for i in input.ideas.iter().filter(|i| i.status == "new") {
        items.push(item(json!({"kind": "idea", "id": i.id, "text": i.text, "name": ""})));
    }
    let or_dash = |p: &str| if p.is_empty() { "-".to_string() } else { p.to_string() };
    for q in questions.iter().filter(|q| q.status == "open" && q.routine) {
        let created = if q.created_at != 0.0 { q.created_at } else { now };
        let age = (((now - created) / 60.0) as i64).max(0);
        let mut text = format!("Rutin soru [{}] (steward_answer id cevap ile cevapla)", q.id);
        if age >= 20 {
            text.push_str(&format!(" [{age} dk önce soruldu: beklemede, öncelik ver]"));
        }
        text.push_str(&format!(": {}", q.text));
        items.push(item(
            json!({"kind": "routine", "name": or_dash(&q.project), "id": q.id, "age_min": age, "text": text}),
        ));
    }
    if cfg.ask_gate != "off" {
        for q in questions {
            if !tour_eligible(q, projects, cfg, input.state, now)? {
                continue;
            }
            let opts = if q.options.is_empty() {
                String::new()
            } else {
                format!("\nSeçenekler: {}", clip(&q.options.join(" | "), 120))
            };
            let text = format!(
                "Sahip sorusu [{}] (steward_answer id cevap; cevabın kapıdan geçer, emin değilsen atla): {}{opts}",
                q.id,
                clip(&q.text, usize::try_from(ASK_ITEM_CHARS).unwrap_or(0))
            );
            items.push(item(json!({"kind": "ask", "name": q.project, "id": q.id, "text": text})));
        }
    }
    let live: BTreeSet<String> = input.views.iter().filter(|v| v.running).map(|v| v.name.clone()).collect();
    let stale: BTreeSet<&str> =
        stale_answers(questions, projects, cfg, now, &live).into_iter().map(|q| q.id.as_str()).collect();
    for q in undelivered_answers(questions) {
        if stale.contains(q.id.as_str()) {
            continue;
        }
        if q.project.is_empty() || q.project == cfg.brain_name || !projects.contains_key(&q.project) {
            let text = format!("Cevaplanan soru [{}]: {}\nCevap: {}", q.id, q.text, q.answer);
            items.push(item(json!({"kind": "blocked", "name": or_dash(&q.project), "id": q.id, "text": text})));
        }
    }
    Ok(items)
}

// ── işaretlerin kaydı ─────────────────────────────────────────────────────────

/// Tarih/sıra ekli oturum adından kök ad (`mecdtfl20261031_3` -> `mecdtfl`); eksiz ad olduğu gibi.
///
/// py: _ask_base
pub fn ask_base(name: &str) -> &str {
    let body = name.strip_suffix('\n').unwrap_or(name); // Python `$` sondaki tek satır sonunu atlar
    P_DATED_NAME_RE.captures(body).and_then(|c| c.get(1)).map_or(name, |m| m.as_str())
}

/// Bu tick'in başlatma kararını tek olay verisine indirir; karar yoksa boş.
///
/// py: start_decision_event
pub fn start_decision_event(actions: &[Action], state: &Map<String, Value>) -> Result<Map<String, Value>, BadValue> {
    let allowed: BTreeSet<&str> =
        actions.iter().filter(|a| a.kind == "start" && a.reason == "due").map(|a| a.name.as_str()).collect();
    let sb = object_of(state.get("start_blocked"))?;
    let mut blocked: Vec<String> = items_of(sb.and_then(|s| s.get("projects")))?.iter().map(pyc::str_of).collect();
    blocked.sort();
    let mut d = Map::new();
    if allowed.is_empty() && blocked.is_empty() {
        return Ok(d);
    }
    let reason = sb
        .and_then(|s| s.get("reason"))
        .filter(|v| !blocked.is_empty() && pyc::truthy(v))
        .map(pyc::str_of)
        .unwrap_or_default();
    let any_blocked = !blocked.is_empty();
    d.insert("allowed".into(), json!(allowed));
    d.insert("blocked".into(), json!(blocked));
    d.insert("reason".into(), Value::from(reason));
    for k in ["active", "max_active", "active_busy", "others_active", "max_active_total", "bekleme_projects"] {
        if let Some(v) = sb.and_then(|s| s.get(k)).filter(|_| any_blocked) {
            d.insert(k.into(), v.clone());
        }
    }
    Ok(d)
}

fn record(kind: &str, name: &str, reason: &str, project: Option<&str>, text: String) -> Action {
    let mut payload = Map::new();
    if let Some(p) = project {
        payload.insert("project".into(), Value::from(p));
    }
    payload.insert("text".into(), Value::from(text));
    Action::new(kind, name, reason, payload)
}

/// Yanıttaki soru/rutin/takıldım/fikir/ders işaretlerinin KAYIT eylemleri (oturuma dokunmaz).
///
/// py: marker_record_actions
pub fn marker_record_actions(name: &str, proj: &str, m: &Markers) -> Vec<Action> {
    let mut out = Vec::new();
    let project = if proj.is_empty() { ask_base(name) } else { proj };
    let routine = |reason: &str, text: String| {
        let mut a = record("ask_user", name, reason, Some(project), text);
        a.payload.insert("routine".into(), Value::Bool(true));
        a
    };
    for (i, q) in m.asks.iter().enumerate() {
        if ask_is_status_line(q) {
            continue; // soru işareti taşımayan durum cümlesi kayıt açmaz
        }
        let mut a = record("ask_user", name, "STEWARD-ASK", Some(project), q.clone());
        // STEWARD-DETAIL: aynı sayıdaysa sırayla, değilse son soruya
        let detail = if m.details.len() == m.asks.len() {
            m.details.get(i)
        } else if i + 1 == m.asks.len() {
            m.details.last()
        } else {
            None
        };
        if let Some(d) = detail.filter(|d| !d.is_empty()) {
            a.payload.insert("detail".into(), Value::from(d.as_str()));
        }
        out.push(a);
    }
    for q in m.routines.iter().filter(|q| q.contains('?')) {
        out.push(routine("STEWARD-ROUTINE", q.clone()));
    }
    for j in &m.jobs {
        out.push(routine("STEWARD-JOB", format!("{JOB_REQUEST_PREFIX}{j}")));
    }
    for ls in &m.lessons {
        out.push(record("lesson_ack", name, "STEWARD-LESSON", Some(project), ls.clone()));
    }
    for b in &m.blocked {
        out.push(routine("STEWARD-BLOCKED", format!("{BLOCKED_TEXT_PREFIX}{b}")));
    }
    for i in &m.ideas {
        out.push(record("idea", name, "STEWARD-IDEA", None, i.clone()));
    }
    out
}

/// `STEWARD-NEXT` bilgisini `state.project_next`e yazar (`none` = sıradaki iş yok).
///
/// py: note_project_next
pub fn note_project_next(
    st: &mut Map<String, Value>,
    proj: &str,
    session: &str,
    m: &Markers,
    now: f64,
) -> Result<(), BadValue> {
    let Some(val) = m.next.as_deref().filter(|v| !proj.is_empty() && !v.is_empty()) else {
        return Ok(());
    };
    let body = pyc::strip(val);
    let mut pn = object_of(st.get("project_next"))?.cloned().unwrap_or_default();
    pn.insert(
        proj.to_string(),
        json!({"text": clip_words(body, 200), "at": now, "session": session, "none": markers::is_no_work(body)}),
    );
    st.insert("project_next".into(), Value::Object(pn));
    Ok(())
}

/// Değnekçi kapalıyken salt kayıt taraması: yalnız `ask_user`/`idea`/`lesson_ack` eylemleri, `seen_assistant` ve
/// `project_next` güncellenir.
///
/// py: plan_markers
pub fn plan_markers(
    views: &[SessionView],
    projects: &IndexMap<String, Project>,
    state: &Map<String, Value>,
    cfg: &Config,
    world: Option<&World>,
    now: f64,
) -> Result<(Vec<Action>, Map<String, Value>), BadValue> {
    let own = world.map(|w| w.own_projects(projects));
    let projects = own.as_ref().unwrap_or(projects);
    let mut st = state.clone();
    let mut seen = object_of(st.get("seen_assistant"))?.cloned().unwrap_or_default();
    let mut actions = Vec::new();
    for v in views {
        if !v.running || v.last_assistant.is_empty() || v.name == cfg.brain_name {
            continue;
        }
        if let Some(w) = world {
            let cls = w.session_class(&v.name, v.blueprint.as_deref());
            if cls != "own" && !(cls == "adhoc" && w.is_adhoc_owner) {
                continue;
            }
        }
        let hash = pyc::sha1_hex(v.last_assistant.as_bytes());
        let digest = pyc::head(&hash, 16);
        if seen.get(&v.name).and_then(Value::as_str) == Some(digest) {
            continue;
        }
        seen.insert(v.name.clone(), Value::from(digest));
        let proj = if projects.contains_key(v.project()) { v.project() } else { "" };
        let mk = scan_markers(&v.last_assistant);
        actions.extend(marker_record_actions(&v.name, proj, &mk));
        note_project_next(&mut st, proj, &v.name, &mk, now)?;
    }
    st.insert("seen_assistant".into(), Value::Object(seen));
    Ok((actions, st))
}
