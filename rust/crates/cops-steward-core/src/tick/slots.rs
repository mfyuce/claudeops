//! 4) Cevap iletimi, 5) uğrama sırası ve başlatma, 6) slot baskısı.

use super::{dict_of, float_map, float_or, num_of, py_in, Tick};
use crate::cards::BadValue;
use crate::consts_gen::{ACTIVE_PHASES, BRAIN_STOP_COOLDOWN_SECONDS};
use crate::identity;
use crate::idletext::{held_instruction_item, is_negative_answer, is_open_answer, notes_wait};
use crate::pyc;
use crate::questions::{paused_sweep_text, undelivered_answers};
use crate::types::{Project, SessionView};
use crate::world::{holds_total_slot, pick_delivery_view};
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap};

const DAY: f64 = 24.0 * 3600.0;

fn halted(p: &Project) -> bool {
    p.phase == "done" || p.phase == "paused"
}

fn active_phase(p: &Project) -> bool {
    ACTIVE_PHASES.contains(&p.phase.as_str())
}

impl<'a> Tick<'a> {
    /// 4. aşamanın başlangıç sayaçları: çalışan/elle açılmış projeler, başlatma sınırı, diğer kimliklerin slotları.
    pub(super) fn count_slots(&mut self) {
        let (cfg, now, views) = (self.cfg, self.now, self.inp.views);
        let mut running: BTreeSet<String> =
            views.iter().filter(|v| v.running && self.mine(v)).map(|v| v.project().to_string()).collect();
        // L2: sahibin elle açtığı oturum (`manual`) projeyi TUTAR
        if let Some(w) = self.inp.world {
            self.manual_projects = views
                .iter()
                .filter(|v| v.running && w.session_class(&v.name, v.blueprint.as_deref()) == "manual")
                .map(|v| w.owned_key(&v.name, v.blueprint.as_deref()))
                .filter(|k| !k.is_empty())
                .collect();
        }
        running.extend(self.manual_projects.iter().cloned());
        self.active = running.len() as i64;
        self.running_projects = running;
        self.max_starts = if cfg.drain { 0 } else { cfg.max_starts_per_tick };
        let Some(w) = self.inp.world else { return };
        if let Some(left) = w.starts_left {
            self.max_starts = self.max_starts.min(left).max(0);
        }
        if cfg.max_active_total > 0 {
            // makine geneli sınır: başka kimliklerin çalışan (çakışmasız) proje oturumları da sayılır
            let mut other: BTreeSet<String> = BTreeSet::new();
            for x in views {
                if !holds_total_slot(x, now, 0.0) {
                    continue; // boşta açık oturum makine geneli slot yemez
                }
                let key = match x.blueprint.as_deref() {
                    Some(bp) if !bp.is_empty() && w.owners.contains_key(bp) => bp.to_string(),
                    _ => match w.resolve(&x.name) {
                        ("project", key) => key,
                        _ => continue,
                    },
                };
                let owner = w.owner_of(&key);
                if !owner.is_empty() && owner != w.sid {
                    other.insert(key);
                }
            }
            self.others_active = other.len() as i64;
        }
    }

    // py: plan_tick._active_busy
    /// Kendi projelerimden makine geneli slotu yiyenler (her çağrıda yeniden: bu tick'te cevap iletilen oturum slot yer).
    fn active_busy(&self) -> Result<i64, BadValue> {
        let mut out: BTreeSet<&str> = BTreeSet::new();
        for v in self.inp.views {
            if !v.running || !self.mine(v) {
                continue;
            }
            let held = self.ho_pending.contains_key(&v.name)
                || holds_total_slot(v, self.now, float_or(self.last_directive_at.get(&v.name), 0.0)?);
            if held {
                out.insert(v.project());
            }
        }
        Ok(out.len() as i64)
    }

