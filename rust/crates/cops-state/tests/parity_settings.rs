//! `settings.py` okuyucuları ve `pycompat` (Python yerleşikleri) paritesi: aynı girdi, aynı çıktı (JSON baytı).
use cops_state::json::Map;
use cops_state::paths::{expanduser_with, parse_proc_stat};
use cops_state::pycompat as py;
use cops_state::settings::Settings;
use cops_state::settings_read::{self, SysEnv};
use cops_state::Json;
use std::os::unix::fs::PermissionsExt;

mod common;
use common::{j, Env};

fn exe(path: &std::path::Path, mode: u32) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, "#!/bin/sh\n").unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
}

const CASES: &str = r#"[
 {},
 {"provider_bin": {"tool": "~/bin2/tool", "claude": " /yok/claude "}},
 {"provider_bin": {"tool": 5}},
 {"provider_bin": {"tool": null}},
 {"provider_bin": {"tool": "~/bin1/noexec"}},
 {"byok": {"claude": {"A": "x", "B": 0, "C": 1.5, "D": [1, "a'", 2.0, null, true], "E": {"k": "v'\"\u0000\u00a0\u2028ş"}, "F": true, "G": "", "H": 1e16, "I": 12345678901234567890123}, "codex": "str"}},
 {"byok": "x"},
 {"ucli_limits": {"max_steps": " 12 ", "max_context_kib": "1_000", "max_tool_calls": "-3", "max_output_tokens": "٣٤", "request_timeout_secs": 5.0, "max_history_kib": "99999999999999999999999", "reasoning_effort": " HIGH ", "stream": "hayır", "show_reasoning": "Evet", "state_dir": 1}},
 {"ucli_limits": {"reasoning_effort": "0", "stream": false, "show_reasoning": "x", "state_dir": "on", "max_steps": true, "max_context_kib": "\u00a07\u3000", "max_tool_calls": "+0_7"}},
 {"ucli_limits": {"reasoning_effort": "max", "stream": "1", "show_reasoning": "no", "state_dir": "kapalı", "max_steps": "1 2", "max_context_kib": 3}},
 {"ucli_limits": "x"},
 {"ucli_usage_warn": {"amber": "2,000,000", "red": "off"}},
 {"ucli_usage_warn": {"amber": "00", "red": null}},
 {"ucli_usage_warn": {"amber": "1_5", "red": 2.5}},
 {"ucli_usage_warn": {"amber": -5, "red": " KAPALI "}},
 {"ucli_usage_warn": {"amber": "99999999999999999999999", "red": false}},
 {"ucli_cost": {"daily_cap_usd": "1,5", "credit_total_usd": "inf", "cache_ttl": " 5M ", "credit_since": "2026-11-22", "credit_until": "２０２６-１２-０２"}},
 {"ucli_cost": {"daily_cap_usd": "nan", "credit_total_usd": 162, "cache_ttl": 5, "credit_since": "2026-1-22", "credit_until": " 2026-12-02 "}},
 {"ucli_cost": {"daily_cap_usd": " 1_0.5 ", "credit_total_usd": "1e400"}},
 {"ucli_cost": {"daily_cap_usd": true, "credit_total_usd": -1, "cache_ttl": "1H"}},
 {"ucli_cost": {"daily_cap_usd": 1e400, "credit_total_usd": "١٢.٥"}},
 {"ucli_script": {"mode": " Full "}},
 {"ucli_script": {"mode": "write"}},
 {"ucli_script": 7},
 {"ucli_endpoint": " https://Evren.example/v1/// "},
 {"ucli_endpoint": "ftp://x"},
 {"ucli_endpoint": "http://[::1]:99999"},
 {"ucli_endpoint": 5},
 {"ucli_endpoint": "http://ｅｘａｍｐｌｅ.com"},
 {"ucli_endpoint": "http://a／b"},
 {"ucli_endpoint": "http://u@[v1.x]:8/"},
 {"ucli_endpoint": "http://a[b]@c"},
 {"ucli_endpoint": "http://h:"},
 {"ucli_endpoint": "http://:80"},
 {"ucli_endpoint": "http://[fe80::1%25eth0]:80"},
 {"ucli_endpoint": "HTTP://X:0080/"},
 {"ucli_endpoint": "http://x:١"},
 {"ucli_web": {"search_url": "http://localhost:8080", "search_flavor": "SearXNG", "allow_fetch_domains": ["A.org", "b.org", "bad_one", "-x.com", 5, "a.org", "ok-1.x9"]}},
 {"ucli_web": {"search_url": "", "search_docker": false, "allow_fetch_domains": "x.org, y.org\tz.org,,\u3000w.org"}},
 {"ucli_web": {"search_docker": 0.0, "allow_fetch_domains": {"a.org": 1}}},
 {"ucli_web": {"search_url": "nope", "search_docker": true}},
 {"ucli_web": {"search_url": "http://x", "search_flavor": "other"}},
 {"ucli_web": {"search_docker": " Off ", "allow_fetch_domains": 7}},
 {"ucli_services": "x"},
 {"ucli_services": []},
 {"ucli_services": [
   {"id": " Claude ", "label": "", "wire": "anthropic-messages", "endpoint": "https://api.anthropic.com/v1//", "env": "ANTHROPIC_API_KEY", "models": "a\nb,,a, c ", "efforts": {" Opus ": ["max", "low", "low", "x", 3], "son": "x", "": ["low"], "OPUS": ["high"]}},
   {"id": "claude", "env": "XX_KEY", "endpoint": "http://x"},
   {"id": "bad env", "env": "K"},
   {"id": "g1", "env": "G_KEY", "wire": "other", "endpoint": "http://g"},
   {"id": "g2", "env": "G_KEY", "endpoint": "http://g h"},
   {"id": "g3", "env": "G_KEY"},
   {"id": "g4", "env": "G_KEY", "endpoint": "https://g4", "models": {"m1": 1, "m2": 2}, "label": ["l", 1]},
   {"id": "g5", "env": "G_KEY", "endpoint": "https://g5", "models": 0, "label": "uzun etiket uzun etiket uzun etiket uzun etiket"},
   {"id": "g6", "env": "G_KEY", "endpoint": "https://g6", "models": [1, 2.5, null, true, " x ", "x", "ş", ["n"]]},
   "satir",
   {"id": "Key", "env": "KEY_K", "endpoint": "https://k"}
 ]},
 {"ucli_services": [{"id": "evren", "env": "UCLI_API_KEY"}, {"id": "zz", "env": "Z_KEY", "endpoint": "https://z", "models": 5}]},
 {"ucli_services": [{"id": "evren", "env": "UCLI_API_KEY", "models": true}]},
 {"ucli_services": [{"id": "evren", "env": "UCLI_API_KEY", "models": {"a": 1}}]},
 {"provider_bin": {"tool": 5, "claude": null}},
 {"uzakgoz": {"dir": "~/work/projects/tmp/uzakgoz", "bin": "~/bin2/tool", "port": " 8080 "}, "derbent": {"dir": "~nosuchuserxyz/a", "port": 80}},
 {"uzakgoz": {"dir": "", "port": "65536", "bin": "~/bin1/noexec"}, "derbent": "x"},
 {"uzakgoz": {"dir": 5, "port": "1_024"}, "derbent": {"dir": "~/der", "port": 1024.0}},
 {"reader": {"dir": "~/rl"}},
 {"reader": {"dir": "/yok"}},
 {"reader": {"dir": ""}},
 {"reader": {"dir": "~/reader/"}},
 {"tunnel_watch": false, "routing_guidance": 0},
 {"tunnel_watch": "", "routing_guidance": " OFF "},
 {"tunnel_watch": null, "routing_guidance": []},
 {"tunnel_watch": 0.0, "routing_guidance": "\u001coff"}
]"#;

