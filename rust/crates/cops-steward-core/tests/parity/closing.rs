//! Grup 2 paritesi: devir/kapatma kararları, bağlam sorusu, toparlama ve DONE çelişkisi.
use crate::harness::{parity, same, Case};
use cops_steward_core::closing::*;
use cops_steward_core::types::{Config, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};

type Doc = Map<String, Value>;

fn check_after(c: &Case, key: &str, got: &Doc) {
    let got = Value::Object(got.clone());
    let want = c.after.get(key).cloned().unwrap_or_else(|| c.args[key].clone());
    assert!(same(&got, &want), "{key} sonrası farklı\n args: {:?}\n python: {want}\n rust:   {got}", c.args);
}

parity!("context_threshold", context_threshold_vectors, |c| context_threshold(
    &c.arg::<Config>("cfg"),
    &c.opt::<String>("model").unwrap_or_default()
));

parity!("handover_defer_decision", handover_defer_decision_vectors, |c| handover_defer_decision(
    &c.arg::<SessionView>("v"),
    &c.arg::<Config>("cfg"),
    c.arg("now"),
    c.opt("since"),
    c.opt("tokens"),
    c.or("warn", 0)
));

parity!("shutdown_note_result", shutdown_note_result_vectors, |c| {
    let mut it: Doc = c.arg("it");
    let got = shutdown_note_result(&mut it, &c.str("kind"), &c.arg::<Doc>("res"), c.arg("now")).expect("sonuç");
    check_after(c, "it", &it);
    got
});

parity!("plan_shutdown", plan_shutdown_vectors, |c| plan_shutdown(
    &c.arg::<Vec<SessionView>>("views"),
    &c.arg::<IndexMap<String, Project>>("projects"),
    &c.opt::<Doc>("sd").unwrap_or_default(),
    &c.arg::<Config>("cfg"),
    c.arg("now"),
    c.opt::<World>("world").as_ref(),
    &c.opt::<IndexMap<String, String>>("blockers").unwrap_or_default()
)
.expect("kapatma"));

parity!("is_context_question", is_context_question_vectors, |c| is_context_question(
    &c.opt::<String>("text").unwrap_or_default()
));

parity!("context_answer", context_answer_vectors, |c| context_answer(
    c.arg("tokens"),
    c.arg("warn"),
    c.arg("ratio"),
    &c.or("lang", "tr".to_string())
));

parity!("done_conflict_answer", done_conflict_answer_vectors, |c| done_conflict_answer(
    &c.arg::<Vec<Question>>("questions"),
    &c.str("proj"),
    c.arg("now")
));

parity!("_confirm_action", p_confirm_action, |c| confirm_action(
    &c.str("name"),
    &c.str("proj"),
    &c.arg::<Config>("cfg"),
    &c.str("why")
));

parity!("is_wrap_up_directive", is_wrap_up_directive_vectors, |c| is_wrap_up_directive(
    &c.opt::<String>("text").unwrap_or_default()
));

parity!("directive_keeps_phase", directive_keeps_phase_vectors, |c| directive_keeps_phase(
    &c.opt::<String>("text").unwrap_or_default(),
    c.opt::<Doc>("data").as_ref()
));

parity!("request_pause_close", request_pause_close_vectors, |c| {
    let mut st: Doc = c.arg("st");
    request_pause_close(&mut st, &c.str("project"), c.arg("now")).expect("istek");
    check_after(c, "st", &st);
    json!(null)
});

/// Bozuk tipli state: Python istisna fırlatır, Rust `BadValue` döner (panik yok).
///
/// py: plan_shutdown, shutdown_note_result, request_pause_close
#[test]
fn bad_state_types_are_errors() {
    let obj = |v: Value| v.as_object().cloned().expect("nesne");
    let none = IndexMap::new();
    let (cfg, projects) = (Config::default(), IndexMap::new());
    for sd in [
        json!({"items": []}),
        json!({"modes": 1}),
        json!({"only": 5}),
        json!({"init": true, "items": {"a": {}}}),
        json!({"init": true, "items": {"a": 1}}),
    ] {
        assert!(plan_shutdown(&[], &projects, &obj(sd.clone()), &cfg, 1.0, None, &none).is_err(), "{sd}");
    }
    let mut it = obj(json!({"fails": "x"}));
    assert!(shutdown_note_result(&mut it, "stop", &Map::new(), 1.0).is_err());
    let mut st = obj(json!({"pause_close": 3}));
    assert!(request_pause_close(&mut st, "p", 1.0).is_err());
}