    // py: plan_tick._slots
    /// Boş başlatma yeri: yerel `max_active`, world varsa makine geneli `max_active_total` de.
    fn free_slots(&self) -> Result<i64, BadValue> {
        let cfg = self.cfg;
        let mut n = cfg.max_active - self.active - self.starts;
        if self.inp.world.is_some() && cfg.max_active_total > 0 {
            n = n.min(cfg.max_active_total - self.active_busy()? - self.others_active - self.starts);
        }
        Ok(n)
    }

    /// Başlatma kapısı: sınır içinde mi ve host/kota tutmuyor mu (`starts < max_starts and _slots() > 0 and not held`).
    fn can_start(&self, target: &str) -> Result<bool, BadValue> {
        Ok(self.starts < self.max_starts
            && self.free_slots()? > 0
            && !self.inp.world.is_some_and(|w| w.start_held(target)))
    }

    fn started(&mut self, target: &str) {
        self.starts += 1;
        self.busy.insert(target.to_string());
        self.last_directive_at.insert(target.to_string(), Value::from(self.now));
    }

    /// Aşama 4: Cevaplanmış sorular ilgili oturuma iletilir; kapalıysa proje açılır (done/paused proje yalnız açıkça "aç"
    /// diyen cevapla).
    pub(super) fn deliver_answers(&mut self) -> Result<(), BadValue> {
        let (cfg, now, views) = (self.cfg, self.now, self.inp.views);
        let projects = self.projects;
        let mine_views: Option<Vec<SessionView>> =
            self.inp.world.map(|_| views.iter().filter(|x| self.mine(x)).cloned().collect());
        let pick_from: &[SessionView] = mine_views.as_deref().unwrap_or(views);
        let mut by_session: HashMap<String, usize> = HashMap::new();
        for q in undelivered_answers(self.inp.questions) {
            let target = q.project.as_str();
            if target.is_empty() || target == cfg.brain_name {
                continue; // genel/beyin sorusu: beyin turunda gösterilir
            }
            let Some(p) = projects.get(target) else {
                // kayıtlı proje olmayan (ad hoc) oturumun sorusu: soruyu açan oturum çalışıyorsa ona gider
                let world = self.inp.world;
                let v = views.iter().find(|x| {
                    x.running
                        && (x.name == q.source || x.name == q.project)
                        && x.name != cfg.brain_name
                        && world.is_none_or(|w| {
                            let cls = w.session_class(&x.name, x.blueprint.as_deref());
                            cls == "own" || (w.is_adhoc_owner && cls == "adhoc")
                        })
                });
                let ready = |v: &&SessionView| !self.busy.contains(&v.name) && v.busy != Some(true) && !v.subagent_active;
                if let Some(v) = v.filter(ready) {
                    self.act("deliver_answer", &v.name, "answer", &[("question_id", Value::from(q.id.as_str()))]);
                    self.busy.insert(v.name.clone());
                    self.last_directive_at.insert(v.name.clone(), Value::from(now));
                }
                continue;
            };
            if let Some(v) = pick_delivery_view(pick_from, target, &q.source) {
                if let Some(&i) = by_session.get(&v.name) {
                    // aynı tick, aynı oturum: birleştir
                    if let Some(a) = self.actions.get_mut(i) {
                        let more = a.payload.entry("more_ids").or_insert_with(|| json!([]));
                        if let Value::Array(ids) = more {
                            ids.push(Value::from(q.id.as_str()));
                        }
                    }
                    continue;
                }
                if self.busy.contains(&v.name) || v.busy == Some(true) || v.subagent_active {
                    continue; // sonraki tick (alt ajan varken ana oturumu uyandırma)
                }
                by_session.insert(v.name.clone(), self.actions.len());
                self.act("deliver_answer", &v.name, "answer", &[("question_id", Value::from(q.id.as_str()))]);
                self.busy.insert(v.name.clone());
                self.last_directive_at.insert(v.name.clone(), Value::from(now));
            } else if self.manual_projects.contains(target) {
                // L2: proje sahibin elle açtığı oturumda; cevap iletilmez, ikinci oturum da açılmaz
            } else if halted(p) && (is_negative_answer(&q.answer) || !is_open_answer(&q.answer)) {
                // "hayır / paused kalsın / açma": faz değişmez, oturum açılmaz; cevap teslim edildi sayılır
                let pairs =
                    [("question_id", Value::from(q.id.as_str())), ("held", Value::from(held_instruction_item(q)))];
                self.act("close_negative_answer", target, "olumsuz sahip cevabı", &pairs);
            } else if halted(p) && !py_in(target, self.st.get("no_work_paused"))? && self.can_start(target)? {
                // sahip cevabı geldi: done/paused proje planned'a döner ve açılır
                self.act("set_phase", target, "sahip cevabı geldi", &[("phase", "planned".into())]);
                self.act("start", target, "answer → start", &[("question_id", Value::from(q.id.as_str()))]);
                self.started(target);
            } else if active_phase(p) && self.can_start(target)? {
                self.act("start", target, "answer → start", &[("question_id", Value::from(q.id.as_str()))]);
                self.started(target);
            }
        }
        Ok(())
    }

