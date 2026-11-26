//! Aile: model/effort kuralları (model_choices, default_model_for, default_effort_for, preferred_default_model,
//! refresh_stored_model, resolved_model_for, model_effort_levels, effort_levels_for, resolve_effort, izin modları,
//! env_overrides) + `effort.py` saf işlevleri.

use crate::common::*;
use cops_providers::effort::{effort_rank, nearest_effort, sort_levels, split_tier};
use cops_providers::{Cli, Providers};
use serde_json::{json, Value};

pub const CLIS: [&str; 8] = ["claude", "agy", "codex", "copilot", "shell", "ucli", "bogus", ""];

pub const MODELS: [&str; 22] = [
    "",
    " ",
    "claude-sonnet-5",
    "claude-sonnet-5-5",
    "claude-sonnet-4-6[1m]",
    "claude-sonnet-10-1",
    "claude-sonnet-5\n",
    "claude-sonnet-123",
    "sonnet",
    "claude-opus-5-5",
    "gemini-3.8-flash",
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-xhigh",
    "gemini-3.1-pro",
    "gpt-5.5",
    "gpt-5.6-terra",
    "x-max",
    "-high",
    "ğ-low",
    "\u{1f}claude-sonnet-5",
    "deepseek-v4-flash",
    "claude-sonnet-٥",
];

pub const EFFORTS: [&str; 12] =
    ["", "low", "medium", "high", "xhigh", "max", "ultra", "none", "minimal", "bogus", "MAX", " high"];

pub fn with<R>(e: &Env, c: &Case, f: impl FnOnce(&Providers<'_>, &FsProbe<'_>) -> R) -> R {
    let settings = e.settings();
    let catalog = e.catalog(c);
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let p = Providers { settings: &settings, catalog: &catalog, paths: &paths, probe: &probe };
    f(&p, &probe)
}

fn rs_model(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, _| {
        let cli = Cli::parse(c.args["cli"].as_str().unwrap());
        let name = c.args.get("name").and_then(Value::as_str).unwrap_or("s1");
        let mut out = json!({
            "model_choices": p.model_choices(cli),
            "default_model_for": p.default_model_for(cli),
            "default_effort_for": p.default_effort_for(cli),
            "preferred_default_model": p.preferred_default_model(cli),
            "default_effort": cli.default_effort(),
            "effort_levels": cli.effort_levels(),
            "permission_modes": cli.permission_modes(),
            "default_permission_mode": cli.default_permission_mode(),
            "env_overrides": cli.env_overrides(name).iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
            "accepts_cli_opts": cli.accepts_cli_opts(),
            "mcp_needs_cwd": cli.mcp_needs_cwd(),
        });
        let models: Vec<String> = strs(c.args.get("models"));
        let efforts: Vec<String> = strs(c.args.get("efforts"));
        if !models.is_empty() {
            let o = out.as_object_mut().unwrap();
            let mut push = |k: &str, v: Value| o.entry(k).or_insert_with(|| json!([])).as_array_mut().unwrap().push(v);
            for m in &models {
                push("model_effort_levels", json!(p.model_effort_levels(cli, m)));
                push("effort_levels_for", json!(p.effort_levels_for(cli, m)));
                push("refresh_stored_model", json!(p.refresh_stored_model(cli, m)));
                push("resolved_model_for", json!(p.resolved_model_for(cli, m)));
                push("resolve_effort", json!(efforts.iter().map(|ef| p.resolve_effort(cli, m, ef)).collect::<Vec<_>>()));
            }
        }
        RsOut::ret(out)
    })
}

fn codex_cache(v: Value) -> Fx {
    file("home/.codex/models_cache.json", &v.to_string(), 0o644)
}

