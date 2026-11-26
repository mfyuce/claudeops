//! `StateDocs::new`un ortamdan okudukları: `CLAUDEOPS_DB_URL` (`dbapi.default_url`) ve `CLAUDEOPS_DIAG_LOG`. Ayrı test
//! ikilisi (tek test): ortam değişkeni başka iş parçacığı yokken değiştirilir.
use cops_state::{Backend, Json, StateDocs, TestEnv};
use std::path::Path;
use std::process::Command;

#[test]
fn db_url_and_diag_log_env() {
    let env = TestEnv::new().unwrap();
    let other = env.root().join("baska.db");
    let diag = env.root().join("baska-diag.log");
    let py = Command::new("python3")
        .args(["-B", "-c", "import sys; sys.path.insert(0, sys.argv[1])\nfrom claudeops import dbapi, store, diaglog\n\
                s = store.Store(sys.argv[2], '')\ns.set_doc('hosts', [3])\nprint(dbapi.default_url()); print(diaglog.diag_log_path()); diaglog.diag_log('py')"])
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../py"))
        .arg(&other)
        .env("CLAUDEOPS_DIR", env.dir().root())
        .env("CLAUDEOPS_EXTENSIONS", "")
        .env("CLAUDEOPS_STORE_BACKEND", "files")
        .env("CLAUDEOPS_DB_URL", "sqlite:///yalniz/yazdirilir.db")
        .env("CLAUDEOPS_DIAG_LOG", &diag)
        .output()
        .unwrap();
    assert!(
        py.status.success(),
        "{}",
        String::from_utf8_lossy(&py.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&py.stdout),
        format!("sqlite:///yalniz/yazdirilir.db\n{}\n", diag.display())
    );
    // SAFETY: bu ikilide tek test var; ortamı başka iş parçacığı okumaz.
    unsafe {
        std::env::remove_var("CLAUDEOPS_STORE_BACKEND");
        std::env::set_var("CLAUDEOPS_DB_URL", format!("sqlite://{}", other.display()));
        std::env::set_var("CLAUDEOPS_DIAG_LOG", &diag);
    }
    let docs = StateDocs::new(env.dir().clone());
    assert_eq!(
        docs.store().unwrap().get_doc("hosts").unwrap(),
        Some(Json::parse("[3]").unwrap()),
        "DB ortamdaki url'den"
    );
    docs.diag_log("rs");
    let log = std::fs::read_to_string(&diag).unwrap();
    assert!(
        log.contains(r#""event": "py""#) && log.contains(r#""event": "rs""#),
        "{log}"
    );
    assert!(!env.dir().join("diag.log").exists());
    // `isolated` iki değişkeni de okumaz
    let iso = StateDocs::isolated(env.dir().clone(), Some(Backend::Files), "");
    assert!(iso.store().is_err(), "durum dizininde DB yok");
    iso.diag_log("iso");
    assert!(std::fs::read_to_string(env.dir().join("diag.log"))
        .unwrap()
        .contains("iso"));
    assert!(!std::fs::read_to_string(&diag).unwrap().contains("iso"));
    // boş değer: varsayılan yol
    unsafe { std::env::set_var("CLAUDEOPS_DIAG_LOG", "") };
    docs.diag_log("bos");
    assert!(std::fs::read_to_string(env.dir().join("diag.log"))
        .unwrap()
        .contains("bos"));
}
