//! Python altın vektörleri (`parity/gen_golden.py` üretir, `tests/golden/`): aynı girdi, aynı çıktı.

use cops_procscan::discovery::fallback_name;
use cops_procscan::mirrors::spec_from_cmdline;
use cops_procscan::needs_ho::{committed_after, handover_done, has_real_user_turn, rfh_marker_in};
use cops_procscan::providers::{AgyState, Cli};
use cops_procscan::session::base_name;
use cops_procscan::transcript::encode_cwd;
use cops_procscan::usage::{fmt_tokens, UsageReader};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

fn dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden")
}

static GOLDEN: LazyLock<Value> = LazyLock::new(|| {
    let raw = std::fs::read_to_string(dir().join("python.json")).expect("altın dosya yok: parity/gen_golden.py");
    serde_json::from_str(&raw).unwrap()
});

fn table(path: &[&str]) -> &'static Vec<Value> {
    let mut v = &*GOLDEN;
    for k in path {
        v = &v[*k];
    }
    v.as_array().unwrap_or_else(|| panic!("{path:?} dizi değil"))
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap()
}

/// BİLİNEN sapmalar (docs/rs-proc.md "Python'dan bilinen sapmalar" 4): serde `NaN`/`Infinity` satırını reddeder,
/// Python kabul eder. claude transkriptlerini Node `JSON.stringify` yazar, bu belirteçleri hiç üretmez.
const KNOWN: &[&str] = &["nan_line.handover_done"];

/// Uyuşmazlıkları tek seferde gösterir; bilinen sapma uyuşmazlık sayılmaz ama KAYBOLURSA test bunu da söyler.
fn check(name: &str, bad: Vec<String>) {
    let (known, bad): (Vec<_>, Vec<_>) = bad.into_iter().partition(|b| KNOWN.iter().any(|k| b.starts_with(k)));
    assert!(bad.is_empty(), "{name}: {} uyuşmazlık:\n{}", bad.len(), bad.join("\n"));
    if name == "transcripts" {
        assert_eq!(known.len(), KNOWN.len(), "bilinen sapma listesi bayat: {known:?}");
    }
}

#[test]
fn rfh_marker() {
    let bad = table(&["rfh"])
        .iter()
        .filter(|c| rfh_marker_in(s(&c[0])) != c[1].as_bool().unwrap())
        .map(|c| format!("{:?} python={}", c[0], c[1]))
        .collect();
    check("rfh", bad);
}

#[test]
fn names_paths_and_token_format() {
    let mut bad = Vec::new();
    for c in table(&["names", "base"]) {
        if base_name(s(&c[0])) != s(&c[1]) {
            bad.push(format!("base {:?} python={:?} rust={:?}", c[0], c[1], base_name(s(&c[0]))));
        }
    }
    for c in table(&["names", "fallback_name"]) {
        let got = fallback_name(s(&c[0]), s(&c[1]), c[2].as_u64().unwrap() as u32);
        if got != s(&c[3]) {
            bad.push(format!("fallback {c:?} rust={got:?}"));
        }
    }
    for c in table(&["names", "encode_cwd"]) {
        if encode_cwd(s(&c[0])) != s(&c[1]) {
            bad.push(format!("encode {c:?} rust={:?}", encode_cwd(s(&c[0]))));
        }
    }
    for c in table(&["names", "fmt_tokens"]) {
        let got = fmt_tokens(c[0].as_u64().unwrap());
        if got != s(&c[1]) {
            bad.push(format!("fmt {c:?} rust={got:?}"));
        }
    }
    check("names", bad);
}

#[test]
fn committed_after_iso_rules() {
    let bad = table(&["committed_after"])
        .iter()
        .filter(|c| committed_after(s(&c[0]), s(&c[1]).trim()) != c[2].as_bool().unwrap())
        .map(|c| format!("{:?} > {:?} python={}", c[0], c[1], c[2]))
        .collect();
    check("committed_after", bad);
}

#[test]
fn provider_detect_and_info() {
    let mut bad = Vec::new();
    for c in table(&["providers", "detect_info"]) {
        let cmd: Vec<String> = c[0].as_array().unwrap().iter().map(|a| s(a).to_owned()).collect();
        let cli = Cli::detect(&cmd);
        let got_cli = cli.map(Cli::as_str);
        let got_info = cli.map(|cli| {
            let i = cli.extract_info(&cmd, "", "", &mut AgyState::default());
            json!({"sid": i.sid, "model": i.model, "permission_mode": i.permission_mode, "effort": i.effort})
        });
        if got_cli != c[1].as_str() || got_info.as_ref().unwrap_or(&Value::Null) != &c[2] {
            bad.push(format!(
                "{:?}\n  python={} {}\n  rust={got_cli:?} {got_info:?}",
                c[0], c[1], c[2]
            ));
        }
    }
    for c in table(&["providers", "mirror_spec"]) {
        let cmd: Vec<String> = c[0].as_array().unwrap().iter().map(|a| s(a).to_owned()).collect();
        let got = spec_from_cmdline(&cmd);
        if got.as_deref() != c[1].as_str() {
            bad.push(format!("spec {:?} python={} rust={got:?}", c[0], c[1]));
        }
    }
    check("providers", bad);
}

#[test]
fn transcripts_needs_ho() {
    let mut bad = Vec::new();
    let cases = GOLDEN["transcripts"].as_object().unwrap();
    for (name, want) in cases {
        let p = dir().join("transcripts").join(format!("{name}.jsonl"));
        // TBD#365: Python artık istisna fırlatmaz; altında `{"error": ...}` kalırsa uyuşmazlık sayılır
        for (fname, got) in [
            ("has_real_user_turn", json!(has_real_user_turn(&p).value)),
            ("handover_done", json!(handover_done(&p).value)),
        ] {
            if got != want[fname] {
                bad.push(format!("{name}.{fname} python={} rust={got}", want[fname]));
            }
        }
    }
    check("transcripts", bad);
}

#[test]
fn usage_totals_two_calls() {
    let mut bad = Vec::new();
    for (name, want) in GOLDEN["usage"].as_object().unwrap() {
        let main = dir().join("usage").join(name).join("s.jsonl");
        let mut r = UsageReader::default();
        let got = [json!(r.usage_for_path(&main)), json!(r.usage_for_path(&main))];
        for (i, g) in got.iter().enumerate() {
            if g != &want[i] {
                bad.push(format!("{name} çağrı {}: python={} rust={g}", i + 1, want[i]));
            }
        }
    }
    check("usage", bad);
}
