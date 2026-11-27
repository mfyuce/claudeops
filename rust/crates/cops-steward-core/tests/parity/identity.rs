//! Grup A (kimlik, yol, sahiplik) paritesi. Elle testlerdeki beklenen değerler Python çalıştırılarak alındı.
use crate::harness::parity;
use cops_steward_core::identity::*;
use cops_steward_core::types::*;
use indexmap::IndexMap;
use serde_json::{json, Value};

/// Vektörün kaydedildiği geçici `STEWARD_DIR`: ortak `cards` dizininin üstü.
fn base_of(paths: &Value) -> String {
    paths["cards"].as_str().and_then(|s| s.strip_suffix("/cards")).expect("cards").to_string()
}

parity!("paths_for", paths_for_vectors, |c| paths_for(&base_of(&c.ret), c.opt::<String>("sid").as_deref())
    .expect("kimlik"));

parity!("_pp", p_pp, |c| {
    let base = base_of(&c.ret);
    match c.args.get("paths") {
        None | Some(Value::Null) => pp(&base, PathsArg::Default),
        Some(Value::String(s)) => pp(&base, PathsArg::Sid(s)),
        Some(_) => pp(&base, PathsArg::Paths(&c.arg::<StewardPaths>("paths"))),
    }
    .expect("kimlik")
});

parity!("services_path", services_path_vectors, |c| services_path(
    c.ret.as_str().and_then(|s| s.strip_suffix("/services.json")).expect("yol")
));

parity!("normalize_host", normalize_host_vectors, |c| normalize_host(&c.arg::<Value>("host")));
parity!("valid_custom_id", valid_custom_id_vectors, |c| c.arg::<Value>("sid").as_str().is_some_and(valid_custom_id));
parity!("valid_steward_id", valid_steward_id_vectors, |c| c.arg::<Value>("sid").as_str().is_some_and(valid_steward_id));
parity!("valid_name", valid_name_vectors, |c| valid_name(&c.str("name")));
parity!("brain_name_for", brain_name_for_vectors, |c| brain_name_for(&c.str("sid")));
parity!("steward_title", steward_title_vectors, |c| steward_title(
    &c.str("sid"),
    &c.str("role"),
    &c.or("session", String::new())
));
parity!("steward_badge", steward_badge_vectors, |c| steward_badge(&c.str("name"), &c.arg("index")));
parity!("build_ownership_index", build_ownership_index_vectors, |c| build_ownership_index(
    &c.arg("names_by_sid"),
    c.opt("brains").as_ref(),
    c.opt("services").as_ref(),
    c.opt("hosts").as_ref()
));
parity!("derived_of", derived_of_vectors, |c| derived_of(&c.str("name"), &c.str("key")));
parity!("_project_key", p_project_key, |c| {
    let projects: IndexMap<String, Value> = c.arg("projects");
    project_key(&c.str("name"), projects.keys().map(String::as_str)).to_string()
});
parity!("reserved_reason", reserved_reason_vectors, |c| { reserved_reason(&c.str("name"), &c.arg("index")) });

/// py: StewardPaths, paths_for
#[test]
fn paths_layout_and_errors() {
    let d = paths_for("/s", None).expect("default");
    assert_eq!((d.root.as_str(), d.lock.as_str(), d.findings.as_str()), ("/s", "/s/.lock", "/s/findings.json"));
    let k = paths_for("/s", Some("iso")).expect("iso");
    assert_eq!(
        (k.root.as_str(), k.cards.as_str(), k.reviews.as_str()),
        ("/s/stewards/iso", "/s/cards", "/s/stewards/iso/reviews")
    );
    assert_eq!(StewardPaths::default().reviews, "");
    for (sid, msg) in [
        ("", "invalid steward id: ''"),
        ("Ab", "invalid steward id: 'Ab'"),
        ("a1", "invalid steward id: 'a1'"),
        ("../x", "invalid steward id: '../x'"),
        ("a'\u{200b}", "invalid steward id: \"a'\\u200b\""),
        ("ab\n", "invalid steward id: 'ab\\n'"),
    ] {
        assert_eq!(paths_for("/s", Some(sid)).expect_err(sid).to_string(), msg);
    }
}

