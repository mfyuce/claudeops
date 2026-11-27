//! Aile: `routing.py` (`_with_block`, `_sync_one` kararı + dosya sonucu, `routing_text`), ucli yardımcıları
//! (`state_dir_for`, `is_child_name`, `mcp_server_name`, `ucli_cost.log_path`, `binary_flag_values`,
//! `binary_supports_flag`, `binary_derives_context`, `reasoning_effort_for`, `is_forbidden_cmd`), ayrıştırıcılar
//! (`_fetch_live_models`, `agy models`), `expand_exec_cmds`, `exec_flags`, `validate_opts` (temiz sözlük tipleri).

use crate::common::*;
use crate::fam_model::with;
use crate::fam_ucli::full_help;
use cops_providers::agy::parse_models;
use cops_providers::real::routing_sync::sync_one;
use cops_providers::routing::with_block;
use cops_providers::ucli::{
    derives_context, flag_values, is_child_name, mcp_server_name, parse_live_models,
    reasoning_effort_for, state_dir_for, supports_flag, usage_log_path, LiveModels,
};
use cops_providers::ucli_opts::{exec_flags, expand_exec_cmds, is_forbidden_cmd, validate_opts};
use cops_providers::Probe;
use serde_json::{json, Value};

fn rs_with_block(_e: &Env, c: &Case) -> RsOut {
    RsOut::ret(json!(with_block(
        c.args["existing"].as_str().unwrap(),
        c.args.get("body").and_then(Value::as_str)
    )))
}

fn with_block_cases() -> Vec<Case> {
    let b = "<!-- claudeops-routing:begin -->";
    let en = "<!-- claudeops-routing:end -->";
    let existings = [
        String::new(),
        "\n\n".into(),
        "kullanıcı metni".into(),
        "kullanıcı metni\n\n\n".into(),
        format!("önce\n\n{b}\neski\n{en}\n\nsonra\n"),
        format!("{b}\neski\n{en}\n"),
        format!("{b}\neski\n{en}"),
        format!("önce\n{b}\nyetim\n{b}\neski\n{en}\nsonra"),
        format!("önce {en} arada {b} sonra"),
        format!("{b}{en}"),
        format!("a\n{b}\nx\n{en}\nb\n{b}\ny\n{en}\nc\n"),
        format!("\u{1f}\n{b}\nx\n{en}\n"),
        "satır sonu yok".into(),
        " \u{1f} ".into(),
    ];
    let bodies = [
        None,
        Some("yönerge"),
        Some("yönerge\n\n"),
        Some("son \u{1f}\u{1c}"),
        Some(""),
        Some("  \n"),
        Some("\u{2028}x\u{2028}"),
    ];
    let mut v = Vec::new();
    for (i, ex) in existings.iter().enumerate() {
        for (j, body) in bodies.iter().enumerate() {
            v.push(Case::new(
                format!("blok{i}-{j}"),
                "with_block",
                json!({"existing": ex, "body": body}),
            ));
        }
    }
    v
}

/// `_sync_one`: GERÇEK `real::routing_sync::sync_one` (karar `sync_plan` + yedek, silme, realpath'e atomik yazım).
fn rs_sync_one(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let path = c.args["path"].as_str().unwrap();
        let create = c.args["create"].as_bool().unwrap();
        let sink = VecSink::default();
        let ret = sync_one(probe, p.settings, p.paths, path, create, &sink);
        let mut rs = RsOut::ret(json!(ret));
        rs.extra_diags = sink.take();
        rs
    })
}

