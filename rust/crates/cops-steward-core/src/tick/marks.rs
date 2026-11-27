//! 3) İşaret taraması (yalnız DEĞİŞMİŞ yanıtlarda) ve iki adımlı STEWARD-DONE; ertelenmiş STEWARD-DONE.

use super::Tick;
use crate::cards::BadValue;
use crate::closing::{confirm_action, done_conflict_answer};
use crate::consts_gen::{P_CONFIRM_HASH_RE, P_CONFIRM_ZERO_RE};
use crate::markers::{done_blocked, lang_fix_action, marker_texts, scan_markers};
use crate::prompts::bad;
use crate::pyc;
use crate::tour::{marker_record_actions, note_project_next};
use crate::types::SessionView;
use serde_json::Value;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;
static CONFIRM_HASH_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CONFIRM_HASH_RE.as_str()));
static CONFIRM_ZERO_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_CONFIRM_ZERO_RE.as_str()));

impl<'a> Tick<'a> {
    /// Aşama 3: Değişmiş son yanıtların işaretleri: kayıt eylemleri, `project_next`, dil düzeltmesi, PLAN-READY, DONE.
    pub(super) fn markers(&mut self) -> Result<(), BadValue> {
        let (cfg, now) = (self.cfg, self.now);
        for v in self.inp.views {
            if !v.running || v.last_assistant.is_empty() || v.name == cfg.brain_name {
                continue;
            }
            if let Some(w) = self.inp.world {
                // yalnız kendi proje oturumları; kayıtsız oturumu yalnız default işler (K9)
                let cls = w.session_class(&v.name, v.blueprint.as_deref());
                if cls != "own" && !(cls == "adhoc" && w.is_adhoc_owner) {
                    continue;
                }
            }
            let hash = pyc::sha1_hex(v.last_assistant.as_bytes());
            let digest = pyc::head(&hash, 16);
            if self.seen.get(&v.name).and_then(Value::as_str) == Some(digest) {
                continue;
            }
            self.seen.insert(v.name.clone(), Value::from(digest));
            let m = scan_markers(&v.last_assistant);
            let projects = self.projects;
            let proj = if projects.contains_key(v.project()) { v.project() } else { "" };
            self.actions.extend(marker_record_actions(&v.name, proj, &m));
            note_project_next(&mut self.st, proj, &v.name, &m, now)?;
            let lf =
                lang_fix_action(&v.name, proj, &marker_texts(&m), cfg, &mut self.st, now).map_err(|e| BadValue(e.0))?;
            self.actions.extend(lf);
            let Some(p) = projects.get(proj).filter(|_| !proj.is_empty()) else { continue };
            if m.plan_ready && p.phase == "planning" {
                self.act("set_phase", proj, "STEWARD-PLAN-READY", &[("phase", "planned".into())]);
            }
            if (m.done || m.confirmed.is_some()) && done_blocked(Some(p)) {
                // sürekli geliştirme projesi: iş paketinin bitişi projeyi `done` yapmaz
            } else if let Some(body) = &m.confirmed {
                self.confirmed(v, proj, body);
            } else if m.done && !self.done_confirm.contains_key(proj) {
                self.done_confirm.insert(proj.to_string(), Value::from(now));
                let a = confirm_action(&v.name, proj, cfg, "STEWARD-DONE iddiası: teyit istendi");
                self.actions.push(a);
            }
        }
        Ok(())
    }

