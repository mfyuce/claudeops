//! Aile: `spawn.py` (plan_spawn = `spawn_session`ın komut kuran kısmı; dry-run satırı; gizli/gnome-terminal başlatmanın
//! komutu, ortamı ve pencere argv'si), `_apply_hook_session_cap`, `spawn_priority_prefix`, `_dry_run_preview`,
//! `_filter_env_overrides`, `detect_display`, `open_mirror_window`.

use crate::common::*;
use crate::fam_build::spec_of;
use crate::fam_model::with;
use crate::fam_ucli::full_help;
use cops_providers::spawn::{
    apply_hook_session_cap, child_env, detect_display, dry_run_preview, filter_env_overrides,
    gnome_terminal_argv, mirror_child_env, mirror_window_command, plan_spawn, priority_prefix,
    window_command, SpawnRequest,
};
use cops_providers::Cli;
use serde_json::{json, Value};
use std::path::Path;

/// Python koşucusunun `os.environ`'u: sabit taban + vaka ortamı (dict ataması: var olan anahtar yerinde).
pub fn parent_env(e: &Env, c: &Case) -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = vec![
        ("HOME".into(), e.home.clone()),
        ("CLAUDEOPS_DIR".into(), e.state.clone()),
        ("PATH".into(), e.bin.clone()),
        ("CLAUDEOPS_EXTENSIONS".into(), "0".into()),
        ("COPS_PARITY_ROOT".into(), e.root.clone()),
    ];
    for (k, v) in &c.env {
        match env.iter_mut().find(|(h, _)| h == k) {
            Some(slot) => slot.1 = v.clone(),
            None => env.push((k.clone(), v.clone())),
        }
    }
    env
}

pub fn pairs(v: &[(String, String)]) -> Vec<Value> {
    v.iter().map(|(k, x)| json!([k, x])).collect()
}

fn kv(v: Option<&Value>) -> Vec<(String, String)> {
    v.and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .map(|p| {
                    (
                        p[0].as_str().unwrap().to_string(),
                        p[1].as_str().unwrap().to_string(),
                    )
                })
                .collect()
        })
        .unwrap_or_default()
}

fn rs_spawn(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let a = &c.args;
        let s = |k: &str| a.get(k).and_then(Value::as_str).map(String::from);
        let req = SpawnRequest {
            name: s("name").unwrap(),
            cwd: s("cwd").unwrap(),
            model: s("model").unwrap(),
            permission_mode: s("perm").unwrap(),
            effort: s("effort").unwrap(),
            resume_id: s("resume"),
            prompt: s("prompt"),
            cli: s("cli").unwrap(),
            mcp_server: a.get("mcp").filter(|v| !v.is_null()).map(spec_of),
            extension_mcp: c.fact("extension_mcp").map(spec_of),
            hook_env: kv(c.fact("hook_env")),
            cli_opts: a.get("cli_opts").and_then(Value::as_object).cloned(),
            dry_run: a["mode"] == "dry",
        };
        let mut rs = RsOut::default();
        let res = plan_spawn(p, &req, &mut rs.out);
        rs.mcp_calls = probe.mcp_calls.borrow().clone();
        let plan = match res {
            Ok(plan) => plan,
            Err(err) => {
                rs.exc = Some(err.0);
                return rs;
            }
        };
        let mode = a["mode"].as_str().unwrap();
        let env = child_env(parent_env(e, c), ":7");
        rs.ret = match mode {
            "dry" => json!({"ret": plan.dry_run_line(&req.cwd), "direct": []}),
            "hidden" => {
                json!({"ret": plan.kind, "direct": [{"name": req.name, "cwd": req.cwd, "inner": plan.inner,
                                                              "env": pairs(&env)}]})
            }
            _ => {
                let frag = format!("TMUXFRAG<{}|{}|{}>", req.name, req.cwd, plan.inner);
                let win = window_command(&plan.inner, (mode == "gt_tmux").then_some(frag.as_str()));
                rs.popen.push(json!({"argv": gnome_terminal_argv(&req.name, &req.cwd, &win), "env": pairs(&env)}));
                json!({"ret": plan.kind, "direct": []})
            }
        };
        rs
    })
}

