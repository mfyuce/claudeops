use cops_local::{questions, valid_sid};
use rusqlite::Connection;

fn db() -> (tempfile::TempDir, std::path::PathBuf) {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("claudeops.db");
    let c = Connection::open(&p).unwrap();
    c.execute("CREATE TABLE docs (name TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL)", []).unwrap();
    let q = r#"[{"id":"q1","project":"p","text":"a?","status":"open","created_at":2000.0,"options":["x"],"extra":"yok"},
{"id":"q2","project":"p","text":"b?","status":"answered","created_at":100.0,"answered_at":150.0,"answer":"evet","answered_by":"owner_phone"},
{"id":"q3","project":"p","text":"c?","status":"answered","created_at":10.0,"answered_at":20.0,"answer":"hayır","answered_by":"cops"}]"#;
    c.execute(
        "INSERT INTO docs VALUES ('steward/questions', ?1, 1, 0)",
        [q],
    )
    .unwrap();
    c.execute(
        "INSERT INTO docs VALUES ('steward/stewards/iso/questions', ?1, 1, 0)",
        [r#"[{"id":"i1","status":"open","created_at":5}]"#],
    )
    .unwrap();
    (d, p)
}

fn ids(v: &serde_json::Value) -> Vec<String> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|r| r["id"].as_str().unwrap().to_string())
        .collect()
}

#[test]
fn default_open_only_all_and_since() {
    let (_d, p) = db();
    assert_eq!(ids(&questions(&p, "").unwrap()), ["q1"]);
    assert_eq!(ids(&questions(&p, "all=1").unwrap()), ["q1", "q2", "q3"]);
    assert_eq!(
        ids(&questions(&p, "since=120").unwrap()),
        ["q1", "q2"],
        "answered_at da sayılır, eski q3 elenir"
    );
    let r = questions(&p, "all=1").unwrap();
    for k in [
        "id",
        "sid",
        "project",
        "text",
        "options",
        "routine",
        "status",
        "created_at",
        "answered_at",
        "answer",
        "answered_by",
    ] {
        assert!(r[0].get(k).is_some(), "{k}");
    }
    assert!(r[0].get("extra").is_none(), "yalnız sözleşme alanları");
    assert_eq!(r[1]["answered_by"], "owner_phone");
    assert_eq!(r[0]["sid"], "default");
}

#[test]
fn other_sid_missing_doc_and_bad_input() {
    let (_d, p) = db();
    assert_eq!(ids(&questions(&p, "sid=iso").unwrap()), ["i1"]);
    assert_eq!(questions(&p, "sid=ucli").unwrap(), serde_json::json!([]));
    assert_eq!(questions(&p, "sid=../x").unwrap_err().0, 400);
    assert_eq!(questions(&p, "since=abc").unwrap_err().0, 400);
    assert_eq!(
        questions(std::path::Path::new("/nonexistent/x.db"), "")
            .unwrap_err()
            .0,
        503
    );
    assert!(
        valid_sid("default")
            && valid_sid("iso")
            && !valid_sid("a")
            && !valid_sid("Iso")
            && !valid_sid("iso1")
    );
}