fn sync_cases(e: &Env) -> Vec<Case> {
    let b = "<!-- claudeops-routing:begin -->";
    let en = "<!-- claudeops-routing:end -->";
    let path = format!("{}/.codex/AGENTS.md", e.home);
    let mut v = Vec::new();
    let settings = [
        json!(null),
        json!({"routing_guidance": "off"}),
        json!({"routing_guidance_text": "  özel yönerge  "}),
        json!({"routing_guidance_text": " "}),
    ];
    let files: [Option<String>; 7] = [
        None,
        Some(String::new()),
        Some("kullanıcı\n".into()),
        Some(format!("kullanıcı\n\n{b}\neski\n{en}\n")),
        Some(format!("{b}\neski\n{en}\n")),
        Some("crlf\r\nsatır\r\n".into()),
        Some(format!("{b}\nözel yönerge\n{en}\n")),
    ];
    for (i, s) in settings.iter().enumerate() {
        for (j, f) in files.iter().enumerate() {
            for create in [false, true] {
                let mut c = Case::new(
                    format!("sync{i}-{j}-{create}"),
                    "sync_one",
                    json!({"path": path, "create": create}),
                );
                if !s.is_null() {
                    c = c.settings_json(s.clone());
                }
                if let Some(text) = f {
                    c = c.file(file("home/.codex/AGENTS.md", text, 0o640));
                }
                v.push(c);
            }
        }
    }
    v.push(
        Case::new(
            "sync-yedek-var",
            "sync_one",
            json!({"path": path, "create": false}),
        )
        .file(file("home/.codex/AGENTS.md", "k\n", 0o600))
        .file(file(
            "home/.codex/AGENTS.md.bak-routing",
            "eski yedek",
            0o600,
        )),
    );
    v.push(
        Case::new(
            "sync-symlink",
            "sync_one",
            json!({"path": path, "create": false}),
        )
        .file(file("home/gercek.md", "k\n", 0o600))
        .file(Fx::Link(
            "home/.codex/AGENTS.md".into(),
            "../gercek.md".into(),
        )),
    );
    v.push(Case::new(
        "sync-dizin-yok-create",
        "sync_one",
        json!({"path": format!("{}/.gemini/GEMINI.md", e.home), "create": true}),
    ));
    v.push(
        Case::new(
            "sync-bozuk-utf8",
            "sync_one",
            json!({"path": path, "create": false}),
        )
        .file(Fx::File(
            "home/.codex/AGENTS.md".into(),
            vec![0xff, b'\n'],
            0o600,
        )),
    );
    v.push(
        Case::new(
            "sync-bozuk-utf8-kapali",
            "sync_one",
            json!({"path": path, "create": true}),
        )
        .settings_json(json!({"routing_guidance": "off"}))
        .file(Fx::File(
            "home/.codex/AGENTS.md".into(),
            vec![b'k', 0xfe],
            0o600,
        )),
    );
    v
}

fn rs_ucli_misc(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let a = &c.args;
        let help = probe.ucli_chat_help(a["binary"].as_str().unwrap());
        let names = strs(a.get("names"));
        let flags = strs(a.get("flags"));
        let live = LiveModels {
            ids: Vec::new(),
            caps: c
                .fact("ucli_live")
                .and_then(|l| l.get("caps"))
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default(),
        };
        RsOut::ret(json!({
            "state_dir_for": strs(a.get("cwds")).iter()
                .map(|cwd| state_dir_for(&p.paths.ucli_state_root(), &probe.realpath(cwd))).collect::<Vec<_>>(),
            "is_child_name": names.iter().map(|n| is_child_name(n)).collect::<Vec<_>>(),
            "mcp_server_name": names.iter().map(|n| mcp_server_name(n)).collect::<Vec<_>>(),
            "log_path": names.iter().map(|n| usage_log_path(&p.paths.ucli_usage_dir(), n)).collect::<Vec<_>>(),
            "flag_values": flags.iter().map(|f| flag_values(&help, f)).collect::<Vec<_>>(),
            "supports": flags.iter().map(|f| supports_flag(&help, f)).collect::<Vec<_>>(),
            "derives": derives_context(&help),
            "reasoning": a.get("reasoning").and_then(Value::as_array).map_or(Vec::new(), |r| r.iter()
                .map(|x| json!(reasoning_effort_for(&live, x[0].as_str().unwrap(), x[1].as_str().unwrap()))).collect()),
            "forbidden": names.iter().map(|n| is_forbidden_cmd(n)).collect::<Vec<_>>(),
        }))
    })
}

