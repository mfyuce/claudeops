//! Aile: komut kurulumu (`build_inner_command`) tüm sağlayıcılar için; claude oneshot argv'si; MCP bağlama
//! (`mcp_launch_args`, `mcp_setup_command`, claude yapılandırma dosyası); ikili çözümü (`resolved_binary`, ucli
//! `resolve_binary`); copilot güven klasörü + BYOK dosyası; yönerge bayrağı (`--append-system-prompt-file`).

use crate::common::*;
use crate::fam_model::with;
use cops_providers::ucli::resolve_binary;
use cops_providers::{BuildArgs, BuildOutput, Cli, McpSpec};
use serde_json::{json, Map, Value};

pub fn spec_of(v: &Value) -> McpSpec {
    McpSpec {
        name: v["name"].as_str().unwrap().into(),
        command: v["command"].as_str().unwrap().into(),
        args: strs(v.get("args")),
        allowed_tools: strs(v.get("allowed_tools")),
    }
}

pub fn rs_build(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let a = &c.args;
        let cli = Cli::parse(a["cli"].as_str().unwrap());
        let mut rs = RsOut::default();
        let mut opts: Option<Map<String, Value>> = a.get("cli_opts").and_then(Value::as_object).cloned();
        if a.get("validate").and_then(Value::as_bool) == Some(true) {
            match p.validate_cli_opts(cli, a.get("raw_opts").unwrap_or(&Value::Null)) {
                Err(err) => {
                    rs.ret = json!({"validate_err": err});
                    return rs;
                }
                Ok(clean) => opts = Some(clean).filter(|m| !m.is_empty()),
            }
        }
        let extra = strs(a.get("extra"));
        let s = |k: &str| a.get(k).and_then(Value::as_str);
        let args = BuildArgs {
            cwd: s("cwd").unwrap(),
            model: s("model").unwrap(),
            permission_mode: s("perm").unwrap(),
            effort: s("effort").unwrap(),
            resume_id: s("resume"),
            prompt: s("prompt"),
            session_name: s("name").unwrap(),
            extra_args: &extra,
            cli_opts: opts.as_ref().filter(|o| cli.accepts_cli_opts() && !o.is_empty()),
        };
        let mut out = BuildOutput::default();
        match p.build_inner_command(cli, &args, &mut out) {
            Ok(cmd) => rs.ret = json!(cmd),
            Err(err) => rs.exc = Some(err.0),
        }
        rs.out = out;
        rs.mcp_calls = probe.mcp_calls.borrow().clone();
        rs
    })
}

fn rs_oneshot(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, _| {
        let cli = Cli::parse(c.args["cli"].as_str().unwrap());
        RsOut::ret(json!(p.oneshot_argv(cli, c.args["prompt"].as_str().unwrap(), c.args.get("model").and_then(Value::as_str))))
    })
}

fn rs_mcp(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let cli = Cli::parse(c.args["cli"].as_str().unwrap());
        let spec = spec_of(&c.args["spec"]);
        let mut out = BuildOutput::default();
        let launch = p.mcp_launch_args(cli, &spec, c.args.get("cwd").and_then(Value::as_str).unwrap_or(""), &mut out);
        let mut rs = RsOut::ret(json!({"launch": launch, "setup": p.mcp_setup_command(cli, &spec)}));
        rs.out = out;
        rs.mcp_calls = probe.mcp_calls.borrow().clone();
        rs
    })
}

fn rs_resolved_binary(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, _| RsOut::ret(json!(p.resolved_binary(c.args["cli"].as_str().unwrap()))))
}

fn rs_resolve_ucli(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, _| match resolve_binary(p) {
        Ok(b) => RsOut::ret(json!(b)),
        Err(err) => RsOut { exc: Some(err.0), ..Default::default() },
    })
}

