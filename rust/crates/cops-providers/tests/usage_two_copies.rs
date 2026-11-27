//! Maliyet toplayıcısının iki Rust kopyası (`cops_review_core::report::usage_cost_usd` ve `real::ledger::scan_usage`)
//! aynı günlükten AYNI toplamı vermeli: elle yazılmış sınır satırları ve rastgele dosyalar.

use cops_providers::real::ledger::scan_usage;
use cops_review_core::report::{anthropic_spent_usd, usage_cost_usd, UNCOUNTABLE_SPENT_USD};
use std::fs;

const MODELS: [&str; 4] = ["", "claude-haiku-5-5", "claude-sonnet-5-5", "bilinmeyen"];

fn totals(path: &str, model: &str, since: f64, mult: f64) -> (f64, f64) {
    (
        scan_usage(path, model, since, mult).total,
        usage_cost_usd(path, model, since, mult).unwrap(),
    )
}

/// Ayrışan (vaka, model, since) listesi.
fn differences(cases: &[(String, Vec<u8>)]) -> Vec<String> {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("a.jsonl").to_string_lossy().into_owned();
    let mut out = Vec::new();
    for (id, data) in cases {
        fs::write(&path, data).unwrap();
        for model in MODELS {
            for (since, mult) in [(0.0, 1.0), (100.0, 1.6), (-1.0, 1.0)] {
                let (ledger, report) = totals(&path, model, since, mult);
                if ledger.to_bits() != report.to_bits() {
                    out.push(format!(
                        "{id} model={model:?} since={since}: defter {ledger} review {report}"
                    ));
                }
            }
        }
    }
    out
}

const USAGE: &str = r#""usage":{"input_tokens":1000,"output_tokens":500}"#;

