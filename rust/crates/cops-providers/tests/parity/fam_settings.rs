//! Aile: `settings.json` okuyucuları (ucli_endpoint, ucli_web, ucli_services, ucli_limits, reasoning/stream/state_dir,
//! script, cache_ttl, ucli_max_session_usd, ucli_metrics, ucli_agents, routing_guidance, byok, spawn_nice,
//! effort_levels_for), `_valid_http_url` ve Python biçimlendirme ilkelleri (`shlex.quote`, `strip`, `json.dumps`, `:g`,
//! `str`, `int`, `float`).

use crate::common::*;
use cops_providers::pyfmt::{fmt_g, json_ascii, parse_float, parse_int, quote, str_of, strip};
use cops_providers::settings::valid_http_url;
use cops_providers::spawn::priority_prefix;
use serde_json::{json, Value};

fn rs_settings(e: &Env, c: &Case) -> RsOut {
    let s = e.settings();
    let web = s.ucli_web();
    let mut wj = serde_json::Map::new();
    if let Some(u) = &web.search_url {
        wj.insert("search_url".into(), json!(u));
        wj.insert("search_flavor".into(), json!("searxng"));
    } else if web.search_docker {
        wj.insert("search_docker".into(), json!(true));
    }
    if !web.allow_fetch_domains.is_empty() {
        wj.insert("allow_fetch_domains".into(), json!(web.allow_fetch_domains));
    }
    let svc: Vec<Value> = s
        .ucli_services()
        .iter()
        .map(|d| {
            json!({"id": d.id, "wire": d.wire, "endpoint": d.endpoint, "env": d.env,
                   "efforts": d.efforts.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>()})
        })
        .collect();
    let pairs = |v: Vec<(String, String)>| v.into_iter().map(|(k, x)| json!([k, x])).collect::<Vec<_>>();
    let elf: Vec<Value> = c
        .args
        .get("svc_models")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .map(|p| json!(s.ucli_effort_levels_for(p[0].as_str().unwrap(), p[1].as_str().unwrap())))
                .collect()
        })
        .unwrap_or_default();
    RsOut::ret(json!({
        "ucli_endpoint": s.ucli_endpoint(),
        "ucli_web": wj,
        "ucli_services": svc,
        "ucli_limit_overrides": s.ucli_limit_overrides().iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
        "ucli_reasoning_mode": s.ucli_reasoning_mode(),
        "ucli_stream": s.ucli_stream(),
        "ucli_show_reasoning": s.ucli_show_reasoning(),
        "ucli_state_dir": s.ucli_state_dir(),
        "ucli_script_mode": s.ucli_script_mode(),
        "ucli_cache_ttl": s.ucli_cache_ttl(),
        "default_max_session_usd": s.default_max_session_usd(),
        "ucli_metrics_enabled": s.ucli_metrics_enabled(),
        "ucli_agents_enabled": s.ucli_agents_enabled(),
        "routing_guidance_enabled": s.routing_guidance_enabled(),
        "routing_guidance_text": s.routing_guidance_text(),
        "byok_copilot": pairs(s.byok_env("copilot")),
        "byok_ucli": pairs(s.byok_env("ucli")),
        "priority_prefix": priority_prefix(&s, "s1"),
        "effort_levels_for": elf,
    }))
}

const SVC_MODELS: [[&str; 2]; 9] = [
    ["claude", "claude-sonnet-5-5"],
    ["claude", "CLAUDE-OPUS-5-5"],
    ["claude", "claude-haiku-5-5"],
    ["claude", "x"],
    ["claude", ""],
    ["evren", "glm"],
    ["yok", "sonnet"],
    ["ozel", "big-sonnet-opus-x"],
    ["ozel", "ab"],
];

