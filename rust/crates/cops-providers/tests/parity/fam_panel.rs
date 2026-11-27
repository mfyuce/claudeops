//! Aile (G11): panel okuyucu artıkları: `settings.ucli_cost_config` (tavan, kredi, kredi dönemi tarihleri, cache_ttl),
//! `ucli_metrics.get_config` (ayardan ve doğrudan `raw` ile), `ucli_provider.instructions_check` (gerçek geçici ağaçta).
//! Girdiler `py/tests` örnekleri (test_ucli_start_opts.py `CostCapTests`, test_ucli_cost_credit.py, test_quota_scoped_api_credit.py
//! `TestCreditWindow`, test_ucli_metrics.py `Idle.test_config_parsing`, test_ucli_broad_glob_and_instr_check.py) + sınırlar.

use crate::common::*;
use cops_providers::settings::{metrics_config, MetricsConfig};
use cops_providers::ucli::instructions_check;
use serde_json::{json, Value};

fn rs_cost(e: &Env, _c: &Case) -> RsOut {
    let c = e.settings().ucli_cost_config();
    RsOut::ret(json!({
        "daily_cap_usd": fjson(c.daily_cap_usd), "cache_ttl": c.cache_ttl, "credit_total_usd": fjson(c.credit_total_usd),
        "credit_since": c.credit_since, "credit_until": c.credit_until,
    }))
}

fn metrics_json(m: MetricsConfig) -> Value {
    json!({"enabled": m.enabled, "interval_s": fjson(m.interval_s), "retention_days": fjson(m.retention_days)})
}

fn rs_metrics(e: &Env, c: &Case) -> RsOut {
    let m = match c.args.get("raw") {
        Some(raw) => metrics_config(raw),
        None => e.settings().ucli_metrics_config(),
    };
    RsOut::ret(metrics_json(m))
}

fn rs_instr(e: &Env, c: &Case) -> RsOut {
    let probe = FsProbe::new(e, c);
    let r = instructions_check(&probe, c.args["cwd"].as_str().unwrap());
    RsOut::ret(json!({
        "limit": r.limit,
        "files": r.files.iter().map(|f| json!({"name": f.name, "bytes": f.bytes, "over": f.over})).collect::<Vec<_>>(),
    }))
}

fn cost_cases() -> Vec<Case> {
    let raws: Vec<Value> = vec![
        // CostCapTests.test_config_parsing_is_safe
        json!({"daily_cap_usd": "20"}),
        json!({"daily_cap_usd": "-5"}),
        json!({"daily_cap_usd": "abc"}),
        json!({"daily_cap_usd": "inf"}),
        json!({}),
        json!({"daily_cap_usd": "12,5"}),
        json!({"cache_ttl": "9h"}),
        json!("bozuk"),
        // CostCapTests.test_credit_total_parsing_is_safe / CreditTest.test_config_parse
        json!({"credit_total_usd": "200"}),
        json!({"credit_total_usd": "12,5"}),
        json!({"credit_total_usd": ""}),
        json!({"credit_total_usd": "-5"}),
        json!({"credit_total_usd": "-3"}),
        json!({"credit_total_usd": "abc"}),
        json!({"credit_total_usd": "inf"}),
        json!({"credit_total_usd": "nan"}),
        // TestCreditWindow.test_config_dates_validated
        json!({"credit_since": "2026-11-22", "credit_until": "yarın"}),
        // sınırlar
        json!({"daily_cap_usd": 20, "credit_total_usd": 2.5, "cache_ttl": "5M"}),
        json!({"daily_cap_usd": 0, "credit_total_usd": false, "cache_ttl": " 5m "}),
        json!({"daily_cap_usd": true, "credit_total_usd": [1], "cache_ttl": 5}),
        json!({"daily_cap_usd": null, "credit_total_usd": {"a": 1}, "cache_ttl": null}),
        json!({"daily_cap_usd": " 1_000 ", "credit_total_usd": "1,000.5"}),
        json!({"daily_cap_usd": "٣,٥", "credit_total_usd": "\u{1f}7\u{1f}"}),
        json!({"daily_cap_usd": "1e2", "credit_total_usd": "-inf"}),
        json!({"daily_cap_usd": "1e400", "credit_total_usd": "NaN"}),
        json!({"daily_cap_usd": 1e300, "credit_total_usd": 1e-300}),
        json!({"daily_cap_usd": "0,0001", "credit_total_usd": "+5"}),
        json!({"daily_cap_usd": "\u{2003}9\u{3000}", "credit_total_usd": "0x10"}),
        json!({"daily_cap_usd": 10000000000000000000000000u128 as f64}),
        json!({"credit_since": " 2026-11-22 ", "credit_until": "2026-1-22"}),
        json!({"credit_since": "２０２６-１１-２２", "credit_until": "٢٠٢٦-١١-٢٢"}),
        json!({"credit_since": "2026-11-22\n", "credit_until": "2026-11-22x"}),
        json!({"credit_since": "\u{1f}2026-11-22\u{85}", "credit_until": "9999-99-99"}),
        json!({"credit_since": 20261122, "credit_until": null}),
        json!({"credit_since": "2026/11/22", "credit_until": "2026-11-2²"}),
        json!({"credit_since": "\u{11F50}026-11-22", "credit_until": "2026-11-22\u{0}"}),
        json!({"credit_since": ["2026-11-22"], "credit_until": true}),
    ];
    let mut v: Vec<Case> = raws
        .into_iter()
        .enumerate()
        .map(|(i, raw)| {
            Case::new(format!("cost{i}"), "cost_config", json!({}))
                .settings_json(json!({"ucli_cost": raw}))
        })
        .collect();
    v.push(Case::new("cost-dosya-yok", "cost_config", json!({})));
    v.push(Case::new("cost-bozuk-json", "cost_config", json!({})).settings("{\"ucli_cost\": "));
    v
}

