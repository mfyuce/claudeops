//! Grup 5: bir tick'in kararları (`plan_tick`). Python'daki tek işlev aşama aşama bölündü; aşamaların SIRASI ve
//! paylaşılan durum (eylem listesi, bu tick'te dokunulan oturumlar, devir izleri) Python'la aynıdır:
//!
//! - `economy`: (1) oturum ekonomisi (eşik devri), (1b) bağlam sorusu, (2) devir sonrası yeniden açma, (2b) sahibin
//!   paused kapatması;
//! - `marks`: (3) işaret taraması ve STEWARD-DONE(-CONFIRMED), ertelenmiş DONE;
//! - `slots`: (4) cevap iletimi, (5) uğrama/başlatma, (6) slot baskısı;
//! - `tour`: (6a) API kurtarma, (6b) rutin soru yükseltme, (7) beyin turu ve durum kaydı.
//!
//! Python'un iç işlevleri (`_mine`, `_unavail`, `_managed`, `_threshold_handover`, `_halted_phase`, `_close_done`,
//! `_quiet_idle`, `_active_busy`, `_slots`) `Tick` yöntemleridir (yanlarında `// py: plan_tick.<ad>`).

mod economy;
mod marks;
mod slots;
mod tour;

use crate::cards::BadValue;
use crate::identity;
use crate::prompts::{bad, is_project_session, object_of};
use crate::pyc;
use crate::tour::{ClaimCheck, OpenWork};
use crate::types::{Action, Config, Idea, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::collections::{BTreeSet, HashMap};

/// `proje -> TODO.md içerik özeti`; `None` = okunamadı/uzak (Python'da istisna ya da boş değer: tetik yok).
pub type TodoSha<'a> = &'a dyn Fn(&str) -> Option<String>;

/// (eylemler, güncellenmiş `state` kopyası).
pub type TickPlan = (Vec<Action>, Map<String, Value>);

/// `plan_tick` girdileri (Python parametreleriyle aynı adlar). Geri çağrılar verilmezse Python'daki `None`.
#[derive(Clone, Copy)]
pub struct TickInput<'a> {
    pub views: &'a [SessionView],
    pub projects: &'a IndexMap<String, Project>,
    pub state: &'a Map<String, Value>,
    pub cfg: &'a Config,
    pub now: f64,
    pub questions: &'a [Question],
    pub ideas: &'a [Idea],
    pub world: Option<&'a World>,
    pub open_work: Option<OpenWork<'a>>,
    pub open_tbd: Option<OpenWork<'a>>,
    pub claim_check: Option<ClaimCheck<'a>>,
    pub todo_sha: Option<TodoSha<'a>>,
    pub open_work_real: Option<OpenWork<'a>>,
}

/// Bir tick'in kararları: `state`in güncellenmiş KOPYASI döner (girdi değişmez). Sıra: ekonomi (devir/yeniden açma) ->
/// işaretler -> cevap iletimi -> uğrama/başlatma -> slot baskısı -> API kurtarma -> beyin turu. `world` verilirse
/// projeler kimliğin sahip olduklarına süzülür. Bozuk tipli `state` alanında (Python istisna fırlatır) `BadValue`.
///
/// py: plan_tick
pub fn plan_tick(input: TickInput<'_>) -> Result<TickPlan, BadValue> {
    let own = input.world.map(|w| w.own_projects(input.projects));
    let projects = own.as_ref().unwrap_or(input.projects);
    let mut t = Tick::new(input, projects)?;
    t.threshold_handovers()?;
    t.context_questions()?;
    t.keep_unavailable_deferrals();
    t.finish_handovers()?;
    t.pause_close()?;
    t.markers()?;
    t.deferred_done()?;
    t.count_slots();
    t.deliver_answers()?;
    let (waiting, free) = t.visits()?;
    t.slot_pressure(waiting, free)?;
    t.api_recovery()?;
    t.escalate_routine();
    t.tour()?;
    Ok(t.finish())
}

/// Tick boyunca paylaşılan durum (Python'un yerel değişkenleri).
pub(crate) struct Tick<'a> {
    inp: TickInput<'a>,
    projects: &'a IndexMap<String, Project>,
    cfg: &'a Config,
    now: f64,
    /// {oturum: blueprint} (boş blueprint yok; aynı ad tekrarında sonuncusu)
    bp: HashMap<&'a str, &'a str>,
    by_name: HashMap<&'a str, &'a SessionView>,
    st: Map<String, Value>,
    ho_pending: Map<String, Value>,
    ho_pause: Map<String, Value>,
    ho_close: Map<String, Value>,
    seen: Map<String, Value>,
    done_pending: Map<String, Value>,
    done_confirm: Map<String, Value>,
    last_directive_at: Map<String, Value>,
    reviewed_at: Map<String, Value>,
    ho_deferred_prev: Map<String, Value>,
    ho_deferred: Map<String, Value>,
    actions: Vec<Action>,
    /// bu tick'te zaten dokunulan oturumlar (ikinci bir eylem gönderilmez)
    busy: BTreeSet<String>,
    // 4. aşamanın sayaçları
    starts: i64,
    max_starts: i64,
    active: i64,
    others_active: i64,
    running_projects: BTreeSet<String>,
    manual_projects: BTreeSet<String>,
    /// 6a'nın yeni `api_err` / `api_outage` durumu (en sonda yazılır)
    api_err: Value,
    api_out: Value,
}