fn misc_cases(e: &Env) -> Vec<Case> {
    let cwds = [
        format!("{}/p1", e.work),
        format!("{}/p1/", e.work),
        "/".into(),
        "".into(),
        "p1".into(),
        format!("{}/yok/../p1", e.work),
        format!("{}/ğ ü+x.y-z_{}", e.work, "a".repeat(50)),
        format!("{}/bag", e.work),
        format!("{}/..", e.work),
        "//".into(),
        format!("{}/p1/./.", e.work),
    ];
    let names = [
        "s1",
        "",
        "a_aj1",
        "a_aj0",
        "a_aj01",
        "_aj1",
        "a_aj",
        "a_aj1\n",
        "a\nb_aj1",
        "x_aj12_aj3",
        "a_ajx",
        "a_aj١",
        "cops-steward",
        "ğ.ad",
        "a b/c",
        &"x".repeat(130),
        "bash",
        "BASH",
        "Python3.11",
        "python",
        "pypy3",
        "node-18",
        "perl5.36\n",
        "busybox_",
        "Rscript",
        "rscript",
        "luajit",
        "²",
        "١",
        "ǅ",
        "K",
        "ⅰ",
    ];
    let helps = [
        full_help(),
        "--allow-checks <M>\n\n  --checks-max x\n[possible values: a,  b ,, c]\n".into(),
        "--allow-checks [possible values: ".into(),
        "--allow-checks x\n--checks-max [possible values: restricted]\n... [possible values: z]"
            .into(),
        "x--allow-checks [possible values: q] --allow-checks [possible values: full]".into(),
        "--allow-checks-x [possible values: q]".into(),
        "--allow-checks\u{345} --allow-checks".into(),
        "advertises a large window".into(),
        String::new(),
    ];
    let flags = ["--allow-checks", "--checks-max", "--x", "--allow", "-"];
    let mut v = Vec::new();
    for (i, h) in helps.iter().enumerate() {
        v.push(
            Case::new(format!("ucli-misc{i}"), "ucli_misc", json!({"binary": format!("{}/ucli", e.bin), "cwds": cwds,
                "names": names, "flags": flags, "reasoning": [["glm", "medium"], ["glm", "low"], ["glm", "max"], ["g2", "x"],
                ["g3", "high"], ["yok", "low"], ["g4", "low"], ["g5", "low"]]}))
                .facts(json!({"ucli_help": h, "ucli_live": {"ids": [], "caps": {
                    "glm": {"reasoning_effort": true, "reasoning_effort_values": ["low", "high"], "reasoning_effort_aliases": {"medium": "high"}},
                    "g2": {"reasoning_effort": "true"},
                    "g3": {"reasoning_effort": true, "reasoning_effort_values": []},
                    "g4": {"reasoning_effort": true, "reasoning_effort_values": "low"},
                    "g5": {"reasoning_effort": true, "reasoning_effort_values": ["high"], "reasoning_effort_aliases": ["low"]}}}}))
                .file(Fx::Link("work/bag".into(), "p1".into())),
        );
    }
    for (i, n) in ["x\u{0b3e}", "Ⓐ"].iter().enumerate() {
        v.push(
            Case::new(format!("ucli-misc-isalnum{i}"), "ucli_misc", json!({"binary": format!("{}/ucli", e.bin), "names": [n]}))
                .known("isalnum: Python genel kategori (L*/N*), Rust `is_alphanumeric` Unicode Alphabetic (Other_Alphabetic birleşik işaret U+0B3E, daire içi Ⓐ) içerir; kullanım günlüğü/metrik dosya adında `_` yerine harf kalır"),
        );
    }
    v
}

fn rs_live(_e: &Env, c: &Case) -> RsOut {
    let live = serde_json::from_str::<Value>(c.args["payload"].as_str().unwrap())
        .map(|v| parse_live_models(&v))
        .unwrap_or_default();
    RsOut::ret(
        json!({"ids": if live.ids.is_empty() { Value::Null } else { json!(live.ids) },
                      "caps": if live.ids.is_empty() { json!({}) } else { Value::Object(live.caps) }}),
    )
}