const DROP: [&str; 4] = [
    "spawn_hidden",
    "spawn_direct_headless",
    "spawn_no_gnome_terminal",
    "spawn_launch_failed",
];

fn spawn_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/p1", e.work);
    let mut v = Vec::new();
    let base = |id: String, cli: &str, mode: &str, extra: Value| {
        let mut a = json!({"cli": cli, "mode": mode, "name": "s1", "cwd": w, "model": "m", "perm": "auto", "effort": "high"});
        a.as_object_mut()
            .unwrap()
            .extend(extra.as_object().unwrap().clone());
        Case::new(id, "spawn", a).facts(json!({"ucli_help": full_help()}))
    };
    let long = format!("{}ğ'\"", "uzun istem ".repeat(70));
    for cli in [
        "claude", "agy", "codex", "copilot", "shell", "ucli", "bogus",
    ] {
        for mode in ["dry", "hidden", "gt", "gt_tmux"] {
            v.push(base(format!("{cli}-{mode}"), cli, mode, json!({})));
            v.push(
                base(
                    format!("{cli}-{mode}-dolu"),
                    cli,
                    mode,
                    json!({"name": "a b'c", "prompt": long, "resume": "1234567890abcdef",
                "model": "gemini-3.8-flash-high", "effort": "max", "perm": "plan"}),
                )
                .facts(json!({"agy_models": ["gemini-3.8-flash-high"]}))
                .env("DISPLAY", ":3")
                .env("CLAUDE_CODE_X", "1")
                .env("GEMINI_KEY", "g")
                .env("ANTIGRAVITY_Y", "a")
                .env("XCLAUDE", "kalir"),
            );
        }
        v.push(base(format!("{cli}-kanca"), cli, "dry", json!({"cli_opts": {"max_session_usd": 5}}))
            .facts(json!({"hook_env": [["CLAUDEOPS_SESSION_USD_CAP", "2.5"], ["COPS_NAME", "ezilir"], ["API_KEY", "sır"],
                                       ["LD_PRELOAD", "/x.so"], ["lower", "x"], ["A B", "x"], ["MY_TOKEN", "t"], ["Auth_X", "a"],
                                       ["UCLI_HOME", "/u h"], ["BASH_ENV", "b"], ["PS4", "p"], ["", "e"]]})));
        // S4: `_KEY`/`_TOKEN`/`_SECRET` adları komut satırında yok, `state/spawn-env/<token>.env` (0700/0600) yazılır.
        for mode in ["dry", "hidden", "gt", "gt_tmux"] {
            v.push(base(format!("{cli}-sir-{mode}"), cli, mode, json!({}))
                .facts(json!({"hook_env": [["PROVIDER_DIR", "/p d"], ["API_KEY", "s'ır $(id)"], ["MY_TOKEN", "t"],
                                           ["X_SECRET", "z"], ["TOKENS", "2"], ["KEY_DIR", "/k"], ["PASSWORD", "p"],
                                           ["DB_PASSWD", "d"], ["GH_CREDENTIALS", "c"], ["PASSWORDS", "kalir"], ["password", "kalir"],
                                           ["GITHUB_PAT", "g"], ["DATABASE_DSN", "pg://u:p@h"], ["NPM_AUTH", "n"],
                                           ["GPG_PASSPHRASE", "q"], ["X_APIKEY", "k"], ["PATH_EXTRA", "kalir"], ["XPAT", "kalir"]]})));
        }
        v.push(base(format!("{cli}-kanca-gizli"), cli, "hidden", json!({}))
            .facts(json!({"hook_env": [["COPS_NAME", "ezilir"], ["PROVIDER_DIR", "/p d"], ["IFS", "x"]]})));
        v.push(
            base(
                format!("{cli}-beyin"),
                cli,
                "hidden",
                json!({"name": "degnekci_iso"}),
            )
            .settings_json(json!({"spawn_nice": "3"})),
        );
        v.push(
            base(format!("{cli}-nice-kapali"), cli, "hidden", json!({}))
                .settings_json(json!({"spawn_nice": "off"})),
        );
        v.push(base(
            format!("{cli}-mcp"),
            cli,
            "dry",
            json!({"mcp": {"name": "cops-steward", "command": "/r/cops",
            "args": ["mcp-steward", "--steward", "iso"], "allowed_tools": ["ask"]}}),
        ));
        v.push(base(format!("{cli}-eklenti-mcp"), cli, "dry", json!({}))
            .facts(json!({"extension_mcp": {"name": "notes", "command": "/r/cops", "args": ["mcp-ext", "notes"], "allowed_tools": ["t"]}})));
        v.push(base(format!("{cli}-eklenti-ve-acik-mcp"), cli, "dry", json!({"mcp": {"name": "a", "command": "c", "args": []}}))
            .facts(json!({"extension_mcp": {"name": "notes", "command": "/r/cops", "args": ["mcp-ext", "notes"]}})));
        v.push(base(
            format!("{cli}-cwd-tirnak"),
            cli,
            "dry",
            json!({"cwd": format!("{w}/a b'c")}),
        ));
    }
    // Yan etkili dallar: kuru kipte dosya/diag/`mcp add` yok, komut satırı aynı; gizli kipte hepsi uygulanır.
    let mcp = json!({"name": "s", "command": "/r/cops", "args": [], "allowed_tools": ["t"]});
    for mode in ["dry", "hidden"] {
        let byok = json!({"byok": {"ucli": {"UCLI_API_KEY": "k", "ANTHROPIC_API_KEY": "a"},
                                   "copilot": {"COPILOT_PROVIDER_API_KEY": "c"}},
                          "routing_guidance_text": "yönerge"});
        for (i, name) in ["s1", "a b"].iter().enumerate() {
            v.push(base(format!("yan-ucli-{mode}-{i}"), "ucli", mode, json!({"name": name, "mcp": mcp}))
                .facts(json!({"panel_port": 8765, "searxng_url": "http://127.0.0.1:1",
                              "agent_token": {"path": format!("{}/ucli_agent_tokens/{name}", e.state)}}))
                .settings_json(byok.clone()));
        }
        v.push(
            base(
                format!("yan-ucli-hizmet-{mode}"),
                "ucli",
                mode,
                json!({"cli_opts": {"service": "claude", "ask_dir": true}}),
            )
            .settings_json(byok.clone()),
        );
        for cli in ["claude", "copilot"] {
            v.push(
                base(format!("yan-{cli}-{mode}"), cli, mode, json!({"mcp": mcp}))
                    .settings_json(byok.clone())
                    .file(file(
                        "home/.copilot/config.json",
                        "{\"trustedFolders\": []}",
                        0o600,
                    )),
            );
        }
    }
    // effort düzeltme olayı (agy kademeli kimlik, codex önbelleği).
    v.push(base(
        "agy-effort-ayar".into(),
        "agy",
        "dry",
        json!({"model": "gemini-3.8-flash-high", "effort": "low"}),
    ));
    v.push(
        base(
            "agy-effort-kardes".into(),
            "agy",
            "dry",
            json!({"model": "gemini-3.8-flash", "effort": "max"}),
        )
        .facts(json!({"agy_models": ["gemini-3.8-flash-low", "gemini-3.8-flash-medium"]})),
    );
    v.push(
        base(
            "codex-effort".into(),
            "codex",
            "dry",
            json!({"model": "gpt-5.5", "effort": "max"}),
        )
        .file(file(
            "home/.codex/models_cache.json",
            &json!({"models": [{"slug": "gpt-5.5", "visibility": "list",
            "supported_reasoning_levels": ["low", "high"]}]})
            .to_string(),
            0o644,
        )),
    );
    // ucli: cli_opts + kanca tavanı, hata.
    v.push(
        base(
            "ucli-opts".into(),
            "ucli",
            "hidden",
            json!({"cli_opts": {"exec_cmds": ["git"], "max_session_usd": 50}}),
        )
        .facts(
            json!({"hook_env": [["CLAUDEOPS_SESSION_USD_CAP", "12"]], "path_executables": ["git"]}),
        ),
    );
    v.push(
        base(
            "ucli-opts-hata".into(),
            "ucli",
            "dry",
            json!({"cli_opts": {"git_commit": true}}),
        )
        .facts(json!({"ucli_help": ""})),
    );
    v.push(base("ucli-ikili-yok".into(), "ucli", "dry", json!({})).env("PATH", ""));
    v.push(
        base("ucli-anahtar".into(), "ucli", "hidden", json!({}))
            .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}})),
    );
    v.push(base(
        "ucli-opts-bos".into(),
        "ucli",
        "dry",
        json!({"cli_opts": {}}),
    ));
    v.push(base(
        "claude-opts".into(),
        "claude",
        "dry",
        json!({"cli_opts": {"exec_cmds": ["git"]}}),
    ));
    v
}