    /// `STEWARD-DONE-CONFIRMED: <hash> ... 0 ...`: kanıtsızsa tek teyit direktifi; kanıtlıysa TODO/TBD sayımı, sahip
    /// cevabı ve alt ajan durumuna göre done / paused / soru / erteleme.
    fn confirmed(&mut self, v: &SessionView, proj: &str, body: &str) {
        let (cfg, now, questions) = (self.cfg, self.now, self.inp.questions);
        if !(pyc::is_match(&CONFIRM_HASH_RE, body) && pyc::is_match(&CONFIRM_ZERO_RE, body)) {
            if !self.done_confirm.contains_key(proj) {
                // kanıtsız teyit: düz iddia gibi
                self.done_confirm.insert(proj.to_string(), Value::from(now));
                self.actions.push(confirm_action(&v.name, proj, cfg, "STEWARD-DONE-CONFIRMED kanıtsız"));
            }
            return;
        }
        let mut left = self.inp.open_work.and_then(|f| f(proj));
        let mut tbd_left = self.inp.open_tbd.map_or(0, |f| f(proj).unwrap_or(0));
        let owner_ans =
            if left.unwrap_or(0) != 0 || tbd_left != 0 { done_conflict_answer(questions, proj, now) } else { None };
        if owner_ans == Some(true) {
            (left, tbd_left) = (Some(0), 0); // sahip 'bitti' dedi: sayı çelişkisi sayılmaz
        }
        let left_n = left.unwrap_or(0);
        let deferred = v.subagent_active || (v.subagent_unknown && !self.quiet_idle(v));
        if owner_ans == Some(false) {
            // sahip cevapladı (bitmedi/devam): yeniden 'çelişti' sorusu açılmaz, kapatma da yok
        } else if tbd_left != 0 && left_n == 0 {
            let text = format!(
                "{}: STEWARD-DONE-CONFIRMED geldi ama TOBEDECIDED.md'de {tbd_left} açık karar var; faz done yapılmadı, \
                 paused (sahip bekliyor). Kararları verir misiniz, yoksa gerçekten bitti mi? Cevap ya da yeni iş gelince \
                 proje yeniden açılır.",
                v.name
            );
            let pairs = [("project", Value::from(proj)), ("text", Value::from(text))];
            self.act("ask_user", &v.name, "STEWARD-DONE-CONFIRMED TBD ile çelişti", &pairs);
            // açık sahip sorusu varken done DEĞİL paused (sahip bekliyor)
            if !deferred {
                self.done_confirm.shift_remove(proj);
                let reason = "STEWARD-DONE-CONFIRMED + açık TBD: sahip bekliyor";
                self.act("set_phase", proj, reason, &[("phase", "paused".into())]);
                if !self.busy.contains(&v.name) {
                    self.close_done(v, proj, "STEWARD-DONE-CONFIRMED + açık TBD");
                }
            }
        } else if left_n != 0 {
            let text = format!(
                "{}: STEWARD-DONE-CONFIRMED geldi (\"{}\") ama projenin TODO.md'sinde {left_n} açık `- [ ]` iş var; faz \
                 done yapılmadı, oturum açık. Gerçekten bitti mi?",
                v.name,
                pyc::head(body, 160)
            );
            let pairs = [("project", Value::from(proj)), ("text", Value::from(text))];
            self.act("ask_user", &v.name, "STEWARD-DONE-CONFIRMED yerel sayımla çelişti", &pairs);
        } else if deferred {
            self.done_pending.insert(v.name.clone(), Value::from(proj)); // alt ajan bitince uygulanır
        } else {
            self.done_confirm.shift_remove(proj);
            // D4: projenin sahibe açık sorusu varken done DEĞİL paused
            let owner_open: Vec<_> = questions.iter().filter(|q| q.status == "open" && q.project == proj).collect();
            if owner_open.is_empty() {
                self.act("set_phase", proj, "STEWARD-DONE", &[("phase", "done".into())]);
                if !self.busy.contains(&v.name) {
                    self.close_done(v, proj, "STEWARD-DONE");
                }
            } else {
                let never = owner_open.iter().filter(|q| q.notified_at == 0.0).count();
                let extra = if never != 0 { format!(" ({never} tanesi telefona gitmedi)") } else { String::new() };
                let reason = format!("STEWARD-DONE + {} açık sahip sorusu{extra}: sahip bekliyor", owner_open.len());
                self.act("set_phase", proj, reason, &[("phase", "paused".into())]);
                if !self.busy.contains(&v.name) {
                    self.close_done(v, proj, "STEWARD-DONE + açık sahip sorusu");
                }
            }
        }
    }

    /// Ertelenmiş STEWARD-DONE: alt ajan sustu mu? (Ertelemeden sonra açık iş düştüyse ya da `NO_DONE_TAG` eklendiyse düşer.)
    pub(super) fn deferred_done(&mut self) -> Result<(), BadValue> {
        let pending: Vec<(String, Value)> = self.done_pending.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        for (name, proj) in pending {
            let v = self.by_name.get(name.as_str()).copied();
            if v.is_none() && self.unavail(&name) {
                continue;
            }
            let Some(v) = v.filter(|v| v.running) else {
                self.done_pending.shift_remove(&name);
                continue;
            };
            // `proj in projects`: dizge olmayan değer kayıtlı proje değildir (liste/sözlük Python'da hata)
            let key = match &proj {
                Value::String(s) => Some(s.as_str()),
                Value::Array(_) | Value::Object(_) => return Err(bad(&proj)),
                _ => None,
            };
            let projects = self.projects;
            let found = key.and_then(|k| projects.get_key_value(k)).filter(|(_, p)| !done_blocked(Some(p)));
            let Some((proj, _)) = found else {
                self.done_pending.shift_remove(&name);
                continue;
            };
            if v.subagent_active
                || (v.subagent_unknown && !self.quiet_idle(v))
                || v.busy == Some(true)
                || self.busy.contains(&name)
            {
                continue;
            }
            let has = |f: Option<crate::tour::OpenWork<'a>>| f.is_some_and(|f| f(proj).unwrap_or(0) != 0);
            if has(self.inp.open_work) || has(self.inp.open_tbd) {
                self.done_pending.shift_remove(&name); // ertelemeden sonra açık iş düşmüş: kapatma
                continue;
            }
            self.act("set_phase", proj, "STEWARD-DONE (ertelenmişti)", &[("phase", "done".into())]);
            self.close_done(v, proj, "STEWARD-DONE (ertelenmişti)");
            self.done_pending.shift_remove(&name);
        }
        Ok(())
    }
}