fn live_cases() -> Vec<Case> {
    let payloads = [
        json!({"data": [{"id": "glm", "task": "chat", "capabilities": {"reasoning_effort": true}}, {"id": "ocr", "task": "ocr"},
                        {"id": "", "task": "chat"}, {"id": "q", "task": "chat", "capabilities": [1]}, {"task": "chat"},
                        {"id": "x", "task": "Chat"}, 5, {"id": "z", "task": "chat", "capabilities": null}]}).to_string(),
        json!({"data": []}).to_string(),
        json!({"data": [{"id": "ocr", "task": "ocr"}]}).to_string(),
        json!({}).to_string(),
        json!({"data": [{"id": "a", "task": "chat"}, {"id": "a", "task": "chat", "capabilities": {"x": 1}}]}).to_string(),
        "{bozuk".into(),
    ];
    let mut v: Vec<Case> = payloads
        .iter()
        .enumerate()
        .map(|(i, p)| {
            Case::new(format!("live{i}"), "live_models", json!({"payload": p}))
                .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}}))
        })
        .collect();
    for (i, p) in [
        "[1]",
        "[]",
        "\"x\"",
        "5",
        "null",
        "true",
        r#"{"data": 5}"#,
        r#"{"data": null}"#,
        r#"{"data": true}"#,
        r#"{"data": "ab"}"#,
        r#"{"data": {"id": "a"}}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(
            Case::new(
                format!("live-bicim{i}"),
                "live_models",
                json!({"payload": p}),
            )
            .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}})),
        );
    }
    v.push(
        Case::new(
            "live-sayi-id",
            "live_models",
            json!({"payload": json!({"data": [{"id": 5, "task": "chat"}]}).to_string()}),
        )
        .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}}))
        .known("dize olmayan model kimliği (5) Python'da int kalır, Rust `str()` ile \"5\""),
    );
    v
}

fn rs_agy(_e: &Env, c: &Case) -> RsOut {
    RsOut::ret(json!(parse_models(c.args["output"].as_str().unwrap())))
}

fn agy_cases() -> Vec<Case> {
    let outs = [
        "Fetching available models...\ngemini-3.8-flash-high\tGemini High\n  claude-opus  \tClaude\n",
        "a\tA\r\nb\tB\rc\tC\x0bd\tD\x0ce\tE\x1cf\tF\u{85}g\tG\u{2028}h\tH\u{2029}i\tI\x1dj\tJ\x1ek\tK",
        "\tboş\n\u{1f}x\u{1f}\tY\nyalnız\nçok\tsekme\tvar",
        "",
    ];
    outs.iter()
        .enumerate()
        .map(|(i, o)| Case::new(format!("agy{i}"), "agy_parse", json!({"output": o})))
        .collect()
}

fn rs_expand(_e: &Env, c: &Case) -> RsOut {
    let r = expand_exec_cmds(&strs(c.args.get("items")), &strs(c.args.get("available")));
    match r {
        Ok(names) => RsOut::ret(json!({"ok": names, "err": ""})),
        // Python `expand_exec_cmds` geçersiz regex'te `re.error` FIRLATIR (doğrulamadan geçen girdide erişilemez);
        // Rust hata metnine sarar: karşılaştırma iç iletiyle.
        Err(err) if err.starts_with("geçersiz regex (") => {
            let inner = err["geçersiz regex (".len()..]
                .rsplit_once("): ")
                .map_or(err.clone(), |(m, _)| m.to_string());
            RsOut {
                exc: Some(inner),
                ..Default::default()
            }
        }
        Err(err) => RsOut::ret(json!({"ok": [], "err": err})),
    }
}

