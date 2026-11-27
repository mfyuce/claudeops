//! Aile (G8): gerçek uygulayıcı (`real`) Python'un aynı geçici ağaçtaki davranışıyla karşılaştırılır: yol çözümü,
//! araç zinciri, `run_checks` kaydı, ajan token'ı, diag günlüğü, `agy_sids` yazımı, `--help` yoklaması ve MCP kaydı
//! (iki tarafta da GERÇEK alt süreç: yalnız vaka ağacındaki sahte kabuk betikleri) ve `urllib` proxy kuralları.

use crate::common::*;
use crate::fam_bg::Rng;
use cops_providers::agy_resume::remember_agy_sid;
use cops_providers::pyjson::Py;
use cops_providers::real::agents::{AgentRegistry, Sources};
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::docs::DocAgySidStore;
use cops_providers::real::help::HelpCache;
use cops_providers::real::proxy::{self, Route};
use cops_providers::real::{checks, pathexec, RealProbe};
use cops_providers::spawn_exec::DiagSink;
use cops_providers::{AgySidStore, BuildOutput, Cli, Diag, McpSpec, Probe, Providers};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::Arc;
use std::time::Duration;

const NOW: f64 = 1_790_000_000.25;

#[derive(Default)]
struct Collect(std::sync::Mutex<Vec<Diag>>);

impl DiagSink for Collect {
    fn log(&self, diag: &Diag) {
        self.0.lock().unwrap().push(diag.clone());
    }
}

fn script(rel: &str, body: &str) -> Fx {
    file(rel, &format!("#!/bin/sh\n{body}\n"), 0o755)
}

fn strs_of(v: &Value) -> Vec<&str> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_str().unwrap())
        .collect()
}

fn pairs(v: &Value) -> Vec<(&str, &str)> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|p| (p[0].as_str().unwrap(), p[1].as_str().unwrap()))
        .collect()
}

