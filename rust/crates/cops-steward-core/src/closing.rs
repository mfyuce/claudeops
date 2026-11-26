//! Devir ve kapatma kararları (grup 2): bağlam eşiği, devir erteleme, kontrollü kapatma, bağlam sorusu, toparlama
//! direktifi, DONE çelişkisi. Eylemi yapmak ve state'i yazmak çağırandadır.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::markers::rfh_marker_in;
use crate::prompts::{bad, items_of, object_of};
use crate::pyc;
use crate::types::{Action, Config, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static CTX_SESSION_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CTX_Q_SESSION_RE.as_str()));
static CTX_HANDOVER_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CTX_Q_HANDOVER_RE.as_str()));
static CTX_EXCLUDE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CTX_Q_EXCLUDE_RE.as_str()));
static DONE_NO_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DONE_NO_RE.as_str()));
static DONE_HEDGE_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DONE_HEDGE_RE.as_str()));
static DONE_YES_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DONE_YES_RE.as_str()));
static WRAP_UP_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_WRAP_UP_RE.as_str()));
static WRAP_UP_ACT_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_WRAP_UP_ACT_RE.as_str()));

/// Bu modelde devri tetikleyen bağlam token eşiği (0 = kapalı).
///
/// py: context_threshold
pub fn context_threshold(cfg: &Config, model: &str) -> i64 {
    let (fable, all) = (cfg.context_warn_tokens_fable, cfg.context_warn_tokens);
    if model.to_lowercase().contains("fable") && fable != 0 && all != 0 {
        return fable.min(all);
    }
    all
}

/// Eşiği aşmış oturumun devri şimdi mi: (`go` | `defer` | `force`, neden).
///
/// py: handover_defer_decision
pub fn handover_defer_decision(
    v: &SessionView,
    cfg: &Config,
    now: f64,
    since: Option<f64>,
    tokens: Option<i64>,
    warn: i64,
) -> (&'static str, String) {
    let why = [
        ("busy", v.busy == Some(true)),
        ("subagent_active", v.subagent_active),
        ("subagent_unknown", v.subagent_unknown),
    ]
    .iter()
    .filter(|(_, on)| *on)
    .map(|(n, _)| *n)
    .collect::<Vec<_>>()
    .join(",");
    let max = cfg.handover_defer_max_minutes;
    if why.is_empty() || max <= 0 {
        return ("go", String::new());
    }
    let ratio = cfg.handover_force_ratio;
    if let Some(tokens) = tokens.filter(|t| *t != 0) {
        if warn != 0 && ratio > 0.0 && tokens as f64 >= warn as f64 * ratio {
            let reason = format!("{why}; context {tokens} >= {} x {warn}", pyc::format_g(ratio));
            return ("force", reason);
        }
    }
    if let Some(since) = since {
        if now - since >= max.saturating_mul(60) as f64 {
            let minutes = pyc::floor_div(now - since, 60.0) as i64;
            return ("force", format!("{why}; deferred {minutes} min >= {max}"));
        }
    }
    ("defer", why)
}

// ── kontrollü kapatma ─────────────────────────────────────────────────────────

fn set_stage(it: &mut Map<String, Value>, stage: &str) {
    it.insert("stage".into(), Value::from(stage));
}

fn move_to(it: &mut Map<String, Value>, stage: &str, now: f64) {
    set_stage(it, stage);
    it.insert("at".into(), Value::from(now));
}

/// `float(d[key])` (anahtar yoksa `KeyError`).
fn required_float(d: &Map<String, Value>, key: &str) -> Result<f64, BadValue> {
    let v = d.get(key).ok_or_else(|| BadValue(format!("missing key: {key}")))?;
    pyc::to_float(v).ok_or_else(|| bad(v))
}

fn stage_of(it: &Map<String, Value>) -> Result<&str, BadValue> {
    let v = it.get("stage").ok_or_else(|| BadValue("missing key: stage".to_string()))?;
    Ok(v.as_str().unwrap_or(""))
}

fn terminal(stage: &str) -> bool {
    P_SD_TERMINAL.contains(&stage)
}

