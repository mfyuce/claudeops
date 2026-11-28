//! Boşta oturum planları (grup 3): ucli kodcu (dürtme / devir / kapatma) ve claude oturumu (yalnız dürtme ve ayıklama).
//! SAF: TODO sayısı, TODO özeti ve kayıtlı soru bilgisi geri çağrılarla gelir.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::idletext::*;
use crate::markers::{clip_words, marker_next_work};
use crate::pyc;
use crate::recovery::{dict_of, doc, float_of, int_of, truthy_at};
use crate::tour::OpenWork;
use crate::types::{Action, Config, Project, SessionView, World};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Doc = Map<String, Value>;
type Fancy = LazyLock<Option<fancy_regex::Regex>>;

static AJ_CHILD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_AJ_CHILD_RE.as_str()));

/// Proje adı -> metin (`None` = geri çağrı yanıt veremedi).
pub type TextOf<'a> = &'a dyn Fn(&str) -> Option<String>;
/// Proje adı -> evet/hayır (`None` = geri çağrı yanıt veremedi).
pub type FlagOf<'a> = &'a dyn Fn(&str) -> Option<bool>;

/// Boşta planlarının ortak girdisi.
#[derive(Clone, Copy)]
pub struct IdleInput<'a> {
    pub views: &'a [SessionView],
    pub projects: &'a IndexMap<String, Project>,
    pub state: &'a Doc,
    pub cfg: &'a Config,
    pub now: f64,
    pub planned: &'a [Action],
    pub world: Option<&'a World>,
}

/// `plan_claude_idle` geri çağrıları. Verilmeyen = Python'daki `None`; `None` dönüşü = bilinmiyor (istisna dahil).
#[derive(Clone, Copy, Default)]
pub struct IdleCallbacks<'a> {
    pub open_work: Option<OpenWork<'a>>,
    pub owner_todo: Option<OpenWork<'a>>,
    pub todo_sha: Option<TextOf<'a>>,
    pub oldest_open: Option<TextOf<'a>>,
    /// `None` dönüşü "soru var" sayılır.
    pub has_question: Option<FlagOf<'a>>,
}

/// `sıradaki: yok` TODO'da açık sahipsiz madde varken kabul edilmez: en eski açık maddeyi metniyle veren dürtme.
///
/// py: _forced_open_nudge
pub fn forced_open_nudge(oldest_open: Option<TextOf<'_>>, project: &str, n_open: i64) -> String {
    let text = oldest_open.and_then(|f| f(project)).unwrap_or_default();
    let text = pyc::strip(&text);
    if text.is_empty() {
        return String::new();
    }
    one_line(
        &format!(
            "'yok' kabul edilmez: TODO.md'de {n_open} açık sahipsiz madde var. En eskisi: «{}». Bunu yap; yalnız \
             gerekçeyle atla (sahibe bağlıysa TOBEDECIDED'a taşı, TODO'dan çıkar), sonra sıradakine geç.",
            clip_words(text, 300)
        ),
        700,
    )
}

fn is_local(v: &SessionView) -> bool {
    matches!(v.host.as_str(), "local" | "")
}

/// Yönetilen, boşta (`busy` kesin yanlış, alt ajan yok), açık ve işi süren projenin yerel tmux oturumu.
fn idle_candidate<'p>(
    v: &SessionView,
    cli: &str,
    input: &IdleInput<'_>,
    projects: &'p IndexMap<String, Project>,
    touched: &BTreeSet<&str>,
    ho_pending: &Doc,
) -> Option<&'p Project> {
    if v.cli != cli || !v.running || !v.tmux || !is_local(v) {
        return None;
    }
    // `$` sondaki tek satır sonundan önce de eşleşir
    let name = v.name.strip_suffix('\n').unwrap_or(&v.name);
    if v.name == input.cfg.brain_name
        || pyc::is_match(&AJ_CHILD_RE, name)
        || touched.contains(v.name.as_str())
        || ho_pending.contains_key(&v.name)
    {
        return None;
    }
    if v.busy != Some(false) || crate::world::bg_blocks_message(v) {
        return None;
    }
    projects.get(v.project()).filter(|p| !matches!(p.phase.as_str(), "done" | "paused"))
}

fn not_own(world: Option<&World>, v: &SessionView) -> bool {
    world.is_some_and(|w| w.session_class(&v.name, v.blueprint.as_deref()) != "own")
}

