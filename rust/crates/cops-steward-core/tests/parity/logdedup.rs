//! Grup 1 (`_log_dedup`) paritesi. Python'un içerik özeti taşınmaz: vektör "önceki kayıt bu içerikle aynı mı" der.
use crate::harness::{cases, parity, Case};
use cops_steward_core::logdedup::*;
use serde_json::{Map, Value};

/// Vektörü oynatır; dönen: (işlev sonucu, çağrı sonrası ilgili konunun kaydı).
fn replay(c: &Case) -> (Option<Map<String, Value>>, Value) {
    let (log, event, now) = (c.str("log"), c.str("event"), c.arg::<f64>("now"));
    let data: Map<String, Value> = c.arg("data");
    let mut probe = LogSeen::new();
    log_dedup(&mut probe, &log, &event, &data, now);
    let mut seen = LogSeen::new();
    if let (Some((key, fresh)), Some(prev)) = (probe.first(), c.opt::<Map<String, Value>>("seen")) {
        let hash = if prev["same"] == Value::Bool(true) { fresh.hash.clone() } else { "başka".to_string() };
        let at = prev["at"].as_f64().expect("at");
        let suppressed = prev["suppressed"].as_i64().expect("suppressed");
        seen.insert(key.clone(), Seen { hash, at, suppressed });
    }
    let ret = log_dedup(&mut seen, &log, &event, &data, now);
    let post = seen.first().map_or(Value::Null, |(_, s)| serde_json::json!({"at": s.at, "suppressed": s.suppressed}));
    (ret, post)
}

parity!("_log_dedup", p_log_dedup, |c| {
    let (ret, post) = replay(c);
    assert!(crate::harness::same(&post, &c.after["seen"]), "durum: {post} != {}", c.after["seen"]);
    ret
});

/// py: _log_dedup
#[test]
fn old_subjects_are_evicted_past_the_cap() {
    assert!(!cases("_log_dedup").is_empty());
    let mut seen = LogSeen::new();
    let data = |i: usize| serde_json::json!({"name": i.to_string()}).as_object().cloned().expect("nesne");
    for i in 0..4000 {
        log_dedup(&mut seen, "l", "e", &data(i), 0.0);
    }
    assert_eq!(seen.len(), 4000);
    log_dedup(&mut seen, "l", "e", &data(4000), 10_000.0);
    assert_eq!(seen.len(), 1);
}
