//! Grup C (proje kartları) paritesi: kayıtlı vektörler + `fixtures/hand` (parity/hand_cases.py).
use crate::harness::{cases, parity};
use cops_steward_core::cards::*;
use cops_steward_core::identity::{PathsArg, StewardPaths};
use cops_steward_core::types::Project;
use indexmap::IndexMap;
use serde_json::{Map, Value};

parity!("card_path", card_path_vectors, |c| {
    let name = c.str("name");
    let ret = c.ret.as_str().expect("yol");
    let base = ret.strip_suffix(&format!("/cards/{name}.json")).expect("kart yolu");
    let paths;
    let arg = match c.args.get("paths") {
        None | Some(Value::Null) => PathsArg::Default,
        Some(Value::String(s)) => PathsArg::Sid(s),
        Some(_) => {
            paths = c.arg::<StewardPaths>("paths");
            PathsArg::Paths(&paths)
        }
    };
    card_path(base, &name, arg).expect("kimlik")
});
parity!("raw_card_from_docs", raw_card_from_docs_vectors, |c| raw_card_from_docs(&c.arg("docs")));
parity!("_short", p_short, |c| short(c.args.get("text").expect("text"), c.opt("n")));
parity!("_str_list", p_str_list, |c| str_list(c.args.get("v").expect("v")));
parity!("_tbd_lines", p_tbd_lines, |c| tbd_lines(&c.opt::<String>("text").unwrap_or_default()));
parity!("_goal_from_docs", p_goal_from_docs, |c| goal_from_docs(&c.arg::<IndexMap<String, String>>("docs")));
parity!("raw_card_fields", raw_card_fields_vectors, |c| {
    raw_card_fields(&c.arg("raw"), c.opt::<Project>("project").as_ref())
});
parity!("parse_card_json", parse_card_json_vectors, |c| {
    parse_card_json(&c.opt::<String>("text").unwrap_or_default())
});
parity!("build_card_prompt", build_card_prompt_vectors, |c| {
    build_card_prompt(
        &c.str("name"),
        &c.arg("raw"),
        c.opt::<Project>("project").as_ref(),
        &c.or("lang", "tr".to_string()),
    )
});
parity!("pick_card_model", pick_card_model_vectors, |c| {
    pick_card_model(&c.str("configured"), &c.arg::<Vec<String>>("choices"), &c.or("fallback", String::new()))
});
parity!("brain_pause_verdict", brain_pause_verdict_vectors, |c| {
    brain_pause_verdict(
        c.opt::<Map<String, Value>>("card").as_ref(),
        c.arg("running"),
        &c.opt::<String>("reason").unwrap_or_default(),
        c.opt("now").unwrap_or(c.now),
    )
    .expect("kart")
});
parity!("card_refresh_reason", card_refresh_reason_vectors, |c| {
    card_refresh_reason(
        c.opt::<Map<String, Value>>("card").as_ref(),
        &c.str("source_hash"),
        c.arg("now"),
        c.arg("max_age_hours"),
    )
    .expect("kart")
});
parity!("card_one_liner", card_one_liner_vectors, |c| card_one_liner(c.opt::<Map<String, Value>>("card").as_ref()));

#[test]
fn hand_fixtures_are_loaded() {
    let recorded =
        std::fs::read_dir(crate::harness::vectors_dir().with_file_name("hand")).expect("fixtures/hand").count();
    assert!(recorded > 15);
    assert!(cases("parse_card_json").len() > 30);
}

/// Python'un istisna fırlattığı bozuk kartlar `Err` döner (panik yok).
#[test]
fn broken_card_values_are_errors() {
    let card = |v: Value| v.as_object().cloned().expect("nesne");
    let bad = card(serde_json::json!({"last_activity": "dün", "attempt_at": [1], "updated_at": {"a": 1}}));
    assert!(brain_pause_verdict(Some(&bad), false, "r", 0.0).is_err());
    assert!(card_refresh_reason(Some(&bad), "h", 0.0, 1).is_err());
}

/// Python `json.loads`un kabul edip `serde_json`un reddettiği girdiler (docs/rs-stew.md).
#[test]
fn parse_card_json_known_differences() {
    assert!(parse_card_json("{\"goal\": NaN}").is_none());
    assert!(parse_card_json("{\"goal\": \"\\ud800\"}").is_none());
    assert!(parse_card_json(&format!("{{\"goal\": {}1{}}}", "[".repeat(200), "]".repeat(200))).is_none());
}