fn metrics_cases() -> Vec<Case> {
    let raws: Vec<Value> = vec![
        // Idle.test_config_parsing
        json!({"enabled": "off"}),
        json!({}),
        json!({"interval_s": "5", "retention_days": "7"}),
        json!({"interval_s": "abc"}),
        // sınırlar
        json!({"enabled": " Hayır ", "interval_s": 0, "retention_days": 99999}),
        json!({"enabled": "FALSE", "interval_s": -3, "retention_days": -1}),
        json!({"enabled": "yes", "interval_s": "inf", "retention_days": "-inf"}),
        json!({"enabled": null, "interval_s": true, "retention_days": false}),
        json!({"enabled": 0, "interval_s": [5], "retention_days": {"a": 1}}),
        json!({"enabled": [], "interval_s": null, "retention_days": ""}),
        json!({"enabled": {"x": 1}, "interval_s": " 2.5 ", "retention_days": "1_0"}),
        json!({"enabled": "\u{1f}no\u{1f}", "interval_s": "٣", "retention_days": "1e3"}),
        json!({"enabled": "", "interval_s": 3600.5, "retention_days": 3650}),
        json!({"enabled": "hayir", "interval_s": "12,5"}),
        json!({"enabled": 1.5, "interval_s": 1e300}),
        json!("off"),
        json!([1]),
    ];
    let mut v = Vec::new();
    for (i, raw) in raws.iter().enumerate() {
        // `get_config(raw)` doğrudan (test_ucli_metrics.py biçimi) ve ayardan (`load_settings().get("ucli_metrics")`).
        v.push(Case::new(
            format!("metrics-raw{i}"),
            "metrics_config",
            json!({"raw": raw}),
        ));
        v.push(
            Case::new(format!("metrics-ayar{i}"), "metrics_config", json!({}))
                .settings_json(json!({"ucli_metrics": raw})),
        );
    }
    v.push(Case::new("metrics-dosya-yok", "metrics_config", json!({})));
    // Python HATASI? `_num` NaN'ı sınırlamaz (`max(nan, lo)` = nan): `interval_s` NaN kalır, örnekleyici `sleep(nan)`.
    v.push(Case::new(
        "metrics-nan",
        "metrics_config",
        json!({"raw": {"interval_s": "nan", "retention_days": "NaN"}}),
    ));
    v
}