pub const RE_PATTERNS: [&str; 78] = [
    "git",
    "gi.",
    "g.*",
    "(ca|ru).+",
    "[[:alpha:]]+",
    "\\w+",
    "\\d",
    "[a-c]+",
    "[^a-z]+",
    "c\\+\\+",
    "a{2}",
    "a{,3}",
    "g{1,}it",
    "x{2,1}",
    "a++",
    "*a",
    "a**",
    "a*?",
    "a*??",
    "(?i)GIT",
    "git(?i)",
    "(?i:G)it",
    "(?-i:g)it",
    "(?P<n>g)(?P=n)",
    "(?P<n>g)\\1",
    "(?P=n)",
    "(?<n>g)",
    "(?>g)",
    "\\p{L}",
    "\\Z",
    "git\\Z",
    "\\Agit",
    "[\\d]+",
    "[\\w-]+",
    "[a\\-z]+",
    "[]a]",
    "[^]a]+",
    "[z-a]",
    "[a-\\d]",
    "a|",
    "|a",
    "()",
    "(",
    ")",
    "a)",
    "[",
    "[a",
    "\\",
    "\\x67it",
    "\\u0067it",
    "\\147it",
    "\\0",
    "\\8",
    "a\\1",
    "(a)\\2",
    "\\q",
    "\\-",
    "\\.",
    "[.]",
    "a{1,2}{3}",
    "^git$",
    "^*",
    "\\b*",
    "(?#yorum)git",
    "{",
    "a{",
    "a{1",
    "a{x}",
    "a{1,2,3}",
    "[&&]",
    "[a&&b]+",
    "[a--b]",
    "[~~]",
    "[|]",
    "(?i",
    "(?z)",
    "(?P<1>a)",
    "(?P<a>x)(?P<a>y)",
];

fn re_cases() -> Vec<Case> {
    let avail = [
        "git", "GIT", "Git", "gitk", "gg", "cargo", "rustc", "c++", "a", "aa", "aaa", "ab", "a]",
        "]", ":", "[", "x", "g1", "gi", "g", "a-b", "-", ".", "a|b", "~", "&", "zz9", "\\",
        "git\n",
    ];
    let mut v = Vec::new();
    for (i, p) in RE_PATTERNS.iter().enumerate() {
        v.push(
            Case::new(
                format!("re-val{i}"),
                "validate",
                json!({"raw": {"exec_cmds": format!("re:{p}")}}),
            )
            .facts(json!({"toolchain": "yok"})),
        );
        v.push(Case::new(
            format!("re-exp{i}"),
            "expand",
            json!({"items": [format!("re:{p}")], "available": avail}),
        ));
    }
    v.push(
        Case::new(
            "re-val-verbose",
            "validate",
            json!({"raw": {"exec_cmds": "re:(?x)g i t"}}),
        )
        .facts(json!({"toolchain": "yok"}))
        .known("DAHA SIKI: Python `(?x)` (verbose) kabul eder; çevirici desteklemez, reddeder"),
    );
    v.push(
        Case::new(
            "re-val-kosul",
            "validate",
            json!({"raw": {"exec_cmds": "re:(a)?(?(1)b|c)"}}),
        )
        .facts(json!({"toolchain": "yok"}))
        .known("DAHA SIKI: Python koşullu grup `(?(1)..)` kabul eder; çevirici reddeder"),
    );
    v.push(
        Case::new(
            "re-val-adli",
            "validate",
            json!({"raw": {"exec_cmds": "re:\\N{LATIN SMALL LETTER G}it"}}),
        )
        .facts(json!({"toolchain": "yok"}))
        .known("DAHA SIKI: Python `\\N{ad}` kabul eder; çevirici reddeder"),
    );
    v
}