/// Kapatma eyleminin sonucunu öğeye işler; `true` = adım yeniden denenecek.
///
/// py: shutdown_note_result
pub fn shutdown_note_result(
    it: &mut Map<String, Value>,
    kind: &str,
    res: &Map<String, Value>,
    now: f64,
) -> Result<bool, BadValue> {
    if res.get("ok").is_some_and(pyc::truthy) {
        it.shift_remove("fails");
        return Ok(false);
    }
    let retry_stage = if kind == "handover" { "wait" } else { "ho" };
    if res.get("code").and_then(Value::as_str) == Some("destructive_budget") {
        set_stage(it, retry_stage);
        return Ok(true);
    }
    let fails = match it.get("fails").filter(|v| pyc::truthy(v)) {
        None => 0,
        Some(v) => pyc::to_int(v).ok_or_else(|| bad(v))?,
    }
    .saturating_add(1);
    it.insert("fails".into(), Value::from(fails));
    if fails >= SHUTDOWN_ACTION_FAIL_MAX {
        move_to(it, "ho_failed", now);
        let error = res.get("error").filter(|v| pyc::truthy(v)).map(pyc::str_of).unwrap_or_default();
        it.insert("fail_error".into(), Value::from(pyc::head(&error, 200)));
        return Ok(false);
    }
    set_stage(it, retry_stage);
    if kind != "handover" {
        it.insert("at".into(), Value::from(now)); // yeniden denenen stop yeni pencere alır
    }
    Ok(true)
}

struct Shutdown<'a> {
    by_name: IndexMap<&'a str, &'a SessionView>,
    modes: Map<String, Value>,
    blockers: &'a IndexMap<String, String>,
    now: f64,
    actions: Vec<Action>,
}

impl Shutdown<'_> {
    /// Tek oturumun kapatma adımı (`plan_shutdown._step`). `started` = `sd["started"]`.
    fn step(&mut self, name: &str, it: &mut Map<String, Value>, started: &Value) -> Result<(), BadValue> {
        let now = self.now;
        let stage = stage_of(it)?.to_string();
        if terminal(&stage) {
            return Ok(());
        }
        let Some(v) = self.by_name.get(name).copied().filter(|v| v.running) else {
            move_to(it, if stage == "wait" { "gone" } else { "closed" }, now);
            return Ok(());
        };
        if stage == "wait" {
            // son etkinlik bilinmiyorsa sessizlik kanıtı yok: yalnız boşta olması yeter; `busy` bilinmiyorsa bekle
            let quiet = if v.last_activity != 0.0 {
                now - v.last_activity.max(0.0) >= SHUTDOWN_QUIET_SECONDS
            } else {
                v.busy == Some(false)
            };
            let blocked = self.blockers.get(name);
            match blocked {
                Some(why) => {
                    it.insert("blocked".into(), Value::from(why.as_str()));
                }
                None => {
                    it.shift_remove("blocked");
                }
            }
            if v.busy != Some(true) && !v.subagent_active && !v.subagent_unknown && quiet && blocked.is_none() {
                self.actions.push(Action::new("handover", name, "shutdown", Map::new()));
                move_to(it, "ho", now);
                it.shift_remove("ho_at");
            } else {
                let started = pyc::to_float(started).ok_or_else(|| bad(started))?;
                if now - started >= SHUTDOWN_WAIT_MAX_SECONDS as f64 {
                    move_to(it, "busy_left", now);
                }
            }
        } else if stage == "ho" {
            let mut ready = rfh_marker_in(&v.last_assistant);
            if ready {
                // `it.get("ho_at", it["at"])`: `at` her durumda okunur
                let at = it.get("at").ok_or_else(|| BadValue("missing key: at".to_string()))?;
                let since = it.get("ho_at").unwrap_or(at);
                ready = v.last_activity >= pyc::to_float(since).ok_or_else(|| bad(since))?;
            }
            if ready && v.busy != Some(true) {
                if self.modes.get(name).and_then(Value::as_str) == Some("keep") {
                    move_to(it, "kept", now);
                } else {
                    self.actions.push(Action::new("stop", name, "shutdown", Map::new()));
                    let at = it.get("at").cloned().ok_or_else(|| BadValue("missing key: at".to_string()))?;
                    it.insert("ho_at".into(), at);
                    move_to(it, "closed", now);
                }
            } else if now - required_float(it, "at")? >= SHUTDOWN_HO_MAX_SECONDS as f64 {
                move_to(it, "ho_timeout", now);
            }
        }
        Ok(())
    }

    fn step_item(&mut self, name: &str, items: &mut Map<String, Value>, started: &Value) -> Result<(), BadValue> {
        match items.get_mut(name) {
            Some(Value::Object(it)) => self.step(name, it, started),
            other => Err(BadValue(format!("bad shutdown item: {other:?}"))),
        }
    }
}