const PY_READ: &str = r#"
from claudeops import settings as s
root = sys.argv[2]
os.environ['PATH'] = f"{root}/home/bin1:{root}/home/bin2:{root}/home/bin1"
cases = json.loads(sys.stdin.read())
def call(f, *a):
    try:
        return f(*a)
    except Exception as e:
        return {'error': type(e).__name__}
out = []
for c in cases:
    with open(s.SETTINGS_JSON, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False)
    s._LOAD_CACHE['sig'] = None
    r = {}
    r['bin'] = [call(s.resolved_binary, x) for x in ('tool', 'claude', 'noexec', 'yok', root + '/home/bin2/tool')]
    r['byok'] = [s.byok_env_for(x) for x in ('claude', 'codex', 'yok')]
    r['limits'] = s.ucli_limit_overrides()
    r['warn'] = list(s.ucli_usage_warn_thresholds())
    r['reason'] = s.ucli_reasoning_mode()
    r['flags'] = [s.ucli_stream_enabled(), s.ucli_show_reasoning_enabled(), s.ucli_state_dir_enabled(), s.tunnel_watch_enabled(), s.routing_guidance_enabled()]
    r['services'] = call(s.ucli_services)
    r['cost'] = s.ucli_cost_config()
    r['script'] = s.ucli_script_mode()
    r['endpoint'] = s.ucli_endpoint()
    r['web'] = s.ucli_web_config()
    r['daemons'] = [s.uzakgoz_config(), s.derbent_config()]
    r['reader'] = s.reader_config()
    out.append(r)
print(json.dumps(out, ensure_ascii=False))
"#;

fn obj(v: Vec<(&str, Json)>) -> Json {
    Json::Object(v.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
}

fn rust_read(s: &Settings, env: &SysEnv, root: &str) -> Json {
    let bin: Vec<Json> = [
        "tool",
        "claude",
        "noexec",
        "yok",
        &format!("{root}/home/bin2/tool"),
    ]
    .iter()
    .map(|x| Json::from(s.resolved_binary(x, env)))
    .collect();
    let byok: Vec<Json> = ["claude", "codex", "yok"]
        .iter()
        .map(|c| {
            Json::Object(
                s.byok_env_for(c)
                    .into_iter()
                    .map(|(k, v)| (k, Json::from(v)))
                    .collect(),
            )
        })
        .collect();
    let limits: Map = s
        .ucli_limit_overrides()
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_json()))
        .collect();
    let (a, r) = s.ucli_usage_warn_thresholds();
    let flags = vec![
        s.ucli_stream_enabled().into(),
        s.ucli_show_reasoning_enabled().into(),
        s.ucli_state_dir_enabled().into(),
        s.tunnel_watch_enabled().into(),
        s.routing_guidance_enabled().into(),
    ];
    let reader = obj(vec![("dir", s.reader_config(env).into())]);
    obj(vec![
        ("bin", Json::Array(bin)),
        ("byok", Json::Array(byok)),
        ("limits", Json::Object(limits)),
        ("warn", Json::Array(vec![a.to_json(), r.to_json()])),
        ("reason", s.ucli_reasoning_mode().into()),
        ("flags", Json::Array(flags)),
        ("services", Json::Array(s.ucli_services())),
        ("cost", s.ucli_cost_config().to_json()),
        ("script", s.ucli_script_mode().into()),
        ("endpoint", s.ucli_endpoint().into()),
        ("web", s.ucli_web_config()),
        (
            "daemons",
            Json::Array(vec![
                s.uzakgoz_config(env).to_json(),
                s.derbent_config(env).to_json(),
            ]),
        ),
        ("reader", reader),
    ])
}