    /// TODO'ya duyarlı açılış: TODO.md içeriği değişince (ya da done/paused projede günlük süpürmede) açık iş varsa
    /// aktif proje cadence beklemeden açılır, done proje planned'a çekilir, paused projeye günde 1 soru. Dönen: TODO'su
    /// değişen aktif projeler.
    fn todo_triggers(&mut self) -> Result<BTreeSet<String>, BadValue> {
        let mut changed = BTreeSet::new();
        let Some(todo_sha) = self.inp.todo_sha else { return Ok(changed) };
        let now = self.now;
        let mut todo_seen: Map<String, Value> =
            dict_of(self.st.get("todo_seen"))?.into_iter().map(|(k, v)| (k, Value::from(pyc::str_of(&v)))).collect();
        let mut paused_asked = float_map(self.st.get("todo_paused_asked"))?;
        let mut todo_swept = float_map(self.st.get("todo_swept"))?;
        let get = |m: &Map<String, Value>, k: &str| m.get(k).and_then(Value::as_f64).unwrap_or(0.0);
        for p in self.projects.values() {
            let cur = todo_sha(&p.name).unwrap_or_default();
            if cur.is_empty() {
                continue;
            }
            let prev = todo_seen.insert(p.name.clone(), Value::from(cur.as_str()));
            let first = prev.is_none();
            let same = prev.as_ref().and_then(Value::as_str) == Some(cur.as_str());
            let swept_due = halted(p) && now - get(&todo_swept, &p.name) >= DAY;
            if active_phase(p) && (first || same) {
                continue;
            }
            if same && !swept_due {
                continue;
            }
            let ow = self.inp.open_work_real.or(self.inp.open_work);
            let Some(ow) = ow.filter(|f| f(&p.name).unwrap_or(0) != 0) else { continue };
            if active_phase(p) {
                changed.insert(p.name.clone());
            } else if p.phase == "done" {
                todo_swept.insert(p.name.clone(), Value::from(now));
                // done projenin TODO'suna açık iş düştü: planned'a çek, sonraki tick açar
                self.act("set_phase", &p.name, "done projenin TODO'suna açık iş geldi", &[("phase", "planned".into())]);
            } else if p.phase == "paused" && now - get(&paused_asked, &p.name) >= DAY {
                let n = ow(&p.name).map_or(Value::Null, Value::from);
                let pairs = [
                    ("project", Value::from(p.name.as_str())),
                    ("options", json!(["Aç", "Paused kalsın"])),
                    ("text", Value::from(paused_sweep_text(&p.name, &n))),
                ];
                self.act("ask_user", &p.name, "paused projenin TODO'suna madde geldi", &pairs);
                paused_asked.insert(p.name.clone(), Value::from(now));
            }
        }
        for (key, val) in [("todo_seen", todo_seen), ("todo_paused_asked", paused_asked), ("todo_swept", todo_swept)] {
            if !val.is_empty() {
                self.st.insert(key.into(), Value::Object(val));
            }
        }
        Ok(changed)
    }