/// `dict(x or {})` (sözlük olmayan dolu değer Python'da hata).
pub(crate) fn dict_of(v: Option<&Value>) -> Result<Map<String, Value>, BadValue> {
    Ok(object_of(v)?.cloned().unwrap_or_default())
}

/// `float(v)`.
pub(crate) fn float_of(v: &Value) -> Result<f64, BadValue> {
    pyc::to_float(v).ok_or_else(|| bad(v))
}

/// `float(v or default)`.
pub(crate) fn float_or(v: Option<&Value>, default: f64) -> Result<f64, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(default),
        Some(x) => float_of(x),
    }
}

/// `key in container` (`container` = `x or {}`): sözlükte anahtar, listede öğe, dizgede alt dizge; diğer tipte hata.
pub(crate) fn py_in(key: &str, container: Option<&Value>) -> Result<bool, BadValue> {
    match container.filter(|v| pyc::truthy(v)) {
        None => Ok(false),
        Some(Value::Object(o)) => Ok(o.contains_key(key)),
        Some(Value::Array(a)) => Ok(a.iter().any(|x| x.as_str() == Some(key))),
        Some(Value::String(s)) => Ok(s.contains(key)),
        Some(other) => Err(bad(other)),
    }
}

/// `{k: float(v) for k, v in dict(x or {}).items()}`.
pub(crate) fn float_map(v: Option<&Value>) -> Result<Map<String, Value>, BadValue> {
    dict_of(v)?.into_iter().map(|(k, x)| Ok((k, Value::from(float_of(&x)?)))).collect()
}

/// `max(...)` içine giren değer: Python yalnız sayıyı (ve bool'u) karşılaştırır, dizge/None hata.
pub(crate) fn num_of(v: &Value) -> Result<f64, BadValue> {
    match v {
        Value::Number(n) => n.as_f64().ok_or_else(|| bad(v)),
        Value::Bool(b) => Ok(f64::from(u8::from(*b))),
        _ => Err(bad(v)),
    }
}

/// `review_items`e giden zaman sözlüğü (`max(...)` içinde kullanılır; bozuk değer tüm çağrıyı düşürür).
pub(crate) fn num_map(m: &Map<String, Value>) -> Result<IndexMap<String, f64>, BadValue> {
    m.iter().map(|(k, x)| Ok((k.clone(), num_of(x)?))).collect()
}

/// `str(x)` / `str(x or "")`.
pub(crate) fn str_or_empty(v: Option<&Value>) -> String {
    v.filter(|v| pyc::truthy(v)).map(pyc::str_of).unwrap_or_default()
}

fn payload(pairs: &[(&str, Value)]) -> Map<String, Value> {
    pairs.iter().map(|(k, v)| ((*k).to_string(), v.clone())).collect()
}

impl<'a> Tick<'a> {
    fn new(inp: TickInput<'a>, projects: &'a IndexMap<String, Project>) -> Result<Self, BadValue> {
        let st = inp.state.clone();
        let now = inp.now;
        let mut done_confirm = Map::new();
        for (k, t) in dict_of(st.get("done_confirm"))? {
            let t = float_of(&t)?;
            if now - t < crate::consts_gen::DONE_CONFIRM_TTL {
                done_confirm.insert(k, Value::from(t));
            }
        }
        Ok(Tick {
            inp,
            projects,
            cfg: inp.cfg,
            now,
            bp: inp
                .views
                .iter()
                .filter_map(|v| Some((v.name.as_str(), v.blueprint.as_deref().filter(|b| !b.is_empty())?)))
                .collect(),
            by_name: inp.views.iter().map(|v| (v.name.as_str(), v)).collect(),
            ho_pending: dict_of(st.get("ho_pending"))?,
            ho_pause: dict_of(st.get("ho_pause"))?,
            ho_close: dict_of(st.get("ho_close"))?,
            seen: dict_of(st.get("seen_assistant"))?,
            done_pending: dict_of(st.get("done_pending"))?,
            done_confirm,
            last_directive_at: dict_of(st.get("last_directive_at"))?,
            reviewed_at: dict_of(st.get("reviewed_at"))?,
            ho_deferred_prev: dict_of(st.get("ho_deferred"))?,
            ho_deferred: Map::new(),
            st,
            actions: Vec::new(),
            busy: BTreeSet::new(),
            starts: 0,
            max_starts: 0,
            active: 0,
            others_active: 0,
            running_projects: BTreeSet::new(),
            manual_projects: BTreeSet::new(),
            api_err: Value::Null,
            api_out: Value::Null,
        })
    }