#[test]
fn settings_readers_match_python() {
    let e = Env::new();
    let home = e.root.join("home");
    exe(&home.join("bin1/noexec"), 0o644);
    exe(&home.join("bin2/tool"), 0o755);
    exe(&home.join("bin1/tool"), 0o755);
    exe(&home.join(".local/bin/claude"), 0o755);
    std::fs::create_dir_all(home.join("work/projects/tmp/uzakgoz")).unwrap();
    std::fs::write(home.join("work/projects/tmp/uzakgoz/Cargo.toml"), "").unwrap();
    std::fs::create_dir_all(home.join("der/Cargo.toml")).unwrap(); // dizin: isfile yanlış
    std::fs::create_dir_all(home.join("reader")).unwrap();
    std::fs::write(home.join("reader/index.html"), "").unwrap();
    std::os::unix::fs::symlink(home.join("reader"), home.join("rl")).unwrap();
    let root = e.root.display().to_string();
    let mut cmd = e.command("files", PY_READ);
    cmd.arg(&root);
    let mut child = cmd.spawn().unwrap();
    std::io::Write::write_all(&mut child.stdin.take().unwrap(), CASES.as_bytes()).unwrap();
    let o = child.wait_with_output().unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let py_out = j(String::from_utf8(o.stdout).unwrap().trim_end());
    let env = SysEnv {
        home: Some(home.display().to_string()),
        path: Some(format!("{root}/home/bin1:{root}/home/bin2:{root}/home/bin1").into()),
    };
    let cases = j(CASES);
    let py_rows = py_out.as_array().unwrap();
    for (i, c) in cases.as_array().unwrap().iter().enumerate() {
        let s = Settings::from_text(Some(&c.to_compact()));
        let rs = rust_read(&s, &env, &root);
        assert_eq!(
            rs.to_compact(),
            py_rows[i].to_compact(),
            "durum {i}: {}",
            c.to_compact()
        );
    }
}

fn obj1(key: &str, v: Json) -> Json {
    obj(vec![(key, v)])
}

fn strs(v: &[String]) -> Json {
    Json::Array(v.iter().map(|x| Json::from(x.as_str())).collect())
}

/// Sınır durumları: uzunluk sınırları, tavanlar, sözlük olmayan bloklar, kırpma, tanınmayan değerler.
fn boundary_cases() -> Vec<Json> {
    let text = |t: &str| Json::from(t);
    let mut v: Vec<Json> = Vec::new();
    // sözlük olması gereken bloklar sözlük değil
    for block in [
        "ucli_web",
        "ucli_cost",
        "ucli_usage_warn",
        "ucli_limits",
        "ucli_script",
    ] {
        for bad in ["null", "\"oops\"", "[\"x\"]", "7", "[]", "true"] {
            v.push(obj1(block, j(bad)));
        }
    }
    for value in ["null", "\"\"", "\" \"", "\"turbo\"", "\"5\"", "\"mid\""] {
        v.push(obj1("ucli_limits", obj1("reasoning_effort", j(value))));
    }
    for mode in ["read", " READ ", "Read", "full", " FULL "] {
        v.push(obj1("ucli_script", obj1("mode", text(mode))));
    }
    // ucli_web: flavor'sız geçerli adres, kırpma, geçersiz alan adları, tek etiket, uzunluk sınırları, tavan
    for url in [
        "  http://127.0.0.1:8888/search  ",
        "\n  http://h/s \t\n",
        "http://127.0.0.1:8888/search",
    ] {
        v.push(obj1("ucli_web", obj1("search_url", text(url))));
    }
    let l63 = "x".repeat(63);
    let l64 = "x".repeat(64);
    let host253 = format!("{l63}.{l63}.{l63}.{}", "y".repeat(61));
    let host254 = format!("{l63}.{l63}.{l63}.{}", "y".repeat(62));
    let bad = [
        "*.org",
        "https://a.org",
        "a.org/path",
        "a_b.org",
        "-a.org",
        "a-.org",
        "a..org",
        "a.org:8080",
        &format!("{l64}.org"),
        ".org",
        "org.",
        "a@b.org",
        "ü.org",
        &host254,
    ]
    .join(",");
    for domains in [
        format!("{bad},ok.org"),
        "localhost".to_string(),
        format!("{l63}.org"),
        host253.clone(),
        host254.clone(),
        "a,1,a-1".to_string(),
        (0..200)
            .map(|i| format!("h{i}.example.org"))
            .collect::<Vec<_>>()
            .join(","),
    ] {
        v.push(obj1(
            "ucli_web",
            obj1("allow_fetch_domains", text(&domains)),
        ));
    }
    // ucli_services: kimlik ve env uzunluk sınırları, env reddi, model ve effort tavanları
    let svc = |id: &str, env: &str| {
        obj(vec![
            ("id", text(id)),
            ("env", text(env)),
            ("endpoint", text("https://a/v1/")),
        ])
    };
    for (id, env) in [
        ("a", "OK_KEY"),
        ("ab", "OK_KEY"),
        (&"a".repeat(20), "OK_KEY"),
        (&"a".repeat(21), "OK_KEY"),
        ("ok1", "AB"),
        ("ok1", "ABC"),
        ("ok1", &"A".repeat(40)),
        ("ok1", &"A".repeat(41)),
        ("ok1", "lower"),
        ("ok1", "1ABC"),
        ("ok1", "_ABC"),
        ("ok1", "AB-C"),
        ("ok1", "ABc"),
        ("ok1", ""),
        ("1ab", "OK_KEY"),
    ] {
        v.push(obj1("ucli_services", Json::Array(vec![svc(id, env)])));
    }
    let models: Vec<String> = (0..70).map(|i| format!("m{i}")).collect();
    let efforts = Json::Object((0..25).map(|i| (format!("m{i}"), j("[\"low\"]"))).collect());
    let mut full = svc("ok1", "OK_KEY");
    if let Some(m) = full.as_object_mut() {
        m.insert("models".into(), strs(&models));
        m.insert("efforts".into(), efforts);
    }
    v.push(obj1("ucli_services", Json::Array(vec![full])));
    v
}