fn expand_cases() -> Vec<Case> {
    let avail = [
        "bash",
        "cargo",
        "cargo-clippy",
        "git",
        "git-lfs",
        "gitk",
        "ls",
        "make",
        "python3",
        "python3.11",
        "rg",
        "rustc",
        "sh",
        "xargs",
        "a.b",
        "a+b",
        "c[1]",
        "[x",
        "-x",
        "Go",
    ];
    let items: Vec<Vec<&str>> = vec![
        vec!["git", "cargo"],
        vec!["git*"],
        vec!["*"],
        vec!["?it"],
        vec!["[gc]*"],
        vec!["[!gc]*"],
        vec!["[a-c]*"],
        vec!["[z-a]*"],
        vec!["[*"],
        vec!["[]]*"],
        vec!["[!]]*"],
        vec!["c[[]1]"],
        vec!["a.b"],
        vec!["a?b"],
        vec!["re:git.*"],
        vec!["re:(ca|ru)\\w+"],
        vec!["re:python3"],
        vec!["re:.*"],
        vec!["re:sh|bash"],
        vec!["zz*"],
        vec!["re:zz"],
        vec!["git", "git*", "re:gi.*"],
        vec!["[-x]*"],
        vec!["[x-]*"],
        vec!["*[!a-z]*"],
        vec!["[A-Z]*"],
        vec!["g*", "c*"],
        vec!["re:"],
        vec!["re:(?i)go"],
        vec!["re:g"],
        vec!["re:\\d"],
        vec!["Go*"],
        vec!["[\\]]*"],
        vec!["[a-]"],
    ];
    let mut v: Vec<Case> = items
        .iter()
        .enumerate()
        .map(|(i, it)| {
            Case::new(
                format!("expand{i}"),
                "expand",
                json!({"items": it, "available": avail}),
            )
        })
        .collect();
    let many: Vec<String> = (0..4001).map(|i| format!("c{i}")).collect();
    v.push(Case::new(
        "expand-cok",
        "expand",
        json!({"items": ["c*"], "available": many}),
    ));
    v
}

fn rs_exec_flags(e: &Env, c: &Case) -> RsOut {
    with(e, c, |_, probe| {
        let opts = c.args["opts"].as_object().cloned().unwrap_or_default();
        RsOut::ret(json!(exec_flags(&opts, &|| probe.rust_toolchain(), &|d| {
            probe.is_dir(d)
        })))
    })
}

fn exec_flags_cases(e: &Env) -> Vec<Case> {
    let root = format!("{}/.rustup/toolchains/nightly-x", e.home);
    let tc = json!({"root": root, "cargo": format!("{root}/bin/cargo"), "rustc": format!("{root}/bin/rustc"),
                    "registry": format!("{}/.cargo/registry", e.home), "git": format!("{}/.cargo/git", e.home),
                    "rustup_home": format!("{}/.rustup", e.home), "cargo_home": format!("{}/.cargo", e.home)});
    let opts = [
        json!({}),
        json!({"exec_cmds": []}),
        json!({"exec_cmds": ["git", "ls"]}),
        json!({"exec_cmds": ["git"], "exec_own_glob": ["a/*", "b"], "exec_bind_ro": ["/o/x", "/o/x"], "exec_timeout": 5}),
        json!({"exec_toolchain": "rust"}),
        json!({"exec_cmds": ["git"], "exec_toolchain": "rust", "exec_bind_ro": [root]}),
        json!({"exec_cmds": ["git"], "exec_toolchain": "go"}),
        json!({"exec_cmds": ["git"], "exec_timeout": 2.9}),
        json!({"exec_cmds": ["git"], "exec_timeout": "7"}),
        json!({"exec_cmds": ["git"], "exec_timeout": 0}),
        json!({"exec_cmds": ["git"], "exec_timeout": true}),
        json!({"exec_cmds": [1, "a"]}),
    ];
    let mut v = Vec::new();
    for (i, o) in opts.iter().enumerate() {
        let why = "doğrulanmamış girdi: dize olmayan komut adı Python'da `\",\".join` TypeError; Rust `str()` ile birleştirir";
        v.push(
            Case::new(format!("exec{i}"), "exec_flags", json!({"opts": o}))
                .facts(json!({"toolchain": tc.clone()}))
                .file(Fx::Dir(".cargo-yok".into(), 0o755))
                .file(Fx::Dir("home/.cargo/git".into(), 0o755))
                .known_if(i == 11, why),
        );
        v.push(
            Case::new(format!("exec{i}-tcsiz"), "exec_flags", json!({"opts": o}))
                .facts(json!({"toolchain": "yok"}))
                .known_if(i == 11, why),
        );
    }
    v
}