fn rs_hook_cap(e: &Env, c: &Case) -> RsOut {
    let s = e.settings();
    let mut env = kv(c.args.get("hook_env"));
    let opts = apply_hook_session_cap(
        &mut env,
        c.args.get("cli_opts").and_then(Value::as_object).cloned(),
        Cli::parse(c.args["cli"].as_str().unwrap()),
        &s,
    );
    RsOut::ret(json!({"opts": opts, "env": pairs(&env)}))
}

fn hook_cases() -> Vec<Case> {
    let caps = [
        "2.5", " 3 ", "0", "-1", "abc", "inf", "nan", "1e-9", "0.001", "1_0", "١٠", "\u{1f}5",
        "Infinity", "", "1e400",
    ];
    let opts = [
        json!(null),
        json!({}),
        json!({"max_session_usd": 5}),
        json!({"max_session_usd": "7"}),
        json!({"max_session_usd": 0}),
        json!({"max_session_usd": true}),
        json!({"max_session_usd": [1]}),
        json!({"max_session_usd": " 4\u{1f}"}),
        json!({"max_session_usd": "nan"}),
        json!({"max_session_usd": -3}),
        json!({"x": 1}),
    ];
    let mut v = Vec::new();
    for (i, cap) in caps.iter().enumerate() {
        for (j, o) in opts.iter().enumerate() {
            for cli in ["ucli", "claude"] {
                if cli == "claude" && j > 2 {
                    continue;
                }
                v.push(Case::new(format!("kanca-{i}-{j}-{cli}"), "hook_cap",
                    json!({"cli": cli, "cli_opts": o, "hook_env": [["A", "1"], ["CLAUDEOPS_SESSION_USD_CAP", cap], ["B", "2"]]})));
            }
        }
    }
    v.push(Case::new(
        "kanca-yok",
        "hook_cap",
        json!({"cli": "ucli", "cli_opts": {"a": 1}, "hook_env": [["A", "1"]]}),
    ));
    v.push(Case::new("kanca-ayar", "hook_cap", json!({"cli": "ucli", "cli_opts": {}, "hook_env": [["CLAUDEOPS_SESSION_USD_CAP", "20"]]}))
        .settings_json(json!({"ucli_max_session_usd": "0"})));
    v.push(Case::new("kanca-ayar2", "hook_cap", json!({"cli": "ucli", "cli_opts": null, "hook_env": [["CLAUDEOPS_SESSION_USD_CAP", "20"]]}))
        .settings_json(json!({"ucli_max_session_usd": "30"})));
    v
}