fn path_cases(e: &Env) -> Vec<Case> {
    let r = &e.root;
    let tree = || {
        vec![
            script("bin/alfa", "true"),
            script("bin2/alfa", "true"),
            script("bin2/beta.sh", "true"),
            file("bin2/okunur", "x", 0o644),
            script("bin2/-tire", "true"),
            script("bin2/bosluk ad", "true"),
            script("bin2/ğ", "true"),
            script("bin2/satir\n", "true"),
            script(&format!("bin2/{}", "u".repeat(65)), "true"),
            script(&format!("bin2/{}", "v".repeat(64)), "true"),
            Fx::Dir("bin2/dizin".into(), 0o755),
            Fx::Link("bin2/bag".into(), "alfa".into()),
            Fx::Link("bin2/kopuk".into(), "yok".into()),
            Fx::Dir("work/a/b/c".into(), 0o755),
            Fx::Link("work/k".into(), "a/b".into()),
            Fx::Link("work/mutlak".into(), format!("{r}/work/a")),
            Fx::Link("work/ust".into(), "../work/k/c".into()),
            Fx::Link("work/dongu1".into(), "dongu2".into()),
            Fx::Link("work/dongu2".into(), "dongu1".into()),
            Fx::Link("work/kendisi".into(), "kendisi".into()),
            Fx::Link("work/a/geri".into(), "..".into()),
        ]
    };
    // göreli yollar sürecin çalışma dizinine bağlıdır (iki tarafta farklı): `which` yalnız ad ve mutlak yolla sınanır
    let which = json!([
        "alfa",
        "beta.sh",
        "okunur",
        "dizin",
        "bag",
        "kopuk",
        "yok",
        "",
        ".",
        "..",
        format!("{r}/bin2/alfa"),
        format!("{r}/bin2/okunur"),
        format!("{r}/bin2"),
        "satir\n"
    ]);
    let mut real: Vec<String> = [
        "",
        ".",
        "..",
        "/",
        "//",
        "///x",
        "work",
        "work/k",
        "work/k/..",
        "work/k/c/../..",
        "work/yok/../k",
        "work/mutlak/b",
        "work/ust",
        "work/ust/..",
        "work/dongu1",
        "work/dongu1/x/y",
        "work/kendisi/z",
        "work/a/geri/work/k",
        "work/a/b/c/",
        "./work//k///c",
        "../../../..",
        "work/k/yok/..",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let parts = [
        "work", "a", "b", "c", "k", "mutlak", "ust", "dongu1", "kendisi", "geri", "..", ".", "",
        "yok",
    ];
    let mut rng = Rng(0x6731);
    for _ in 0..300 {
        let n = 1 + rng.below(7);
        let mut p: Vec<&str> = (0..n).map(|_| parts[rng.below(parts.len())]).collect();
        if rng.below(2) == 0 {
            p.insert(0, "work");
        }
        let joined = p.join("/");
        real.push(if rng.below(5) == 0 {
            format!("{r}/{joined}")
        } else {
            joined
        });
    }
    let paths = [
        format!("{r}/bin2:{r}/bin"),
        format!("{r}/bin:{r}/bin2:{r}/bin"),
        format!("{r}/yok:{r}/bin2/alfa:{r}/bin2"),
        String::new(),
        ":".to_string(),
        format!("::{r}/bin2:"),
    ];
    paths
        .iter()
        .enumerate()
        .map(|(i, path)| {
            let mut c = Case::new(
                format!("yol-{i}"),
                "g8_paths",
                json!({"which": which, "real": real}),
            )
            .env("PATH", path);
            c.files = tree();
            c
        })
        .collect()
}

fn toolchain_cases() -> Vec<Case> {
    let tc = |names: &[&str]| -> Vec<Fx> {
        names
            .iter()
            .flat_map(|n| {
                ["cargo", "rustc"]
                    .map(|t| file(&format!("home/.rustup/toolchains/{n}/bin/{t}"), "x", 0o644))
            })
            .collect()
    };
    let settings = |t: &[u8]| Fx::File("home/.rustup/settings.toml".into(), t.to_vec(), 0o600);
    let two = ["1.98.0-x86_64", "stable-x86_64"];
    let mut v = Vec::new();
    let mut add = |id: &str, files: Vec<Fx>, env: Option<&str>| {
        let mut c = Case::new(format!("zincir-{id}"), "g8_toolchain", json!({}));
        c.files = files;
        if let Some(w) = env {
            c = c.env("RUSTUP_TOOLCHAIN", w);
        }
        v.push(c);
    };
    add(
        "ayar-utf8-degil",
        [
            tc(&two),
            vec![settings(b"\xff\ndefault_toolchain = \"stable\"\n")],
        ]
        .concat(),
        None,
    );
    add("dizin-yok", vec![], None);
    add(
        "bos",
        vec![Fx::Dir("home/.rustup/toolchains".into(), 0o755)],
        None,
    );
    add(
        "dizin-dosya",
        vec![file("home/.rustup/toolchains", "x", 0o600)],
        None,
    );
    add("tek", tc(&["stable-x86_64"]), None);
    add(
        "eksik-rustc",
        vec![file("home/.rustup/toolchains/a/bin/cargo", "x", 0o644)],
        None,
    );
    add("iki", tc(&two), None);
    for want in ["stable", "1.98", "nightly", "", "s"] {
        add(&format!("istek-{want}"), tc(&two), Some(want));
    }
    add(
        "istek-iki-aday",
        tc(&["stable-a", "stable-b"]),
        Some("stable"),
    );
    for (i, text) in [
        &b"default_toolchain = \"stable-x86_64\"\n"[..],
        b"default_toolchain=\"stable\"",
        b"  \tdefault_toolchain   =   \"1.98.0\"  # yorum\n",
        b"version = \"12\"\r\ndefault_toolchain = \"stable\"\r\n",
        b"default_toolchain = \"\"\ndefault_toolchain = \"stable\"\n",
        b"default_toolchain = ' stable'\n",
        b"# default_toolchain = \"stable\"\n",
        b"default_toolchain = \"yok\"\n",
        b"default_toolchain = \" stable \"\n",
        b"x default_toolchain = \"stable\"\n",
        b"default_toolchains = \"stable\"\n",
        b"default_toolchain = \"stable\n\"\n",
    ]
    .iter()
    .enumerate()
    {
        let mut files = tc(&two);
        files.push(settings(text));
        add(&format!("ayar{i}"), files, None);
    }
    v
}

fn checks_cases() -> Vec<Case> {
    let owners = json!(["", "owner", "../x", "a b", "x\n", "ğ", "baska"]);
    let reg = |body: &[u8], mode: u32| {
        vec![Fx::File(
            "state/ucli_checks/owner.json".into(),
            body.to_vec(),
            mode,
        )]
    };
    let item = |name: &str, argv: &str| format!(r#"{{"check":[{{"name":{name},"argv":{argv}}}]}}"#);
    let mut bodies: Vec<(String, Vec<u8>)> = vec![
        ("iyi".into(), br#"{"version": 1, "check": [{"name": "unittest", "argv": ["python3", "-m"]}], "full": {"x": 1}}"#.to_vec()),
        ("bos-liste".into(), br#"{"check": []}"#.to_vec()),
        ("bos".into(), b"".to_vec()),
        ("bozuk".into(), b"{".to_vec()),
        ("utf8".into(), vec![0xff, b'{', b'}']),
        ("bom".into(), "\u{feff}{\"check\": []}".as_bytes().to_vec()),
        ("liste".into(), b"[]".to_vec()),
        ("check-nesne".into(), br#"{"check": {}}"#.to_vec()),
        ("oge-liste".into(), br#"{"check": [[]]}"#.to_vec()),
        ("yinelenen".into(), br#"{"check":[{"name":"a","argv":["x"]},{"name":"a","argv":["y"]}]}"#.to_vec()),
        ("inf-ve-dize".into(), br#"{"check":[{"name":"inf","argv":["x"]},{"name":Infinity,"argv":["y"]}]}"#.to_vec()),
        ("inf-iki".into(), br#"{"check":[{"name":Infinity,"argv":["x"]},{"name":Infinity,"argv":["y"]}]}"#.to_vec()),
        ("cok".into(), format!(r#"{{"check":[{}]}}"#, (0..201).map(|i| format!(r#"{{"name":"a{i}","argv":["x"]}}"#)).collect::<Vec<_>>().join(",")).into_bytes()),
        ("sinir".into(), format!(r#"{{"check":[{}]}}"#, (0..200).map(|i| format!(r#"{{"name":"a{i}","argv":["x"]}}"#)).collect::<Vec<_>>().join(",")).into_bytes()),
    ];
    let long = format!("\"{}\"", "a".repeat(49));
    let edge = format!("\"{}\"", "a".repeat(48));
    for (i, name) in [
        "null",
        "0",
        "5",
        "true",
        "false",
        "[]",
        "[\"a\"]",
        "{}",
        "\"\"",
        "\"A\"",
        "\"a b\"",
        "\"a\\n\"",
        "\"a\\n\\n\"",
        "NaN",
        "-Infinity",
        &long,
        &edge,
    ]
    .iter()
    .enumerate()
    {
        bodies.push((format!("ad{i}"), item(name, r#"["x"]"#).into_bytes()));
    }
    for (i, argv) in [
        "[]",
        "null",
        "\"x\"",
        "[\"\"]",
        "[1]",
        "[\"x\", null]",
        "{}",
        "[\" \"]",
    ]
    .iter()
    .enumerate()
    {
        bodies.push((format!("argv{i}"), item("\"a\"", argv).into_bytes()));
    }
    let mut v = Vec::new();
    let mut add = |id: String, files: Vec<Fx>| {
        let mut c = Case::new(
            format!("kayit-{id}"),
            "g8_checks",
            json!({"owners": owners}),
        );
        c.files = files;
        v.push(c);
    };
    for (id, body) in bodies {
        add(id, reg(&body, 0o600));
    }
    add("yok".into(), vec![]);
    for mode in [0o644, 0o640, 0o604, 0o700, 0o400, 0o000, 0o610] {
        add(format!("izin{mode:o}"), reg(br#"{"check": []}"#, mode));
    }
    add("derin".into(), reg(&vec![b'['; 100_000], 0o600));
    add(
        "dizin".into(),
        vec![Fx::Dir("state/ucli_checks/owner.json".into(), 0o700)],
    );
    add(
        "symlink".into(),
        vec![
            file("state/ucli_checks/real.json", r#"{"check": []}"#, 0o600),
            Fx::Link("state/ucli_checks/owner.json".into(), "real.json".into()),
        ],
    );
    add(
        "ust-dosya".into(),
        vec![file("state/ucli_checks", "x", 0o600)],
    );
    add(
        "buyuk".into(),
        reg(&vec![b' '; checks::MAX_BYTES as usize + 1], 0o600),
    );
    v
}

fn agent_cases() -> Vec<Case> {
    let basic = json!([
        ["issue", "p1"],
        ["lookup", "1"],
        ["issue", "p1"],
        ["lookup", "1"],
        ["lookup", "2"],
        ["issue", "p2"],
        ["revoke", "p1"],
        ["lookup", "2"],
        ["lookup", "3"],
        ["revoke", "p1"],
        ["revoke", "yok"]
    ]);
    let reject = json!([
        ["issue", "p1_aj1"],
        ["issue", ""],
        ["issue", "../x"],
        ["issue", "a b"],
        ["issue", ".a"],
        ["issue", "ğ"],
        ["issue", "a".repeat(101)],
        ["issue", "a".repeat(100)],
        ["issue", "satir\n"],
        ["issue", "p_aj0"],
        ["revoke", "../victim"]
    ]);
    let mut v = Vec::new();
    let state = |id: &str, body: &str, steps: &Value| {
        Case::new(
            format!("ajan-{id}"),
            "g8_agents",
            json!({"now": NOW, "steps": steps}),
        )
        .file(file("state/ucli_agents.json", body, 0o644))
    };
    v.push(Case::new(
        "ajan-temel",
        "g8_agents",
        json!({"now": NOW, "steps": basic}),
    ));
    v.push(
        Case::new(
            "ajan-ret",
            "g8_agents",
            json!({"now": 1_790_000_000.0, "steps": reject}),
        )
        .file(file("state/victim", "x", 0o600)),
    );
    for (i, body) in [
        "", "{", "[]", "5", "null", r#"{"parents": []}"#, r#"{"children": 3, "x": {"y": [1.5, true, null, "ğ", 1e300]}}"#,
        r#"{"parents": {"p1": {"seq": 7, "sha256": "eski", "issued": 1.0, "baska": []}}, "children": {"c": {}}}"#,
        r#"{"parents": {"p1": {"issued": 1}, "p2": 5}}"#,
        r#"{"children": {}, "parents": {"p1": []}}"#,
        r#"{"parents": {"p1": {"sha256": 5}, "p2": "x"}}"#,
        r#"{"parents": {}, "children": {}, "b": 123456789012345678901234567890}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(state(&format!("belge{i}"), body, &basic));
    }
    v.push(state("utf8-degil", "", &basic).file(Fx::File(
        "state/ucli_agents.json".into(),
        b"{\xff}".to_vec(),
        0o600,
    )));
    v.push(state("okunamaz", "", &basic).file(file(
        "state/ucli_agents.json",
        r#"{"parents": {}}"#,
        0o000,
    )));
    v.push(state("kilit-baglanti-degil", "{}", &basic).file(file(
        "state/ucli_agents.json.lock",
        "",
        0o600,
    )));
    v.push(
        Case::new(
            "ajan-token-dizini-dosya",
            "g8_agents",
            json!({"now": NOW, "steps": [["issue", "p1"]]}),
        )
        .file(file("state/ucli_agent_tokens", "x", 0o600)),
    );
    v.push(
        Case::new(
            "ajan-token-dizini-genis",
            "g8_agents",
            json!({"now": NOW, "steps": [["issue", "p1"]]}),
        )
        .file(Fx::Dir("state/ucli_agent_tokens".into(), 0o755))
        .file(Fx::Link(
            "state/ucli_agent_tokens/p1".into(),
            "../victim".into(),
        ))
        .file(file("state/victim", "x", 0o600)),
    );
    v
}

fn diag_cases() -> Vec<Case> {
    let events = json!([
        [
            "ucli_flag_unsupported",
            [["name", "s1"], ["flag", "--x"], ["binary", "/b"]]
        ],
        ["olay", []],
        [
            "türler",
            [
                ["b", true],
                ["n", null],
                ["i", -3],
                ["f", 1.5],
                ["l", ["a", 1, false]],
                ["s", "ğ\n\t\u{1}\"\\"]
            ]
        ],
        ["ezen", [["ts", "benim"], ["x", 1]]]
    ]);
    let c = |id: &str| Case::new(format!("gunluk-{id}"), "g8_diag", json!({"events": events}));
    vec![
        c("yeni"),
        c("ekle").file(file("state/diag.log", "{\"eski\": 1}\n", 0o640)),
        c("yol")
            .env("CLAUDEOPS_DIAG_LOG", "")
            .file(file("state/diag.log", "", 0o600)),
        c("dizin").file(Fx::Dir("state/diag.log".into(), 0o755)),
    ]
}

fn agy_cases() -> Vec<Case> {
    let writes = json!([
        ["a", "1"],
        ["b", "2"],
        ["a", "1"],
        ["a", "3"],
        ["ğ ad", "x\"y"]
    ]);
    let c = |id: &str| Case::new(format!("agy-{id}"), "g8_agy", json!({"writes": writes}));
    let doc = |body: &[u8], mode: u32| Fx::File("state/agy_sids.json".into(), body.to_vec(), mode);
    let mut v = vec![c("yeni")];
    for (i, body) in [
        &b"{}"[..],
        b"[]",
        b"{",
        b"",
        br#"{"z": "9", "a": "0", "n": 5, "o": {"k": [1.5, null]}}"#,
        br#"{"a": "1", "b": "2"}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(c(&format!("belge{i}")).file(doc(body, 0o640)));
    }
    v.push(
        c("symlink")
            .file(file("state/hedef", "{}", 0o600))
            .file(Fx::Link("state/agy_sids.json".into(), "hedef".into())),
    );
    v
}

const HELP_SCRIPT: &str = "printf 'bir\\r\\niki\\r\\n'; echo \"$@\"; echo hata >&2";

fn help_cases(e: &Env) -> Vec<Case> {
    let bins = ["tam", "bos", "bosluk", "hata", "izinsiz", "yok", "dizin"]
        .map(|b| format!("{}/bin/{b}", e.root));
    let calls: Vec<Value> = bins
        .iter()
        .flat_map(|b| [json!(["claude", b]), json!(["ucli", b]), json!(["ucli", b])])
        .collect();
    let mut calls = calls;
    calls.push(json!(["ucli", "tam"]));
    let bad = format!("{}/bin/utf8", e.root);
    calls.extend(["claude", "ucli", "claude", "ucli"].map(|k| json!([k, bad])));
    vec![Case::new("yardim", "g8_help", json!({"calls": calls}))
        .file(script("bin/tam", HELP_SCRIPT))
        .file(script("bin/bos", "true"))
        .file(script("bin/bosluk", "printf '  \\n\\t'"))
        .file(script("bin/hata", "echo '--flag'; exit 7"))
        .file(script("bin/utf8", "printf '\\377 --flag\\n'"))
        .file(file("bin/izinsiz", "#!/bin/sh\necho x\n", 0o644))
        .file(Fx::Dir("bin/dizin".into(), 0o755))]
}

fn mcp_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/work/p1", e.work.trim_end_matches("/work"));
    let spec = json!({"name": "cops-steward", "command": "/usr/bin/python3", "args": ["-m", "x", "a b"],
                      "allowed_tools": ["t1", "t.2", "kötü ad"]});
    let ucli = |body: &str| {
        script(
            "bin/ucli",
            &format!("case \"$1\" in chat) echo '--with-mcp <V>'; exit 0;; esac\n{body}"),
        )
    };
    let c = |id: &str, body: &str| {
        Case::new(
            format!("mcp-{id}"),
            "g8_mcp",
            json!({"spec": spec, "cwd": w, "timeout": 1}),
        )
        .file(ucli(body))
    };
    let record = "pwd > cwd.txt; for a in \"$@\"; do echo \"$a\"; done > args.txt";
    let old = || file("work/p1/.ucli/mcp.json", "eski", 0o600);
    vec![
        c("basarili", record),
        c(
            "eski-kayit",
            &format!("test ! -e .ucli/mcp.json && {record}"),
        )
        .file(old()),
        c("eski-bag", record)
            .file(file("home/hedef", "dokunma", 0o600))
            .file(Fx::Link(
                "work/p1/.ucli/mcp.json".into(),
                "../../../home/hedef".into(),
            )),
        c("kayit-dizin", record).file(Fx::Dir("work/p1/.ucli/mcp.json".into(), 0o755)),
        c("silinemez", record)
            .file(old())
            .file(Fx::Dir("work/p1/.ucli".into(), 0o500)),
        c("ucli-bag", record)
            .file(Fx::Dir("home/baska".into(), 0o755))
            .file(Fx::Link("work/p1/.ucli".into(), "../../home/baska".into())),
        c("bozuk-cikti", &format!("printf '\\377\\n'; {record}")),
        c("bozuk-cikti-hata", "printf 'hata \\377' >&2; exit 3"),
        c("cikis", "echo cikti; echo hata >&2; exit 3"),
        c("cikis-yalniz-stdout", "echo 'yalnız çıktı'; exit 4"),
        c(
            "cikis-uzun",
            "i=0; while [ $i -lt 60 ]; do echo \"satir $i ğüşiöç\" >&2; i=$((i+1)); done; exit 5",
        ),
        c("cikis-sessiz", "exit 6"),
        c("sinyal", "kill -KILL $$"),
        c("zaman-asimi", "exec sleep 20"),
        // `#!` yorumlayıcısı yok: `chat --help` de koşmaz, MCP bayrağı bilinmiyor
        Case::new(
            "mcp-calistirilamaz",
            "g8_mcp",
            json!({"spec": spec, "cwd": w, "timeout": 1}),
        )
        .file(file("bin/ucli", "#!/yok/yorumlayici\n", 0o755)),
    ]
}

/// `urllib` proxy kuralları (saf; ağ yok): rastgele ortam x hedef.
fn proxy_cases() -> Vec<Case> {
    const NAMES: [&str; 13] = [
        "http_proxy",
        "HTTP_PROXY",
        "Http_Proxy",
        "https_proxy",
        "HTTPS_PROXY",
        "no_proxy",
        "NO_PROXY",
        "all_proxy",
        "REQUEST_METHOD",
        "ftp_proxy",
        "_proxy",
        "xproxy",
        "http_PROXY",
    ];
    const VALUES: [&str; 40] = [
        "",
        "http://p:3128",
        "https://p:3128/",
        "p:3128",
        "p",
        "//p:1",
        "http://u:s@p:2",
        "u:s@p:2",
        "http://u@p:2",
        "http://u:@p",
        "http://:s@p",
        "http://k%40x:pa%3Ass@p%41:8/yol",
        "http://u:p@w@p:2",
        "socks5://p:1",
        "HTTP://P:1",
        "http:/p",
        "http:p",
        "/p",
        "//",
        "http://",
        "ftp://p",
        "http://p/a@b",
        "a/b",
        ":80",
        "@p",
        "u:s@",
        "*",
        "ornek.com",
        ".ornek.com",
        "a.com, .ornek.com ,,",
        "ornek.com:8080",
        "127.0.0.1",
        "ORNEK.COM",
        "com",
        "x*",
        " * ",
        "http://ğ:ş@p:1",
        "localhost,127.0.0.1",
        "[::1]:1",
        "%zz@p",
    ];
    const NETLOCS: [&str; 9] = [
        "ornek.com",
        "api.ornek.com",
        "ornek.com:8080",
        "API.Ornek.COM:443",
        "127.0.0.1:1",
        "localhost",
        "xornek.com",
        "ornek.com:",
        "[::1]:8",
    ];
    let mut rng = Rng(0x9921);
    let cases: Vec<Value> = (0..2500)
        .map(|_| {
            let mut env: Vec<(&str, &str)> = Vec::new();
            for _ in 0..rng.below(5) {
                let name = NAMES[rng.below(NAMES.len())];
                if env.iter().all(|(k, _)| *k != name) {
                    env.push((name, VALUES[rng.below(VALUES.len())]));
                }
            }
            let scheme = if rng.below(2) == 0 { "http" } else { "https" };
            json!([
                env,
                format!("{scheme}://{}/m", NETLOCS[rng.below(NETLOCS.len())])
            ])
        })
        .collect();
    vec![Case::new("vekil", "g8_proxy", json!({"cases": cases}))]
}

fn rs_proxy(case: &Value) -> Value {
    let env: Vec<(String, String)> = pairs(&case[0])
        .into_iter()
        .map(|(k, v)| (k.into(), v.into()))
        .collect();
    let (scheme, rest) = case[1].as_str().unwrap().split_once("://").unwrap();
    match proxy::route(&env, scheme, rest.split('/').next().unwrap()) {
        Route::Direct => json!(["direct"]),
        Route::Unusable => json!(["unusable"]),
        Route::Proxy {
            hostport,
            tls_to_proxy,
            auth,
        } => {
            let auth = auth.map(|a| String::from_utf8(a.expose().to_vec()).unwrap());
            json!(["proxy", hostport, tls_to_proxy, auth])
        }
    }
}

fn real(e: &Env, c: &Case) -> RealProbe {
    real_probe(e, c)
}

static SEQ: AtomicU8 = AtomicU8::new(0);

fn counted_entropy(buf: &mut [u8]) -> std::io::Result<()> {
    buf.fill(SEQ.fetch_add(1, Ordering::SeqCst) + 1);
    Ok(())
}

fn now_fixed() -> f64 {
    NOW
}

fn now_whole() -> f64 {
    1_790_000_000.0
}

fn rs_g8(e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    let probe = real(e, c);
    let paths = e.paths();
    match c.op {
        "g8_paths" => RsOut::ret(json!({
            "which": strs_of(&a["which"]).iter().map(|n| probe.which(n)).collect::<Vec<_>>(),
            "real": strs_of(&a["real"]).iter().map(|p| probe.realpath(p)).collect::<Vec<_>>(),
            "exec": probe.path_executables(),
        })),
        "g8_toolchain" => RsOut::ret(match pathexec::rust_toolchain(&e.home, &case_env(e, c)) {
            Ok(t) => {
                json!([{"root": t.root, "cargo": t.cargo, "rustc": t.rustc, "registry": t.registry, "git": t.git,
                "rustup_home": t.rustup_home, "cargo_home": t.cargo_home}, ""])
            }
            Err(err) => json!([null, err]),
        }),
        "g8_checks" => RsOut::ret(Value::from(
            strs_of(&a["owners"])
                .iter()
                .map(|o| {
                    match checks::registry_path(&paths.ucli_checks_root(), o)
                        .and_then(|p| checks::load_registry(&p))
                    {
                        Ok(data) => json!(["", jsonable(&data)]),
                        Err(err) => json!([err, null]),
                    }
                })
                .collect::<Vec<_>>(),
        )),
        "g8_agents" => {
            SEQ.store(0, Ordering::SeqCst);
            let now = if a["now"].as_f64() == Some(NOW) {
                now_fixed
            } else {
                now_whole
            };
            let reg = AgentRegistry::new(&paths).with_sources(Sources {
                entropy: counted_entropy,
                now,
            });
            let out: Vec<Value> = pairs(&a["steps"])
                .into_iter()
                .map(|(step, name)| {
                    let done = match step {
                        "issue" => reg.issue_token(name).map(Value::from),
                        "revoke" => reg.revoke_parent(name).map(|()| Value::Null),
                        _ => {
                            let byte: u8 = name.parse().unwrap();
                            let token: String =
                                std::iter::repeat_n(format!("{byte:02x}"), 32).collect();
                            Ok(reg
                                .parent_for_token(&token)
                                .map_or(Value::Null, Value::from))
                        }
                    };
                    match done {
                        Ok(v) => json!(["ok", v]),
                        Err(err) => json!(["err", err]),
                    }
                })
                .collect();
            RsOut::ret(Value::from(out))
        }
        "g8_diag" => {
            let log = DiagLog::from_env(&paths, &case_env(e, c));
            for ev in a["events"].as_array().unwrap() {
                let fields: Vec<(&str, Value)> = ev[1]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|f| (f[0].as_str().unwrap(), f[1].clone()))
                    .collect();
                log.log(ev[0].as_str().unwrap(), &fields);
            }
            fix_ts(log.path());
            RsOut::ret(Value::Null)
        }
        "g8_agy" => {
            let store = DocAgySidStore::new(&paths, file_docs(&paths));
            // Okunamayan ya da nesne olmayan belge yazılmaz: çağıran (`ProcScan`, Python `_remember_agy_sid`) günlüğe yazar.
            let mut diags = Vec::new();
            for (name, sid) in pairs(&a["writes"]) {
                match remember_agy_sid(&store, name, sid, false) {
                    Err(err) if err == cops_providers::agy_resume::AGY_SIDS_UNREADABLE => diags
                        .push(cops_providers::Diag {
                            event: "agy_sids_unreadable",
                            fields: vec![("name", json!(name))],
                        }),
                    Err(err) => return RsOut::ret(json!(err)),
                    Ok(_) => {}
                }
            }
            let doc = store.load().filter(Py::is_object);
            RsOut {
                extra_diags: diags,
                ..RsOut::ret(doc.map_or(json!({}), |d| d.to_value()))
            }
        }
        "g8_proxy" => RsOut::ret(
            a["cases"]
                .as_array()
                .unwrap()
                .iter()
                .map(rs_proxy)
                .collect(),
        ),
        "g8_help" => {
            let sink = Arc::new(Collect::default());
            let probe = real_probe_with_help(e, c, HelpCache::default().with_diag(sink.clone()));
            let texts: Vec<String> = pairs(&a["calls"])
                .into_iter()
                .map(|(kind, bin)| {
                    if kind == "claude" {
                        probe.claude_help(bin)
                    } else {
                        probe.ucli_chat_help(bin)
                    }
                })
                .collect();
            let extra_diags = std::mem::take(&mut *sink.0.lock().unwrap());
            RsOut {
                extra_diags,
                ..RsOut::ret(Value::from(texts))
            }
        }
        "g8_mcp" => {
            let probe = probe.with_mcp_timeout(Duration::from_secs(a["timeout"].as_u64().unwrap()));
            let list = |k: &str| {
                strs_of(&a["spec"][k])
                    .iter()
                    .map(|s| s.to_string())
                    .collect::<Vec<_>>()
            };
            let spec = McpSpec {
                name: a["spec"]["name"].as_str().unwrap().into(),
                command: a["spec"]["command"].as_str().unwrap().into(),
                args: list("args"),
                allowed_tools: list("allowed_tools"),
            };
            let settings = e.settings();
            let catalog = e.catalog(c);
            let providers = Providers {
                settings: &settings,
                catalog: &catalog,
                paths: &paths,
                probe: &probe,
            };
            let mut out = BuildOutput::default();
            let argv =
                providers.mcp_launch_args(Cli::Ucli, &spec, a["cwd"].as_str().unwrap(), &mut out);
            let mut rs = RsOut::ret(json!(argv));
            rs.out = out;
            rs
        }
        other => panic!("bilinmeyen işlem {other}"),
    }
}

/// Koşucunun `_jsonable` biçimi (sonlu olmayan sayılar işaretli).
fn jsonable(v: &Py) -> Value {
    match v {
        Py::Float(f) => fjson(*f),
        Py::Array(a) => a.iter().map(jsonable).collect(),
        Py::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), jsonable(v))).collect()),
        other => other.to_value(),
    }
}

/// Zaman damgası iki tarafta da sabit metne çevrilir.
pub fn fix_ts(path: &str) {
    let Ok(text) = std::fs::read_to_string(path) else {
        return;
    };
    let re = regex::Regex::new(r#""ts": "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d""#).unwrap();
    std::fs::write(path, re.replace_all(&text, "\"ts\": \"T\"").as_bytes()).unwrap();
}

pub fn run() {
    let mut r = Runner::new();
    let mut cases = path_cases(&r.e);
    cases.extend(toolchain_cases());
    cases.extend(checks_cases());
    cases.extend(agent_cases());
    cases.extend(diag_cases());
    cases.extend(agy_cases());
    cases.extend(help_cases(&r.e));
    cases.extend(mcp_cases(&r.e));
    cases.extend(proxy_cases());
    // `mcp add argv` karşılaştırması sahte süreç listesindendir; burada argv betiğin yazdığı dosyadan karşılaştırılır
    r.run(cases, &[], rs_g8);
    r.finish("g8");
}