fn rs_validate(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        RsOut::ret(
            match validate_opts(&c.args["raw"], p.settings, &|| probe.rust_toolchain()) {
                Ok(m) => json!({"ok": m, "err": ""}),
                Err(err) => json!({"ok": {}, "err": err}),
            },
        )
    })
}

fn validate_cases() -> Vec<Case> {
    let raws = [
        json!({"service": "Claude", "exec_cmds": "git, cargo, git", "exec_own_glob": "t/*, t/*", "exec_bind_ro": "/o/a/, /o/a",
               "exec_write": "1", "exec_timeout": "08", "max_cost_usd": "2", "max_session_usd": 3, "git_commit": "on",
               "max_prompt_tokens": " 5 ", "show_usage": 1, "allow_image": "true", "search_token_env": " TOK ",
               "price": " 1 , 2.50 ", "ucli_checks": {"mode": " FULL ", "accept_risk": "yes"}, "bilinmeyen": 1}),
        json!({"max_cost_usd": 1e-7, "max_session_usd": "1e2", "price": "1e-3,1e3"}),
        json!({"max_cost_usd": true}),
        json!({"max_session_usd": [1]}),
        json!({"price": 5}),
        json!({"price": "1,,2"}),
        json!({"exec_cmds": {"a": 1}}),
        json!({"exec_cmds": "\u{1f}git\u{1f}"}),
        json!({"exec_timeout": "٣", "exec_cmds": "git"}),
        json!({"max_prompt_tokens": "1_000"}),
        json!({"max_prompt_tokens": "\u{2003}9\u{2003}"}),
        json!({"ucli_checks": {"mode": "restricted", "max": "", "accept_risk": 0}}),
        json!({"ucli_checks": {"mode": "restricted", "max": null}}),
        json!({"ucli_checks": 0}),
        json!({"ucli_checks": 1}),
        json!({"ucli_checks": "x"}),
        json!({"git_commit": 1.0}),
        json!({"git_commit": 0.0}),
        json!({"allow_image": 1.0}),
        json!({"no_prompt_cache": "True"}),
        json!({"search_token_env": 5}),
        json!({"search_token_env": "ab"}),
        json!({"search_token_env": "A\n"}),
        json!({"accept_risk": true, "exec_cmds": "git", "exec_own_glob": "x/*"}),
        json!({"exec_cmds": "git", "exec_bind_ro": ["/a/b\n"]}),
        json!({"exec_cmds": "git", "exec_own_glob": ["a/*\n"]}),
        json!({"exec_cmds": ["git\n"]}),
    ];
    raws.iter()
        .enumerate()
        .map(|(i, r)| {
            Case::new(format!("val{i}"), "validate", json!({"raw": r}))
                .facts(json!({"toolchain": "yok"}))
                .known_if(
                    i == 6,
                    "str(dict) Python repr, Rust JSON metni (hata iletisinde)",
                )
        })
        .collect()
}

pub fn run() {
    let mut r = Runner::new();
    r.run(with_block_cases(), &[], rs_with_block);
    let cases = sync_cases(&r.e);
    r.run(cases, &[], rs_sync_one);
    let cases = misc_cases(&r.e);
    r.run(cases, &[], rs_ucli_misc);
    r.run(live_cases(), &[], rs_live);
    r.run(agy_cases(), &[], rs_agy);
    r.run(expand_cases(), &[], rs_expand);
    r.run(re_cases(), &[], |e, c| {
        if c.op == "expand" {
            rs_expand(e, c)
        } else {
            rs_validate(e, c)
        }
    });
    let cases = exec_flags_cases(&r.e);
    r.run(cases, &[], rs_exec_flags);
    r.run(validate_cases(), &[], rs_validate);
    r.finish("misc");
}
