//! Belge deposu paritesi: gerçek Python (`statedocs` + `agy_provider`) ile gerçek [`StateDocStore`] (rs/state `StateDocs`)
//! aynı başlangıç durumunda aynı işlemleri koşar; dönüşler, dosyalar, DB `docs` satırları (gövde + sürüm), `diag.log`
//! olayları ve DB `diag` akışı karşılaştırılır. Kipler: `files`, `dual`, `db`. Her taraf kendi GEÇİCİ durum dizininde.

#[path = "g8/support.rs"]
mod support;

use cops_providers::agy_resume::{remember_agy_sid, AGY_SIDS_UNREADABLE};
use cops_providers::pyjson::Py;
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::docs::{DocAgySidStore, DocStore, StateDocStore};
use cops_providers::real::modelio::RealModelIo;
use cops_providers::real::Env;
use cops_providers::{AgySidStore, ModelIo, Paths};
use cops_state::{Backend, StateDir, StateDocs};
use serde_json::{json, Value};
use std::fs;
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;
use support::{mkfifo, spawn_guard, Tmp};

const MODES: [(&str, Backend); 3] = [
    ("files", Backend::Files),
    ("dual", Backend::Dual),
    ("db", Backend::Db),
];

fn python(t: &Tmp, mode: &str, step: &str, case: &Value) -> Value {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let root = case["root"].as_str().unwrap();
    let _g = spawn_guard();
    let out = Command::new("/usr/bin/python3")
        .args(["-s", "-B", "-W", "ignore"])
        .arg(format!("{manifest}/tests/parity/docs_driver.py"))
        .args([step, &case.to_string()])
        .env_clear()
        .env("HOME", t.path("home"))
        .env("CLAUDEOPS_DIR", root)
        .env("CLAUDEOPS_EXTENSIONS", "0")
        .env("CLAUDEOPS_STORE_BACKEND", mode)
        .env("LANG", "C.UTF-8")
        .env("PYTHONPATH", format!("{manifest}/../../../py"))
        .current_dir(&t.root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "python {step}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

fn docs(paths: &Paths, backend: Backend) -> (Arc<StateDocStore>, DiagLog) {
    let dir = StateDir::at(&paths.claudeops_dir);
    let store = Arc::new(StateDocStore::new(Arc::new(StateDocs::isolated(
        dir,
        Some(backend),
        "",
    ))));
    let log = format!("{}/diag.log", paths.claudeops_dir);
    let diag = DiagLog::new(log.clone()).with_mirror(store.diag_mirror(log));
    (store, diag)
}

fn rust_ops(paths: &Paths, backend: Backend, ops: &[Value]) -> Vec<Value> {
    let (store, diag) = docs(paths, backend);
    let agy = DocAgySidStore::new(paths, store.clone());
    let io = RealModelIo::new(paths, Env::fixed(Vec::<(String, String)>::new()), store);
    let object = |v: Option<Py>| v.filter(Py::is_object).map_or(json!({}), |d| d.to_value());
    ops.iter()
        .map(|op| match op[0].as_str().unwrap() {
            "load" => object(agy.load()),
            "claude" => io.claude_models_doc().unwrap_or_else(|| json!({})),
            "remember" => {
                let (name, sid) = (op[1].as_str().unwrap(), op[2].as_str().unwrap());
                match remember_agy_sid(&agy, name, sid, false) {
                    Ok(_) => {}
                    // çağıran (`ProcScan`, Python `_remember_agy_sid`) günlüğe yazar
                    Err(e) if e == AGY_SIDS_UNREADABLE => {
                        diag.log("agy_sids_unreadable", &[("name", json!(name))]);
                    }
                    Err(e) => return json!({ "error": e }),
                }
                Value::Null
            }
            _ => {
                let path = match op[1].as_str().unwrap() {
                    "agy_sids" => paths.agy_sids_json(),
                    _ => paths.claude_models_json(),
                };
                fs::write(path, op[2].as_str().unwrap()).unwrap();
                Value::Null
            }
        })
        .collect()
}

fn scenarios() -> Vec<(&'static str, Value)> {
    let both =
        |file: &str, row: &str| json!({"files": {"agy_sids": file}, "rows": {"agy_sids": row}});
    let ops = json!([
        ["load"],
        ["remember", "yeni", "s9"],
        ["load"],
        ["remember", "yeni", "s9"],
        ["remember", "eski", "s2"],
        ["load"]
    ]);
    let mut all = vec![
        ("bos", json!({})),
        (
            "yalniz-dosya",
            json!({"files": {"agy_sids": r#"{"eski": "d1"}"#}}),
        ),
        (
            "yalniz-db",
            json!({"rows": {"agy_sids": r#"{"eski": "v1"}"#}}),
        ),
        (
            "esit",
            both(r#"{"eski": "a", "ş": "ğ"}"#, r#"{"eski": "a", "ş": "ğ"}"#),
        ),
        (
            "farkli",
            both(r#"{"eski": "dosya"}"#, r#"{"eski": "db", "fazla": "x"}"#),
        ),
        ("bozuk-dosya-db-var", both("{yarim", r#"{"eski": "db"}"#)),
        (
            "bozuk-dosya-db-yok",
            json!({"files": {"agy_sids": "{yarim"}}),
        ),
        ("dosya-liste", json!({"files": {"agy_sids": "[1]"}})),
        ("db-liste", json!({"rows": {"agy_sids": "[1]"}})),
        ("dizin", json!({"files": {"agy_sids": null}})),
        (
            "dizin-db-var",
            json!({"files": {"agy_sids": null}, "rows": {"agy_sids": r#"{"eski": "v"}"#}}),
        ),
        (
            "vekil",
            json!({"files": {"agy_sids": "{\"eski\": \"\\ud800\"}"}}),
        ),
        (
            "buyuk-sayi",
            json!({"files": {"agy_sids": r#"{"n": 123456789012345678901234567890, "f": 1.5, "b": true, "x": null}"#}}),
        ),
        (
            "db-dosyasi-yok",
            json!({"db": false, "files": {"agy_sids": r#"{"eski": "d1"}"#}}),
        ),
    ];
    for (_, c) in &mut all {
        c["ops"] = ops.clone();
    }
    all.push((
        "elle-duzenleme",
        json!({
            "files": {"agy_sids": r#"{"eski": "a"}"#},
            "ops": [
                ["load"],
                ["write", "agy_sids", r#"{"eski": "elle-degisti-uzun"}"#],
                ["load"],
                ["remember", "yeni", "s"],
                ["load"]
            ]
        }),
    ));
    for (id, setup) in [
        ("claude-yok", json!({})),
        (
            "claude-dosya",
            json!({"files": {"claude_models": r#"{"models": {"m1": "enabled"}}"#}}),
        ),
        (
            "claude-db",
            json!({"rows": {"claude_models": r#"{"models": {"m2": "enabled"}}"#}}),
        ),
        (
            "claude-farkli",
            json!({"files": {"claude_models": r#"{"models": {"d": "enabled"}}"#},
                   "rows": {"claude_models": r#"{"models": {"v": "enabled"}}"#}}),
        ),
        (
            "claude-bozuk",
            json!({"files": {"claude_models": "x"}, "rows": {"claude_models": r#"{"models": {}}"#}}),
        ),
    ] {
        let mut c = setup;
        c["ops"] = json!([["claude"], ["claude"]]);
        all.push((id, c));
    }
    all
}

/// Python istisnası ile Rust hata dönüşü aynı sonuçtur (ileti dile özgü).
fn failures_alike(mut v: Value) -> Value {
    if let Some(returns) = v["returns"].as_array_mut() {
        for r in returns {
            if r.get("exception").is_some() || r.get("error").is_some() {
                *r = json!("hata");
            }
        }
    }
    v
}

/// rs/state'ten miras bilinen fark: `dual` kipte DB'ye aktarılamayan (eşlenmemiş vekil) belge için Python, başarısız
/// aktarımdan ÖNCE "statedocs import" günlüğünü yazar; Rust yazmaz (aktarım olmadı).
fn without_import_notes(mut v: Value) -> Value {
    for key in ["diag", "mirror"] {
        let rows = v["state"][key].as_array_mut().unwrap();
        let before = rows.len();
        rows.retain(|r| !r[0].as_str().unwrap().starts_with("statedocs import"));
        assert!(rows.len() <= before);
    }
    v
}

/// rs/state'ten miras bilinen farklar: `db` kipinde DB dosyası yoksa Python onu yaratıp yazar, Rust hiçbir yere yazmaz;
/// `dual` kipte Python DB'yi yaratır, Rust yaratmaz (dosya iki tarafta aynı).
fn expect_missing_db(mode: &str, py: &Value, rs: &Value) {
    assert_eq!(py["state"]["has_db"], json!(mode != "files"), "{mode}");
    assert_eq!(rs["state"]["has_db"], json!(false), "{mode}");
    let file = |v: &Value| -> Value {
        serde_json::from_str(v["state"]["files"]["agy_sids"].as_str().unwrap()).unwrap()
    };
    assert_eq!(file(py), json!({"eski": "s2", "yeni": "s9"}));
    if mode == "db" {
        assert_eq!(file(rs), json!({"eski": "d1"}), "DB'siz db kipinde yazıldı");
        assert!(rs["returns"][1]["error"]
            .as_str()
            .unwrap()
            .contains("DB yok"));
    } else {
        assert_eq!(file(rs), file(py));
        assert_eq!(rs["returns"], py["returns"]);
    }
}

#[test]
fn state_docs_match_python_in_every_backend() {
    let mut compared = 0;
    for (id, scenario) in scenarios() {
        for (mode, backend) in MODES {
            let t = Tmp::new();
            let side = |name: &str| {
                let root = t.path(name);
                fs::create_dir(&root).unwrap();
                let mut case = scenario.clone();
                case["root"] = json!(root);
                case
            };
            let py = python(&t, mode, "run", &side("py"));
            let rs_case = side("rs");
            python(&t, mode, "seed", &rs_case);
            let paths = Paths {
                claudeops_dir: t.path("rs"),
                home: t.path("home"),
                repo_dir: t.path("repo"),
            };
            let returns = rust_ops(&paths, backend, rs_case["ops"].as_array().unwrap());
            let state = python(&t, mode, "dump", &rs_case);
            let rs = json!({"returns": returns, "state": state});
            if id == "db-dosyasi-yok" {
                expect_missing_db(mode, &py, &rs);
            } else if id == "vekil" && mode == "dual" {
                assert_ne!(rs["state"]["diag"], py["state"]["diag"]);
                assert_eq!(without_import_notes(rs), without_import_notes(py));
            } else {
                assert_eq!(failures_alike(rs), failures_alike(py), "{id} [{mode}]");
            }
            compared += 1;
        }
    }
    assert_eq!(compared, 20 * MODES.len());
}

/// Python dosyayı açıp asılır; Rust normal dosya olmayanı hiçbir kipte açmaz ve yazmaz.
#[test]
fn a_fifo_document_is_never_opened_or_replaced() {
    for (_, backend) in MODES {
        let t = Tmp::new();
        let paths = t.paths();
        mkfifo(&paths.agy_sids_json());
        let (store, _) = docs(&paths, backend);
        let agy =
            DocAgySidStore::new(&paths, store.clone()).with_lock_timeout(Duration::from_secs(1));
        assert!(agy.load().is_none());
        assert_eq!(
            remember_agy_sid(&agy, "a", "1", false),
            Err(AGY_SIDS_UNREADABLE.to_string())
        );
        assert!(store
            .read("claude_models", &paths.agy_sids_json())
            .is_none());
        let kind = fs::symlink_metadata(paths.agy_sids_json())
            .unwrap()
            .file_type();
        assert!(std::os::unix::fs::FileTypeExt::is_fifo(&kind));
    }
}

/// Kip `settings.json` `store_backend`den okunur (ortam zorlaması olmadan), `db`de bayat aynadan karar verilmez.
#[test]
fn the_backend_comes_from_settings_and_db_ignores_the_stale_mirror() {
    let t = Tmp::new();
    let case = json!({
        "root": t.path("state"),
        "files": {"agy_sids": r#"{"a": "bayat"}"#},
        "rows": {"agy_sids": r#"{"a": "db"}"#},
        "ops": []
    });
    python(&t, "db", "seed", &case);
    t.write("state/settings.json", r#"{"store_backend": " DB "}"#, 0o600);
    let docs = support::docs_in(&t.paths(), None);
    let got = docs.read("agy_sids", &t.paths().agy_sids_json()).unwrap();
    assert_eq!(got.get("a").and_then(Py::as_str), Some("db"));
}
