//! Python testlerinin doğrudan sınadığı ÖZEL yardımcılar (`_num`, `_run_seconds`, `_fence_step`, `_canon_rank`) parite
//! kancasında sarılmaz; beklenen değerler o Python testlerinden alınır ve Rust'ın açık yüzeyi üzerinden sınanır.
//! Eşleme tablosu: `docs/rs-rev.md`.
use cops_review_core::{parse, py, store, Finding, ReviewPaths, ReviewStore, ReviewTarget};
use cops_state::{Backend, Json, Map, StateDir, StateDocs};
use std::sync::Arc;

fn obj(text: &str) -> Map {
    Json::parse(text).unwrap().as_object().unwrap().clone()
}

/// `test_review.TestPathsAndStores.test_planner_survives_corrupt_history_numbers`
#[test]
fn num_tolerates_corrupt_values() {
    assert_eq!(py::num(Some(&Json::Str("abc".into()))), 0.0);
    assert_eq!(py::num(Some(&Json::Null)), 0.0);
    assert_eq!(py::num(None), 0.0);
    assert_eq!(py::num(Some(&Json::Str("12.5".into()))), 12.5);
}

/// `test_review_duration_summary.DurationTest.test_run_seconds`
#[test]
fn run_seconds_cases() {
    assert_eq!(store::run_seconds(&obj(r#"{"started_at": 100.0, "finished_at": 142.04}"#)), Some(42.0));
    assert_eq!(store::run_seconds(&obj(r#"{"finished_at": 5.0}"#)), None);
    assert_eq!(store::run_seconds(&obj(r#"{"started_at": 10.0, "finished_at": 5.0}"#)), None);
    assert_eq!(store::run_seconds(&obj(r#"{"started_at": "x", "finished_at": 5.0}"#)), None);
}

fn refs(md: &str) -> Vec<String> {
    parse::parse_findings(md).into_iter().map(|f| f.r#ref).collect()
}

/// `test_review_fence_kinds.FenceKindTest.test_fence_step`: aç, başka türle kapanmaz, kendi türüyle kapanır, düz satır.
#[test]
fn fence_closes_only_with_own_kind() {
    let h = "## R-1 | P1 | a:1 | b\n";
    assert!(refs(&format!("```py\n{h}")).is_empty());
    assert!(refs(&format!("```\n~~~\n{h}")).is_empty());
    assert_eq!(refs(&format!("```\n```\n{h}")), ["R-1"]);
    assert!(refs(&format!("~~~\n```\n{h}")).is_empty());
    assert_eq!(refs(&format!("düz\n{h}")), ["R-1"]);
}

/// Aynı anahtarlı kayıtlar `records` (fid, state, created_at JSON'u) iken yeni bulgunun `dup_of`u.
fn canonical_of(records: &[(&str, &str, Option<&str>)]) -> String {
    let d = tempfile::tempdir().unwrap();
    let docs = Arc::new(StateDocs::isolated(StateDir::at(d.path()), Some(Backend::Files), ""));
    let st = ReviewStore::new(docs, ReviewPaths::at(d.path()));
    let mut all = Map::new();
    for (fid, state, at) in records {
        let at = at.map_or(String::new(), |a| format!(r#", "created_at": {a}"#));
        let rec = format!(r#"{{"project": "p", "where": "a:1", "title": "t", "review_file": "old", "state": "{state}"{at}}}"#);
        all.insert((*fid).into(), Json::parse(&rec).unwrap());
    }
    st.save_findings(all).unwrap();
    let new = Finding { r#ref: "R-1".into(), severity: "P3".into(), r#where: "a:2".into(), title: "t".into(), body: String::new() };
    assert!(st.add_findings("p", "new", &[new]).unwrap().is_empty());
    let data = st.load_findings().unwrap();
    data.iter()
        .find_map(|(_, v)| v.get("dup_of").and_then(Json::as_str).map(String::from))
        .unwrap()
}

/// `test_review_canonical.CanonRankTest` (3 test): kademe, kademe içinde en eski, bozuk/eksik zaman damgası 0 sayılır.
/// Her durum iki kayıt sırasıyla da denenir (sonuç sözlük sırasına bağlı değil).
#[test]
fn canonical_record_by_tier_then_age() {
    let check = |a: (&str, &str, Option<&str>), b: (&str, &str, Option<&str>)| {
        assert_eq!(canonical_of(&[a, b]), a.0, "{a:?} < {b:?}");
        assert_eq!(canonical_of(&[b, a]), a.0, "{a:?} < {b:?} (ters sıra)");
    };
    for good in ["verified", "approved", "exported"] {
        check(("g", good, Some("9")), ("n", "new", Some("1")));
    }
    for bad in ["refuted", "rejected"] {
        check(("n", "new", Some("9")), ("b", bad, Some("1")));
    }
    check(("x", "new", Some("1")), ("y", "new", Some("2")));
    check(("x", "verified", Some("1")), ("y", "approved", Some("2")));
    check(("x", "new", Some("\"x\"")), ("y", "new", Some("1")));
    check(("x", "new", None), ("y", "new", Some("1")));
}

/// `test_review_lens.LensPathKeyTest.test_lens_never_in_planner_targets`: hedefin varsayılan merceği boş.
#[test]
fn planner_targets_have_no_lens() {
    assert_eq!(ReviewTarget::new("agy", "m", "m").lens, "");
}

/// `test_review.TestPathsAndStores.test_paths` (review yolları payı; `steward.paths_for`in kalanı bu crate'te yok).
#[test]
fn review_paths_layout_per_identity() {
    let d = std::path::Path::new("/s");
    let p = ReviewPaths::for_sid(d, "reviewer").unwrap();
    let r = d.join("steward/stewards/reviewer");
    assert_eq!(p.reviews, r.join("reviews"));
    assert_eq!(p.review_pool, r.join("review_pool.json"));
    assert_eq!(p.review_history, r.join("review_history.json"));
    assert_eq!(p.findings, r.join("findings.json"));
    assert_eq!(ReviewPaths::for_sid(d, "default").unwrap().findings, d.join("steward/findings.json"));
    for bad in ["", "..", "a/b", "A", "a1"] {
        assert!(ReviewPaths::for_sid(d, bad).is_err(), "{bad:?}");
    }
}
