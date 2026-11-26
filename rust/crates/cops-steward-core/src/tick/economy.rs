//! 1) Oturum ekonomisi (eşik devri), 1b) bağlam sorusu, 2) devir sonrası yeniden açma, 2b) sahibin paused kapatması.

use super::{dict_of, float_of, float_or, Tick};
use crate::cards::BadValue;
use crate::closing::{
    context_answer, context_owner_topic, context_threshold, handover_defer_decision, is_context_question,
};
use crate::consts_gen::PAUSE_CLOSE_EXPIRE_SECONDS;
use crate::idletext::expired_handover_note;
use crate::markers::rfh_marker_in;
use crate::types::{Action, SessionView};
use crate::world::sibling_running;
use serde_json::{json, Value};

impl<'a> Tick<'a> {
    // py: plan_tick._threshold_handover
    /// Eşik devri: ertelenecekse kayıt (`handover_deferred` eylemi yalnız ilk ertelemede ya da neden değişince) + oturum bu
    /// tick'te başka eylem almaz; değilse devir. Dönen: devir başladı mı.
    pub(super) fn threshold_handover(
        &mut self,
        v: &SessionView,
        reason: String,
        tokens: Option<i64>,
        warn: i64,
    ) -> Result<bool, BadValue> {
        let prev = self.ho_deferred_prev.get(&v.name).and_then(Value::as_object);
        let since = match prev {
            Some(p) => Some(float_or(p.get("since"), self.now)?),
            None => None,
        };
        let (verdict, why) = handover_defer_decision(v, self.cfg, self.now, since, tokens, warn);
        self.busy.insert(v.name.clone());
        if verdict == "defer" {
            let new_why = prev.is_none_or(|p| p.get("why").and_then(Value::as_str) != Some(why.as_str()));
            self.ho_deferred.insert(v.name.clone(), json!({"since": since.unwrap_or(self.now), "why": why}));
            if new_why {
                self.act("handover_deferred", &v.name, why, &[("handover_reason", Value::from(reason))]);
            }
            return Ok(false);
        }
        // gerekçe eki yalnız önceden ertelenmiş devirde (altın kayıt)
        let reason = match (since, verdict) {
            (None, _) => reason,
            (Some(_), "force") => format!("{reason} (zorla: {why})"),
            (Some(_), _) => format!("{reason} (ertelenmişti)"),
        };
        self.act("handover", &v.name, reason, &[]);
        self.ho_pending.insert(v.name.clone(), Value::from(self.now));
        Ok(true)
    }

    /// Aşama 1: Bağlam token'ı biliniyorsa tek ölçüt odur; değilse satır sayısı (yeni açılmış oturumda tetiklemez).
    pub(super) fn threshold_handovers(&mut self) -> Result<(), BadValue> {
        let (cfg, now) = (self.cfg, self.now);
        for v in self.inp.views {
            if !v.running || !v.tmux || !self.managed(&v.name) {
                continue;
            }
            if self.ho_pending.contains_key(&v.name) || !self.halted_phase(&v.name).is_empty() {
                continue; // devir sürüyor; paused/done projede otomatik devir yok
            }
            let warn_tokens = context_threshold(cfg, &v.model);
            let ctx = v.context_tokens.unwrap_or(0);
            if warn_tokens != 0 && ctx != 0 {
                if ctx >= warn_tokens {
                    self.threshold_handover(
                        v,
                        format!("context {ctx} token >= {warn_tokens}"),
                        Some(ctx),
                        warn_tokens,
                    )?;
                }
            } else if let Some(h) = v.history_size.filter(|h| *h >= cfg.history_warn_at) {
                let young = cfg.history_min_age_minutes != 0
                    && v.started_at != 0.0
                    && (now - v.started_at) < cfg.history_min_age_minutes.saturating_mul(60) as f64;
                if !young {
                    self.threshold_handover(v, format!("history_size {h} >= {}", cfg.history_warn_at), None, 0)?;
                }
            }
        }
        Ok(())
    }