fn edge_lines() -> Vec<(String, Vec<u8>)> {
    let mut v: Vec<(String, Vec<u8>)> = Vec::new();
    let mut add =
        |id: &str, line: String| v.push((id.to_string(), format!("{line}\n").into_bytes()));
    let rec = |extra: &str| format!("{{{extra}{USAGE}}}");
    add("duz", rec(""));
    for t in [
        "5",
        "500",
        "0",
        "-1",
        "1e400",
        "NaN",
        "Infinity",
        "-Infinity",
        "true",
        "false",
        "null",
        r#""500""#,
        r#"" 500 ""#,
        r#""nan""#,
        r#""inf""#,
        r#""1_000""#,
        r#""bozuk""#,
        r#""""#,
        "[500]",
        "{}",
        "123456789012345678901234567890",
        r#""٥٠٠""#,
    ] {
        add(&format!("t={t}"), rec(&format!("\"t\":{t},")));
    }
    for depth in [
        10, 100, 127, 128, 200, 500, 510, 511, 512, 513, 600, 990, 1100, 5000,
    ] {
        for inner in ["", "1"] {
            add(
                &format!("derin-{depth}-{inner}"),
                rec(&format!(
                    "\"d\":{}{inner}{},",
                    "[".repeat(depth),
                    "]".repeat(depth)
                )),
            );
        }
    }
    add("derin-yarim", "[".repeat(100_000));
    let many = "[{".repeat(600);
    add("ayrac-dizede", rec(&format!("\"a\":\"x\\\"{many}\",")));
    add("ayrac-yarim-dizede", format!("{{\"a\":\"{many}"));
    add(
        "ayrac-sig",
        rec(&format!("\"a\":[{}1],", "[],".repeat(600))),
    );
    for n in [
        "0",
        "-1",
        "1.5",
        "true",
        "null",
        r#""7""#,
        "NaN",
        "Infinity",
        "1e15",
        "1.0000001e15",
        "1e400",
        "123456789012345678901234567890",
        "[1]",
        "{}",
    ] {
        for key in [
            "input_tokens",
            "prompt_tokens",
            "output_tokens",
            "completion_tokens",
            "cached_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
            "diger",
        ] {
            add(
                &format!("{key}={n}"),
                format!(
                    r#"{{"usage":{{"input_tokens":200000,"prompt_tokens":150000,"output_tokens":9,"{key}":{n}}}}}"#
                ),
            );
        }
    }
    add(
        "yinelenen-anahtar",
        format!(r#"{{"usage":{{"input_tokens":1}},{USAGE}}}"#),
    );
    add(
        "yinelenen-sayac",
        r#"{"usage":{"input_tokens":1,"input_tokens":9000}}"#.into(),
    );
    add("vekil", rec(r#""a":"\ud800","#));
    add(
        "vekil-model",
        format!("{{\"event\":\"task_start\",\"model\":\"claude-haiku-5-5\\ud800\"}}\n{{{USAGE}}}"),
    );
    for m in [
        r#""claude-haiku-5-5""#,
        "5",
        "true",
        r#"["haiku"]"#,
        r#"{"haiku":1}"#,
        r#""""#,
        "null",
        "NaN",
        "1.5",
    ] {
        add(
            &format!("task_start-{m}"),
            format!("{{\"event\":\"task_start\",\"model\":{m},{USAGE}}}\n{{{USAGE}}}"),
        );
    }
    add("task_end", rec(r#""event":"task_end","#));
    add("bom", format!("\u{feff}{{{USAGE}}}"));
    add("cr-sonu", format!("{{{USAGE}}}\r"));
    add("cr-ayrac", format!("{{{USAGE}}}\r{{{USAGE}}}"));
    add("iki-belge", format!("{{{USAGE}}}{{{USAGE}}}"));
    for pad in [" ", "\t", "\u{b}", "\u{c}", "\u{a0}", "\u{1c}"] {
        add(&format!("bosluk-{pad:?}"), format!("{pad}{{{USAGE}}}{pad}"));
    }
    add("nul", format!("{{{USAGE}}}\u{0}"));
    add("denetim-metinde", rec("\"a\":\"\u{1}\","));
    add("sondaki-virgul", format!("{{{USAGE},}}"));
    v.push((
        "utf8-bozuk".into(),
        [b"\xff\n".as_slice(), format!("{{{USAGE}}}\n").as_bytes()].concat(),
    ));
    v.push((
        "yarim".into(),
        format!("{{{USAGE}}}\n{{\"usage\":{{\"inp").into_bytes(),
    ));
    v.push(("satir-sonsuz".into(), format!("{{{USAGE}}}").into_bytes()));
    v.push(("bos".into(), Vec::new()));
    v
}

fn random_files(count: usize) -> Vec<(String, Vec<u8>)> {
    let mut state = 0x2545_f491_4f6c_dd1d_u64;
    let mut below = move |n: usize| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state % n as u64) as usize
    };
    let keys = [
        "input_tokens",
        "prompt_tokens",
        "output_tokens",
        "completion_tokens",
        "cached_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
    ];
    let values = [
        "0", "1", "99999", "100000", "100001", "-3", "2.5", "true", "null", r#""4""#, "NaN",
        "1e16", "1e400",
    ];
    let stamps = [
        "0", "50", "100", "101", r#""101""#, r#""x""#, "null", "NaN", "[1]",
    ];
    (0..count)
        .map(|i| {
            let mut data = String::new();
            for _ in 0..1 + below(8) {
                let mut fields = Vec::new();
                match below(6) {
                    0 => fields
                        .push(r#""event":"task_start","model":"claude-haiku-5-5""#.to_string()),
                    1 => fields
                        .push(r#""event":"task_start","model":"claude-fable-5-1""#.to_string()),
                    2 => fields.push(r#""event":"task_end""#.to_string()),
                    _ => {}
                }
                if below(3) > 0 {
                    fields.push(format!("\"t\":{}", stamps[below(stamps.len())]));
                }
                if below(8) > 0 {
                    let u: Vec<String> = (0..below(6))
                        .map(|_| {
                            format!(
                                "\"{}\":{}",
                                keys[below(keys.len())],
                                values[below(values.len())]
                            )
                        })
                        .collect();
                    fields.push(format!("\"usage\":{{{}}}", u.join(",")));
                }
                let mut line = format!("{{{}}}", fields.join(","));
                if below(10) == 0 {
                    line.truncate(below(line.len() + 1));
                }
                data.push_str(&line);
                data.push('\n');
            }
            (format!("rastgele-{i}"), data.into_bytes())
        })
        .collect()
}

/// Derinlik sınırında üç yol aynı karara varır: kayıt nesnesiyle birlikte 512 kat sayılır; daha derini toplama girmez,
/// defterde `problem` (açık tavan kapanır), review bütçe kapısında "sayılamadı" (Python `test_rsprov_cost_depth`).
#[test]
fn both_copies_draw_the_depth_limit_at_the_same_line() {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("p/anthropic/claude-sonnet-5-5");
    fs::create_dir_all(&dir).unwrap();
    let file = dir.join("a.usage.jsonl");
    let path = file.to_string_lossy().into_owned();
    let reviews = root.path().to_string_lossy().into_owned();
    // `levels`: kayıt nesnesi dahil iç içe kat
    for (levels, inner) in [(512, ""), (512, "1"), (513, ""), (513, "1"), (5000, "")] {
        let (open, close) = ("[".repeat(levels - 1), "]".repeat(levels - 1));
        fs::write(&file, format!("{{{USAGE},\"d\":{open}{inner}{close}}}\n")).unwrap();
        let ledger = scan_usage(&path, "", 0.0, 1.0);
        let report = usage_cost_usd(&path, "", 0.0, 1.0).unwrap();
        let spent = anthropic_spent_usd(&reviews).unwrap();
        assert_eq!(ledger.total.to_bits(), report.to_bits(), "{levels} {inner}");
        if levels <= 512 {
            assert!(report > 0.0, "{levels} {inner}");
            assert_eq!(ledger.problem, None, "{levels} {inner}");
            assert!(spent > 0.0 && spent < 1.0, "{levels} {inner}: {spent}");
        } else {
            assert_eq!(
                (report, ledger.problem),
                (0.0, Some("çok derin satır")),
                "{levels} {inner}"
            );
            assert_eq!(spent, UNCOUNTABLE_SPENT_USD, "{levels} {inner}");
        }
    }
}

#[test]
fn edge_lines_cost_the_same_in_both_copies() {
    let found = differences(&edge_lines());
    assert!(
        found.is_empty(),
        "{} fark:\n{}",
        found.len(),
        found.join("\n")
    );
}

#[test]
fn random_logs_cost_the_same_in_both_copies() {
    let found = differences(&random_files(3000));
    assert!(
        found.is_empty(),
        "{} fark:\n{}",
        found.len(),
        found
            .iter()
            .take(40)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