/// `rec.get("mode", "dry") != kip`
fn other_mode(rec: &Doc, mode: &str) -> bool {
    rec.get("mode").map_or(mode != "dry", |m| m.as_str() != Some(mode))
}

fn record(now: f64, n: i64, mode: &str, text: Option<&str>) -> Value {
    let mut rec = doc(json!({"at": now, "n": n, "mode": mode}));
    if let Some(t) = text {
        rec.insert("text".into(), json!(t));
    }
    Value::Object(rec)
}

/// (eylemler, güncellenmiş state).
pub type IdlePlan = (Vec<Action>, Doc);

/// Yönetilen ucli kodcu boşta kalmasın: `idle_nudge` / `idle_close` (handover | respawn | stop).
///
/// py: plan_ucli_idle
pub fn plan_ucli_idle(input: IdleInput<'_>, open_work: Option<OpenWork<'_>>) -> Result<IdlePlan, BadValue> {
    let IdleInput { views, state, cfg, now, planned, world, .. } = input;
    let unchanged = || Ok((Vec::new(), state.clone()));
    let mode = cfg.ucli_idle.as_str();
    if !matches!(mode, "dry" | "act") || cfg.ucli_idle_nudge_secs <= 0 || cfg.drain {
        return unchanged();
    }
    let own = world.map(|w| w.own_projects(input.projects));
    let projects = own.as_ref().unwrap_or(input.projects);
    let mut rec_all = dict_of(state.get("ucli_idle"))?;
    let mut ho_pending = dict_of(state.get("ho_pending"))?;
    let mut ho_close = dict_of(state.get("ho_close"))?;
    let touched: BTreeSet<&str> = planned.iter().map(|a| a.name.as_str()).collect();
    let live = cfg.mode != "observe" && mode == "act";
    let mut out: Vec<Action> = Vec::new();
    let mut changed = false;
    for v in views {
        let Some(proj) = idle_candidate(v, "ucli", &input, projects, &touched, &ho_pending) else { continue };
        if not_own(world, v) {
            continue;
        }
        let thr = ucli_idle_threshold(cfg, &v.cache_ttl);
        let since = v.idle_since.max(v.last_activity);
        if thr <= 0 || v.idle_since == 0.0 || since <= 0.0 || now - since < thr as f64 {
            continue;
        }
        let rec = dict_of(rec_all.get(&v.name))?;
        let (mut at, n) = (float_of(rec.get("at"))?, int_of(rec.get("n"))?);
        let failed = turn_failed(&v.last_assistant);
        // dürtmeden sonra etkinlik: zincir sıfırlanır (başarısız tur etkinlik DEĞİL)
        let mut chain = if since > at && !failed { 0 } else { n };
        if other_mode(&rec, mode) {
            (at, chain) = (0.0, 0);
        }
        if at != 0.0 && since <= at && now - at < thr as f64 {
            continue;
        }
        let idle_secs = (now - since) as i64;
        if chain >= cfg.ucli_idle_max_consecutive {
            if failed && !truthy_at(&rec, "failed_closed") {
                // ardışık başarısız turlar: dürtmeyi kes, oturumu kapat
                let payload = doc(json!({"project": proj.name, "idle_secs": idle_secs, "threshold": thr, "n": chain,
                    "mode": "stop", "pause": true, "marker": "turn_failed", "next": ""}));
                let why = format!("ucli ardışık {chain} başarısız tur, dürtme kesildi");
                out.push(Action::new("idle_close", &v.name, why, payload));
                let closed = json!({"at": now, "n": chain, "mode": mode, "failed_closed": true});
                rec_all.insert(v.name.clone(), closed);
                changed = true;
            }
            continue;
        }
        if waiting_for_gate(&v.last_assistant) {
            continue;
        }
        let hint = next_work_hint(proj, open_work, false);
        let (marker, ready) = idle_finish_marker(&v.last_assistant);
        let step = chain.saturating_add(1);
        let mut info = doc(json!({"project": proj.name, "idle_secs": idle_secs, "threshold": thr, "n": step}));
        let mut nudged = None;
        if !marker.is_empty() {
            let pause = hint.is_empty();
            let action_mode = match (ready, pause) {
                (true, false) => "respawn",
                (true, true) => "stop",
                (false, _) => "handover",
            };
            info.extend(doc(json!({"mode": action_mode, "pause": pause, "marker": marker, "next": hint})));
            let why = format!("ucli boşta {idle_secs} sn, cevap: {marker}");
            out.push(Action::new("idle_close", &v.name, why, info));
            if action_mode == "handover" && live {
                ho_pending.insert(v.name.clone(), json!(now));
                if pause {
                    ho_close.insert(v.name.clone(), json!(proj.name));
                }
            }
        } else {
            let hint = next_work_hint(proj, open_work, true);
            if hint.is_empty() {
                continue;
            }
            let escape = if hint.starts_with(P_TODO_HINT_PREFIX) { "" } else { IDLE_STALE_NOTE_ESCAPE };
            let text = one_line(&format!("devam: {hint}{escape}"), 600);
            if at != 0.0
                && since > at
                && !failed
                && rec.get("text").and_then(Value::as_str) == Some(text.as_str())
                && !other_mode(&rec, mode)
            {
                continue; // AYNI `devam` metni gönderildi ve oturum yanıtladı
            }
            info.extend(doc(json!({"text": text, "next": hint})));
            let why = format!("ucli boşta {idle_secs} sn, sıradaki iş var");
            out.push(Action::new("idle_nudge", &v.name, why, info));
            nudged = Some(text);
        }
        rec_all.insert(v.name.clone(), record(now, step, mode, nudged.as_deref()));
        changed = true;
    }
    if !changed {
        return unchanged();
    }
    let mut st = state.clone();
    st.insert("ucli_idle".into(), Value::Object(rec_all));
    if live {
        if !ho_pending.is_empty() {
            st.insert("ho_pending".into(), Value::Object(ho_pending));
        }
        if !ho_close.is_empty() {
            st.insert("ho_close".into(), Value::Object(ho_close));
        }
    }
    Ok((out, st))
}

