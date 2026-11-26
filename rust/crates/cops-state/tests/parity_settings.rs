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
    let err = |e: settings_read::SettingsTypeError| obj(vec![("error", e.python.into())]);
    let bin: Vec<Json> = [
        "tool",
        "claude",
        "noexec",
        "yok",
        &format!("{root}/home/bin2/tool"),
    ]
    .iter()
    .map(|x| s.resolved_binary(x, env).map_or_else(err, Json::from))
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
        ("services", s.ucli_services().map_or_else(err, Json::Array)),
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
print(json.dumps([res, [ps_(r) for r in stats], paths.ucli_key_file(''), paths.ucli_key_file('grok')], ensure_ascii=False))
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
    let home = e.root.join("home").display().to_string();
    let key = |s: &str| {
        let name = if s.is_empty() {
            "ucli_api_key".into()
        } else {
            format!("ucli_key_{s}")
        };
        expanduser_with(&format!("~/.claude/claudeops/{name}"), Some(&home))
    };
    let rs = Json::Array(vec![
        Json::Array(res),
        Json::Array(ps),
        key("").into(),
        key("grok").into(),
    ]);
    assert_eq!(rs.to_compact(), out.trim_end());
    // ucli_key_file kendi işlevi: süreç HOME'u ile aynı kural
    assert!(cops_state::paths::ucli_key_file("x").ends_with("/.claude/claudeops/ucli_key_x"));
}

/// H3: okunamayan (G/Ç hatası) settings.json varsayılanları döndürür (Python gibi) ama önbelleği EZMEZ: son iyi değer
/// korunur, N+1. hatada da varsayılan döner, hata geçince yeni içerik okunur (Python bu imzada varsayılanda kalır).
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
    assert_eq!(
        py.trim(),
        "system system",
        "Python: hata imzası önbellekte kalır"
    );
    assert_eq!(
        r.load().str_of("theme"),
        "light",
        "Rust: hata geçince yeni içerik"
    );
}

/// Sahibe soruldu S2: UTF-8 olmayan settings.json. Python `load_settings` istisna fırlatır; Rust varsayılanlara düşer.
#[test]
fn settings_non_utf8_documented_divergence() {
    let e = Env::new();
    std::fs::write(e.dir().settings_json(), b"{\"theme\": \"dark\xff\"}").unwrap();
    let py = e.py(
        "files",
        "from claudeops.settings import load_settings\ntry:\n    load_settings(); print('ok')\nexcept Exception as ex:\n    print(type(ex).__name__)",
    );
    assert_eq!(py.trim(), "UnicodeDecodeError");
    assert_eq!(
        cops_state::settings::load(&e.dir()).str_of("theme"),
        "system"
    );
}
