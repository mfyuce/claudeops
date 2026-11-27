//! Yerel saat dilimi eşliği (`fixtures/tz.json`, üretici `parity/tz_cases.py`). `TZ` süreç geneli olduğu için her dilim
//! bu ikilinin ayrı bir alt sürecinde koşar.

use std::process::Command;

use cops_steward_core::pyc;
use serde_json::Value;

const ZONE_VAR: &str = "COPS_TZ_PARITY_ZONE";

#[test]
fn local_time_matches_python_in_dst_zones() {
    let all: Vec<Value> = serde_json::from_str(include_str!("../fixtures/tz.json")).expect("tz.json");
    let Ok(zone) = std::env::var(ZONE_VAR) else {
        assert!(all.len() >= 5, "{} dilim", all.len());
        for case in &all {
            let zone = case["zone"].as_str().expect("zone");
            assert!(std::path::Path::new("/usr/share/zoneinfo").join(zone).is_file(), "tzdata yok: {zone}");
            let out = Command::new(std::env::current_exe().expect("exe"))
                .args(["--exact", "local_time_matches_python_in_dst_zones", "--nocapture"])
                .env(ZONE_VAR, zone)
                .env("TZ", zone)
                .output()
                .expect("alt süreç");
            let text = String::from_utf8_lossy(&out.stdout);
            assert!(out.status.success() && text.contains("1 passed"), "{zone}:\n{text}");
        }
        return;
    };
    let case = all.iter().find(|c| c["zone"] == zone.as_str()).expect("dilim");
    let mut diffs = Vec::new();
    for row in case["localtime"].as_array().expect("localtime") {
        let (at, want) = (row[0].as_f64().expect("ts"), row[1].as_str().expect("str"));
        let got = pyc::localtime(at).format("%Y-%m-%dT%H:%M:%S").to_string();
        if got != want {
            diffs.push(format!("localtime({at}) = {got}, Python {want}"));
        }
    }
    for row in case["mktime"].as_array().expect("mktime") {
        let (wall, want) = (row[0].as_str().expect("str"), row[1].as_f64().expect("ts"));
        let got = pyc::mktime_iso_seconds(wall);
        if got != Some(want) {
            diffs.push(format!("mktime({wall}) = {got:?}, Python {want}"));
        }
    }
    assert!(diffs.is_empty(), "{zone}: {} fark\n{}", diffs.len(), diffs[..diffs.len().min(15)].join("\n"));
}
