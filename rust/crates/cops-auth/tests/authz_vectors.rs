//! Python `authz` eylem tablosuyla eşitlik (`tests/data/authz_vectors.json`).

use cops_auth::authz::{action_for, Kind, Principal, RequestView, ACTION_TABLE, UNMAPPED};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("data/authz_vectors.json")).unwrap()
}

#[test]
fn table_is_identical_in_order() {
    let v = vectors();
    let expect: Vec<(&str, &str)> = v["table"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| (r[0].as_str().unwrap(), r[1].as_str().unwrap()))
        .collect();
    assert_eq!(ACTION_TABLE, expect.as_slice());
    assert_eq!(v["unmapped"], UNMAPPED);
}

#[test]
fn action_for_matches_python() {
    let v = vectors();
    let cases = v["actions"].as_array().unwrap();
    assert!(cases.len() > 300, "{}", cases.len());
    for c in cases {
        let (m, p) = (c[0].as_str().unwrap(), c[1].as_str().unwrap());
        assert_eq!(action_for(m, p), c[2].as_str().unwrap(), "{m} {p:?}");
    }
}

#[test]
fn legacy_principal_matches_python() {
    let v = vectors();
    let p = Principal::legacy();
    assert_eq!(v["legacy"]["uid"], p.uid.as_str());
    assert_eq!(v["legacy"]["roles"], serde_json::json!(p.roles));
    assert_eq!(p.kind, Kind::Legacy);
    assert!(p.has_role("admin") && !p.has_role("user"));
}

#[test]
fn duplicate_cookie_takes_last_and_header_takes_first() {
    let view = RequestView {
        method: "GET".into(),
        path: "/".into(),
        raw_query: String::new(),
        headers: vec![
            ("cookie".into(), "cops_t=a; x; cops_t=b; xcops_t=c".into()),
            ("cookie".into(), "cops_t=ikinci-baslik".into()),
        ],
        client_ip: "127.0.0.1".parse().unwrap(),
        peer_loopback: true,
    };
    assert_eq!(view.cookie("cops_t"), Some("b"));
    assert_eq!(view.cookie("x"), Some(""));
    assert_eq!(view.cookie("yok"), None);
}