/// py: valid_name, valid_custom_id, valid_steward_id
#[test]
fn name_rules_edges() {
    let a48 = "a".repeat(48);
    // (ad, valid_name, valid_custom_id, valid_steward_id)
    let table: &[(String, bool, bool, bool)] = &[
        ("".into(), false, false, false),
        ("a".into(), true, false, false),
        ("ab".into(), true, true, true),
        ("ab\n".into(), false, false, false),
        ("ab\n\n".into(), false, false, false),
        ("default".into(), true, false, true),
        ("default\n".into(), false, false, false),
        ("degnekci\n".into(), false, false, false),
        ("a-b".into(), true, false, false),
        ("a--b".into(), false, false, false),
        ("a_b-c1".into(), true, false, false),
        ("-a".into(), false, false, false),
        (a48.clone(), true, false, false),
        (format!("{}\n", &a48[1..]), false, false, false),
        (format!("{a48}\n"), false, false, false),
        ("a".repeat(17), true, false, false),
        (format!("{}\n", "a".repeat(16)), false, false, false),
        ("çay".into(), false, false, false),
    ];
    for (s, name, custom, steward) in table {
        assert_eq!((valid_name(s), valid_custom_id(s), valid_steward_id(s)), (*name, *custom, *steward), "{s:?}");
    }
}

/// py: normalize_host
#[test]
fn normalize_host_edges() {
    let table = [
        (json!(null), ""),
        (json!(""), ""),
        (json!(" local "), ""),
        (json!(" yuhem\u{a0}"), "yuhem"),
        (json!(0), ""),
        (json!(0.0), ""),
        (json!(5), "5"),
        (json!(2.0), "2.0"),
        (json!(true), "True"),
        (json!(false), ""),
        (json!([]), ""),
        (json!(["a"]), "['a']"),
        (json!({}), ""),
        (json!({"a": 1}), "{'a': 1}"),
    ];
    for (h, want) in table {
        assert_eq!(normalize_host(&h), want, "{h}");
    }
}

/// py: reviewer_ids, is_reviewer
#[test]
fn reviewers_from_settings() {
    let st = json!({"rev": {"role": " reviewer "}, "default": {"role": "reviewer"}, "iso": {"role": "steward"},
        "bad1": {"role": "reviewer"}, "x": {"role": "reviewer"}, "nodict": "reviewer", "lst": {"role": ["reviewer"]},
        "degnekcix": {"role": "reviewer"}, "nl\n": {"role": "reviewer"}, "none": {"role": null}});
    let rv = reviewer_ids(Some(&st));
    assert_eq!(rv.iter().map(String::as_str).collect::<Vec<_>>(), ["rev"]);
    for (sid, want) in
        [(None, false), (Some("default"), false), (Some("rev"), true), (Some("iso"), false), (Some(""), false)]
    {
        assert_eq!(is_reviewer(sid, &rv), want, "{sid:?}");
    }
    for st in [None, Some(json!(null)), Some(json!([])), Some(json!("x"))] {
        assert!(reviewer_ids(st.as_ref()).is_empty());
    }
}

/// py: ReviewerRefused, LockTimeout, OwnedElsewhere, OwnedElsewhere.__init__, ReservedName, ReservedName.__init__
#[test]
fn error_messages() {
    assert_eq!(ReviewerRefused("m".into()).to_string(), "m");
    assert_eq!(LockTimeout("could not lock x".into()).to_string(), "could not lock x");
    assert_eq!(OwnedElsewhere::new("p", "o").to_string(), "project 'p' is owned by steward 'o'");
    assert_eq!(OwnedElsewhere::new("a'b", "c\"\n").to_string(), "project \"a'b\" is owned by steward 'c\"\\n'");
    assert_eq!(ReservedName::new("p", "o").to_string(), "project name 'p' is reserved (o)");
    assert_eq!(ReservedName::new("a'b", "c\"\n").to_string(), "project name \"a'b\" is reserved (c\"\n)");
}