    fn act(&mut self, kind: &str, name: &str, reason: impl Into<String>, pairs: &[(&str, Value)]) {
        self.actions.push(Action::new(kind, name, reason, payload(pairs)));
    }

    /// Ad -> proje (world varsa kimliğin projesi, yoksa kayıtlı projelerden önek kuralı).
    fn key_of(&self, name: &str) -> String {
        match self.inp.world {
            Some(w) => w.project_key(name),
            None => identity::project_key(name, self.projects.keys().map(String::as_str)).to_string(),
        }
    }

    // py: plan_tick._mine
    /// Görünüm bu kimliğin proje oturumu mu.
    fn mine(&self, v: &SessionView) -> bool {
        is_project_session(v, self.projects)
            && self.inp.world.is_none_or(|w| w.session_class(&v.name, v.blueprint.as_deref()) == "own")
    }

    // py: plan_tick._unavail
    /// Ad, host'u erişilemeyen bir projeye çözülüyor mu.
    fn unavail(&self, name: &str) -> bool {
        self.inp.world.is_some_and(|w| !w.unavailable.is_empty() && w.unavailable.contains(&w.project_key(name)))
    }

    // py: plan_tick._managed
    /// Oturum ekonomisi yalnız değnekçinin yönettiği oturumlara: beyin + kayıtlı proje oturumları.
    fn managed(&self, name: &str) -> bool {
        if name == self.cfg.brain_name {
            return true;
        }
        match self.inp.world {
            None => !identity::project_key(name, self.projects.keys().map(String::as_str)).is_empty(),
            Some(w) => !w.project_key(name).is_empty() && w.session_class(name, self.bp.get(name).copied()) == "own",
        }
    }

    // py: plan_tick._halted_phase
    /// Oturumun projesi paused/done ise fazın adı, değilse "".
    fn halted_phase(&self, name: &str) -> &'a str {
        let key = self.key_of(name);
        let projects: &'a IndexMap<String, Project> = self.projects;
        match projects.get(&key).filter(|_| !key.is_empty()) {
            Some(p) if p.phase == "paused" || p.phase == "done" => p.phase.as_str(),
            _ => "",
        }
    }

    // py: plan_tick._quiet_idle
    /// Alt ajan durumu bilinmiyor ama oturum kesin boşta ve `SHUTDOWN_QUIET_SECONDS`tir sessiz.
    fn quiet_idle(&self, v: &SessionView) -> bool {
        v.busy == Some(false)
            && v.last_activity != 0.0
            && (self.now - v.last_activity) >= crate::consts_gen::SHUTDOWN_QUIET_SECONDS
    }

    fn drop_handover(&mut self, name: &str) {
        self.ho_pending.shift_remove(name);
        self.ho_close.shift_remove(name);
        self.ho_pause.shift_remove(name);
    }

    /// `state.<key> = val` (dolu ise) ya da anahtarı sil (boşken anahtar yazılmaz).
    fn put_or_pop(&mut self, key: &str, val: Value) {
        if pyc::truthy(&val) {
            self.st.insert(key.to_string(), val);
        } else {
            self.st.shift_remove(key);
        }
    }

    /// Güncellenmiş durum kopyasını yazar ve eylemleri döner.
    fn finish(mut self) -> TickPlan {
        self.st.insert("ho_pending".into(), Value::Object(std::mem::take(&mut self.ho_pending)));
        let ho_close = Value::Object(std::mem::take(&mut self.ho_close));
        self.put_or_pop("ho_close", ho_close);
        let ho_pause = Value::Object(std::mem::take(&mut self.ho_pause));
        self.put_or_pop("ho_pause", ho_pause);
        self.st.insert("seen_assistant".into(), Value::Object(std::mem::take(&mut self.seen)));
        let done_confirm = Value::Object(std::mem::take(&mut self.done_confirm));
        self.put_or_pop("done_confirm", done_confirm);
        let done_pending = Value::Object(std::mem::take(&mut self.done_pending));
        self.put_or_pop("done_pending", done_pending);
        let ho_deferred = Value::Object(std::mem::take(&mut self.ho_deferred));
        self.put_or_pop("ho_deferred", ho_deferred);
        self.st.insert("last_directive_at".into(), Value::Object(std::mem::take(&mut self.last_directive_at)));
        self.st.insert("reviewed_at".into(), Value::Object(std::mem::take(&mut self.reviewed_at)));
        let (api_err, api_out) = (std::mem::take(&mut self.api_err), std::mem::take(&mut self.api_out));
        self.put_or_pop("api_err", api_err);
        self.put_or_pop("api_outage", api_out);
        self.st.insert("last_tick".into(), Value::from(self.now));
        (self.actions, self.st)
    }
}