#[test]
fn settings_boundaries_match_python() {
    let e = Env::new();
    let root = e.root.display().to_string();
    let cases = boundary_cases();
    let input = Json::Array(cases.clone()).to_compact();
    let mut cmd = e.command("files", PY_READ);
    cmd.arg(&root);
    let mut child = cmd.spawn().unwrap();
    std::io::Write::write_all(&mut child.stdin.take().unwrap(), input.as_bytes()).unwrap();
    let o = child.wait_with_output().unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let py_out = j(String::from_utf8(o.stdout).unwrap().trim_end());
    // PY_READ'in PATH'i ile aynı
    let env = SysEnv {
        home: Some(e.root.join("home").display().to_string()),
        path: Some(format!("{root}/home/bin1:{root}/home/bin2:{root}/home/bin1").into()),
    };
    let py_rows = py_out.as_array().unwrap();
    assert_eq!(py_rows.len(), cases.len());
    for (i, c) in cases.iter().enumerate() {
        let s = Settings::from_text(Some(&c.to_compact()));
        assert_eq!(
            rust_read(&s, &env, &root).to_compact(),
            py_rows[i].to_compact(),
            "durum {i}: {}",
            c.to_compact()
        );
    }
}

/// Sınırların beklenen değerleri (parite iki tarafın birlikte kaymasını yakalamaz).
#[test]
fn settings_boundary_values() {
    let s = |t: &str| Settings::from_text(Some(t));
    for block in ["[\"x\"]", "\"oops\"", "7", "null"] {
        let a = s(&format!(
            r#"{{"ucli_web": {block}, "ucli_cost": {block}, "ucli_usage_warn": {block}}}"#
        ));
        assert_eq!(a.ucli_web_config(), j(r#"{"search_docker": true}"#));
        assert_eq!(a.get("ucli_web"), Some(&Json::object()));
        let (amber, red) = a.ucli_usage_warn_thresholds();
        assert_eq!(
            (amber.as_i64(), red.as_i64()),
            (Some(1_000_000), Some(3_000_000))
        );
        let c = a.ucli_cost_config();
        assert_eq!(
            (c.daily_cap_usd, c.credit_total_usd, c.cache_ttl.as_str()),
            (0.0, 0.0, "1h")
        );
    }
    assert_eq!(
        s(r#"{"ucli_limits": {"reasoning_effort": "turbo"}}"#).ucli_reasoning_mode(),
        "auto"
    );
    assert_eq!(
        s(r#"{"ucli_script": {"mode": " Read "}}"#).ucli_script_mode(),
        "read"
    );
    assert_eq!(
        s(r#"{"ucli_web": {"search_url": "  http://h/s \n"}}"#).ucli_web_config(),
        j(r#"{"search_url": "http://h/s", "search_flavor": "searxng"}"#)
    );
    let domains = |text: &str| -> usize {
        s(&format!(
            r#"{{"ucli_web": {{"allow_fetch_domains": "{text}"}}}}"#
        ))
        .ucli_web_config()
        .get("allow_fetch_domains")
        .and_then(Json::as_array)
        .map_or(0, <[Json]>::len)
    };
    let l63 = "x".repeat(63);
    assert_eq!(domains("localhost"), 1);
    assert_eq!(domains(&format!("{l63}.org")), 1);
    assert_eq!(domains(&format!("{l63}x.org")), 0);
    assert_eq!(
        domains(&format!("{l63}.{l63}.{l63}.{}", "y".repeat(61))),
        1,
        "253"
    );
    assert_eq!(
        domains(&format!("{l63}.{l63}.{l63}.{}", "y".repeat(62))),
        0,
        "254"
    );
    let many: Vec<String> = (0..200).map(|i| format!("h{i}.org")).collect();
    assert_eq!(domains(&many.join(",")), 64);
    let ids = |id: &str, env: &str| -> usize {
        s(&format!(
            r#"{{"ucli_services": [{{"id": "{id}", "env": "{env}", "endpoint": "https://a"}}]}}"#
        ))
        .ucli_services()
        .len()
            - 1 // evren
    };
    assert_eq!((ids("a", "KEY"), ids("ab", "KEY")), (0, 1));
    assert_eq!(
        (ids(&"a".repeat(20), "KEY"), ids(&"a".repeat(21), "KEY")),
        (1, 0)
    );
    assert_eq!((ids("ab", "KE"), ids("ab", "KEY")), (0, 1));
    assert_eq!(
        (ids("ab", &"K".repeat(40)), ids("ab", &"K".repeat(41))),
        (1, 0)
    );
    assert_eq!(ids("ab", "lower"), 0);
    let models: Vec<String> = (0..70).map(|i| format!("\"m{i}\"")).collect();
    let efforts: Vec<String> = (0..25).map(|i| format!("\"m{i}\": [\"low\"]")).collect();
    let out = s(&format!(
        r#"{{"ucli_services": [{{"id": "ab", "env": "KEY", "endpoint": "https://a", "models": [{}], "efforts": {{{}}}}}]}}"#,
        models.join(","),
        efforts.join(",")
    ))
    .ucli_services();
    let svc = &out[1];
    assert_eq!(
        svc.get("models")
            .and_then(Json::as_array)
            .map(<[Json]>::len),
        Some(60)
    );
    assert_eq!(
        svc.get("efforts")
            .and_then(Json::as_object)
            .map(|m| m.len()),
        Some(20)
    );
}

/// Sözlük olması gereken HER anahtar (ve diğerleri) sözlük olmayan değerle: tam `load_settings` çıktısı Python ile aynı.
#[test]
fn every_key_with_wrong_type_matches_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        r#"
from claudeops import settings as s
for bad in (5, 'x', [1], None):
    with open(s.SETTINGS_JSON, 'w', encoding='utf-8') as f:
        json.dump({k: bad for k in s.DEFAULT_SETTINGS}, f)
    s._LOAD_CACHE['sig'] = None
    print(json.dumps(s.load_settings(), ensure_ascii=False))
"#,
    );
    let mut lines = out.lines();
    for bad in ["5", "\"x\"", "[1]", "null"] {
        let all = Json::Object(
            cops_state::settings::defaults()
                .keys()
                .map(|k| (k.clone(), j(bad)))
                .collect(),
        );
        let got = Settings::from_text(Some(&all.to_compact()));
        assert_eq!(
            Json::Object(got.as_map().clone()).to_compact(),
            lines.next().unwrap(),
            "{bad}"
        );
        let dicts = got
            .as_map()
            .values()
            .filter(|v| **v == Json::object())
            .count();
        assert_eq!(dicts, 12, "sözlük anahtarlarının tamamı {{}}");
    }
}

/// Değişmeyen dosya yeniden ayrıştırılmaz (aynı `Arc`); değişince yeni nesne. Python da bir kez ayrıştırır.
#[test]
fn settings_cache_hit() {
    let e = Env::new();
    e.write("settings.json", r#"{"fleet_sort": "cwd"}"#);
    let r = cops_state::settings::SettingsReader::new(e.dir());
    let first = r.load();
    for _ in 0..5 {
        assert!(std::sync::Arc::ptr_eq(&first, &r.load()));
    }
    assert_eq!(first.str_of("fleet_sort"), "cwd");
    e.write("settings.json", r#"{"fleet_sort": "name "}"#);
    let second = r.load();
    assert!(!std::sync::Arc::ptr_eq(&first, &second));
    assert_eq!(second.str_of("fleet_sort"), "name ");
    let py = e.py(
        "files",
        r#"
from claudeops import settings as s
n = []
f = s._load_settings_uncached
s._load_settings_uncached = lambda: (n.append(1), f())[1]
for _ in range(5):
    s.load_settings()
print(len(n))
"#,
    );
    assert_eq!(py.trim_end(), "1");
}

/// `_backup_if_corrupt`: dosya yok ya da boşsa yedek de hata da yok (Python aynı).
#[test]
fn missing_or_empty_settings_not_backed_up() {
    let e = Env::new();
    let corrupt = || {
        std::fs::read_dir(&e.state)
            .unwrap()
            .filter(|x| {
                x.as_ref()
                    .unwrap()
                    .file_name()
                    .to_string_lossy()
                    .contains(".corrupt-")
            })
            .count()
    };
    let py = "from claudeops import settings as s\ns._backup_if_corrupt()\nprint('ok')";
    assert!(cops_state::settings::backup_if_corrupt(&e.dir()).is_none());
    assert_eq!(e.py("files", py).trim_end(), "ok");
    assert!(!e.dir().settings_json().exists());
    e.write("settings.json", " \n\t");
    assert!(cops_state::settings::backup_if_corrupt(&e.dir()).is_none());
    e.py("files", py);
    assert_eq!(corrupt(), 0);
}

#[test]
fn defaults_lists_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        "from claudeops import settings as s\nprint(json.dumps([s.DEFAULT_UCLI_SERVICES, sorted(s._ON_WORDS), list(s.UCLI_REASONING_LEVELS), \
         s.USAGE_WARN_DEFAULTS, s._MAX_FETCH_DOMAINS, s.UZAKGOZ_DEFAULT_DIR, s.DERBENT_DEFAULT_DIR, s._KNOWN_BINARY_PATHS, \
         [s.UCLI_STREAM_DEFAULT, s.UCLI_SHOW_REASONING_DEFAULT, s.UCLI_STATE_DIR_DEFAULT]], ensure_ascii=False))",
    );
    let mut on: Vec<&str> = settings_read::ON_WORDS.to_vec();
    on.sort_unstable();
    let arr = |v: &[&str]| Json::Array(v.iter().map(|x| Json::from(*x)).collect());
    let rs = Json::Array(vec![
        Json::Array(settings_read::default_ucli_services().to_vec()),
        arr(&on),
        arr(&settings_read::UCLI_REASONING_LEVELS),
        obj(vec![
            ("amber", Json::Int(settings_read::USAGE_WARN_DEFAULTS.0)),
            ("red", Json::Int(settings_read::USAGE_WARN_DEFAULTS.1)),
        ]),
        Json::Int(settings_read::MAX_FETCH_DOMAINS as i64),
        settings_read::UZAKGOZ_DEFAULT_DIR.into(),
        settings_read::DERBENT_DEFAULT_DIR.into(),
        obj(vec![(
            "claude",
            arr(settings_read::known_binary_paths("claude")),
        )]),
        Json::Array(vec![
            settings_read::UCLI_STREAM_DEFAULT.into(),
            settings_read::UCLI_SHOW_REASONING_DEFAULT.into(),
            settings_read::UCLI_STATE_DIR_DEFAULT.into(),
        ]),
    ]);
    assert_eq!(rs.to_compact(), out.trim_end());
}

const NUMS: &[&str] = &[
    "0",
    " 12 ",
    "+5",
    "-0",
    "1_000",
    "1__0",
    "_1",
    "1_",
    "٣٤",
    "١_٢",
    "1٣",
    "12a",
    "",
    " ",
    "0x10",
    "1e3",
    "1.0",
    "−5",
    "\u{a0}12\u{3000}",
    "\u{1c}5",
    "5\u{1c}",
    "007",
    "99999999999999999999999",
    "+_1",
    "1 2",
    "inf",
    "Infinity",
    "-nan",
    "+NaN",
    "1e-5",
    ".5",
    "5.",
    ".",
    "1_0.5",
    "1_.5",
    "1._5",
    "1e1_0",
    "1e_10",
    "١.٥",
    "nan(1)",
    "1e400",
    "-1e400",
    "0.1e",
    "e5",
    "+.5",
    "-.e1",
    " 1.5 ",
    "1,5",
    "-",
    "+",
    "1e+5",
    "1E-0_1",
    "\t-7\n",
    "²",
    "1\u{0}",
    "123456789012345678901234567890.5",
    "4.9e-325",
    "0_0",
    "00_1",
    "infinityx",
    "Inf",
    "-iNF",
    "\u{2028}3",
    "0.30000000000000004",
    "1.7976931348623159e308",
];

#[test]
fn int_float_parse_match_python() {
    let e = Env::new();
    let input = Json::Array(NUMS.iter().map(|s| Json::from(*s)).collect()).to_compact();
    let out = e.py_in(
        "files",
        r#"
def f(x):
    try:
        v = float(x)
        return repr(v)
    except ValueError:
        return None
def i(x):
    try:
        return str(int(x))
    except ValueError:
        return None
xs = json.load(sys.stdin)
print(json.dumps([[i(x), f(x)] for x in xs]))
"#,
        &input,
    );
    let rs = Json::Array(
        NUMS.iter()
            .map(|s| {
                let i = py::parse_int(s).map_or(Json::Null, |n| n.to_string().into());
                let f =
                    py::parse_float(s).map_or(Json::Null, |v| py::str_of(&Json::Float(v)).into());
                Json::Array(vec![i, f])
            })
            .collect(),
    );
    assert_eq!(rs.to_compact(), out.trim_end());
}

/// R-B2a-1: Python `int()` 4300 haneden uzun ondalık metni reddeder (`sys.int_info.str_digits_check_threshold`; baştaki
/// sıfırlar sayılır, alt çizgi, işaret ve boşluk sayılmaz). `/api/term/history` `start`/`end` bu yüzden 400 `invalid_range`.
#[test]
fn int_digit_limit_matches_python() {
    let e = Env::new();
    let r = |s: &str, n: usize| s.repeat(n);
    let xs: Vec<String> = vec![
        r("1", 4300),
        r("1", 4301),
        r("0", 4300),
        r("0", 4301),
        r("0", 5000),
        format!("{}1", r("1_", 2200)),
        format!("{}1", r("1_", 4300)),
        format!("-{}", r("9", 4300)),
        format!("+{}", r("9", 4301)),
        format!("  {}\n", r("7", 4300)),
        format!(" {} ", r("7", 4301)),
        r("\u{0661}", 4301),
    ];
    let input = Json::Array(xs.iter().map(|s| Json::from(s.as_str())).collect()).to_compact();
    let out = e.py_in(
        "files",
        r#"
def i(x):
    try:
        return str(int(x))
    except ValueError:
        return None
xs = json.load(sys.stdin)
print(json.dumps([i(x) for x in xs]))
"#,
        &input,
    );
    let rs = Json::Array(
        xs.iter()
            .map(|s| py::parse_int(s).map_or(Json::Null, |n| n.to_string().into()))
            .collect(),
    );
    assert_eq!(rs.to_compact(), out.trim_end());
}

#[test]
fn str_repr_match_python() {
    let e = Env::new();
    let vals = j(
        r#"[null, true, false, 0, -7, 12345678901234567890123, 1.0, 1e16, 1e-5, 2.5e-300, 1e400, -1e400,
        "düz", "a'b", "a\"b", "a'\"b", "\\", "\u0000\u0007\b\t\n\r\u000b\u001f\u007f\u0080\u009f\u00a0\u00adé",
        "\u2028\u2029\u200b\u3000\ue000\ufeff\ufffe", "\ud83d\ude00", "\udb40\udc01", "\ud800\udc00",
        [], {}, [1, "x", [null]], {"k'": "v", "": {"a": [1.5]}}]"#,
    );
    let out = e.py_in(
        "files",
        "vals = json.load(sys.stdin)\nprint(json.dumps([[str(v), repr(v)] for v in vals], ensure_ascii=False))",
        &vals.to_compact(),
    );
    let rs = Json::Array(
        vals.as_array()
            .unwrap()
            .iter()
            .map(|v| Json::Array(vec![py::str_of(v).into(), py::repr(v).into()]))
            .collect(),
    );
    assert_eq!(rs.to_compact(), out.trim_end());
}

/// `unicode_tables.rs` Python 3.10 `unicodedata`/`str` yöntemleriyle aynı (her kod noktası).
#[test]
fn unicode_tables_match_python() {
    let e = Env::new();
    let out = e.py(
        "files",
        r#"
import unicodedata
from claudeops import settings as s
def ranges(pred):
    out, start = [], None
    for c in range(0x110000):
        p = pred(c)
        if p and start is None: start = c
        if not p and start is not None: out.append([start, c - 1]); start = None
    if start is not None: out.append([start, 0x10FFFF])
    return out
skip = lambda c: 0xD800 <= c <= 0xDFFF
print(json.dumps([
  ranges(lambda c: not skip(c) and not chr(c).isprintable()),
  ranges(lambda c: not skip(c) and chr(c).isspace()),
  ranges(lambda c: not skip(c) and unicodedata.decimal(chr(c), None) is not None),
  [c for c in range(0x110000) if not skip(c) and unicodedata.decimal(chr(c), -1) == 0],
  [c for c in range(0x80, 0x110000) if not skip(c) and not s._valid_http_url('http://a' + chr(c) + 'b')],
  ranges(lambda c: not skip(c) and chr(c).isalnum()),
]))
"#,
    );
    let ranges = |pred: &dyn Fn(char) -> bool| {
        let mut out: Vec<Json> = Vec::new();
        let mut start: Option<u32> = None;
        for c in 0..=0x10FFFFu32 {
            let p = char::from_u32(c).is_some_and(pred);
            match (p, start) {
                (true, None) => start = Some(c),
                (false, Some(s)) => {
                    out.push(Json::Array(vec![
                        Json::Int(s.into()),
                        Json::Int((c - 1).into()),
                    ]));
                    start = None;
                }
                _ => {}
            }
        }
        if let Some(s) = start {
            out.push(Json::Array(vec![Json::Int(s.into()), Json::Int(0x10FFFF)]));
        }
        Json::Array(out)
    };
    let py_v = j(out.trim_end());
    let py_a = py_v.as_array().unwrap();
    // vekil aralığı (D800..DFFF) Rust char'ı değil; Python tarafında atlandı, aralık sınırları uyuşsun diye
    // yazdırılamazlar listesinde Rust tarafı da onu atlar (char::from_u32 None).
    assert_eq!(ranges(&|c| !py::is_printable(c)), py_a[0], "isprintable");
    assert_eq!(ranges(&py::is_space), py_a[1], "isspace");
    assert_eq!(
        ranges(&|c| py::decimal_value(c).is_some()),
        py_a[2],
        "decimal"
    );
    let zeros: Vec<Json> = (0..=0x10FFFFu32)
        .filter(|c| char::from_u32(*c).is_some_and(|ch| py::decimal_value(ch) == Some(0)))
        .map(|c| Json::Int(c.into()))
        .collect();
    assert_eq!(Json::Array(zeros), py_a[3], "sıfırlar");
    // `_valid_http_url` her ASCII dışı kod noktasında (NFKC netloc denetimi, boşluk reddi) aynı
    let bad: Vec<Json> = (0x80..=0x10FFFFu32)
        .filter(|c| {
            char::from_u32(*c)
                .is_some_and(|ch| !settings_read::valid_http_url(&format!("http://a{ch}b")))
        })
        .map(|c| Json::Int(c.into()))
        .collect();
    assert_eq!(Json::Array(bad), py_a[4], "NFKC netloc");
    assert_eq!(
        ranges(&|c| py::is_alnum_str(c.encode_utf8(&mut [0; 4]))),
        py_a[5],
        "isalnum"
    );
    assert!(!py::is_alnum_str(""), "boş dize: Python False");
}

#[test]
fn expanduser_and_proc_match_python() {
    let e = Env::new();
    let paths = [
        "~",
        "~/",
        "~//x",
        "~/a/b",
        "x~",
        "",
        "~root",
        "~root/x",
        "~nosuchuserxyz/a",
        "~nosuchuserxyz",
        "/abs",
        "~~",
    ];
    let homes: [Option<&str>; 5] = [Some("/h"), Some("/h/"), Some(""), Some("/"), None];
    let input = Json::Array(paths.iter().map(|s| Json::from(*s)).collect()).to_compact();
    let out = e.py_in(
        "files",
        r#"
ps = json.load(sys.stdin)
res = []
orig = os.environ['HOME']
for h in ['/h', '/h/', '', '/', None]:
    if h is None:
        os.environ.pop('HOME', None)
    else:
        os.environ['HOME'] = h
    res.append([os.path.expanduser(p) for p in ps])
os.environ['HOME'] = orig
from claudeops import paths
stats = ['1 (a b) c) S 7 8 9', '1 (x)', '2 abc', '3 (ç)\u3000R\u20281 2']
def ps_(r):
    try:
        return paths.parse_proc_stat(r)
    except ValueError:
        return None
print(json.dumps([res, [ps_(r) for r in stats]], ensure_ascii=False))
"#,
        &input,
    );
    let res: Vec<Json> = homes
        .iter()
        .map(|h| {
            Json::Array(
                paths
                    .iter()
                    .map(|p| Json::from(expanduser_with(p, *h)))
                    .collect(),
            )
        })
        .collect();
    let stats = [
        "1 (a b) c) S 7 8 9",
        "1 (x)",
        "2 abc",
        "3 (\u{e7})\u{3000}R\u{2028}1 2",
    ];
    let ps: Vec<Json> = stats
        .iter()
        .map(|r| {
            parse_proc_stat(r).map_or(Json::Null, |v| {
                Json::Array(v.into_iter().map(Json::from).collect())
            })
        })
        .collect();
    // `ucli_key_file` süreç `HOME`unu okur: paritesi `env_paths.rs`te (geçici `HOME`)
    let rs = Json::Array(vec![Json::Array(res), Json::Array(ps)]);
    assert_eq!(rs.to_compact(), out.trim_end());
}

/// H3: okunamayan (G/Ç hatası) settings.json varsayılanları döndürür (Python gibi) ama önbelleği EZMEZ: son iyi değer
/// korunur, N+1. hatada da varsayılan döner, hata geçince yeni içerik okunur (Python ile aynı, TBD#374 S7).
#[test]
fn settings_io_error_keeps_last_good() {
    let e = Env::new();
    let p = e.dir().settings_json();
    std::fs::write(&p, r#"{"theme": "dark"}"#).unwrap();
    let r = cops_state::settings::SettingsReader::new(e.dir());
    assert_eq!(r.load().str_of("theme"), "dark");
    std::fs::write(&p, r#"{"theme": "light", "x": 1}"#).unwrap(); // yeni imza
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o000)).unwrap();
    if std::fs::read(&p).is_ok() {
        return; // root: izin hatası üretilemez
    }
    for _ in 0..5 {
        assert_eq!(
            r.load().str_of("theme"),
            "system",
            "hata: varsayılan (Python ile aynı)"
        );
        assert_eq!(
            r.last_good().unwrap().str_of("theme"),
            "dark",
            "son iyi değer ezilmedi"
        );
    }
    let py = e.py(
        "files",
        "from claudeops import settings as s\na = s.load_settings()['theme']\nos.chmod(s.SETTINGS_JSON, 0o644)\nprint(a, s.load_settings()['theme'])",
    );
    assert_eq!(py.trim(), "system light", "Python: hata önbelleğe girmez");
    assert_eq!(
        r.load().str_of("theme"),
        "light",
        "Rust: hata geçince yeni içerik"
    );
}

/// TBD#374 S2: bozuk/UTF-8 olmayan settings.json iki dilde de varsayılanlara düşer; `store_backend` son iyi değeri korur.
#[test]
fn settings_corrupt_keeps_store_backend_like_python() {
    for bad in [&b"{\"theme\": \"dark\xff\"}"[..], b"{yarim", b"[1]"] {
        let e = Env::new();
        let p = e.dir().settings_json();
        std::fs::write(&p, r#"{"store_backend": "db", "theme": "dark"}"#).unwrap();
        let r = cops_state::settings::SettingsReader::new(e.dir());
        assert_eq!(r.load().str_of("store_backend"), "db");
        std::fs::write(e.root.join("bad"), bad).unwrap();
        let py = e.py(
            "files",
            &format!(
                "from claudeops import settings as s\na = s.load_settings()\nos.replace('{}', s.SETTINGS_JSON)\nb = s.load_settings()\nprint(a['store_backend'], b['store_backend'], b['theme'])",
                e.root.join("bad").display()
            ),
        );
        assert_eq!(py.trim(), "db db system");
        std::fs::write(&p, bad).unwrap();
        let got = r.load();
        assert_eq!(got.str_of("store_backend"), "db");
        assert_eq!(got.str_of("theme"), "system");
        // silinen dosya düz varsayılandır
        std::fs::remove_file(&p).unwrap();
        assert_eq!(r.load().str_of("store_backend"), "files");
    }
}
