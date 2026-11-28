//! Alınamayan dosya kilidi günlüğe düşer (`file_lock_refused`, TBD#397 kalanı; Python `instances._locked` ve
//! `atomic_json._file_lock_outer`, rs/prov `47e3077c` / `bf4d3ed7`): çağıran reddi yutsa da iz kalır, yazım YOK.
use cops_state::instances::{Instances, NewInstance};
use cops_state::roster::Roster;
use cops_state::{Backend, Json, StateDocs, TestEnv};
use std::os::unix::fs::symlink;

fn refused_events(env: &TestEnv) -> Vec<Json> {
    std::fs::read_to_string(env.dir().join("diag.log"))
        .unwrap_or_default()
        .lines()
        .filter_map(|l| Json::parse(l).ok())
        .filter(|j| j.get("event").and_then(Json::as_str) == Some("file_lock_refused"))
        .collect()
}

#[test]
fn instances_lock_refusal_is_logged_with_document_path() {
    let env = TestEnv::new().unwrap();
    let d = env.dir().clone();
    let docs = StateDocs::isolated(d.clone(), Some(Backend::Files), "");
    std::fs::create_dir_all(d.root()).unwrap();
    symlink("/nonexistent-cops-lock", d.join("instances.json.lock")).unwrap();
    assert!(Instances::new(&docs)
        .record("n1", &NewInstance::default())
        .is_err());
    assert!(!d.instances_json().exists(), "kilitsiz yazım olmamalı");
    let ev = refused_events(&env);
    assert_eq!(ev.len(), 1, "{ev:?}");
    assert_eq!(
        ev[0].get("path").and_then(Json::as_str),
        Some(d.instances_json().to_str().unwrap())
    );
}

#[test]
fn roster_lock_refusal_is_logged_with_lock_base_path() {
    let env = TestEnv::new().unwrap();
    let d = env.dir().clone();
    let docs = StateDocs::isolated(d.clone(), Some(Backend::Files), "");
    std::fs::create_dir_all(d.root()).unwrap();
    symlink("/nonexistent-cops-lock", d.join("roster.lock")).unwrap();
    assert!(Roster::new(&docs).lock().is_err());
    let ev = refused_events(&env);
    assert_eq!(ev.len(), 1, "{ev:?}");
    assert_eq!(
        ev[0].get("path").and_then(Json::as_str),
        Some(d.join("roster").to_str().unwrap())
    );
}