/// Bir claude oturumunun dürtme adımı: ortak payload alanları ve zincir kaydı.
struct Step<'a> {
    session: &'a str,
    project: &'a str,
    idle_secs: i64,
    threshold: i64,
    n: i64,
    mode: &'a str,
    now: f64,
}

impl Step<'_> {
    /// Eylemi ekler ve zincir kaydını yazar; `extra` ortak alanların ardına gelir.
    fn send(&self, kind: &str, why: String, text: &str, extra: Value, out: &mut Vec<Action>, rec_all: &mut Doc) {
        let mut payload =
            doc(json!({"project": self.project, "idle_secs": self.idle_secs, "threshold": self.threshold,
            "n": self.n, "text": text}));
        payload.extend(doc(extra));
        out.push(Action::new(kind, self.session, why, payload));
        rec_all.insert(self.session.to_string(), record(self.now, self.n, self.mode, Some(text)));
    }
}

/// `int(nn.get("open", -1))`
pub(crate) fn recorded_open(nn: &Doc) -> Result<i64, BadValue> {
    match nn.get("open") {
        None => Ok(-1),
        Some(v) => pyc::to_int(v).ok_or_else(|| BadValue(v.to_string())),
    }
}

/// Yönetilen yerel tmux claude oturumu boşta: `idle_nudge` / `owner_todo_move` / `todo_triage`. Kapatma/devir YOK.
///
/// py: plan_claude_idle
pub fn plan_claude_idle(input: IdleInput<'_>, calls: IdleCallbacks<'_>) -> Result<IdlePlan, BadValue> {
    let IdleInput { views, state, cfg, now, planned, world, .. } = input;
    let unchanged = || Ok((Vec::new(), state.clone()));
    let mode = cfg.claude_idle.as_str();
    if !matches!(mode, "dry" | "act") || cfg.claude_idle_nudge_secs <= 0 || cfg.drain {
        return unchanged();
    }
    let own = world.map(|w| w.own_projects(input.projects));
    let projects = own.as_ref().unwrap_or(input.projects);
    let mut rec_all = dict_of(state.get("claude_idle"))?;
    let mut otm = dict_of(state.get("owner_todo_move"))?;
    let mut next_none = dict_of(state.get("next_none"))?;
    let mut tri = dict_of(state.get("todo_triage"))?;
    let mut ocn = dict_of(state.get("owner_claim_nudge"))?;
    let mut none_changed = false;
    let ho_pending = dict_of(state.get("ho_pending"))?;
    let touched: BTreeSet<&str> = planned.iter().map(|a| a.name.as_str()).collect();
    let mut out: Vec<Action> = Vec::new();
    for v in views {
        let Some(proj) = idle_candidate(v, "claude", &input, projects, &touched, &ho_pending) else { continue };
        if not_own(world, v) {
            continue;
        }
        let name = proj.name.as_str();
        let since = v.last_activity;
        let thr = cfg.claude_idle_nudge_secs;
        if since <= 0.0 || now - since < thr as f64 {
            continue;
        }
        let rec = dict_of(rec_all.get(&v.name))?;
        let (mut at, n) = (float_of(rec.get("at"))?, int_of(rec.get("n"))?);
        let mut chain = if since > at { 0 } else { n };
        if other_mode(&rec, mode) {
            (at, chain) = (0.0, 0);
        }
        if (at != 0.0 && since <= at && now - at < thr as f64) || chain >= cfg.ucli_idle_max_consecutive {
            continue;
        }
        let txt = v.last_assistant.as_str();
        // oturum kendi sahipsiz işini bildirdi: ASK/gate/sahipte kapıları onu engellemez
        let stated = marker_next_work(txt);
        if turn_failed(txt)
            || (stated.is_empty() && (waiting_for_gate(txt) || P_ASK_MARKERS.iter().any(|m| txt.contains(m))))
        {
            continue;
        }
        let idle_secs = (now - since) as i64;
        let step =
            Step { session: &v.name, project: name, idle_secs, threshold: thr, n: chain.saturating_add(1), mode, now };
        if !stated.is_empty() {
            let why = format!("claude boşta {idle_secs} sn, oturum STEWARD-NEXT bildirdi");
            let text = one_line(&format!("devam: {stated}"), 400);
            let extra = json!({"next": stated, "cli": "claude", "via": "stated_next"});
            step.send("idle_nudge", why, &text, extra, &mut out, &mut rec_all);
            continue;
        }
        if let Some(owner_todo) = calls.owner_todo {
            // TODO.md'de sahibe bağlı satır: oturuma BİR kez "TOBEDECIDED'a taşı"
            let n_own = owner_todo(name).unwrap_or(0);
            if n_own > 0 {
                let prev = dict_of(otm.get(name))?;
                let recent =
                    !other_mode(&prev, mode) && now - float_of(prev.get("at"))? < OWNER_TODO_MOVE_SECONDS as f64;
                if !recent {
                    let text = one_line(
                        &format!(
                            "TODO.md'deki sahibe bağlı {n_own} maddeyi TOBEDECIDED'a taşı (kısa, tek cevapla kapanır \
                             soru olarak), TODO'da yalnız sahipsiz iş kalsın; sonra kalan işe devam et."
                        ),
                        600,
                    );
                    let why = format!("TODO'da sahibe bağlı {n_own} madde");
                    let extra = json!({"next": format!("owner_in_todo={n_own}"), "owner_in_todo": n_own,
                        "cli": "claude"});
                    step.send("owner_todo_move", why, &text, extra, &mut out, &mut rec_all);
                    otm.insert(name.to_string(), json!({"at": now, "mode": mode, "n": n_own}));
                    continue;
                }
            }
        }
        if let Some(todo_sha) = calls.todo_sha {
            if next_none_stated(txt) || owner_wait(txt) {
                // TODO'da açık madde var ama oturum "yok/sahipte" diyor: BİR kez ayıklama mesajı (TODO sha başına)
                let n_open = calls.open_work.and_then(|f| f(name)).unwrap_or(0);
                let sha = todo_sha(name).unwrap_or_default();
                if n_open > 0 && !sha.is_empty() {
                    let prev = dict_of(tri.get(name))?;
                    let done =
                        prev.get("sha").and_then(Value::as_str) == Some(sha.as_str()) && !other_mode(&prev, mode);
                    if !done {
                        let why = format!("TODO'da {n_open} açık madde, oturum 'yok/sahipte' diyor");
                        let extra = json!({"next": format!("todo_open={n_open}"), "todo_open": n_open,
                            "sha": pyc::head(&sha, 12), "cli": "claude"});
                        step.send("todo_triage", why, TODO_TRIAGE_TEXT, extra, &mut out, &mut rec_all);
                        let entry = json!({"sha": sha, "at": now, "mode": mode, "open": n_open, "session": v.name});
                        tri.insert(name.to_string(), entry);
                        continue;
                    }
                    let forced = forced_open_nudge(calls.oldest_open, name, n_open);
                    if !forced.is_empty() {
                        let why =
                            format!("TODO'da {n_open} açık madde, oturum tekrar 'yok' dedi: en eski madde verildi");
                        let extra = json!({"next": format!("todo_open={n_open}"), "cli": "claude",
                            "via": "none_rejected"});
                        step.send("idle_nudge", why, &forced, extra, &mut out, &mut rec_all);
                    }
                    continue; // aynı sha: ayıklama zaten yapıldı, "devam" dürtmesi de gitmez
                }
            }
        }
        if owner_wait(txt) && idle_finish_marker(txt).0.is_empty() {
            if let Some(has_question) = calls.has_question {
                if now - since >= thr.max(OWNER_CLAIM_MIN_IDLE_SECS) as f64 {
                    // oturum 'sahipte' diyor ama kayıtlı soru YOK: proje başına dönem başına BİR dürtme
                    let has = has_question(name).unwrap_or(true);
                    let prev = dict_of(ocn.get(name))?;
                    let nudged = prev.get("session").and_then(Value::as_str) == Some(v.name.as_str())
                        && since <= float_of(prev.get("at"))?;
                    if !has && !nudged {
                        let minutes = pyc::floor_div(now - since, 60.0) as i64;
                        let why = format!("oturum 'sahipte' diyor, kayıtlı soru yok (boşta {minutes} dk)");
                        let extra = json!({"next": "owner_claim_unrecorded", "cli": "claude",
                            "via": "owner_claim_unrecorded"});
                        step.send("idle_nudge", why, OWNER_CLAIM_NUDGE_TEXT, extra, &mut out, &mut rec_all);
                        ocn.insert(name.to_string(), json!({"at": now, "session": v.name, "mode": mode}));
                        continue;
                    }
                }
            }
        }
        if !idle_finish_marker(txt).0.is_empty() || owner_wait(txt) {
            continue;
        }
        // Karar "iş VAR MI"ya dayanır: açık sahipsiz TODO maddesi ya da notta `sıradaki:`; mesaj SABİT.
        let n_open = calls.open_work.and_then(|f| f(name)).unwrap_or(0);
        let note_hint = next_work_hint(proj, None, true);
        if n_open <= 0 && note_hint.is_empty() {
            continue;
        }
        let nn = dict_of(next_none.get(name))?;
        if next_none_stated(txt) {
            if !nn.is_empty()
                && recorded_open(&nn)? == n_open
                && nn.get("session").and_then(Value::as_str) == Some(v.name.as_str())
            {
                let forced =
                    if n_open > 0 { forced_open_nudge(calls.oldest_open, name, n_open) } else { String::new() };
                if !forced.is_empty() {
                    let why = format!("claude boşta {idle_secs} sn, 'yok' reddedildi, {n_open} açık madde");
                    let extra = json!({"next": format!("todo_open={n_open}"), "cli": "claude", "via": "none_rejected"});
                    step.send("idle_nudge", why, &forced, extra, &mut out, &mut rec_all);
                }
                continue;
            }
            if nn.is_empty() {
                // ilk görüş: kaydet; TODO sonra değişirse yeniden dürtülür
                next_none.insert(name.to_string(), json!({"open": n_open, "at": now, "session": v.name}));
                none_changed = true;
                continue;
            }
            next_none.shift_remove(name);
            none_changed = true;
        } else if !nn.is_empty() {
            next_none.shift_remove(name);
            none_changed = true;
        }
        let hint = if n_open > 0 { format!("TODO.md'de {n_open} açık sahipsiz madde") } else { note_hint };
        let why = format!("claude boşta {idle_secs} sn, sıradaki iş var");
        let extra = json!({"next": hint, "cli": "claude"});
        step.send("idle_nudge", why, CLAUDE_IDLE_NUDGE_TEXT, extra, &mut out, &mut rec_all);
    }
    if out.is_empty() && !none_changed {
        return unchanged();
    }
    let mut st = state.clone();
    st.insert("claude_idle".into(), Value::Object(rec_all));
    let optional = [("todo_triage", tri), ("owner_claim_nudge", ocn), ("owner_todo_move", otm)];
    for (key, value) in optional {
        if !value.is_empty() {
            st.insert(key.into(), Value::Object(value));
        }
    }
    if next_none.is_empty() {
        st.shift_remove("next_none");
    } else {
        st.insert("next_none".into(), Value::Object(next_none));
    }
    Ok((out, st))
}