/// py: reserved_reason
#[test]
fn reserved_reason_edges() {
    let index: OwnershipIndex = serde_json::from_value(
        json!({"services": {"vk": {}, "ex": {"match": "exact"}}, "brains": {"degnekci_iso": "iso"}}),
    )
    .expect("indeks");
    let names = ["", "deg", "degnekci_x", "degnekci_iso2", "vkx", "ex", "exx", "other"];
    let got: Vec<String> = names.iter().map(|n| reserved_reason(n, &index)).collect();
    let b = "brain name degnekci";
    assert_eq!(got, [b, b, b, b, "service vk", "service ex", "", ""]);
}

/// py: steward_badge
#[test]
fn badge_edges() {
    let index: OwnershipIndex = serde_json::from_value(
        json!({"owners": {"ncs": "iso", "a": "x", "a20261001": "y", "e": ""}, "brains": {"b1": "", "b2": "k"}}),
    )
    .expect("indeks");
    let got = |n: &str| steward_badge(n, &index).map(|b| (b.role, b.sid, b.title));
    let t = |r: &str, s: &str, title: &str| Some((r.to_string(), s.to_string(), title.to_string()));
    assert_eq!(got("b1"), None);
    assert_eq!(got("b2"), t("brain", "k", "değnekçi · k · beyin"));
    assert_eq!(got("degnekci"), t("brain", "default", "değnekçi · default · beyin"));
    assert_eq!(got("degnekci_"), None);
    assert_eq!(got("degnekci_q"), t("brain", "q", "değnekçi · q · beyin"));
    assert_eq!(got("degnekcix"), None);
    assert_eq!(got("ncs"), t("project", "iso", "ncs (değnekçi: iso)"));
    assert_eq!(got("ncs20261019_1"), t("project", "iso", "ncs20261019_1 (değnekçi: iso)"));
    assert_eq!(got("ncsx"), None);
    assert_eq!(got("a20261001"), t("project", "y", "a20261001 (değnekçi: y)"));
    assert_eq!(got("a20261001_2"), t("project", "y", "a20261001_2 (değnekçi: y)"));
    assert_eq!(got("e"), None);
}

/// py: build_ownership_index
#[test]
fn ownership_index_edges_keep_order() {
    let names: IndexMap<String, Option<Vec<String>>> =
        serde_json::from_value(json!({"z": ["p", "q", "p"], "a": ["q", "r", "Bad Name"], "n": null})).expect("adlar");
    let brains = serde_json::from_value(json!({"a": "", "w": "wbrain"})).expect("beyin");
    let services = serde_json::from_value(json!({"ok": 5, "Bad": {}, "s2": {"match": "exact"}})).expect("servis");
    let hosts = serde_json::from_value(json!({"z": {"p": " h1 "}, "a": {"r": "local", "q": "h"}})).expect("host");
    let got = build_ownership_index(&names, Some(&brains), Some(&services), Some(&hosts));
    assert_eq!(
        serde_json::to_string(&got).expect("json"),
        r#"{"owners":{"r":"a","Bad Name":"a","p":"z"},"conflicts":{"q":["a","z"]},"brains":{"degnekci_a":"a","degnekci_n":"n","wbrain":"w","degnekci_z":"z"},"services":{"ok":{},"s2":{"match":"exact"}},"hosts":{"p":"h1"}}"#
    );
}

/// py: _from_dict
#[test]
fn from_dict_drops_unknown_and_requires() {
    let obj = |v: Value| v.as_object().cloned().expect("nesne");
    let p: Project = from_dict(&obj(json!({"name": "a", "x": 1, "priority": 2}))).expect("proje");
    assert_eq!(p, Project { name: "a".into(), priority: 2, ..Default::default() });
    assert_eq!(from_dict::<Project>(&obj(json!({}))), Err(FromDictError::Missing("name")));
    assert_eq!(from_dict::<Idea>(&obj(json!({"id": "i", "text": "t"}))), Err(FromDictError::Missing("created_at")));
    assert_eq!(from_dict::<Question>(&obj(json!({"id": "q"}))), Err(FromDictError::Missing("project")));
    assert!(matches!(
        from_dict::<Project>(&obj(json!({"name": "a", "priority": "x"}))),
        Err(FromDictError::BadType(_))
    ));
}
