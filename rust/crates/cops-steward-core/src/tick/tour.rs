//! 6a) API hatasında takılan oturumlar, 6b) cevapsız rutin sorunun sahibine düşmesi, 7) beyin turu ve tur sayaçları.

use super::{dict_of, float_or, num_map, str_or_empty, Tick};
use crate::cards::BadValue;
use crate::consts_gen::{
    BLOCKED_ESCALATE_SECONDS, BLOCKED_MAX_TOURS, BLOCKED_TEXT_PREFIX, ROUTINE_ESCALATE_SECONDS, SKIP_QUIET_SECONDS,
};
use crate::prompts::{bad, cut_tour_items, mark_ask_seen, stale_answers};
use crate::pyc;
use crate::recovery::plan_api_recovery;
use crate::tour::{review_items, TourInput};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

type Item = Map<String, Value>;

fn kind_is(it: &Item, kind: &str) -> bool {
    it.get("kind").and_then(Value::as_str) == Some(kind)
}

/// `str(it.get("id"))`
fn id_str(it: &Item) -> String {
    pyc::str_of(it.get("id").unwrap_or(&Value::Null))
}

impl<'a> Tick<'a> {
    /// Bu tick'te atlanacak oturumlar: dokunulanlar + devri sürenler (`busy_names | set(ho_pending)`).
    fn skip_set(&self) -> BTreeSet<String> {
        self.busy.iter().cloned().chain(self.ho_pending.keys().cloned()).collect()
    }

    /// Aşama 6a: API hatasında takılan oturumlar (yalnız bu kimliğin yönettiği, tmux'lu görünümler).
    pub(super) fn api_recovery(&mut self) -> Result<(), BadValue> {
        let eligible = |v: &crate::types::SessionView| v.tmux && self.managed(&v.name);
        let skip = self.skip_set();
        let err = dict_of(self.st.get("api_err"))?;
        let out = Value::Object(dict_of(self.st.get("api_outage"))?);
        let (actions, api_err, api_out) = plan_api_recovery(self.inp.views, &eligible, &skip, &err, &out, self.now)?;
        for a in actions {
            if a.kind == "nudge" {
                self.busy.insert(a.name.clone());
            }
            self.actions.push(a);
        }
        self.api_err = Value::Object(api_err.into_iter().map(|(k, v)| (k, Value::Object(v))).collect());
        self.api_out = api_out;
        Ok(())
    }

    /// Aşama 6b: Beynin cevaplamadığı rutin soru sahibine düşer (takılma maddesi daha geç).
    pub(super) fn escalate_routine(&mut self) {
        let now = self.now;
        for q in self.inp.questions {
            let limit = if q.text.starts_with(BLOCKED_TEXT_PREFIX) {
                BLOCKED_ESCALATE_SECONDS
            } else {
                ROUTINE_ESCALATE_SECONDS
            };
            if q.status == "open" && q.routine && (now - q.created_at) >= limit as f64 {
                let name = if q.project.is_empty() { "-" } else { q.project.as_str() };
                self.act(
                    "escalate_routine",
                    name,
                    "rutin soru cevapsız",
                    &[("question_id", Value::from(q.id.as_str()))],
                );
            }
        }
    }

