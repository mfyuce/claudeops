//! Çok derin iç içe `settings.json` (Python `py/tests/test_rsprov_settings_depth.py`): değer en çok 512 kapsayıcının
//! içinde olabilir; daha derin belge bozuk sayılır, varsayılanlar döner. Python `settings._too_deep` ile aynı sayım.

use cops_state::settings::Settings;

fn nested(levels: usize, inner: &str) -> String {
    format!("{}{inner}{}", "[".repeat(levels), "]".repeat(levels))
}

fn fleet_sort(doc: &str) -> String {
    Settings::from_text(Some(doc))
        .str_of("fleet_sort")
        .to_string()
}

fn doc(deep: &str) -> String {
    format!(r#"{{"fleet_sort": "cwd", "stewards": {{"x": {deep}}}}}"#)
}

#[test]
fn limit_is_512_enclosing_containers() {
    let default = Settings::from_text(None).str_of("fleet_sort").to_string();
    assert_ne!(default, "cwd");
    assert_eq!(fleet_sort(&doc(&nested(511, ""))), "cwd");
    assert_eq!(fleet_sort(&doc(&nested(511, "1"))), default);
    assert_eq!(fleet_sort(&doc(&nested(512, ""))), default);
    assert_eq!(fleet_sort(&doc(&nested(100_000, ""))), default);
    let unknown = format!(
        r#"{{"fleet_sort": "cwd", "bilinmeyen": {}}}"#,
        nested(600, "")
    );
    assert_eq!(fleet_sort(&unknown), default);
}
