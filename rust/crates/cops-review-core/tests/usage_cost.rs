//! `usage_cost_usd`: `task_end` toplamı yinelenmez; Haiku 5.5 100K üstü istem pahalı dilimden (Python ile aynı).
use cops_review_core::report::usage_cost_usd;

fn cost(name: &str, lines: &[&str], model: &str) -> f64 {
    let p = std::env::temp_dir().join(format!(
        "cops-usage-cost-{}-{name}.jsonl",
        std::process::id()
    ));
    std::fs::write(&p, lines.join("\n")).unwrap();
    let got = usage_cost_usd(p.to_str().unwrap(), model, 0.0, 1.0);
    std::fs::remove_file(&p).unwrap();
    got.unwrap()
}

#[test]
fn task_end_total_is_not_billed_again() {
    let got = cost(
        "end",
        &[
            r#"{"event":"task_start","model":"claude-sonnet-5-5","t":1}"#,
            r#"{"event":"request","t":2,"usage":{"cache_creation_input_tokens":7989,"cache_read_input_tokens":0,"cached_tokens":0,"completion_tokens":5,"prompt_tokens":7993}}"#,
            r#"{"event":"task_end","t":3,"usage":{"cached_tokens":0,"completion_tokens":5,"prompt_tokens":7993}}"#,
        ],
        "",
    );
    assert!(
        (got - (4.0 * 2.0 + 5.0 * 10.0 + 7989.0 * 2.5) / 1e6).abs() < 1e-12,
        "{got}"
    );
}

#[test]
fn haiku_tier_follows_each_request_prompt_size() {
    let line = |prompt: u32| {
        format!(
            r#"{{"event":"request","t":1,"usage":{{"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"prompt_tokens":{prompt},"completion_tokens":1000}}}}"#
        )
    };
    let (low, high) = (line(100_000), line(100_001));
    let a = cost("low", &[&low, &low], "claude-haiku-5-5");
    assert!(
        (a - 2.0 * (100_000.0 * 0.10 + 1000.0 * 0.50) / 1e6).abs() < 1e-12,
        "{a}"
    );
    let b = cost("high", &[&high], "claude-haiku-5-5");
    assert!(
        (b - (100_001.0 * 0.50 + 1000.0 * 2.50) / 1e6).abs() < 1e-12,
        "{b}"
    );
}