    /// Aşama 5: Uğrama sırası: çalışmayan, aktif fazdaki, süresi dolmuş projeler başlatılır; başlatılamayanların nedeni
    /// `state.start_blocked`a yazılır. Dönen: (bekleyen var mı, kalan boş yer).
    pub(super) fn visits(&mut self) -> Result<(bool, i64), BadValue> {
        let (cfg, now) = (self.cfg, self.now);
        let projects = self.projects;
        // observe kipinde `last_visit` ilerlemez: `observed_visit` "uğranmış gibi" davranmayı sağlar
        let observed = dict_of(self.st.get("observed_visit"))?;
        let visit_of = |p: &Project| -> Result<f64, BadValue> {
            let o = float_or(observed.get(&p.name), 0.0)?;
            Ok(if o > p.last_visit { o } else { p.last_visit })
        };
        let mut tbd_asked = float_map(self.st.get("tbd_asked"))?;
        let todo_changed = self.todo_triggers()?;
        let mut due: Vec<(&'a Project, f64)> = Vec::new();
        let mut held: Vec<String> = Vec::new();
        for p in projects.values() {
            if !active_phase(p)
                || p.cadence_minutes <= 0
                || self.running_projects.contains(&p.name)
                || self.busy.contains(&p.name)
            {
                continue;
            }
            if let Some(w) = self.inp.world {
                if w.unavailable.contains(&p.name) || w.quota_held.contains(&p.name) {
                    continue; // host erişilemiyor / kota bekçisi: başlatma tutulur
                }
            }
            if self.brain_stopped(&p.name)? {
                continue; // beyin "kalan iş yok" diye durdurdu: cadence soğuk bağlamla hemen yeniden açmaz
            }
            let visit = visit_of(p)?;
            let due_now = visit == 0.0
                || todo_changed.contains(&p.name)
                || (now - visit) >= p.cadence_minutes.saturating_mul(60) as f64;
            if !due_now {
                continue;
            }
            if let (Some(ow), Some(tbd)) = (self.inp.open_work, self.inp.open_tbd) {
                if ow(&p.name) == Some(0) && tbd(&p.name).unwrap_or(0) > 0 {
                    // yalnız TBD kaldı: oturum açmak boşa tur; sahibe tek soru (günde en çok ~4)
                    let asked = tbd_asked.get(&p.name).and_then(Value::as_f64).unwrap_or(0.0);
                    if now - asked >= 6.0 * 3600.0 {
                        let n = tbd(&p.name).map_or("None".to_string(), |n| n.to_string());
                        let text = format!(
                            "{}: yerel TODO.md'de açık iş kalmadı, TOBEDECIDED.md'de {n} açık karar var. Kararları verir \
                             misiniz? Cevap gelince oturumu açıp devam ederim.",
                            p.name
                        );
                        let pairs = [("project", Value::from(p.name.as_str())), ("text", Value::from(text))];
                        self.act("ask_user", &p.name, "yalnız TBD kaldı", &pairs);
                        tbd_asked.insert(p.name.clone(), Value::from(now));
                    }
                    continue;
                }
            }
            if notes_wait(p) {
                held.push(p.name.clone()); // not BEKLEME ile başlıyor: dış bir şey bekleniyor
                continue;
            }
            due.push((p, visit));
        }
        due.sort_by(|a, b| {
            a.0.priority.cmp(&b.0.priority).then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        });
        let mut free = self.free_slots()?.max(0);
        if cfg.auto_start {
            for (p, _) in &due {
                if self.starts >= self.max_starts || free <= 0 {
                    break;
                }
                self.act("start", &p.name, "due", &[("phase", Value::from(p.phase.as_str()))]);
                free -= 1;
                self.started(&p.name);
            }
        }
        let tbd_asked = Value::Object(tbd_asked);
        self.put_or_pop("tbd_asked", tbd_asked);
        let waiting: Vec<&str> = due.iter().map(|(p, _)| p.name.as_str()).filter(|n| !self.busy.contains(*n)).collect();
        self.start_blocked(&waiting, free, held)?;
        Ok((!waiting.is_empty(), free))
    }

    /// `brain_stopped` kaydı (beyin durdurdu) bu projeye çözülüp soğuma süresi içinde mi (`any(...)`, kısa devreli).
    fn brain_stopped(&self, project: &str) -> Result<bool, BadValue> {
        for (k, v) in dict_of(self.st.get("brain_stopped"))? {
            if identity::project_key(&k, self.projects.keys().map(String::as_str)) == project
                && self.now - float_or(Some(&v), 0.0)? < BRAIN_STOP_COOLDOWN_SECONDS as f64
            {
                return Ok(true);
            }
        }
        Ok(false)
    }

    /// Süresi dolup BAŞLATILAMAYAN projelerin nedeni (`state.start_blocked`); BEKLEME notlu projeler ayrıca.
    fn start_blocked(&mut self, waiting: &[&str], free: i64, mut held: Vec<String>) -> Result<(), BadValue> {
        let cfg = self.cfg;
        if waiting.is_empty() {
            self.st.shift_remove("start_blocked");
        } else {
            let active_busy = self.active_busy()?;
            let total = self.inp.world.is_some() && cfg.max_active_total > 0;
            let total_free = cfg.max_active_total - active_busy - self.others_active - self.starts;
            let why = if !cfg.auto_start {
                "auto_start_off" // motor cadence ile oturum açmaz (sahip kararı); sınır nedeni değil
            } else if self.starts >= self.max_starts && free > 0 {
                "max_starts"
            } else if total && total_free <= 0 && total_free < cfg.max_active - self.active - self.starts {
                "max_active_total"
            } else {
                "max_active"
            };
            let mut names: Vec<&str> = waiting.to_vec();
            names.sort_unstable();
            let mut rec =
                json!({"projects": names, "reason": why, "active": self.active, "max_active": cfg.max_active});
            if why == "max_active_total" {
                if let Value::Object(o) = &mut rec {
                    o.insert("active_busy".into(), Value::from(active_busy));
                    o.insert("others_active".into(), Value::from(self.others_active));
                    o.insert("max_active_total".into(), Value::from(cfg.max_active_total));
                }
            }
            self.st.insert("start_blocked".into(), rec);
        }
        if !held.is_empty() {
            held.sort_unstable();
            match self.st.get_mut("start_blocked") {
                Some(Value::Object(o)) => {
                    o.insert("bekleme_projects".into(), json!(held));
                }
                _ => {
                    self.st.insert("start_blocked".into(), json!({"projects": held, "reason": "notes_bekleme"}));
                }
            }
        }
        Ok(())
    }

    /// Aşama 6: Slot baskısı: bekleyen varsa uzun süredir boşta duran proje oturumları durdurulur.
    pub(super) fn slot_pressure(&mut self, waiting: bool, free: i64) -> Result<(), BadValue> {
        if !waiting || free > 0 {
            return Ok(());
        }
        let (cfg, now) = (self.cfg, self.now);
        for v in self.inp.views {
            if !v.running || !self.mine(v) || self.busy.contains(&v.name) || self.ho_pending.contains_key(&v.name) {
                continue;
            }
            // `max(last_activity, last_directive_at.get(ad, 0.0), started_at)`
            let directed = match self.last_directive_at.get(&v.name) {
                None => 0.0,
                Some(x) => num_of(x)?,
            };
            let idle_since =
                [directed, v.started_at].into_iter().fold(v.last_activity, |a, b| if b > a { b } else { a });
            if v.busy == Some(false)
                && idle_since != 0.0
                && (now - idle_since) >= cfg.stop_idle_minutes.saturating_mul(60) as f64
            {
                self.act("stop", &v.name, format!("idle ≥ {} dk, slot bekleyen var", cfg.stop_idle_minutes), &[]);
                self.busy.insert(v.name.clone());
            }
        }
        Ok(())
    }
}