fn model_cases() -> Vec<Case> {
    let base = |id: String, cli: &str| {
        Case::new(id, "model", json!({"cli": cli, "models": MODELS, "efforts": EFFORTS, "name": "oturum-1"}))
    };
    let mut v = Vec::new();
    for cli in CLIS {
        v.push(base(format!("bos-{cli}"), cli));
        v.push(
            base(format!("ayar-{cli}"), cli)
                .settings_json(json!({"default_model": {cli: "gpt-5.5", "claude": "claude-opus-5-5", "ucli": "deepseek-v4-flash"},
                                       "default_effort": {cli: "low", "claude": "max", "codex": "max", "ucli": "high"}})),
        );
        v.push(base(format!("ayar-gecersiz-{cli}"), cli).settings_json(
            json!({"default_model": {cli: 5, "claude": ["x"]}, "default_effort": {cli: "ultra", "claude": null}}),
        ));
        v.push(base(format!("ayar-tip-{cli}"), cli).settings_json(json!({"default_model": "x", "default_effort": [1]})));
        v.push(base(format!("ayar-bozuk-{cli}"), cli).settings("{bozuk"));
        v.push(base(format!("ayar-liste-{cli}"), cli).settings("[1,2]"));
    }
    // claude: canlı model listesi (claude_models.json) biçimleri.
    let states = [
        json!({"models": {"claude-sonnet-5": "enabled", "claude-sonnet-5-5": "enabled", "claude-opus-5-5": "enabled",
                          "claude-haiku-5-5": "disabled"}}),
        json!({"models": {"claude-sonnet-6": "enabled", "claude-sonnet-10": "enabled", "claude-sonnet-9-9": "enabled",
                          "claude-sonnet-10-0": "enabled"}}),
        json!({"models": {"claude-sonnet-5-5": "disabled"}}),
        json!({"models": {}}),
        json!({"models": ["claude-sonnet-5"]}),
        json!({"models": {"zeta": "enabled", "Alpha": "enabled", "ğ": "enabled", "a": true, "b": "Enabled"}}),
        json!([1]),
        json!("x"),
        json!({"models": {"claude-sonnet-05": "enabled", "claude-sonnet-5": "enabled"}}),
        json!({"models": {"claude-sonnet-5[1m]": "enabled", "claude-sonnet-5-5[1m]": "enabled", "opus": "enabled"}}),
    ];
    for (i, st) in states.iter().enumerate() {
        for cli in ["claude", "bogus"] {
            v.push(base(format!("claude-state{i}-{cli}"), cli).file(file("state/claude_models.json", &st.to_string(), 0o644)));
        }
    }
    v.push(base("claude-state-bozuk".into(), "claude").file(file("state/claude_models.json", "{x", 0o644)));
    v.push(
        base("claude-state-ayar".into(), "claude")
            .file(file("state/claude_models.json", &states[1].to_string(), 0o644))
            .settings_json(json!({"default_model": {"claude": "claude-sonnet-6"}})),
    );
    // codex: models_cache.json biçimleri.
    let caches = [
        json!({"models": [
            {"slug": "gpt-5.5", "visibility": "list", "priority": 2,
             "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "high"}, {"effort": "xhigh"}]},
            {"slug": "gpt-5.6-terra", "visibility": "list", "priority": 1,
             "supported_reasoning_levels": [{"effort": "ultra"}, {"effort": "max"}, "low", {"effort": "high"}, {"x": 1}, 5]},
            {"slug": "gizli", "visibility": "hide", "priority": 0},
            {"slug": "", "visibility": "list"},
            {"slug": "gpt-oncelksiz", "visibility": "list"}]}),
        json!({"models": [{"slug": "a", "visibility": "list", "priority": 1.5}, {"slug": "b", "visibility": "list", "priority": -1},
                          {"slug": "c", "visibility": "list", "priority": 1.5}]}),
        json!({"models": [{"slug": "a", "visibility": "list", "priority": "1"}, {"slug": "b", "visibility": "list", "priority": 2}]}),
        json!({"models": [{"slug": "a", "visibility": "list", "priority": null}, {"slug": "b", "visibility": "list", "priority": 2}]}),
        json!({"models": [{"slug": "a", "visibility": "list", "priority": true}, {"slug": "b", "visibility": "list", "priority": 0}]}),
        json!({"models": [1, {"slug": "b", "visibility": "list"}]}),
        json!({"models": [{"slug": 5, "visibility": "list"}, {"slug": "b", "visibility": "list"}]}),
        json!({"models": [{"slug": "gpt-5.5", "visibility": "list", "supported_reasoning_levels": {"high": 1, "low": 2}}]}),
        json!({"models": [{"slug": "gpt-5.5", "visibility": "list", "supported_reasoning_levels": "high"}]}),
        json!({"models": [{"slug": "gpt-5.5", "visibility": "list", "supported_reasoning_levels": []},
                          {"slug": "gpt-5.5", "visibility": "list", "supported_reasoning_levels": ["max"]}]}),
        json!({"models": [{"slug": "gpt-5.5", "visibility": "list", "supported_reasoning_levels": [{"effort": 3}, null]}]}),
        json!({"models": {"slug": "x"}}),
        json!([]),
        json!({}),
    ];
    for (i, cache) in caches.iter().enumerate() {
        let c = base(format!("codex-cache{i}"), "codex").file(codex_cache(cache.clone()));
        v.push(if i == 6 {
            c.known("codex models_cache: dize olmayan slug (5) Python'da model listesine int olarak girer; Rust Vec<String> atlar")
        } else {
            c
        });
    }
    v.push(base("codex-cache-bozuk".into(), "codex").file(file("home/.codex/models_cache.json", "{\"models\": [", 0o644)));
    v.push(base("codex-cache-nan".into(), "codex").file(file(
        "home/.codex/models_cache.json",
        "{\"models\": [{\"slug\": \"a\", \"visibility\": \"list\", \"priority\": NaN}]}",
        0o644,
    )).known("Python json.load NaN/Infinity kabul eder; serde_json reddeder (bu ailede katalog testte serde ile elle kurulur; crate okuma yolu: `src-codex-nan`)"));
    // agy: canlı `agy models` kimlikleri.
    let agy = [
        json!(["gemini-3.8-flash-high", "gemini-3.8-flash-low", "gemini-3.8-flash-medium", "claude-opus-4-6-thinking",
               "gpt-oss-120b-medium", "gemini-3.1-pro-high", "gemini-3.8-flash-ultra"]),
        json!(["gemini-3.8-flash", "gemini-3.8-flash-xhigh", "gemini-3.8-flash-minimal"]),
        json!([""]),
        json!([]),
    ];
    for (i, list) in agy.iter().enumerate() {
        v.push(base(format!("agy-models{i}"), "agy").facts(json!({"agy_models": list})));
        v.push(
            base(format!("agy-models-ayar{i}"), "agy")
                .facts(json!({"agy_models": list}))
                .settings_json(json!({"default_model": {"agy": "gemini-3.8-flash-high"}, "default_effort": {"agy": "xhigh"}})),
        );
    }
    // ucli: canlı model listesi.
    v.push(base("ucli-live".into(), "ucli").facts(json!({"ucli_live": {"ids": ["glm-5.3", "deepseek-v4-flash"], "caps": {}}})));
    v.push(
        base("ucli-live-ayar".into(), "ucli")
            .facts(json!({"ucli_live": {"ids": ["glm-5.3", "qwen"], "caps": {}}}))
            .settings_json(json!({"default_model": {"ucli": "qwen"}, "default_effort": {"ucli": "low"}})),
    );
    v
}

fn rs_effort(_e: &Env, c: &Case) -> RsOut {
    let levels = strs(c.args.get("levels"));
    let models = strs(c.args.get("models"));
    let requests = strs(c.args.get("requests"));
    RsOut::ret(json!({
        "rank": levels.iter().map(|l| effort_rank(l)).collect::<Vec<_>>(),
        "split": models.iter().map(|m| { let (a, b) = split_tier(m); json!([a, b]) }).collect::<Vec<_>>(),
        "sort": sort_levels(levels.iter().cloned()),
        "nearest": requests.iter().map(|r| nearest_effort(r, &levels)).collect::<Vec<_>>(),
    }))
}

fn effort_cases() -> Vec<Case> {
    let lists: [&[&str]; 9] = [
        &["low", "medium", "high"],
        &["high", "low", "high", "", "medium"],
        &["max"],
        &["minimal"],
        &["bogus", "other"],
        &["ultra", "none", "xhigh", "weird", "low"],
        &[],
        &["MAX", "Low"],
        &["medium", "medium"],
    ];
    let models = [
        "gemini-3.8-flash-high", "gemini-3.8-flash", "-high", "high", "a--low", "x-ultra", "x-none", "", "a-b-max",
        "gemini-xhigh", "x-High", "x-high\n", "ğ-minimal",
    ];
    lists
        .iter()
        .enumerate()
        .map(|(i, l)| {
            Case::new(format!("effort{i}"), "effort", json!({"levels": l, "models": models, "requests": EFFORTS}))
        })
        .collect()
}

pub fn run() {
    let mut r = Runner::new();
    r.run(model_cases(), &[], rs_model);
    r.run(effort_cases(), &[], rs_effort);
    r.finish("model/effort");
}