fn settings_cases() -> Vec<Case> {
    let docs: Vec<(&str, Value)> = vec![
        ("bos", json!({})),
        ("limitler", json!({"ucli_limits": {"max_steps": "12", "max_context_kib": 0, "max_tool_calls": -5,
            "max_output_tokens": "abc", "request_timeout_secs": 3.7, "max_history_kib": " 64 ",
            "reasoning_effort": "HIGH", "stream": "off", "show_reasoning": "evet", "state_dir": "açık"}})),
        ("limitler2", json!({"ucli_limits": {"max_steps": "1_000", "max_context_kib": "+7", "max_tool_calls": true,
            "max_output_tokens": "٣٢", "request_timeout_secs": "\u{1f}9\u{1c}", "max_history_kib": null,
            "reasoning_effort": "0", "stream": "", "show_reasoning": "Hayır", "state_dir": 1}})),
        ("limitler3", json!({"ucli_limits": {"reasoning_effort": 0, "stream": false, "show_reasoning": true,
            "state_dir": "KAPALI", "max_steps": "1__0", "max_context_kib": "_1", "max_tool_calls": "1_"}})),
        ("limitler4", json!({"ucli_limits": {"reasoning_effort": "max ", "stream": "y", "show_reasoning": "maybe",
            "state_dir": "none"}})),
        ("limitler-tip", json!({"ucli_limits": [1], "ucli_script": "full", "ucli_cost": "5m", "ucli_web": "x"})),
        ("script", json!({"ucli_script": {"mode": " READ "}, "ucli_cost": {"cache_ttl": "5M"}})),
        ("script2", json!({"ucli_script": {"mode": "off"}, "ucli_cost": {"cache_ttl": 5}})),
        ("script3", json!({"ucli_script": {"mode": "Full"}, "ucli_cost": {"cache_ttl": " 1h "}})),
        ("web1", json!({"ucli_web": {"search_url": "https://ara.example.org/search", "search_flavor": "SearXNG",
            "allow_fetch_domains": "Docs.Python.org, example.com\u{1f}rust-lang.org  ,bad_host, -x.com, a..b, example.com"}})),
        ("web2", json!({"ucli_web": {"search_url": "notaurl", "search_docker": "on",
            "allow_fetch_domains": ["a.com", 5, "B.COM", "ğ.com", "\u{212a}.com"]}})),
        ("web3", json!({"ucli_web": {"search_url": "", "search_docker": "off"}})),
        ("web4", json!({"ucli_web": {"search_docker": false}})),
        ("web5", json!({"ucli_web": {"search_docker": 0, "search_flavor": "other", "search_url": "http://x"}})),
        ("web6", json!({"ucli_web": {"search_docker": null, "allow_fetch_domains": null}})),
        ("web7", json!({"ucli_web": {"search_docker": "", "allow_fetch_domains": ""}})),
        ("web8", json!({"ucli_web": {"search_url": "  http://h:8080/  ", "allow_fetch_domains":
            (0..70).map(|i| format!("h{i}.com")).collect::<Vec<_>>().join(" ")}})),
        ("web9", json!({"ucli_web": {"allow_fetch_domains": format!("{}.com,{}.com", "a".repeat(63), "b".repeat(64))}})),
        ("web10", json!({"ucli_web": {"allow_fetch_domains": [format!("{}.{}.{}.{}", "a".repeat(63), "b".repeat(63),
            "c".repeat(63), "d".repeat(61)), format!("{}.{}.{}.{}", "a".repeat(63), "b".repeat(63), "c".repeat(63), "d".repeat(62))]}})),
        ("web11", json!({"ucli_web": {"allow_fetch_domains": "x.com\u{85}y.com\u{a0}z.com\u{2003}w.com"}})),
        ("endpoint1", json!({"ucli_endpoint": " https://api.example.com/v1/// "})),
        ("endpoint2", json!({"ucli_endpoint": "ftp://x"})),
        ("endpoint3", json!({"ucli_endpoint": 5})),
        ("endpoint4", json!({"ucli_endpoint": "http://x:99999"})),
        ("servisler1", json!({"ucli_services": [
            {"id": "Claude", "wire": "anthropic-messages", "endpoint": "https://api.anthropic.com/v1/", "env": "ANTHROPIC_API_KEY",
             "efforts": {" Sonnet ": ["low", "high", "low", "max", "ultra", 5], "opus": "high", "": ["low"], "sonnet": ["medium"],
                         "haiku": []}},
            {"id": "claude", "endpoint": "https://dup", "env": "XAI_API_KEY"},
            {"id": "x", "endpoint": "https://x", "env": "XAI_API_KEY"},
            {"id": "grok", "endpoint": "", "env": "XAI_API_KEY"},
            {"id": "bad-env", "endpoint": "https://x", "env": "ab"},
            {"id": "wire", "endpoint": "https://x", "env": "WIRE_KEY", "wire": "openai"},
            {"id": "noscheme", "endpoint": "api.x.com", "env": "WIRE_KEY"},
            "string-entry",
            {"id": "ozel", "endpoint": "http://ozel.local", "env": "OZEL_KEY",
             "efforts": {"sonnet": ["low"], "opus": ["high"], "big": ["max"], "ab": ["low"], "ba": ["high"]}}]})),
        ("servisler2", json!({"ucli_services": [{"id": "evren", "env": "UCLI_API_KEY", "endpoint": "https://e/"},
            {"id": "ozel", "endpoint": "https://o", "env": "OZEL_KEY",
             "efforts": (0..25).map(|i| (format!("k{i:02}"), json!(["low"]))).collect::<serde_json::Map<_, _>>()}]})),
        ("servisler3", json!({"ucli_services": []})),
        ("servisler4", json!({"ucli_services": {"id": "x"}})),
        ("servisler5", json!({"ucli_services": [{"id": "ozel", "endpoint": "https://o", "env": "OZEL_KEY",
            "efforts": {"zz": ["low"], "aa": ["high"], "ZZ": ["max"]}}]})),
        ("servisler6", json!({"ucli_services": [{"id": "ozel", "endpoint": "https://o", "env": "OZEL_KEY",
            "efforts": {"b": ["low"], "a": ["high"]}}]})),
        ("usd1", json!({"ucli_max_session_usd": "1,5"})),
        ("usd2", json!({"ucli_max_session_usd": "abc"})),
        ("usd3", json!({"ucli_max_session_usd": "-1"})),
        ("usd4", json!({"ucli_max_session_usd": "inf"})),
        ("usd5", json!({"ucli_max_session_usd": "nan"})),
        ("usd6", json!({"ucli_max_session_usd": 3})),
        ("usd7", json!({"ucli_max_session_usd": true})),
        ("usd8", json!({"ucli_max_session_usd": "0"})),
        ("usd9", json!({"ucli_max_session_usd": null})),
        ("usd10", json!({"ucli_max_session_usd": " 1e2 "})),
        ("usd11", json!({"ucli_max_session_usd": "-0"})),
        ("usd12", json!({"ucli_max_session_usd": 2.5})),
        ("metrics1", json!({"ucli_metrics": {"enabled": "Hayır"}, "ucli_agents": "OFF ", "routing_guidance": "KAPALI"})),
        ("metrics2", json!({"ucli_metrics": {"enabled": 0}, "ucli_agents": "", "routing_guidance": false})),
        ("metrics3", json!({"ucli_metrics": {"enabled": null}, "ucli_agents": null, "routing_guidance": null})),
        ("metrics4", json!({"ucli_metrics": {"enabled": []}, "ucli_agents": 0, "routing_guidance": "x"})),
        ("metrics5", json!({"ucli_metrics": {"enabled": "no "}, "ucli_agents": false, "routing_guidance": 0})),
        ("metrics6", json!({"ucli_metrics": "off", "ucli_agents": "hayır", "routing_guidance": "none"})),
        ("metrics7", json!({"ucli_metrics": {"enabled": "yes"}, "ucli_agents": "none", "routing_guidance": "\u{1f}off\u{1f}"})),
        ("nice1", json!({"spawn_nice": "5"})),
        ("nice2", json!({"spawn_nice": 5})),
        ("nice3", json!({"spawn_nice": "0"})),
        ("nice4", json!({"spawn_nice": "OFF"})),
        ("nice5", json!({"spawn_nice": "20"})),
        ("nice6", json!({"spawn_nice": "-3"})),
        ("nice7", json!({"spawn_nice": 19})),
        ("nice8", json!({"spawn_nice": null})),
        ("nice9", json!({"spawn_nice": " 7 "})),
        ("nice10", json!({"spawn_nice": "٧"})),
        ("nice11", json!({"spawn_nice": 7.0})),
        ("nice12", json!({"spawn_nice": ""})),
        ("nice13", json!({"spawn_nice": true})),
        ("rtext1", json!({"routing_guidance_text": "  yönerge \u{1f}"})),
        ("rtext2", json!({"routing_guidance_text": 5})),
        ("rtext3", json!({"routing_guidance_text": true})),
        ("rtext4", json!({"routing_guidance_text": 1e20})),
        ("rtext5", json!({"routing_guidance_text": 0.1})),
        ("byok1", json!({"byok": {"copilot": {"ZED": "1", "ALPHA": "2", "MID": 0, "N": null, "X": 5, "L": [1], "F": 1.5,
            "B": false, "T": true, "E": ""}, "ucli": {"UCLI_API_KEY": " k ", "ZZ": "z", "AA": "a"}}})),
        ("byok2", json!({"byok": {"copilot": "x", "ucli": [1]}})),
        ("byok3", json!({"byok": "x"})),
        ("bilinmeyen-anahtar", json!({"bilinmeyen": 1, "theme": "dark"})),
    ];
    let mut v: Vec<Case> = docs
        .into_iter()
        .map(|(id, d)| Case::new(id, "settings", json!({"svc_models": SVC_MODELS})).settings_json(d))
        .collect();
    v.push(Case::new("dosya-yok", "settings", json!({"svc_models": SVC_MODELS})));
    v.push(Case::new("bozuk-json", "settings", json!({})).settings("{\"spawn_nice\": "));
    v.push(Case::new("json-liste", "settings", json!({})).settings("[]"));
    v.push(Case::new("json-yinelenen", "settings", json!({})).settings(r#"{"spawn_nice": "3", "spawn_nice": "4"}"#));
    v.push(
        Case::new("byok-yinelenen", "settings", json!({}))
            .settings(r#"{"byok": {"copilot": {"B": "1", "A": "2", "B": "3"}}}"#),
    );
    v.push(
        Case::new("byok-sozluk", "settings", json!({}))
            .settings_json(json!({"byok": {"copilot": {"D": {"a": 1}}}}))
            .known("str(dict) Python repr (`{'a': 1}`), Rust JSON metni (`{\"a\":1}`); yalnız bozuk elle düzenlenmiş ayarda"),
    );
    v.push(
        Case::new("rtext-liste", "settings", json!({}))
            .settings_json(json!({"routing_guidance_text": [1, "a"]}))
            .known("str(list) Python repr, Rust JSON metni; yalnız bozuk elle düzenlenmiş ayarda"),
    );
    v.push(
        Case::new("buyuk-int", "settings", json!({}))
            .settings_json(json!({"ucli_limits": {"max_steps": "99999999999999999999"}}))
            .known("Python int sınırsız; Rust i64 (taşan değer atlanır)"),
    );
    v
}

fn rs_valid_url(_e: &Env, c: &Case) -> RsOut {
    RsOut::ret(json!(strs(c.args.get("urls")).iter().map(|u| valid_http_url(u)).collect::<Vec<_>>()))
}

fn url_cases() -> Vec<Case> {
    let urls = [
        "http://x", "https://x/", "HTTP://X", "Https://Example.com:443/a?b#c", "ftp://x", "http://", "http:///x",
        "http://:80", "http://user@:80", "http://user:pw@host:80/p", "http://x:99999", "http://x:65535", "http://x:65536",
        "http://x:abc", "http://x:", "http://x:+80", "http://x:-0", "http://x:٨٠", "http://x:0080", "http://[::1]:80/v1",
        "http://[::1", "http://x]", "http://a[b]c", "http://[::1]x", "http://[::1]:", "http://[zz]:80", "http://x\u{7f}",
        "http://ex ample", "http:/x", "1http://x", "h-t.tp://x", "http:x", "//x", "http://x?y", "http://x#y",
        "http://@x", "http://x:80:90", "http://[::1]:80:90", "http://ğ.com", "http://x/\u{85}", "http://x\u{a0}",
        "http://x/\u{2028}", "http://1.2.3.4:8080", "http://x:0", "http://x:\u{663}", "",
    ];
    vec![
        Case::new("url", "valid_url", json!({"urls": urls.as_slice()})),
        Case::new("url-nfkc", "valid_url", json!({"urls": ["http://a\u{ff03}b", "http://a\u{ff1a}80"]}))
            .known("urlsplit NFKC ağ konumu denetimi (tam genişlik `＃`/`：` normalleşince ayraç olur) taşınmadı: Python geçersiz, Rust geçerli sayar"),
    ]
}

fn rs_pyfmt(_e: &Env, c: &Case) -> RsOut {
    let ss = strs(c.args.get("strs"));
    let floats: Vec<f64> = c.args.get("floats").and_then(Value::as_array).map_or(Vec::new(), |a| {
        a.iter().map(|x| x.as_f64().unwrap()).collect()
    });
    let values: Vec<Value> = c.args.get("values").and_then(Value::as_array).cloned().unwrap_or_default();
    RsOut::ret(json!({
        "quote": ss.iter().map(|s| quote(s)).collect::<Vec<_>>(),
        "strip": ss.iter().map(|s| strip(s)).collect::<Vec<_>>(),
        "json": ss.iter().map(|s| json_ascii(s)).collect::<Vec<_>>(),
        "g": floats.iter().map(|f| fmt_g(*f)).collect::<Vec<_>>(),
        "str": values.iter().map(str_of).collect::<Vec<_>>(),
        "int": ss.iter().map(|s| parse_int(s)).collect::<Vec<_>>(),
        "float": ss.iter().map(|s| parse_float(s).map(fjson)).collect::<Vec<_>>(),
    }))
}

fn pyfmt_cases() -> Vec<Case> {
    let strs = [
        "", " ", "a", "a b", "it's", "ğ", "a/b-c.d_e@f%g+h=i:j,k", "$x", "\u{1c}x\u{1f}", "\u{85}x\u{a0}", "\u{2028}",
        "\t\n", "5", " 5 ", "+5", "-0", "1_000", "1__0", "_1", "1_", "0x10", "١٢", "٣.٥", "inf", "-Infinity", "nan",
        "NaN", "1e5", "1E-3", ".5", "5.", "+.5", "1e", "e5", "infinity", "iNfInItY", "+inf", "1.5", "1,5", "\u{2003}7\u{3000}",
        "\"q\"\\", "\u{7f}\u{8}\u{c}", "😀", "\u{10ffff}", "a\u{0}b", "5\u{1f}", "Ⅻ", "²", "0b1", "1e400", "-1e400", "1_0.5",
    ];
    let floats = [
        8.0, 0.5, 1234567.0, 1e-5, 100.0, 0.0001, 123456.0, 1e16, -2.5, 1e-310, 0.30000000000000004, 99999.95, 999999.5,
        1e100, 5e-324, 0.0, -0.0, 1.0e15, 123456789.0, 0.000123456789, 3.0, 2.675, 1e21, 1.5e-7,
    ];
    let values = json!([null, true, false, 0, 1.0, 1e16, 1e15, 1e-5, 0.0001, 0.1, -0.0, 1.2345678901234568e+29, "x", 5,
        -7, 2.5e-7, 123456789012.5, 1e300]);
    vec![
        Case::new("pyfmt", "pyfmt", json!({"strs": strs.as_slice(), "floats": floats.as_slice(), "values": values})),
        Case::new("pyfmt-liste", "pyfmt", json!({"values": [[1, "a"], {"a": 1}]}))
            .known("str(list/dict) Python repr, Rust JSON metni; yalnız bozuk elle düzenlenmiş ayarda görülür"),
        Case::new("pyfmt-buyuk", "pyfmt", json!({"strs": ["99999999999999999999"]}))
            .known("Python int sınırsız; Rust i64 (taşan değer None)"),
    ]
}

pub fn run() {
    let mut r = Runner::new();
    r.run(pyfmt_cases(), &[], rs_pyfmt);
    r.run(url_cases(), &[], rs_valid_url);
    r.run(settings_cases(), &[], rs_settings);
    r.finish("settings/pyfmt");
}