    /// Aşama 1b: "Bu oturumda mı sürdüreyim, devirle mi" sorusunu bağlam ölçümünden motor cevaplar; eşiğe yakınsa devir de başlar.
    pub(super) fn context_questions(&mut self) -> Result<(), BadValue> {
        let cfg = self.cfg;
        if !cfg.auto_context_answer {
            return Ok(());
        }
        for q in self.inp.questions {
            if q.status != "open" || !is_context_question(&q.text) {
                continue;
            }
            // sahibe ait konu seçenekte/detayda/birleşen metinde: cevap soruyu kapatırdı
            let mut other = q.options.iter().chain([&q.detail]).chain(&q.extra_texts).chain(&q.prev_texts);
            if other.any(|t| context_owner_topic(t)) {
                continue;
            }
            let Some(&v) = self.by_name.get(q.source.as_str()) else { continue };
            let ctx = v.context_tokens.unwrap_or(0);
            if !v.running || !v.tmux || ctx == 0 || !self.managed(&v.name) {
                continue;
            }
            let warn = context_threshold(cfg, &v.model);
            if warn == 0 || self.ho_pending.contains_key(&v.name) || self.busy.contains(&v.name) {
                continue;
            }
            if !self.halted_phase(&v.name).is_empty() {
                continue; // paused/done: devir başlatılmaz, soru sahipte/beyinde kalır
            }
            let (ho, text) = context_answer(ctx, warn, cfg.auto_context_ratio, &cfg.lang);
            let answer = |handover: bool| {
                let p = json!({"question_id": q.id, "answer": text, "handover": handover});
                Action::new("auto_answer", &v.name, "context", p.as_object().cloned().unwrap_or_default())
            };
            if !ho {
                self.actions.push(answer(false));
                continue;
            }
            // "önce devir" cevabı devirle birlikte gider; devir ertelenirse soru açık kalır
            let mark = self.actions.len();
            let limit = (cfg.auto_context_ratio * warn as f64) as i64;
            if self.threshold_handover(v, format!("context soru: {ctx} token >= {limit}"), Some(ctx), warn)? {
                self.actions.insert(mark, answer(true));
            }
        }
        Ok(())
    }

    /// Host kapalı: görünümü yok diye erteleme izi silinmez.
    pub(super) fn keep_unavailable_deferrals(&mut self) {
        for (name, rec) in &self.ho_deferred_prev {
            if !self.ho_deferred.contains_key(name) && !self.by_name.contains_key(name.as_str()) && self.unavail(name) {
                self.ho_deferred.insert(name.clone(), rec.clone());
            }
        }
    }

    /// Aşama 2: Devir gönderilmiş oturumlar: READY FOR HANDOVER geldi ya da süre doldu -> yeniden aç (proje paused/done ise
    /// açma, `ho_halted`).
    pub(super) fn finish_handovers(&mut self) -> Result<(), BadValue> {
        let (cfg, now, views) = (self.cfg, self.now, self.inp.views);
        let pending: Vec<(String, Value)> = self.ho_pending.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        for (name, sent_at) in pending {
            if !self.managed(&name) {
                self.drop_handover(&name); // yönetilmeyen oturum: yeniden açılmaz
                continue;
            }
            if self.busy.contains(&name) {
                continue;
            }
            let v = self.by_name.get(name.as_str()).copied();
            if v.is_none() && self.unavail(&name) {
                continue; // host kapalı: devir izi korunur
            }
            let halted = self.halted_phase(&name);
            let Some(v) = v.filter(|v| v.running) else {
                if !self.ho_close.contains_key(&name) && !halted.is_empty() {
                    let why = format!("devir sonrası oturum kapanmış ama proje {halted}: yeniden açılmadı");
                    self.act("ho_halted", &name, why, &[("phase", halted.into()), ("step", "gone".into())]);
                } else if !self.ho_close.contains_key(&name)
                    && !sibling_running(views, &name, self.projects, cfg, self.inp.world)
                {
                    self.act("respawn", &name, "handover sent, session gone → start", &[]);
                }
                self.drop_handover(&name); // devir bitmeden oturum gitti: pause yazılmaz
                self.busy.insert(name);
                continue;
            };
            let ready = rfh_marker_in(&v.last_assistant);
            let expired = (now - float_of(&sent_at)?) >= cfg.ho_grace_minutes.saturating_mul(60) as f64;
            // busy None (sinyal yok) = meşgul değil; yalnız kesin True bekletir
            if v.busy == Some(true) || !(ready || expired) {
                continue;
            }
            if sibling_running(views, &name, self.projects, cfg, self.inp.world) {
                self.act("stop", &name, "devir bitti, projenin başka oturumu çalışıyor → kapat", &[]);
            } else if let Some(project) = self.ho_close.get(&name).cloned() {
                let why_pause = self.ho_pause.get(&name).filter(|w| crate::pyc::truthy(w)).cloned();
                match why_pause {
                    Some(why) => self.act(
                        "stop",
                        &name,
                        "keepwarm zinciri: devir bitti → kapat + paused",
                        &[("pause", json!({"project": project, "reason": why}))],
                    ),
                    None => self.act("stop", &name, "STEWARD-DONE: devir bitti → kapat", &[]),
                }
            } else if !halted.is_empty() {
                let why = format!("devir bitti ama proje {halted}: yeniden açılmadı, oturum devir notuyla açık");
                let step = if ready { "ready" } else { "expired" };
                self.act("ho_halted", &name, why, &[("phase", halted.into()), ("step", step.into())]);
            } else {
                let note = if ready { String::new() } else { expired_handover_note(&v.last_assistant, &cfg.lang) };
                let reason = if ready { "READY FOR HANDOVER" } else { "handover grace expired" };
                let pairs: &[(&str, Value)] = if note.is_empty() { &[] } else { &[("card_note", Value::from(note))] };
                self.act("respawn", &name, reason, pairs);
            }
            self.drop_handover(&name);
            self.busy.insert(name);
        }
        Ok(())
    }