    /// Aşama 7: Beyin turu: maddeler toplanır, çözülemeyen `blocked` maddesi kapatılır, aralık dolduysa ve beyin boştaysa tur
    /// gider; soru/atlama/takılma sayaçları ve panel özeti `state`e yazılır.
    pub(super) fn tour(&mut self) -> Result<(), BadValue> {
        let (cfg, now) = (self.cfg, self.now);
        let mut skip_seen = Map::new();
        for (k, r) in dict_of(self.st.get("skip_seen"))? {
            if let Value::Object(rec) = &r {
                if now - float_or(rec.get("at"), 0.0)? < SKIP_QUIET_SECONDS {
                    skip_seen.insert(k, r);
                }
            }
        }
        let mut sigs: IndexMap<String, String> = IndexMap::new();
        let skip = self.skip_set();
        let (lda, reviewed) = (num_map(&self.last_directive_at)?, num_map(&self.reviewed_at)?);
        let mut items = review_items(TourInput {
            views: self.inp.views,
            projects: self.projects,
            cfg,
            now,
            questions: self.inp.questions,
            ideas: self.inp.ideas,
            skip: &skip,
            last_directive_at: &lda,
            reviewed_at: &reviewed,
            world: self.inp.world,
            skip_seen: &skip_seen,
            sigs_out: Some(&mut sigs),
            open_work: self.inp.open_work,
            claim_check: self.inp.claim_check,
            state: &self.st,
        })?;
        // bayat blokaj kaydı: kapat (her tick beyne düşmesin)
        let live: BTreeSet<String> = self.inp.views.iter().filter(|v| v.running).map(|v| v.name.clone()).collect();
        for q in stale_answers(self.inp.questions, self.projects, cfg, now, &live) {
            let pairs = [("question_id", Value::from(q.id.as_str()))];
            self.act("close_stale_answer", &q.project, "bayat blokaj kaydı", &pairs);
        }
        // `blocked` maddesi art arda BLOCKED_MAX_TOURS turda çözülmediyse kapat
        let mut blocked_tours: IndexMap<String, i64> = IndexMap::new();
        for (k, n) in dict_of(self.st.get("blocked_tours"))? {
            blocked_tours.insert(k, pyc::to_int(&n).ok_or_else(|| bad(&n))?);
        }
        let tours_of = |bt: &IndexMap<String, i64>, it: &Item| bt.get(&id_str(it)).copied().unwrap_or(0);
        let mut kept = Vec::with_capacity(items.len());
        for it in items {
            if kind_is(&it, "blocked") && tours_of(&blocked_tours, &it) >= BLOCKED_MAX_TOURS {
                let name = str_or_empty(it.get("name"));
                let name = if name.is_empty() { "-".to_string() } else { name };
                let reason = format!("beyin {BLOCKED_MAX_TOURS} turda iletemedi/çözemedi (proje ya da oturum yok)");
                let pairs =
                    [("question_id", it.get("id").cloned().unwrap_or(Value::Null)), ("reason", Value::from(reason))];
                self.act("close_stale_answer", &name, format!("beyin {BLOCKED_MAX_TOURS} turda çözemedi"), &pairs);
            } else {
                kept.push(it);
            }
        }
        items = kept;
        let last_tour = float_or(self.st.get("last_tour"), 0.0)?;
        let brain = self.by_name.get(cfg.brain_name.as_str()).copied();
        let deferred = self.st.get("tour_deferred").is_some_and(pyc::truthy);
        let mut tour_gap = if deferred { cfg.tour_retry_minutes } else { cfg.tour_minutes }.saturating_mul(60);
        let fresh_q: BTreeSet<&str> = self
            .inp
            .questions
            .iter()
            .filter(|q| q.status == "open" && q.created_at > last_tour)
            .map(|q| q.id.as_str())
            .collect();
        let urgent = items.iter().any(|it| {
            ((kind_is(it, "routine") || kind_is(it, "ask"))
                && it.get("id").and_then(Value::as_str).is_some_and(|id| fresh_q.contains(id)))
                || (kind_is(it, "blocked") && tours_of(&blocked_tours, it) == 0)
        });
        if urgent {
            tour_gap = tour_gap.min(60); // YENİ acil madde: tur aralığını beklemeden bir sonraki tick'te
        }
        // kesmeden ÖNCE: 8. sıradan sonrası sayaçtan düşmesin
        let blocked_now: BTreeSet<String> = items.iter().filter(|it| kind_is(it, "blocked")).map(id_str).collect();
        let all_items = items.clone();
        let total_items = items.len();
        let brain_free = brain.is_some_and(|b| b.running && b.busy == Some(false));
        if !items.is_empty() && (now - last_tour) >= tour_gap as f64 && brain_free {
            items = cut_tour_items(&items, &cfg.ask_gate);
            mark_ask_seen(&mut self.st, &items, now)?;
            self.st.shift_remove("tour_deferred");
            let reason = format!("{} madde", items.len());
            let tour_items = Value::Array(items.iter().cloned().map(Value::Object).collect());
            self.act("tour", &cfg.brain_name, reason, &[("items", tour_items)]);
            for it in items.iter().filter(|it| kind_is(it, "blocked")) {
                *blocked_tours.entry(id_str(it)).or_insert(0) += 1;
            }
            self.st.insert("last_tour".into(), Value::from(now));
            let mut tour_sig = Map::new();
            for it in &items {
                if let Some(sig) = it.get("name").and_then(Value::as_str).and_then(|n| sigs.get(n)) {
                    tour_sig.insert(pyc::str_of(&it["name"]), Value::from(sig.as_str()));
                }
            }
            self.st.insert("tour_sig".into(), Value::Object(tour_sig));
            for it in &items {
                let kind = it.get("kind").ok_or_else(|| BadValue("missing key: kind".into()))?;
                if kind.as_str() == Some("review") {
                    let name = it.get("name").ok_or_else(|| BadValue("missing key: name".into()))?;
                    self.reviewed_at.insert(pyc::str_of(name), Value::from(now));
                }
            }
        }
        // kapanan sorunun kaydı düşer
        let open_ids: BTreeSet<&str> =
            self.inp.questions.iter().filter(|q| q.status == "open").map(|q| q.id.as_str()).collect();
        for key in ["ask_seen", "ask_gated"] {
            if self.st.contains_key(key) {
                let kept: Map<String, Value> =
                    dict_of(self.st.get(key))?.into_iter().filter(|(k, _)| open_ids.contains(k.as_str())).collect();
                if kept.is_empty() {
                    self.st.shift_remove(key);
                } else {
                    self.st.insert(key.into(), Value::Object(kept));
                }
            }
        }
        self.put_or_pop("skip_seen", Value::Object(skip_seen));
        // çözülen/kapanan madde sayacı düşer
        let blocked_tours: Map<String, Value> = blocked_tours
            .into_iter()
            .filter(|(k, _)| blocked_now.contains(k))
            .map(|(k, n)| (k, Value::from(n)))
            .collect();
        self.put_or_pop("blocked_tours", Value::Object(blocked_tours));
        self.st.insert("pending_items".into(), Value::from(total_items.max(items.len())));
        let pending_list: Vec<Value> = all_items
            .iter()
            .take(20)
            .map(|it| {
                json!({
                    "kind": str_or_empty(it.get("kind")),
                    "name": str_or_empty(it.get("name")),
                    "text": pyc::head(&str_or_empty(it.get("text")), 300),
                })
            })
            .collect();
        self.st.insert("pending_list".into(), Value::Array(pending_list));
        Ok(())
    }
}