fn item_done(item: &Value) -> Result<bool, BadValue> {
    let it = item.as_object().ok_or_else(|| bad(item))?;
    Ok(terminal(stage_of(it)?))
}

fn waiting_item(now: f64) -> Value {
    let mut it = Map::new();
    move_to(&mut it, "wait", now);
    Value::Object(it)
}

/// `plan_shutdown` sonucu: (eylemler, yeni `sd`, bitti mi).
pub type ShutdownPlan = (Vec<Action>, Map<String, Value>, bool);

/// Kontrollü kapatma adımı: `sd` = `{started, items: {ad: {stage, at}}}`; dönüş (eylemler, yeni `sd`, bitti mi).
/// `blockers`: {oturum adı: sebep} (sessizlik tek başına "iş bitti" sayılmaz).
///
/// py: plan_shutdown
pub fn plan_shutdown(
    views: &[SessionView],
    projects: &IndexMap<String, Project>,
    sd: &Map<String, Value>,
    cfg: &Config,
    now: f64,
    world: Option<&World>,
    blockers: &IndexMap<String, String>,
) -> Result<ShutdownPlan, BadValue> {
    let mut sd = sd.clone();
    let modes = object_of(sd.get("modes"))?.cloned().unwrap_or_default();
    sd.entry("started").or_insert_with(|| Value::from(now));
    let started = sd.get("started").cloned().unwrap_or(Value::Null);
    let mut items = match sd.entry("items").or_insert_with(|| Value::Object(Map::new())) {
        Value::Object(o) => o.clone(),
        other => return Err(bad(other)),
    };
    let own: Option<IndexMap<String, Project>> = world.map(|w| w.own_projects(projects));
    let own = own.as_ref().unwrap_or(projects);
    // `shutdown --only P`: yalnız bu projelerin oturumları
    let only: BTreeSet<String> = items_of(sd.get("only"))?.iter().map(pyc::str_of).collect();
    let is_own = |v: &SessionView| {
        if v.name == cfg.brain_name || !v.running {
            return false;
        }
        if !only.is_empty() && !only.contains(v.project()) {
            return false;
        }
        match world {
            Some(w) => w.session_class(&v.name, v.blueprint.as_deref()) == "own",
            None => own.contains_key(v.project()),
        }
    };
    if !sd.get("init").is_some_and(pyc::truthy) {
        sd.insert("init".into(), Value::Bool(true));
        for v in views.iter().filter(|v| is_own(v)) {
            items.insert(v.name.clone(), waiting_item(now));
        }
    }
    let by_name: IndexMap<&str, &SessionView> = views.iter().map(|v| (v.name.as_str(), v)).collect();
    let brain_running = by_name.get(cfg.brain_name.as_str()).is_some_and(|v| v.running);
    let mut run = Shutdown { by_name, modes, blockers, now, actions: Vec::new() };
    let brain = cfg.brain_name.as_str();
    let names: Vec<String> = items.keys().filter(|n| *n != brain).cloned().collect();
    for name in &names {
        run.step_item(name, &mut items, &started)?;
    }
    let mut projects_done = true;
    for (_, item) in items.iter().filter(|(n, _)| *n != brain) {
        if !item_done(item)? {
            projects_done = false;
            break;
        }
    }
    if projects_done && only.is_empty() {
        if brain_running && !items.contains_key(brain) {
            items.insert(brain.to_string(), waiting_item(now));
        }
        if items.contains_key(brain) {
            run.step_item(brain, &mut items, &started)?;
        }
    }
    let mut done = projects_done;
    if done {
        for item in items.values() {
            if !item_done(item)? {
                done = false;
                break;
            }
        }
    }
    sd.insert("items".into(), Value::Object(items));
    Ok((run.actions, sd, done))
}

// ── bağlam sorusu ─────────────────────────────────────────────────────────────

/// "Bu oturumda mı sürdüreyim, devirle mi?" kalıbı (commit/push/silme geçen soru sayılmaz).
///
/// py: is_context_question
pub fn is_context_question(text: &str) -> bool {
    let t = pyc::ci_input(text);
    pyc::is_match(&CTX_SESSION_RE, &t)
        && pyc::is_match(&CTX_HANDOVER_RE, &t)
        // desen derlenemez ya da aranamazsa soru otomatik cevaplanmaz
        && CTX_EXCLUDE_RE.as_ref().is_some_and(|r| matches!(r.is_match(&t), Ok(false)))
}