fn rs_misc(e: &Env, c: &Case) -> RsOut {
    let a = &c.args;
    let s = |k: &str| a.get(k).and_then(Value::as_str).unwrap_or("");
    RsOut::ret(match c.op {
        "prefix" => json!(priority_prefix(&e.settings(), s("name"))),
        "preview" => json!(dry_run_preview(s("cwd"), &kv(a.get("overrides")), s("inv"))),
        "filter_env" => json!(pairs(&filter_env_overrides(kv(a.get("overrides"))))),
        "detect_display" => {
            let d = c
                .env
                .iter()
                .rev()
                .find(|(k, _)| k == "DISPLAY")
                .map(|(_, v)| v.as_str());
            json!(detect_display(d, &|p| Path::new(p).exists()))
        }
        "mirror" => {
            let (host, name, port) = (s("host"), s("name"), a["port"].as_u64().unwrap() as u16);
            let mut rs = RsOut::ret(json!({"ok": true}));
            let win = mirror_window_command(&e.repo, host, name, port);
            rs.popen.push(json!({
                "argv": gnome_terminal_argv(&format!("{host}:{name}"), &e.home, &win),
                "env": pairs(&mirror_child_env(parent_env(e, c), ":7", &e.state)),
            }));
            return rs;
        }
        op => panic!("bilinmeyen işlem {op}"),
    })
}