/// `resolve_binary`, claudeops'un KENDİ kopyası vaka ağacında (`<kök>/work/repo/bin/ucli`; Python `OWN_UCLI` aynı yola çevrilir).
fn rs_resolve_ucli_own(e: &Env, c: &Case) -> RsOut {
    let settings = e.settings();
    let catalog = e.catalog(c);
    let paths = cops_providers::Paths { repo_dir: format!("{}/work/repo", e.root), ..e.paths() };
    let probe = FsProbe::new(e, c);
    let p = cops_providers::Providers { settings: &settings, catalog: &catalog, paths: &paths, probe: &probe };
    match resolve_binary(&p) {
        Ok(b) => RsOut::ret(json!(b)),
        Err(err) => RsOut { exc: Some(err.0), ..Default::default() },
    }
}

fn bcase(id: String, cli: &str, args: Value) -> Case {
    let mut base = json!({"cli": cli, "cwd": "", "model": "m", "perm": "auto", "effort": "high", "name": "s1"});
    base.as_object_mut().unwrap().extend(args.as_object().unwrap().clone());
    Case::new(id, "build", base)
}

const PERMS: [&str; 9] = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan", "autopilot", "", "bogus"];

fn build_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/p1", e.work);
    let mut v = Vec::new();
    let prompts: [Option<&str>; 6] = [None, Some(""), Some("merhaba dünya"), Some("it's \"q\" $x `y`\nikinci"), Some("-p"), Some("ğüş\u{1f}")];
    let names = ["s1", "", "a b", "it's", "ğ-ad", "-n"];
    let models = ["claude-sonnet-5-5", "", "gemini-3.8-flash-high", "gemini-3.8-flash", "gemini", "gpt-5.5", "a b", "x'y"];
    for cli in ["claude", "agy", "codex", "copilot", "shell", "bogus"] {
        for (i, perm) in PERMS.iter().enumerate() {
            let m = models[i % models.len()];
            let eff = ["", "low", "medium", "high", "xhigh", "max", "ultra", "bogus", "MAX"][i];
            v.push(bcase(format!("{cli}-perm{i}"), cli, json!({"perm": perm, "model": m, "effort": eff, "cwd": w,
                "prompt": prompts[i % prompts.len()], "name": names[i % names.len()],
                "resume": ([None, Some(""), Some("abc-123"), Some("a b'c")])[i % 4]}))
                .facts(json!({"agy_models": ["gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-xhigh"]})));
        }
        v.push(bcase(format!("{cli}-extra"), cli, json!({"extra": ["--mcp-config", "/a b/c.json", "-c", "k=v"], "cwd": w})));
        v.push(bcase(format!("{cli}-path-yok"), cli, json!({"cwd": w})).env("PATH", ""));
        v.push(bcase(format!("{cli}-path-iki"), cli, json!({"cwd": w}))
            .env("PATH", &format!("{0}/yok:{0}/bin2:{0}/bin", e.root))
            .file(file(&format!("bin2/{cli}"), "x", 0o755)));
        v.push(bcase(format!("{cli}-path-calismaz"), cli, json!({"cwd": w}))
            .env("PATH", &format!("{0}/bin2", e.root))
            .file(file(&format!("bin2/{cli}"), "x", 0o644)));
        v.push(bcase(format!("{cli}-override"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: "  ~/araclar/ikili  "}}))
            .file(file("home/araclar/ikili", "x", 0o755)));
        v.push(bcase(format!("{cli}-override-calismaz"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: "~/araclar/ikili"}}))
            .file(file("home/araclar/ikili", "x", 0o644)));
        v.push(bcase(format!("{cli}-override-dizin"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: format!("{}/araclar", e.home)}}))
            .file(Fx::Dir("home/araclar".into(), 0o755)));
        v.push(bcase(format!("{cli}-override-bosluklu"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: format!("{}/a b/c'd", e.home)}}))
            .file(file("home/a b/c'd", "x", 0o755)));
        v.push(bcase(format!("{cli}-override-tilde-kullanici"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: "~root/x"}})));
        v.push(bcase(format!("{cli}-override-bos"), cli, json!({"cwd": w}))
            .settings_json(json!({"provider_bin": {cli: " \u{1f} "}})));
        for (i, bad) in [json!(5), json!(null), json!(true), json!(["/x"]), json!({"a": 1}), json!(1.5)].into_iter().enumerate() {
            v.push(bcase(format!("{cli}-override-tip{i}"), cli, json!({"cwd": w})).settings_json(json!({"provider_bin": {cli: bad}})));
        }
    }
    // claude: PATH'te yokken bilinen kurulum konumları (sıra önemli).
    for (i, rel) in ["home/cc/node_modules/.bin/claude", "home/.local/bin/claude", "home/.npm-global/bin/claude"].iter().enumerate() {
        v.push(bcase(format!("claude-bilinen{i}"), "claude", json!({"cwd": w})).env("PATH", "").file(file(rel, "x", 0o755)));
    }
    v.push(bcase("claude-bilinen-iki".into(), "claude", json!({"cwd": w}))
        .env("PATH", "")
        .file(file("home/.local/bin/claude", "x", 0o755))
        .file(file("home/cc/node_modules/@anthropic-ai/claude-code/bin/claude.exe", "x", 0o755)));
    // claude yönergesi (routing): kapalı, override metni (ilk yazım / aynı / farklı / bozuk dosya).
    let rg = |id: &str, s: Value| bcase(format!("claude-routing-{id}"), "claude", json!({"cwd": w})).settings_json(s);
    v.push(rg("kapali", json!({"routing_guidance": "off"})));
    v.push(rg("override", json!({"routing_guidance_text": "  Yönerge: düşük başla.\n"})));
    v.push(rg("override-ayni", json!({"routing_guidance_text": "Yönerge"}))
        .file(file("state/routing-guidance.md", "Yönerge\n", 0o640)));
    v.push(rg("override-farkli", json!({"routing_guidance_text": "Yönerge"}))
        .file(file("state/routing-guidance.md", "eski\n", 0o640)));
    v.push(rg("override-crlf", json!({"routing_guidance_text": "a\r\nb"}))
        .file(file("state/routing-guidance.md", "a\r\nb\n", 0o600)));
    v.push(rg("override-bozuk-utf8", json!({"routing_guidance_text": "Yönerge"}))
        .file(Fx::File("state/routing-guidance.md".into(), vec![0xff, 0xfe, b'x'], 0o600)));
    v.push(rg("override-symlink", json!({"routing_guidance_text": "Yönerge"}))
        .file(file("state/hedef.md", "eski", 0o600))
        .file(Fx::Link("state/routing-guidance.md".into(), "hedef.md".into())));
    v.push(rg("override-bosluk", json!({"routing_guidance_text": " \u{1f} "})));
    v.push(rg("override-dizin", json!({"routing_guidance_text": "Y"}))
        .file(Fx::Dir("state/routing-guidance.md".into(), 0o755)));
    // copilot: güven klasörü (config.json JSONC) ve BYOK dosyası.
    let cfg = |t: &str| file("home/.copilot/config.json", t, 0o600);
    let cp = |id: &str| bcase(format!("copilot-{id}"), "copilot", json!({"cwd": w}));
    for (i, text) in [
        r#"{"trustedFolders": ["/a/[x]", "WORK"], "x": [1]}"#,
        r#"{"trustedFolders": ["/a]b"], "x": [1]}"#,
        r#"{"trustedFolders": [ // eski ] "WORK"
 /* ] */ "/q\"]" ]}"#,
        r#"{"trustedFolders": [ "/a]""#,
        r#"{"trustedFolders": ["/a", "\x", "WORK"]}"#,
        r#"{"trustedFolders": ["WORK\u002f", "/\u00e7]"]}"#,
    ]
    .iter()
    .enumerate()
    {
        v.push(cp(&format!("trust-ayrac{i}")).file(cfg(&text.replace("WORK", &w))));
    }
    v.push(bcase("copilot-trust-unicode-ham".into(), "copilot", json!({"cwd": format!("{w}/ç")}))
        .file(cfg(&format!(r#"{{"trustedFolders": ["{w}/ç"]}}"#))));
    v.push(bcase("copilot-trust-ayrac-cwd".into(), "copilot", json!({"cwd": format!("{w}/[q]")}))
        .file(cfg(r#"{"trustedFolders": ["/a]b"]}"#)));
    v.push(cp("trust-bos").file(cfg("{\n  \"trustedFolders\": []\n}\n")));
    v.push(cp("trust-dolu").file(cfg("// yorum\n{\"trustedFolders\" :[\n  \"/x\"\n], \"a\": 1}")));
    v.push(cp("trust-var").file(cfg(&format!("{{\"trustedFolders\": [\"{w}\"]}}"))));
    v.push(cp("trust-anahtar-yok").file(cfg("{\"x\": []}")));
    v.push(cp("trust-kapanmamis").file(cfg("{\"trustedFolders\": [ \"/a\"")));
    v.push(cp("trust-crlf").file(cfg("{\r\n\"trustedFolders\": [\r\n]\r\n}\r\n")));
    v.push(cp("trust-bozuk-utf8").file(Fx::File("home/.copilot/config.json".into(), vec![b'{', 0xff, b'}'], 0o600)));
    v.push(cp("trust-symlink")
        .file(file("home/gercek/config.json", "{\"trustedFolders\": []}", 0o640))
        .file(Fx::Link("home/.copilot/config.json".into(), "../gercek/config.json".into())));
    v.push(cp("trust-copilot-home").env("COPILOT_HOME", &format!("{}/ch", e.root)).file(file("ch/config.json", "{\"trustedFolders\": []}", 0o644)));
    v.push(cp("trust-copilot-home-bos").env("COPILOT_HOME", "").file(cfg("{\"trustedFolders\": []}")));
    v.push(bcase("copilot-trust-goreli".into(), "copilot", json!({"cwd": "p1"})).file(cfg("{\"trustedFolders\": []}")));
    v.push(bcase("copilot-trust-unicode".into(), "copilot", json!({"cwd": format!("{w}/ğ \"x\"")})).file(cfg("{\"trustedFolders\": []}")));
    let byok = |b: Value| json!({"byok": {"copilot": b}});
    v.push(cp("byok-yaz").settings_json(byok(json!({"ZED": "z v", "ALPHA": "it's", "bad-name": "x", "lower": "y", "N": "", "X": 5}))));
    v.push(cp("byok-ustune").settings_json(byok(json!({"A": "1"})))
        .file(file("home/.claude/claudeops/copilot_byok_env", "eski", 0o644)));
    v.push(cp("byok-sil-yonetilen")
        .file(file("home/.claude/claudeops/copilot_byok_env", "export A=1\n", 0o600))
        .file(file("home/.claude/claudeops/copilot_byok_env.managed", "", 0o600)));
    v.push(cp("byok-elle").file(file("home/.claude/claudeops/copilot_byok_env", "export A=1\n", 0o600)));
    v.push(cp("byok-yalniz-gecersiz").settings_json(byok(json!({"bad-name": "x"})))
        .file(file("home/.claude/claudeops/copilot_byok_env.managed", "", 0o600)));
    v.push(cp("byok-dizin-yok").settings_json(byok(json!({"A": "1"})))
        .file(Fx::Remove("home/.claude/claudeops".into())));
    v.push(cp("byok-symlink").settings_json(byok(json!({"A": "1"})))
        .file(file("home/hedef", "h", 0o600))
        .file(Fx::Link("home/.claude/claudeops/copilot_byok_env".into(), "../../hedef".into())));
    v
}

fn oneshot_cases() -> Vec<Case> {
    let helps = [
        "", "Options:\n  --no-session-persistence  x\n", "--no-session-persistence-x", "x--no-session-persistence",
        "a-–no-session-persistence", "--no-session-persistence", "--no-session-persistenceğ", "_--no-session-persistence",
    ];
    let mut v = Vec::new();
    for (i, h) in helps.iter().enumerate() {
        for cli in ["claude", "agy", "codex", "copilot", "shell", "ucli"] {
            v.push(
                Case::new(format!("oneshot{i}-{cli}"), "oneshot", json!({"cli": cli, "prompt": "özet: \"x\" --tools", "model": ([None, Some(""), Some("claude-haiku-5-5")])[i % 3]}))
                    .facts(json!({"claude_help": h})),
            );
        }
    }
    v.push(Case::new("oneshot-ikili-yok", "oneshot", json!({"cli": "claude", "prompt": "p"})).env("PATH", "").facts(json!({"claude_help": "--no-session-persistence"})));
    v
}

fn mcp_cases(e: &Env) -> Vec<Case> {
    let specs = [
        json!({"name": "cops-steward", "command": "/r/py/cops", "args": ["mcp-steward", "--steward", "abc"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "ABC"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "ab1"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "ğü"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "aB"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "a漢"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", ""]}),
        json!({"name": "s", "command": "c", "args": ["--steward"]}),
        json!({"name": "s", "command": "c", "args": ["--steward", "abc", "--steward", "def"]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext", "foo-bar_1"]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext", "foo/bar"]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext", "ğ"]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext", ""]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext", "--"]}),
        json!({"name": "s", "command": "c", "args": ["mcp-ext"]}),
        json!({"name": "s", "command": "c", "args": ["x", "mcp-ext", "y"]}),
        json!({"name": "ad \"q\"", "command": "/a b/ç", "args": ["it's", "ğ\n\u{1f}\\", "\u{2028}\u{7f}😀", ""]}),
        json!({"name": "e", "command": "c", "args": []}),
    ];
    let mut v = Vec::new();
    for (i, s) in specs.iter().enumerate() {
        for cli in ["claude", "codex", "agy", "copilot", "shell"] {
            v.push(Case::new(format!("mcp{i}-{cli}"), "mcp", json!({"cli": cli, "spec": s, "cwd": format!("{}/p1", e.work)})));
        }
    }
    v.push(Case::new("mcp-orchestration-dosya", "mcp", json!({"cli": "claude", "spec": specs[0]}))
        .file(file("state/orchestration/mcp_config_abc.json", "eski", 0o600)));
    v.push(Case::new("mcp-orchestration-engel", "mcp", json!({"cli": "claude", "spec": specs[0]}))
        .file(file("state/orchestration", "dosya", 0o600)));
    v
}

fn binary_cases(e: &Env) -> Vec<Case> {
    let mut v = Vec::new();
    for cli in ["claude", "codex", "agy", "copilot", "ucli", "yok"] {
        v.push(Case::new(format!("rb-{cli}"), "resolved_binary", json!({"cli": cli})));
        v.push(Case::new(format!("rb-{cli}-pathsiz"), "resolved_binary", json!({"cli": cli})).env("PATH", ""));
    }
    let ru = |id: &str| Case::new(format!("ru-{id}"), "resolve_ucli", json!({}));
    v.push(ru("path"));
    v.push(ru("hic").env("PATH", ""));
    v.push(ru("override").settings_json(json!({"provider_bin": {"ucli": "  /yok/ucli  "}})));
    v.push(ru("override-bos").settings_json(json!({"provider_bin": {"ucli": " "}})).env("PATH", ""));
    v.push(ru("env").env("UCLI_BIN", "/env/ucli"));
    v.push(ru("env-bos").env("UCLI_BIN", "").env("PATH", ""));
    v.push(ru("kardes-release").env("PATH", "")
        .file(file("home/work/projects/tmp/unified-cli/target/release/ucli", "x", 0o644))
        .file(file("home/work/projects/tmp/unified-cli/target/debug/ucli", "x", 0o755)));
    v.push(ru("kardes-debug").env("PATH", "").file(file("home/work/projects/tmp/unified-cli/target/debug/ucli", "x", 0o755)));
    v.push(ru("kardes-dizin").env("PATH", "").file(Fx::Dir("home/work/projects/tmp/unified-cli/target/release/ucli".into(), 0o755)));
    v.push(ru("override-tip").settings_json(json!({"provider_bin": {"ucli": null}})));
    v.push(ru("override-tip-sayi").settings_json(json!({"provider_bin": {"ucli": 5}})).env("UCLI_BIN", "/env/ucli"));
    // Kaynaklar birlikteyken öncelik (Python `ResolveBinaryTests`): ayar > `UCLI_BIN` > kendi kopya > PATH > kardeş
    // release > kardeş debug. Kendi kopya vaka ağacında (`repo/bin/ucli`).
    let own = |id: &str| Case::new(format!("ru-kendi-{id}"), "resolve_ucli_own", json!({}));
    let rel = "home/work/projects/tmp/unified-cli/target/release/ucli";
    let dbg = "home/work/projects/tmp/unified-cli/target/debug/ucli";
    let sh = "#!/bin/sh\n";
    v.push(own("path-ve-kardesleri-yener").file(file("work/repo/bin/ucli", sh, 0o755)).file(file(rel, sh, 0o755)).file(file(dbg, sh, 0o755)));
    v.push(own("yoksa-path-kardesleri-yener").file(file(rel, sh, 0o755)).file(file(dbg, sh, 0o755)));
    v.push(own("yoksa-pathsiz-release").env("PATH", "").file(file(rel, sh, 0o755)).file(file(dbg, sh, 0o755)));
    v.push(own("calistirilamaz-da-sayilir").env("PATH", "").file(file("work/repo/bin/ucli", sh, 0o644)));
    v.push(own("dizin-sayilmaz").env("PATH", "").file(Fx::Dir("work/repo/bin/ucli".into(), 0o755)).file(file(dbg, sh, 0o755)));
    v.push(own("env-yener").file(file("work/repo/bin/ucli", sh, 0o755)).env("UCLI_BIN", "/from/env/ucli"));
    v.push(own("ayar-env-yener").file(file("work/repo/bin/ucli", sh, 0o755)).env("UCLI_BIN", "/from/env/ucli")
        .settings_json(json!({"provider_bin": {"ucli": "/from/settings/ucli"}})));
    v.push(own("ayar-debuga-zorlar").file(file("work/repo/bin/ucli", sh, 0o755)).file(file(rel, sh, 0o755)).file(file(dbg, sh, 0o755))
        .settings_json(json!({"provider_bin": {"ucli": format!("{}/{dbg}", e.root)}})));
    v.push(own("env-debuga-zorlar").file(file("work/repo/bin/ucli", sh, 0o755)).file(file(rel, sh, 0o755)).file(file(dbg, sh, 0o755))
        .env("UCLI_BIN", &format!("{}/{dbg}", e.root)));
    v.push(own("hic").env("PATH", ""));
    v
}

pub fn run() {
    let mut r = Runner::new();
    let cases = build_cases(&r.e);
    r.run(cases, &[], rs_build);
    r.run(oneshot_cases(), &[], rs_oneshot);
    let cases = mcp_cases(&r.e);
    r.run(cases, &[], rs_mcp);
    let cases = binary_cases(&r.e);
    r.run(cases, &[], |e, c| match c.op {
        "resolve_ucli" => rs_resolve_ucli(e, c),
        "resolve_ucli_own" => rs_resolve_ucli_own(e, c),
        _ => rs_resolved_binary(e, c),
    });
    r.finish("build");
}
