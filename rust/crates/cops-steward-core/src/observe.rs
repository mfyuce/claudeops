//! Gözlem kipi süzgeci (grup 4): tur eylemlerini uygulanacak / kuru (`would:`) diye ayırır. SAF.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::prompts::{bad, items_of};
use crate::pyc;
use crate::recovery::{dict_of, observe_cluster};
use crate::types::Action;
use serde_json::{json, Map, Value};

type Doc = Map<String, Value>;

/// (uygulanacak, kuru/`would:`, güncellenmiş state).
pub type Observed = (Vec<Action>, Vec<Action>, Doc);

/// Uygulanmayan turun artırdığı `blocked_tours` sayaçlarını geri alır.
fn give_back_blocked_tours(a: &Action, st: &mut Doc) -> Result<(), BadValue> {
    let mut counts = dict_of(st.get("blocked_tours"))?;
    for item in items_of(a.payload.get("items"))? {
        let it = item.as_object().ok_or_else(|| bad(&item))?;
        let key = pyc::str_of(it.get("id").unwrap_or(&Value::Null));
        if it.get("kind").and_then(Value::as_str) != Some("blocked") {
            continue;
        }
        let Some(slot) = counts.get_mut(&key) else { continue };
        let left = pyc::to_int(slot).ok_or_else(|| bad(slot))?.saturating_sub(1).max(0);
        *slot = json!(left);
        if left == 0 {
            counts.shift_remove(&key);
        }
    }
    if counts.is_empty() {
        st.shift_remove("blocked_tours");
    } else {
        st.insert("blocked_tours".into(), Value::Object(counts));
    }
    Ok(())
}

/// `would:` tekilleştirme anahtarı: (tür, ad, soru / iş / küme).
fn observe_key(a: &Action) -> Result<String, BadValue> {
    let given = ["question_id", "job_id"].iter().find_map(|k| a.payload.get(*k).filter(|v| pyc::truthy(v)));
    let tail = match given {
        Some(v) => pyc::str_of(v),
        None => observe_cluster(a)?,
    };
    Ok(format!("{}:{}:{tail}", a.kind, a.name))
}

/// `plan_tick`in eylemlerini kipe göre ayırır. `act`: hepsi uygulanır, observe izleri silinir. `observe`:
/// `OBSERVE_SKIPPED` türleri uygulanmaz, aynı anahtar `OBSERVE_DEDUP_SECONDS` içinde bir kez raporlanır.
///
/// py: observe_filter
pub fn observe_filter(actions: &[Action], mode: &str, state: &Doc, now: f64) -> Result<Observed, BadValue> {
    let mut st = state.clone();
    if mode != "observe" {
        st.shift_remove("observed");
        st.shift_remove("observed_visit");
        return Ok((actions.to_vec(), Vec::new(), st));
    }
    let mut seen = Map::new();
    for (key, v) in dict_of(st.get("observed"))? {
        let at = pyc::to_float(&v).ok_or_else(|| bad(&v))?;
        if now - at < OBSERVE_DEDUP_SECONDS as f64 {
            seen.insert(key, json!(at));
        }
    }
    let mut visits = dict_of(st.get("observed_visit"))?;
    let (mut apply, mut dry) = (Vec::new(), Vec::new());
    for a in actions {
        if !OBSERVE_SKIPPED.contains(&a.kind.as_str()) {
            apply.push(a.clone());
            continue;
        }
        if a.kind == "tour" {
            give_back_blocked_tours(a, &mut st)?;
        }
        if a.kind == "start" && !a.payload.get("question_id").is_some_and(pyc::truthy) {
            visits.insert(a.name.clone(), json!(now));
        }
        let key = observe_key(a)?;
        if seen.contains_key(&key) {
            continue;
        }
        seen.insert(key, json!(now));
        dry.push(a.clone());
    }
    st.insert("observed".into(), Value::Object(seen));
    st.insert("observed_visit".into(), Value::Object(visits));
    Ok((apply, dry, st))
}