fn misc_cases() -> Vec<Case> {
    let mut v = Vec::new();
    for (i, n) in [
        "s1",
        "degnekci",
        "degnekci_x",
        "Degnekci",
        " degnekci",
        "",
        "değnekçi",
    ]
    .iter()
    .enumerate()
    {
        for (j, nice) in [json!(null), json!("5"), json!("off"), json!(19), json!(20)]
            .iter()
            .enumerate()
        {
            let c = Case::new(format!("prefix-{i}-{j}"), "prefix", json!({"name": n}));
            v.push(if nice.is_null() {
                c
            } else {
                c.settings_json(json!({"spawn_nice": nice}))
            });
        }
    }
    let long = "x".repeat(700);
    let ov = json!([
        ["API_KEY", "s"],
        ["my_token", "t"],
        ["Auth", "a"],
        ["PASSWORD", "p"],
        ["CREDENTIALS_FILE", "c"],
        ["SECRET", "z"],
        ["PASSWD", "q"],
        ["GITHUB_PAT", "g"],
        ["DATABASE_DSN", "d"],
        ["GPG_PASSPHRASE", "p"],
        ["PATH_EXTRA", "x"],
        ["COPS_NAME", "a b"],
        ["MONKEY", "m"],
        ["\u{212a}EY", "k"],
        ["ſecret", "s"],
        ["X", "it's"]
    ]);
    v.push(Case::new(
        "preview",
        "preview",
        json!({"cwd": "/a b", "overrides": ov, "inv": "claude --model m"}),
    ));
    v.push(Case::new(
        "preview-uzun",
        "preview",
        json!({"cwd": "/w", "overrides": [], "inv": long}),
    ));
    v.push(Case::new(
        "preview-unicode",
        "preview",
        json!({"cwd": "/w", "overrides": [], "inv": "ğ".repeat(700)}),
    ));
    v.push(Case::new(
        "preview-sinir",
        "preview",
        json!({"cwd": "/w", "overrides": [], "inv": "y".repeat(600 - 9)}),
    ));
    v.push(Case::new(
        "preview-sinir2",
        "preview",
        json!({"cwd": "/w", "overrides": [], "inv": "y".repeat(600 - 8)}),
    ));
    v.push(Case::new("filter", "filter_env", json!({"overrides": [["OK", "1"], ["LD_PRELOAD", "x"], ["LD_LIBRARY_PATH", "x"],
        ["LD_AUDIT", "x"], ["BASH_ENV", "x"], ["ENV", "x"], ["PROMPT_COMMAND", "x"], ["SHELLOPTS", "x"], ["BASHOPTS", "x"],
        ["PS4", "x"], ["IFS", "x"], ["lower", "x"], ["_U", "x"], ["9X", "x"], ["A-B", "x"], ["", "x"], ["X\n", "x"], ["Ä", "x"],
        ["A1_", "y"]]})));
    v.push(Case::new("display-env", "detect_display", json!({})).env("DISPLAY", ":9"));
    v.push(Case::new("display-bos", "detect_display", json!({})).env("DISPLAY", ""));
    v.push(Case::new("display-yok", "detect_display", json!({})));
    v.push(
        Case::new(
            "ayna",
            "mirror",
            json!({"host": "ulak31", "name": "proje 1", "port": 8765}),
        )
        .env("DISPLAY", ":0")
        .env("CLAUDE_X", "1"),
    );
    v.push(Case::new(
        "ayna-tirnak",
        "mirror",
        json!({"host": "h'x", "name": "ğ\"", "port": 1}),
    ));
    v
}

pub fn run() {
    let mut r = Runner::new();
    let cases = spawn_cases(&r.e);
    r.run(cases, &DROP, rs_spawn);
    r.run(hook_cases(), &[], rs_hook_cap);
    r.run(misc_cases(), &[], rs_misc);
    r.finish("spawn");
}