fn instr_cases(e: &Env) -> Vec<Case> {
    let w = e.work.clone();
    let big = |rel: &str, n: usize| Fx::File(rel.into(), vec![b'x'; n], 0o644);
    vec![
        // InstructionsCheckTests.test_sizes
        Case::new(
            "instr-boyut",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(big("work/p1/AGENTS.md", 50000))
        .file(big("work/p1/CLAUDE.md", 100)),
        // test_exact_limit_not_over (+ bir fazlası)
        Case::new(
            "instr-sinir",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(big("work/p1/CLAUDE.md", 40960)),
        Case::new(
            "instr-sinir-ustu",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(big("work/p1/CLAUDE.md", 40961)),
        // test_no_files_and_bad_cwd
        Case::new(
            "instr-dosyasiz",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        ),
        Case::new("instr-bos", "instr_check", json!({"cwd": ""})),
        Case::new(
            "instr-goreli",
            "instr_check",
            json!({"cwd": "relative/dir"}),
        ),
        Case::new(
            "instr-yok",
            "instr_check",
            json!({"cwd": format!("{w}/yok/zzz")}),
        ),
        Case::new(
            "instr-dosya-cwd",
            "instr_check",
            json!({"cwd": format!("{w}/p1/f")}),
        )
        .file(file("work/p1/f", "x", 0o644)),
        Case::new(
            "instr-nul",
            "instr_check",
            json!({"cwd": format!("{w}/p1\u{0}")}),
        )
        .file(big("work/p1/CLAUDE.md", 5)),
        // test_symlink_escape_ignored (+ içeride kalan symlink, kırık symlink, dizin adlı AGENTS.md)
        Case::new(
            "instr-symlink-kacis",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(big("work/o/secret.md", 20000))
        .file(Fx::Link(
            "work/p1/AGENTS.md".into(),
            format!("{w}/o/secret.md"),
        )),
        Case::new(
            "instr-symlink-ici",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(big("work/p1/CLAUDE.md", 7))
        .file(Fx::Link("work/p1/AGENTS.md".into(), "CLAUDE.md".into())),
        Case::new(
            "instr-symlink-kirik",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(Fx::Link("work/p1/AGENTS.md".into(), "yok.md".into())),
        Case::new(
            "instr-dizin",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(Fx::Dir("work/p1/AGENTS.md".into(), 0o755))
        .file(big("work/p1/CLAUDE.md", 0)),
        // cwd'nin kendisi symlink, sonda `/`, `..`, Unicode ad
        Case::new(
            "instr-cwd-symlink",
            "instr_check",
            json!({"cwd": format!("{w}/bag/")}),
        )
        .file(big("work/p1/AGENTS.md", 3))
        .file(Fx::Link("work/bag".into(), format!("{w}/p1"))),
        Case::new(
            "instr-cwd-nokta",
            "instr_check",
            json!({"cwd": format!("{w}/yok/../p1/.")}),
        )
        .file(big("work/p1/AGENTS.md", 4)),
        Case::new(
            "instr-unicode",
            "instr_check",
            json!({"cwd": format!("{w}/ğ ü")}),
        )
        .file(big("work/ğ ü/CLAUDE.md", 9)),
        Case::new("instr-kok", "instr_check", json!({"cwd": "/"})),
        // test_no_content_returned: dönüşte içerik yok (karşılaştırma tüm dönüşü kapsar)
        Case::new(
            "instr-icerik",
            "instr_check",
            json!({"cwd": format!("{w}/p1")}),
        )
        .file(file("work/p1/CLAUDE.md", "TOPSECRET", 0o644)),
        // listelenemeyen (yalnız x) dizin: boyut yine okunur (stat), içerik okunmaz
        Case::new(
            "instr-izinsiz-dizin",
            "instr_check",
            json!({"cwd": format!("{w}/gizli")}),
        )
        .file(file("work/gizli/AGENTS.md", "abc", 0o644))
        .file(Fx::Dir("work/gizli".into(), 0o311)),
    ]
}

pub fn run() {
    let mut r = Runner::new();
    r.run(cost_cases(), &[], rs_cost);
    r.run(metrics_cases(), &[], rs_metrics);
    let cases = instr_cases(&r.e);
    r.run(cases, &[], rs_instr);
    r.finish("panel");
}