/// (devir gerekli mi, cevap metni).
///
/// py: context_answer
pub fn context_answer(tokens: i64, warn: i64, ratio: f64, lang: &str) -> (bool, String) {
    let pct = if warn != 0 { pyc::round(100.0 * tokens as f64 / warn as f64) } else { 0 };
    let ho = warn != 0 && tokens as f64 >= ratio * warn as f64;
    let k = format!("{}K/{}K", tokens.div_euclid(1000), warn.div_euclid(1000));
    let text = match (lang == "en", ho) {
        (true, true) => format!(
            "Hand over first: context {k} ({pct}% of the handover threshold). The handover message is being sent now; \
             the new session continues from the handover note. Start no new work here, write the note."
        ),
        (true, false) => {
            format!("Continue in this session (context {k}, {pct}% of the handover threshold: far from it).")
        }
        (false, true) => format!(
            "Önce devir: bağlam {k} (devir eşiğinin %{pct}'i). Devir mesajı şimdi gönderiliyor; yeni oturum devir \
             notuyla sürdürür. Burada yeni iş başlatma, devir notunu yaz."
        ),
        (false, false) => format!("Bu oturumda sürdür (bağlam {k}, devir eşiğinin %{pct}'i: eşiğe uzak)."),
    };
    (ho, text)
}

// ── DONE çelişkisi ve toparlama ───────────────────────────────────────────────

/// Son 24 saatin STEWARD-DONE-CONFIRMED çelişki sorusuna sahip cevabı: `None` = cevap yok, `true` = "bitti",
/// `false` = başka/çekinceli cevap.
///
/// py: done_conflict_answer
pub fn done_conflict_answer(questions: &[Question], project: &str, now: f64) -> Option<bool> {
    let mut best: Option<&Question> = None;
    for q in questions {
        let at = if q.answered_at != 0.0 { q.answered_at } else { q.created_at };
        if q.status == "answered"
            && q.project == project
            && q.text.contains("STEWARD-DONE-CONFIRMED")
            && !pyc::strip(&q.answer).is_empty()
            && now - at < DONE_ANSWER_TTL
            && best.is_none_or(|b| q.answered_at >= b.answered_at)
        {
            best = Some(q);
        }
    }
    let a = pyc::ci_input(&best?.answer);
    let found = |re: &Fancy| re.as_ref().and_then(|r| r.is_match(&a).ok());
    // belirsizlikte (arama hatası dahil) kapatma yok
    Some(found(&DONE_YES_RE) == Some(true) && found(&DONE_NO_RE) == Some(false) && found(&DONE_HEDGE_RE) == Some(false))
}

/// Tek satır teyit direktifi (`nudge` yolu).
///
/// py: _confirm_action
pub fn confirm_action(name: &str, project: &str, cfg: &Config, why: &str) -> Action {
    let text = if cfg.lang == "en" { DONE_CONFIRM_TEXT_EN } else { DONE_CONFIRM_TEXT_TR };
    let mut payload = Map::new();
    payload.insert("text".into(), Value::from(text));
    payload.insert("confirm".into(), Value::Bool(true));
    payload.insert("project".into(), Value::from(project));
    Action::new("nudge", name, why, payload)
}

/// Direktif bir toparlama isteği mi (commit/push + READY FOR HANDOVER).
///
/// py: is_wrap_up_directive
pub fn is_wrap_up_directive(text: &str) -> bool {
    let t = pyc::ci_input(text);
    pyc::is_match(&WRAP_UP_RE, &t) && pyc::is_match(&WRAP_UP_ACT_RE, &t)
}

/// Direktif fazı değiştirmesin mi: açık `keep_phase` bayrağı ya da toparlama metni.
///
/// py: directive_keeps_phase
pub fn directive_keeps_phase(text: &str, data: Option<&Map<String, Value>>) -> bool {
    data.and_then(|d| d.get("keep_phase")) == Some(&Value::Bool(true)) || is_wrap_up_directive(text)
}

/// Paused yapılan projenin açık oturumu için devir+kapat isteği (`state.pause_close`).
///
/// py: request_pause_close
pub fn request_pause_close(st: &mut Map<String, Value>, project: &str, now: f64) -> Result<(), BadValue> {
    let mut pc = object_of(st.get("pause_close"))?.cloned().unwrap_or_default();
    pc.insert(project.to_string(), Value::from(now));
    st.insert("pause_close".into(), Value::Object(pc));
    Ok(())
}