    // py: plan_tick._close_done
    /// Faz done olduktan sonra oturumu kapat: önce devir (`ho_close`), sonra stop. Devir atlanır: `done_handover` kapalı,
    /// devir sürüyor, tmux'suz/yönetilmeyen oturum ya da bağlam eşiğin `done_handover_min_ratio` oranından küçük.
    pub(super) fn close_done(&mut self, v: &SessionView, project: &str, why: &str) {
        let cfg = self.cfg;
        self.busy.insert(v.name.clone());
        let warn = context_threshold(cfg, &v.model);
        let ctx = v.context_tokens.unwrap_or(0);
        let small = cfg.done_handover_min_ratio != 0.0
            && warn != 0
            && ctx != 0
            && (ctx as f64) < cfg.done_handover_min_ratio * warn as f64;
        let pending = self.ho_pending.contains_key(&v.name);
        if cfg.done_handover && v.tmux && self.managed(&v.name) && !pending && !small {
            self.act("handover", &v.name, format!("{why} → devir, sonra kapat"), &[]);
            self.ho_pending.insert(v.name.clone(), Value::from(self.now));
            self.ho_close.insert(v.name.clone(), Value::from(project));
        } else if !pending {
            self.act("stop", &v.name, why, &[]);
        }
    }

    /// Aşama 2b: Sahip/CLI projeyi paused yaptı (`state.pause_close`): boştaki oturum hemen devir + kapat, meşgulse sonraki
    /// tick. Faz paused değilse, oturum yoksa ya da süre dolduysa istek düşer.
    pub(super) fn pause_close(&mut self) -> Result<(), BadValue> {
        let (cfg, now) = (self.cfg, self.now);
        for (project, req_at) in dict_of(self.st.get("pause_close"))? {
            let mut pc = dict_of(self.st.get("pause_close"))?;
            let p = self.projects.get(&project);
            let mine: Vec<&'a SessionView> = self
                .inp
                .views
                .iter()
                .filter(|v| v.running && v.name != cfg.brain_name && self.key_of(&v.name) == project)
                .collect();
            let gone = p.is_none_or(|p| p.phase != "paused")
                || mine.is_empty()
                || (now - float_of(&req_at)?) >= PAUSE_CLOSE_EXPIRE_SECONDS as f64;
            if gone {
                pc.shift_remove(&project);
                self.st.insert("pause_close".into(), Value::Object(pc));
                continue;
            }
            let mut left = false;
            for v in mine {
                if self.busy.contains(&v.name) || self.ho_pending.contains_key(&v.name) {
                    continue;
                }
                if v.busy == Some(true) {
                    left = true;
                    continue;
                }
                self.close_done(v, &project, "sahip paused yaptı: boşta oturum devir + kapat");
            }
            if !left {
                pc.shift_remove(&project);
                self.st.insert("pause_close".into(), Value::Object(pc));
            }
        }
        Ok(())
    }
}
