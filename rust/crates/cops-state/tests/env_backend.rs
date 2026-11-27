//! `StateDocs::backend` ortamı HER çağrıda okur (Python `statedocs.backend()` gibi). Ayrı test ikilisi: ortam değişkeni
//! tek testte, başka iş parçacığı yokken değiştirilir.
use cops_state::{Backend, StateDocs, TestEnv};

#[test]
fn env_backend_read_per_call() {
    let env = TestEnv::new().unwrap();
    let docs = StateDocs::new(env.dir().clone());
    // SAFETY: bu ikilide tek test var; ortamı başka iş parçacığı okumaz.
    unsafe { std::env::set_var("CLAUDEOPS_STORE_BACKEND", " DB ") };
    assert_eq!(docs.backend(), Backend::Db);
    unsafe { std::env::set_var("CLAUDEOPS_STORE_BACKEND", "dual") };
    assert_eq!(
        docs.backend(),
        Backend::Dual,
        "aynı nesne yeni değeri görür"
    );
    unsafe { std::env::set_var("CLAUDEOPS_STORE_BACKEND", "\u{1c}files\u{1c}") };
    assert_eq!(
        docs.backend(),
        Backend::Files,
        "Python strip() U+001C'yi de atar"
    );
    unsafe { std::env::set_var("CLAUDEOPS_STORE_BACKEND", "gecersiz") };
    std::fs::write(env.dir().settings_json(), r#"{"store_backend": "db"}"#).unwrap();
    assert_eq!(docs.backend(), Backend::Db, "geçersiz ortam: settings.json");
    unsafe { std::env::remove_var("CLAUDEOPS_STORE_BACKEND") };
    let iso = StateDocs::isolated(env.dir().clone(), Some(Backend::Files), "");
    unsafe { std::env::set_var("CLAUDEOPS_STORE_BACKEND", "db") };
    assert_eq!(iso.backend(), Backend::Files, "isolated ortamı okumaz");
}
