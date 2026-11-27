//! Aile: ucli komut kurulumu. `chat --help` yoklamasına bağlı her bayrak (tanınan / tanınmayan / değer listesi), ayarlar
//! (`ucli_limits`, web, script, metrics, state-dir, endpoint, byok anahtar dosyası), `cli_opts` doğrulama + uygulama
//! (hizmetler, exec ailesi, git/yetenek izinleri, ask_dir, ucli_checks, USD tavanları), alt ajan token'ı, MCP kaydı.

use crate::common::*;
use crate::fam_build::{rs_build, spec_of};
use crate::fam_model::with;
use cops_providers::ucli::state_dir_for;
use cops_providers::{BuildOutput, Cli};
use serde_json::{json, Value};

pub const FLAGS: [&str; 51] = [
    "--allow-create",
    "--search-url",
    "--allow-fetch",
    "--allow-script",
    "--request-timeout-secs",
    "--max-history-kib",
    "--effort",
    "--stream",
    "--show-reasoning",
    "--metrics-file",
    "--interactive",
    "--state-dir",
    "--provider",
    "--cache-ttl",
    "--usage-log",
    "--instructions-auto",
    "--max-cost-usd",
    "--max-session-usd",
    "--allow-git-commit",
    "--allow-git-push",
    "--max-prompt-tokens",
    "--max-repeated-calls",
    "--max-consecutive-failures",
    "--max-continuation-steps",
    "--exec-per-script",
    "--price",
    "--no-prompt-cache",
    "--show-usage",
    "--checkpoint",
    "--instructions-user",
    "--instructions-max-kib",
    "--search-token-env",
    "--allow-image",
    "--allow-scholar",
    "--ask-dir",
    "--allow-exec",
    "--allow-exec-cmd",
    "--allow-exec-own-glob",
    "--exec-bind-ro",
    "--exec-env",
    "--exec-memory-mib",
    "--exec-max-tasks",
    "--exec-timeout-secs",
    "--allow-edit",
    "--ask-edit",
    "--allow-checks",
    "--checks-max",
    "--checks-file",
    "--checks-accept-risk",
    "--allow-agents",
    "--with-mcp",
];

/// `chat --help` metni: `skip` dışındaki bayraklar; değer listeleri `values`.
pub fn help(skip: &[&str], values: &[(&str, &str)], derives: bool) -> String {
    let mut out = String::from("Usage: ucli chat [OPTIONS]\n\nOptions:\n");
    for f in FLAGS.iter().filter(|f| !skip.contains(f)) {
        out.push_str(&format!("      {f} <VAL>\n          açıklama"));
        if let Some((_, v)) = values.iter().find(|(k, _)| k == f) {
            out.push_str(&format!(" [possible values: {v}]"));
        }
        out.push('\n');
    }
    if derives {
        out.push_str("  --max-context-kib: when the model advertises a large window, derived\n");
    }
    out
}

pub fn full_help() -> String {
    help(
        &[],
        &[
            ("--allow-checks", "restricted, full"),
            ("--checks-max", "restricted, full"),
        ],
        false,
    )
}

fn toolchain(e: &Env) -> Value {
    let root = format!(
        "{}/.rustup/toolchains/stable-x86_64-unknown-linux-gnu",
        e.home
    );
    json!({"root": root, "cargo": format!("{root}/bin/cargo"), "rustc": format!("{root}/bin/rustc"),
           "registry": format!("{}/.cargo/registry", e.home), "git": format!("{}/.cargo/git", e.home),
           "rustup_home": format!("{}/.rustup", e.home), "cargo_home": format!("{}/.cargo", e.home)})
}

fn ucase(e: &Env, id: impl Into<String>, args: Value) -> Case {
    let mut base = json!({"cli": "ucli", "cwd": format!("{}/p1", e.work), "model": "glm-5.3", "perm": "read-only",
                          "effort": "medium", "name": "s1"});
    base.as_object_mut()
        .unwrap()
        .extend(args.as_object().unwrap().clone());
    Case::new(id, "build", base).facts(json!({"ucli_help": full_help(), "path_executables": ["cargo", "git", "ls", "python3", "rg", "sh", "make"]}))
}

fn opts(e: &Env, id: &str, raw: Value) -> Case {
    ucase(
        e,
        format!("opts-{id}"),
        json!({"validate": true, "raw_opts": raw}),
    )
}

fn caps() -> Value {
    json!({"ids": ["glm-5.3", "gemma-4-31b", "deepseek-v4-flash", "qwen"],
           "caps": {"glm-5.3": {"reasoning_effort": true, "reasoning_effort_values": ["low", "high"],
                                "reasoning_effort_aliases": {"medium": "high"}},
                    "gemma-4-31b": {"reasoning_effort": false},
                    "deepseek-v4-flash": {"reasoning_effort": true, "reasoning_effort_values": null},
                    "qwen": {"reasoning_effort": true, "reasoning_effort_values": ["max"]}}})
}

fn build_cases(e: &Env) -> Vec<Case> {
    let mut v = Vec::new();
    let w = format!("{}/p1", e.work);
    // Temel: izin kipi x effort x model x oturum adı.
    let perms = ["read-only", "allow-edit", "allow-create", "", "bogus"];
    let efforts = ["medium", "high", "low", "", "max"];
    let models = [
        "glm-5.3",
        "",
        "gemma-4-31b",
        "deepseek-v4-flash",
        "qwen",
        "bilinmeyen",
    ];
    let names = ["s1", "", "a b", "ğ_ad", "s1_aj2", "s1_aj0", "x\n"];
    for (i, perm) in perms.iter().enumerate() {
        for (j, eff) in efforts.iter().enumerate() {
            let k = i * 5 + j;
            v.push(
                ucase(
                    e,
                    format!("temel-{k}"),
                    json!({"perm": perm, "effort": eff, "model": models[k % models.len()],
                "name": names[k % names.len()]}),
                )
                .facts(json!({"ucli_live": caps()})),
            );
        }
    }
    // Eski ikili: hiçbir isteğe bağlı bayrak yok / bağlam türetme işareti / tek tek eksik bayraklar.
    v.push(
        ucase(e, "eski-ikili", json!({"perm": "allow-create"}))
            .facts(json!({"ucli_help": "", "ucli_live": caps()})),
    );
    v.push(ucase(e, "turetir", json!({})).facts(json!({"ucli_help": help(&[], &[], true)})));
    v.push(
        ucase(e, "turetir-ayar", json!({}))
            .facts(json!({"ucli_help": help(&[], &[], true)}))
            .settings_json(json!({"ucli_limits": {"max_context_kib": "512"}})),
    );
    for f in [
        "--search-url",
        "--allow-fetch",
        "--effort",
        "--stream",
        "--metrics-file",
        "--interactive",
        "--state-dir",
        "--usage-log",
        "--request-timeout-secs",
        "--max-history-kib",
        "--allow-agents",
        "--allow-script",
        "--show-reasoning",
        "--allow-create",
    ] {
        v.push(ucase(e, format!("eksik{f}"), json!({"perm": "allow-create"}))
            .facts(json!({"ucli_help": help(&[f], &[], false), "ucli_live": caps(), "panel_port": 8765,
                          "agent_token": {"path": "/tok/s1"}, "searxng_url": "http://127.0.0.1:18080"}))
            .settings_json(json!({"ucli_web": {"allow_fetch_domains": "a.com"}, "ucli_limits": {"state_dir": "on",
                "show_reasoning": "on"}, "ucli_script": {"mode": "read"}})));
    }
    // Bayrak eşleşmesi TAM sözcük: önek/sonek benzerleri bayrak sayılmaz.
    v.push(ucase(e, "benzer-bayrak", json!({})).facts(json!({"ucli_help":
        "--stream-x --xinteractive -–effort --state-dirs --usage_log --interactiveğ ğ--metrics-file --metrics-file"})));
    // Ayarlar.
    let st = |id: &str, s: Value| {
        ucase(e, format!("ayar-{id}"), json!({}))
            .settings_json(s)
            .facts(json!({"ucli_live": caps()}))
    };
    v.push(st(
        "limit",
        json!({"ucli_limits": {"max_steps": "7", "max_context_kib": "9", "max_tool_calls": "3",
        "max_output_tokens": "100", "request_timeout_secs": "30", "max_history_kib": "16"}}),
    ));
    v.push(st(
        "limit-high",
        json!({"ucli_limits": {"max_steps": "0", "max_tool_calls": "x"}}),
    ));
    v.push(
        ucase(e, "ayar-limit-high-effort", json!({"effort": "high"}))
            .settings_json(json!({"ucli_limits": {"max_output_tokens": "5"}})),
    );
    for mode in ["off", "low", "max", "auto", "medium", "high"] {
        v.push(st(
            &format!("reasoning-{mode}"),
            json!({"ucli_limits": {"reasoning_effort": mode}}),
        ));
    }
    v.push(st(
        "stream-off",
        json!({"ucli_limits": {"stream": "off", "show_reasoning": "on"}}),
    ));
    v.push(st("script-full", json!({"ucli_script": {"mode": "full"}})));
    v.push(st(
        "metrics-off",
        json!({"ucli_metrics": {"enabled": "off"}}),
    ));
    v.push(st(
        "endpoint",
        json!({"ucli_endpoint": "https://ozel.example/v1/"}),
    ));
    v.push(st(
        "endpoint-gecersiz",
        json!({"ucli_endpoint": "javascript:x"}),
    ));
    v.push(st("web-url", json!({"ucli_web": {"search_url": "https://s.example/x", "allow_fetch_domains": ["a.com", "b.org"]}})));
    v.push(st(
        "web-docker-kapali",
        json!({"ucli_web": {"search_docker": "off"}}),
    ));
    v.push(
        ucase(e, "web-docker-hazir", json!({}))
            .facts(json!({"searxng_url": "http://127.0.0.1:18080"})),
    );
    v.push(ucase(e, "web-docker-bos-url", json!({})).facts(json!({"searxng_url": ""})));
    v.push(
        ucase(e, "web-eksik-bayrak-docker", json!({}))
            .facts(json!({"ucli_help": help(&["--search-url"], &[], false)})),
    );
    v.push(
        ucase(e, "web-eksik-bayrak-url", json!({}))
            .facts(json!({"ucli_help": help(&["--search-url"], &[], false)}))
            .settings_json(json!({"ucli_web": {"search_url": "https://s/x"}})),
    );
    // state-dir: ayar açık, oturum geçmişi yeni dizinde, eski dizinde, ikisinde.
    let sdir = state_dir_for(&format!("{}/.claude/claudeops/ucli-state", e.home), &w);
    let srel = sdir
        .strip_prefix(&format!("{}/", e.root))
        .unwrap()
        .to_string();
    v.push(st(
        "statedir-acik",
        json!({"ucli_limits": {"state_dir": "on"}}),
    ));
    v.push(ucase(e, "statedir-yeni-gecmis", json!({})).file(file(
        &format!("{srel}/s1.jsonl"),
        "{}",
        0o600,
    )));
    v.push(
        ucase(e, "statedir-eski-gecmis", json!({}))
            .settings_json(json!({"ucli_limits": {"state_dir": "on"}}))
            .file(file("work/p1/.ucli/chat/s1.jsonl", "{}", 0o600)),
    );
    v.push(
        ucase(e, "statedir-iki-gecmis", json!({}))
            .file(file(&format!("{srel}/s1.jsonl"), "{}", 0o600))
            .file(file("work/p1/.ucli/chat/s1.jsonl", "{}", 0o600)),
    );
    v.push(
        ucase(e, "statedir-adsiz", json!({"name": ""}))
            .settings_json(json!({"ucli_limits": {"state_dir": "on"}})),
    );
    v.push(
        ucase(
            e,
            "statedir-cwd-sondaki-egik",
            json!({"cwd": format!("{w}/")}),
        )
        .settings_json(json!({"ucli_limits": {"state_dir": "on"}})),
    );
    v.push(
        ucase(
            e,
            "statedir-cwd-yok",
            json!({"cwd": format!("{w}/yok/../q")}),
        )
        .settings_json(json!({"ucli_limits": {"state_dir": "on"}})),
    );
    v.push(
        ucase(
            e,
            "statedir-cwd-symlink",
            json!({"cwd": format!("{}/bag", e.work)}),
        )
        .settings_json(json!({"ucli_limits": {"state_dir": "on"}}))
        .file(Fx::Link("work/bag".into(), "p1".into())),
    );
    v.push(
        ucase(e, "statedir-cwd-kok", json!({"cwd": "/"}))
            .settings_json(json!({"ucli_limits": {"state_dir": "on"}})),
    );
    v.push(
        ucase(
            e,
            "statedir-cwd-unicode",
            json!({"cwd": format!("{}/ğ ü+x", e.work)}),
        )
        .settings_json(json!({"ucli_limits": {"state_dir": "on"}})),
    );
    // Evren anahtar dosyası (byok.ucli.UCLI_API_KEY) eşitlemesi.
    let key = |id: &str| ucase(e, format!("anahtar-{id}"), json!({}));
    v.push(
        key("yaz").settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "  evren_llm_k  "}}})),
    );
    v.push(key("bosluk").settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": " \u{1f} "}}})));
    v.push(
        key("sil")
            .file(file("home/.claude/claudeops/ucli_api_key", "eski", 0o600))
            .file(file(
                "home/.claude/claudeops/ucli_api_key.managed",
                "",
                0o600,
            )),
    );
    v.push(key("elle").file(file("home/.claude/claudeops/ucli_api_key", "eski", 0o644)));
    v.push(
        key("izin")
            .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}}))
            .file(file("home/.claude/claudeops/ucli_api_key", "eski", 0o644)),
    );
    v.push(
        key("dizin-yok")
            .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}}))
            .file(Fx::Remove("home/.claude/claudeops".into())),
    );
    v.push(key("ev-bosluklu").settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}})));
    // Alt ajan.
    let ag = |id: &str| ucase(e, format!("ajan-{id}"), json!({}));
    v.push(ag("acik").facts(json!({"panel_port": 8765, "agent_token": {"path": "/x y/tok"}})));
    v.push(
        ag("anahtarli")
            .facts(json!({"panel_port": 8765, "agent_token": {"path": "/tok"}}))
            .settings_json(json!({"byok": {"ucli": {"UCLI_API_KEY": "k"}}})),
    );
    v.push(ag("port-yok").facts(json!({"agent_token": {"path": "/tok"}})));
    v.push(ag("port-sifir").facts(json!({"panel_port": 0, "agent_token": {"path": "/tok"}})));
    v.push(
        ag("token-hata").facts(json!({"panel_port": 8765, "agent_token": {"error": "disk dolu"}})),
    );
    v.push(
        ag("kapali")
            .facts(json!({"panel_port": 8765}))
            .settings_json(json!({"ucli_agents": "off"})),
    );
    v.push(
        ucase(e, "ajan-cocuk", json!({"name": "ust_aj3"}))
            .facts(json!({"panel_port": 8765, "agent_token": {"path": "/t"}})),
    );
    v.push(
        ucase(e, "ajan-adsiz", json!({"name": ""}))
            .facts(json!({"panel_port": 8765, "agent_token": {"path": "/t"}})),
    );
    // --with-mcp yalnız extra_args'tan.
    v.push(ucase(
        e,
        "with-mcp",
        json!({"extra": ["--with-mcp", "--başka"]}),
    ));
    v.push(ucase(
        e,
        "with-mcp-yok",
        json!({"extra": ["--mcp-config", "x"]}),
    ));
    v
}

fn opts_cases(e: &Env) -> Vec<Case> {
    let mut v = Vec::new();
    let tc = toolchain(e);
    let raws: Vec<(&str, Value)> = vec![
        ("bos", json!({})),
        ("null", json!(null)),
        ("liste", json!([1])),
        ("dize", json!("x")),
        ("sifir", json!(0)),
        ("hizmet-bilinmeyen", json!({"service": "yok"})),
        ("hizmet-evren", json!({"service": " EVREN "})),
        ("hizmet-claude-anahtarsiz", json!({"service": "claude"})),
        ("hizmet-grok-anahtarsiz", json!({"service": "grok"})),
        ("cmds-temel", json!({"exec_cmds": "cargo, git\nrg,,cargo"})),
        ("cmds-liste", json!({"exec_cmds": ["cargo", " git ", 5]})),
        (
            "cmds-cok",
            json!({"exec_cmds": (0..13).map(|i| format!("c{i}")).collect::<Vec<_>>()}),
        ),
        ("cmds-kabuk", json!({"exec_cmds": "bash"})),
        ("cmds-buyuk", json!({"exec_cmds": "Rscript"})),
        ("cmds-python3", json!({"exec_cmds": "python3.11"})),
        ("cmds-yol", json!({"exec_cmds": "/bin/ls"})),
        ("cmds-eval", json!({"exec_cmds": "ls:allow-eval"})),
        ("cmds-gecersiz", json!({"exec_cmds": "-rf"})),
        ("cmds-glob", json!({"exec_cmds": "car*,?it"})),
        ("cmds-glob-gecersiz", json!({"exec_cmds": "ca$*"})),
        ("cmds-re", json!({"exec_cmds": "re:^(cargo|rg)$"})),
        ("cmds-re-bos", json!({"exec_cmds": "re:"})),
        (
            "cmds-re-uzun",
            json!({"exec_cmds": format!("re:{}", "a".repeat(61))}),
        ),
        ("cmds-re-bozuk", json!({"exec_cmds": "re:(a"})),
        ("cmds-re-lookahead", json!({"exec_cmds": "re:(?!sh)[a-z]+"})),
        ("cmds-re-backref", json!({"exec_cmds": "re:(a)\\1"})),
        ("cmds-re-uyumsuz", json!({"exec_cmds": "re:zzz"})),
        ("cmds-glob-uyumsuz", json!({"exec_cmds": "zz*"})),
        ("cmds-glob-yasak", json!({"exec_cmds": "s?"})),
        ("cmds-glob-sinif", json!({"exec_cmds": "[cg]*"})),
        ("cmds-glob-ters-sinif", json!({"exec_cmds": "[!c]*"})),
        ("cmds-glob-ters-aralik", json!({"exec_cmds": "[z-a]*"})),
        ("cmds-glob-kapanmamis", json!({"exec_cmds": "[ca*"})),
        (
            "toolchain",
            json!({"exec_cmds": "git", "exec_toolchain": " Rust "}),
        ),
        (
            "toolchain-baska",
            json!({"exec_cmds": "git", "exec_toolchain": "go"}),
        ),
        (
            "glob-temel",
            json!({"exec_cmds": "cargo", "exec_own_glob": "tests/**, scripts/*.sh"}),
        ),
        ("glob-komutsuz", json!({"exec_own_glob": "tests/**"})),
        (
            "glob-cok",
            json!({"exec_cmds": "cargo", "exec_own_glob": ["a", "b", "c", "d", "e"]}),
        ),
        (
            "glob-genis",
            json!({"exec_cmds": "cargo", "exec_own_glob": "**"}),
        ),
        (
            "glob-genis-kabul",
            json!({"exec_cmds": "cargo", "exec_own_glob": "*,**/*", "accept_risk": "on"}),
        ),
        (
            "glob-genis-kabul-false",
            json!({"exec_cmds": "cargo", "exec_own_glob": "*", "accept_risk": "false"}),
        ),
        (
            "glob-genis-kabul-0",
            json!({"exec_cmds": "cargo", "exec_own_glob": "*", "accept_risk": 0}),
        ),
        (
            "glob-mutlak",
            json!({"exec_cmds": "cargo", "exec_own_glob": "/etc/*"}),
        ),
        (
            "glob-ust",
            json!({"exec_cmds": "cargo", "exec_own_glob": "a/../b"}),
        ),
        (
            "glob-bos-parca",
            json!({"exec_cmds": "cargo", "exec_own_glob": "a//b"}),
        ),
        (
            "glob-tire",
            json!({"exec_cmds": "cargo", "exec_own_glob": "-x"}),
        ),
        (
            "bind-temel",
            json!({"exec_cmds": "cargo", "exec_bind_ro": "/opt/sdk/lib/, /usr/share/x"}),
        ),
        (
            "bind-kok",
            json!({"exec_cmds": "cargo", "exec_bind_ro": "/opt"}),
        ),
        (
            "bind-ust",
            json!({"exec_cmds": "cargo", "exec_bind_ro": "/opt/../etc"}),
        ),
        (
            "bind-cift",
            json!({"exec_cmds": "cargo", "exec_bind_ro": "/opt//x"}),
        ),
        ("bind-komutsuz", json!({"exec_bind_ro": "/opt/x"})),
        (
            "bind-cok",
            json!({"exec_cmds": "cargo", "exec_bind_ro": (0..7).map(|i| format!("/o/p{i}")).collect::<Vec<_>>()}),
        ),
        ("write", json!({"exec_cmds": "cargo", "exec_write": "on"})),
        ("write-1", json!({"exec_cmds": "cargo", "exec_write": 1})),
        (
            "write-yes",
            json!({"exec_cmds": "cargo", "exec_write": "yes"}),
        ),
        ("write-komutsuz", json!({"exec_write": true})),
        (
            "timeout",
            json!({"exec_cmds": "cargo", "exec_timeout": " 30 "}),
        ),
        (
            "timeout-sinir",
            json!({"exec_cmds": "cargo", "exec_timeout": 601}),
        ),
        (
            "timeout-sifir",
            json!({"exec_cmds": "cargo", "exec_timeout": 0}),
        ),
        (
            "timeout-float",
            json!({"exec_cmds": "cargo", "exec_timeout": 1.5}),
        ),
        (
            "timeout-yazi",
            json!({"exec_cmds": "cargo", "exec_timeout": "x"}),
        ),
        ("timeout-komutsuz", json!({"exec_timeout": 5})),
        (
            "timeout-bool",
            json!({"exec_cmds": "cargo", "exec_timeout": true}),
        ),
        ("cost", json!({"max_cost_usd": "1,5"})),
        ("cost-sinir", json!({"max_cost_usd": 100.5})),
        ("cost-negatif", json!({"max_cost_usd": -1})),
        ("cost-nan", json!({"max_cost_usd": "nan"})),
        ("cost-inf", json!({"max_cost_usd": "inf"})),
        ("cost-sifir", json!({"max_cost_usd": "0"})),
        ("cost-yazi", json!({"max_cost_usd": "abc"})),
        ("session", json!({"max_session_usd": 250})),
        ("session-sinir", json!({"max_session_usd": 1000.01})),
        ("git", json!({"git_commit": "yes", "git_push": 1})),
        ("git-hayir", json!({"git_commit": "no", "git_push": false})),
        ("git-gecersiz", json!({"git_commit": "maybe"})),
        ("git-2", json!({"git_push": 2})),
        (
            "int",
            json!({"max_prompt_tokens": "1000", "max_repeated_calls": 0, "max_consecutive_failures": "5",
                       "max_continuation_steps": false, "exec_per_script": "", "instructions_max_kib": 256}),
        ),
        ("int-sinir", json!({"instructions_max_kib": 257})),
        ("int-negatif", json!({"max_repeated_calls": -1})),
        ("int-yazi", json!({"max_prompt_tokens": "1e3"})),
        ("int-true", json!({"max_prompt_tokens": true})),
        ("int-float", json!({"max_prompt_tokens": 1.0})),
        (
            "bayraklar",
            json!({"no_prompt_cache": true, "show_usage": "on", "instructions_user": "1", "checkpoint": "yes"}),
        ),
        ("bayrak-gecersiz", json!({"show_usage": "evet"})),
        (
            "yetenek",
            json!({"allow_image": true, "allow_scholar": "on"}),
        ),
        (
            "yetenek-hayir",
            json!({"allow_image": "false", "ask_edit": 0}),
        ),
        (
            "yetenek-hayir-2",
            json!({"allow_scholar": false, "allow_image": "0", "ask_edit": "", "checkpoint": null}),
        ),
        ("checkpoint-hayir-false", json!({"checkpoint": false})),
        ("checkpoint-hayir-yazi", json!({"checkpoint": "false"})),
        ("checkpoint-hayir-0", json!({"checkpoint": "0"})),
        ("checkpoint-hayir-bos", json!({"checkpoint": ""})),
        ("checkpoint-hayir-null", json!({"checkpoint": null})),
        ("checkpoint-evet", json!({"checkpoint": true})),
        (
            "talimat",
            json!({"instructions_user": true, "instructions_max_kib": 64}),
        ),
        ("ask-edit-yazmasiz", json!({"ask_edit": true})),
        (
            "ask-edit",
            json!({"exec_cmds": "cargo", "exec_write": true, "ask_edit": "yes"}),
        ),
        (
            "approval",
            json!({"exec_cmds": "cargo", "exec_write": true, "ask_edit": 1, "approval_dir": true}),
        ),
        (
            "approval-askdir",
            json!({"exec_cmds": "cargo", "exec_write": true, "ask_edit": 1, "approval_dir": true, "ask_dir": "on"}),
        ),
        ("approval-yalniz", json!({"approval_dir": true})),
        ("askdir", json!({"ask_dir": true})),
        ("ste", json!({"search_token_env": " SEARX_TOKEN "})),
        ("ste-deger", json!({"search_token_env": "sk-abc"})),
        ("ste-uzun", json!({"search_token_env": "A".repeat(65)})),
        ("ste-bos", json!({"search_token_env": ""})),
        ("ste-bosluk", json!({"search_token_env": "   "})),
        ("price", json!({"price": "3, 15"})),
        ("price-4", json!({"price": "3,15,0.3,3.75"})),
        ("price-3", json!({"price": "1,2,3"})),
        ("price-sifir", json!({"price": "0,1"})),
        ("price-buyuk", json!({"price": "1,1000.5"})),
        ("price-nan", json!({"price": "nan,1"})),
        ("price-yazi", json!({"price": "a,1"})),
        ("price-g", json!({"price": "0.000001,999.99999"})),
        (
            "checks-restricted",
            json!({"ucli_checks": {"mode": "Restricted"}}),
        ),
        (
            "checks-full",
            json!({"ucli_checks": {"mode": "full", "accept_risk": "on"}}),
        ),
        (
            "checks-full-risksiz",
            json!({"ucli_checks": {"mode": "full"}}),
        ),
        (
            "checks-max-full",
            json!({"ucli_checks": {"mode": "restricted", "max": "full", "accept_risk": true}}),
        ),
        (
            "checks-max-dusuk",
            json!({"ucli_checks": {"mode": "full", "max": "restricted", "accept_risk": true}}),
        ),
        (
            "checks-mode-gecersiz",
            json!({"ucli_checks": {"mode": "x"}}),
        ),
        ("checks-tip", json!({"ucli_checks": "full"})),
        ("checks-bos", json!({"ucli_checks": {}})),
        ("checks-false", json!({"ucli_checks": false})),
        ("checks-liste", json!({"ucli_checks": []})),
    ];
    for (id, raw) in raws {
        v.push(opts(e, id, raw).facts(json!({"toolchain": tc.clone()})));
    }
    // Regex lehçesi: geçerli/geçersiz kararı (PATH üzerinde açma ayrıca `expand` vakalarında).
    for (i, pat) in [
        "re:\\d+",
        "re:[[:alpha:]]+",
        "re:a{2,1}",
        "re:(?i)CARGO",
        "re:\\Acargo\\Z",
        "re:\\bgit",
        "re:a++",
        "re:(?<n>git)",
        "re:(?P<n>git)",
        "re:(?P=n)",
        "re:[a-",
        "re:\\p{L}+",
        "re:x{,3}",
    ]
    .iter()
    .enumerate()
    {
        v.push(opts(e, &format!("re-lehce{i}"), json!({"exec_cmds": pat})));
    }
    // Uygulama tarafı: hizmet anahtarlı, araç zinciri, kontroller, eksik güvenlik bayrakları.
    let byok = json!({"byok": {"ucli": {"ANTHROPIC_API_KEY": " sk-ant ", "XAI_API_KEY": "xai"}}});
    v.push(opts(e, "hizmet-claude", json!({"service": "claude"})).settings_json(byok.clone()));
    v.push(
        ucase(
            e,
            "opts-hizmet-claude-effort",
            json!({"validate": true, "raw_opts": {"service": "claude"},
        "model": "claude-opus-5-5", "effort": "max"}),
        )
        .settings_json(byok.clone()),
    );
    v.push(
        ucase(
            e,
            "opts-hizmet-claude-effort-gecersiz",
            json!({"validate": true, "raw_opts": {"service": "claude"},
        "model": "claude-haiku-5-5", "effort": "high"}),
        )
        .settings_json(byok.clone()),
    );
    v.push(
        ucase(
            e,
            "opts-hizmet-claude-modelsiz",
            json!({"validate": true, "raw_opts": {"service": "claude"}, "model": ""}),
        )
        .settings_json(byok.clone()),
    );
    v.push(
        opts(e, "hizmet-claude-tavan", json!({"service": "claude"}))
            .settings_json(byok.clone())
            .facts(json!({"cost_exceeded": true})),
    );
    v.push(
        opts(
            e,
            "hizmet-claude-buyuk-talimat",
            json!({"service": "claude"}),
        )
        .settings_json(byok.clone())
        .file(file("work/p1/CLAUDE.md", &"x".repeat(40961), 0o644)),
    );
    v.push(
        opts(
            e,
            "hizmet-claude-sinir-talimat",
            json!({"service": "claude"}),
        )
        .settings_json(byok.clone())
        .file(file("work/p1/AGENTS.md", &"x".repeat(40960), 0o644)),
    );
    v.push(
        opts(e, "hizmet-claude-ttl", json!({"service": "claude"})).settings_json(
            json!({"byok": {"ucli": {"ANTHROPIC_API_KEY": "k"}}, "ucli_cost": {"cache_ttl": "5m"}}),
        ),
    );
    v.push(opts(e, "hizmet-claude-eski-ikili", json!({"service": "claude"})).settings_json(byok.clone())
        .facts(json!({"ucli_help": help(&["--cache-ttl", "--usage-log", "--instructions-auto", "--effort"], &[], false)})));
    v.push(
        opts(e, "hizmet-claude-providersiz", json!({"service": "claude"}))
            .settings_json(byok.clone())
            .facts(json!({"ucli_help": help(&["--provider"], &[], false)})),
    );
    v.push(
        opts(
            e,
            "hizmet-grok",
            json!({"service": "grok", "max_cost_usd": 2, "max_session_usd": 0}),
        )
        .settings_json(byok.clone()),
    );
    v.push(
        opts(e, "hizmet-grok-tavan-ayar", json!({"service": "grok"})).settings_json(
            json!({"byok": {"ucli": {"XAI_API_KEY": "x"}}, "ucli_max_session_usd": "0"}),
        ),
    );
    v.push(opts(e, "hizmet-ozel", json!({"service": "ozel"})).settings_json(json!({
        "byok": {"ucli": {"OZEL_KEY": "o"}},
        "ucli_services": [{"id": "ozel", "endpoint": "https://o/v1/", "env": "OZEL_KEY", "wire": "anthropic-messages",
                           "efforts": {"glm": ["medium"], "glm-5": ["low"]}}]})));
    v.push(
        opts(
            e,
            "hizmet-anahtar-dosyasi-symlink",
            json!({"service": "grok"}),
        )
        .settings_json(byok.clone())
        .file(file("home/hedef", "h", 0o600))
        .file(Fx::Link(
            "home/.claude/claudeops/ucli_key_grok".into(),
            "../../hedef".into(),
        )),
    );
    // Dizin açılamayınca komut değişir (`Probe::apply_now`): bayrak düşer ve/veya günlüğe yazılır.
    v.push(ucase(e, "dizin-metrics-dosya", json!({})).file(file("state/ucli_metrics", "x", 0o600)));
    let usage = "home/.claude/claudeops/ucli_usage";
    v.push(ucase(e, "dizin-usage-diger-dosya", json!({})).file(file(
        &format!("{usage}/other"),
        "x",
        0o600,
    )));
    v.push(ucase(e, "dizin-usage-kok-dosya", json!({})).file(file(usage, "x", 0o600)));
    v.push(ucase(e, "dizin-usage-izinsiz", json!({})).file(Fx::Dir(usage.into(), 0o500)));
    v.push(
        opts(e, "dizin-usage-claude-dosya", json!({"service": "claude"}))
            .settings_json(byok.clone())
            .file(file(usage, "x", 0o600)),
    );
    v.push(ucase(e, "opts-cost-fiyatli", json!({"validate": true, "raw_opts": {"max_cost_usd": "0.5"}, "model": "claude-sonnet-5-5"})));
    v.push(ucase(
        e,
        "opts-cost-fiyatsiz",
        json!({"validate": true, "raw_opts": {"max_cost_usd": "0.5"}}),
    ));
    v.push(ucase(
        e,
        "opts-cost-modelsiz",
        json!({"validate": true, "raw_opts": {"max_cost_usd": "0.5"}, "model": ""}),
    ));
    // Fiyat ve USD tavanı: tablo fiyatı, açık fiyat, fiyatı bilinmeyen model, `--price` tanımayan ikili.
    for (id, model, extra) in [
        ("haiku", "claude-haiku-5-5", json!({"max_cost_usd": 2})),
        ("fable", "claude-fable-5-1", json!({})),
        ("sonnet", "claude-sonnet-5-5", json!({"max_cost_usd": 2})),
        (
            "acik",
            "claude-haiku-5-5",
            json!({"price": "1,5", "max_cost_usd": 2}),
        ),
        ("bilinmeyen", "nobody-knows-1", json!({})),
        (
            "bilinmeyen-tavansiz",
            "nobody-knows-1",
            json!({"max_session_usd": 0}),
        ),
        ("oneksiz", "haiku-5-5", json!({"max_cost_usd": 2})),
        (
            "tarihli",
            "claude-haiku-5-5-20261101",
            json!({"max_cost_usd": 2}),
        ),
    ] {
        let mut o = extra.as_object().cloned().unwrap_or_default();
        o.insert("service".into(), json!("claude"));
        v.push(
            ucase(
                e,
                &format!("fiyat-{id}"),
                json!({"cli_opts": o, "model": model}),
            )
            .settings_json(byok.clone()),
        );
    }
    v.push(
        ucase(
            e,
            "fiyat-ikili-tanimiyor",
            json!({"cli_opts": {"service": "claude"}, "model": "claude-haiku-5-5"}),
        )
        .settings_json(byok.clone())
        .facts(json!({"ucli_help": help(&["--price"], &[], false)})),
    );
    v.push(ucase(
        e,
        "fiyat-evren-acik-tavan",
        json!({"cli_opts": {"service": "evren", "max_session_usd": 3}, "model": "nobody-knows-1"}),
    ));
    v.push(ucase(
        e,
        "fiyat-evren-tavansiz",
        json!({"cli_opts": {"max_cost_usd": 1}, "model": "nobody-knows-1"}),
    ));
    v.push(
        opts(
            e,
            "toolchain-uygula",
            json!({"exec_cmds": "git", "exec_toolchain": "rust", "exec_bind_ro": "/opt/sdk",
        "exec_timeout": 7}),
        )
        .facts(json!({"toolchain": tc.clone()}))
        .file(Fx::Dir("home/.cargo/registry".into(), 0o755)),
    );
    v.push(
        opts(
            e,
            "toolchain-yok",
            json!({"exec_cmds": "git", "exec_toolchain": "rust"}),
        )
        .facts(json!({"toolchain": "Rust araç zinciri belirsiz/yok (2 aday): /x"})),
    );
    v.push(
        opts(
            e,
            "exec-write-create",
            json!({"exec_cmds": "git", "exec_write": true}),
        )
        .facts(json!({"toolchain": tc.clone()})),
    );
    v.push(ucase(
        e,
        "opts-exec-write-allow-create",
        json!({"validate": true, "perm": "allow-create",
        "raw_opts": {"exec_cmds": "git", "exec_write": true, "ask_edit": true}}),
    ));
    v.push(ucase(
        e,
        "opts-exec-write-allow-edit",
        json!({"validate": true, "perm": "allow-edit",
        "raw_opts": {"exec_cmds": "git", "exec_write": true}}),
    ));
    v.push(ucase(
        e,
        "opts-ask-edit-exec-yok",
        json!({"perm": "allow-edit", "cli_opts": {"ask_edit": true}}),
    ));
    v.push(ucase(
        e,
        "opts-ask-edit-exec-yok-izinsiz",
        json!({"cli_opts": {"ask_edit": true}}),
    ));
    v.push(
        ucase(
            e,
            "opts-ask-edit-exec-yok-bayraksiz",
            json!({"perm": "allow-edit", "cli_opts": {"ask_edit": true}}),
        )
        .facts(json!({"ucli_help": help(&["--ask-edit"], &[], false)})),
    );
    for f in [
        "--allow-exec",
        "--allow-exec-cmd",
        "--allow-exec-own-glob",
        "--exec-bind-ro",
        "--exec-env",
        "--exec-memory-mib",
        "--exec-max-tasks",
        "--exec-timeout-secs",
        "--allow-edit",
        "--ask-edit",
        "--allow-git-commit",
        "--allow-git-push",
        "--allow-image",
        "--allow-scholar",
        "--ask-dir",
        "--allow-checks",
        "--checks-max",
        "--checks-file",
        "--checks-accept-risk",
        "--max-cost-usd",
        "--max-session-usd",
        "--price",
        "--search-token-env",
        "--checkpoint",
    ] {
        v.push(opts(e, &format!("eksik{f}"), json!({"exec_cmds": "git", "exec_toolchain": "rust", "exec_own_glob": "t/*",
            "exec_timeout": 9, "exec_write": true, "ask_edit": true, "git_commit": true, "git_push": true, "allow_image": true,
            "allow_scholar": true, "max_cost_usd": 1, "max_session_usd": 2, "price": "1,2", "checkpoint": true,
            "search_token_env": "TOK"}))
            .facts(json!({"toolchain": tc.clone(), "ucli_help": help(&[f], &[], false)})));
        v.push(
            opts(
                e,
                &format!("eksik-checks{f}"),
                json!({"ucli_checks": {"mode": "full", "accept_risk": true}, "ask_dir": true}),
            )
            .settings_json(json!({"ucli_limits": {"state_dir": "on"}}))
            .facts(json!({"ucli_help": help(&[f], &[("--allow-checks", "restricted")], false)})),
        );
    }
    v.push(
        opts(e, "ste-arama", json!({"search_token_env": "TOK"}))
            .facts(json!({"searxng_url": "http://127.0.0.1:1"})),
    );
    v.push(opts(e, "askdir-adsiz", json!({"ask_dir": true})).file(Fx::Dir("state".into(), 0o755)));
    v.push(ucase(
        e,
        "opts-askdir-adsiz2",
        json!({"validate": true, "raw_opts": {"ask_dir": true}, "name": ""}),
    ));
    v.push(ucase(
        e,
        "opts-askdir-gecersiz-ad",
        json!({"validate": true, "raw_opts": {"ask_dir": true}, "name": "a b"}),
    ));
    v.push(ucase(
        e,
        "opts-askdir-satir-sonu",
        json!({"validate": true, "raw_opts": {"ask_dir": true}, "name": "ab\n"}),
    ));
    v.push(ucase(
        e,
        "opts-askdir-uzun",
        json!({"validate": true, "raw_opts": {"ask_dir": true}, "name": "a".repeat(101)}),
    ));
    v.push(
        ucase(
            e,
            "opts-askdir-var",
            json!({"validate": true, "raw_opts": {"ask_dir": true}}),
        )
        .file(Fx::Dir("state/ucli_ask/s1".into(), 0o755)),
    );
    v.push(ucase(
        e,
        "opts-approval-repl",
        json!({"cli_opts": {"approval_dir": true}}),
    ));
    v.push(ucase(
        e,
        "opts-checks-adsiz",
        json!({"validate": true, "name": "", "raw_opts": {"ucli_checks": {"mode": "restricted"}}}),
    ));
    v.push(opts(
        e,
        "checks-uygula",
        json!({"ucli_checks": {"mode": "restricted", "max": "full", "accept_risk": true}}),
    ));
    v.push(opts(e, "checks-deger-tanimsiz", json!({"ucli_checks": {"mode": "full", "accept_risk": true}}))
        .facts(json!({"ucli_help": help(&[], &[("--allow-checks", "restricted"), ("--checks-max", "restricted")], false)})));
    v.push(
        opts(
            e,
            "checks-statedir-yok",
            json!({"ucli_checks": {"mode": "restricted"}}),
        )
        .facts(json!({"ucli_help": help(&["--state-dir"], &[], false)})),
    );
    v.push(
        opts(
            e,
            "checks-eski-gecmis",
            json!({"ucli_checks": {"mode": "restricted"}}),
        )
        .file(file("work/p1/.ucli/chat/s1.jsonl", "{}", 0o600)),
    );
    v.push(
        opts(
            e,
            "checks-kayit-hata",
            json!({"ucli_checks": {"mode": "restricted"}}),
        )
        .facts(json!({"checks_err": "kayıt 0600 değil"})),
    );
    // `--instructions-*` bayrağını tanımayan ikili: bayraklar atlanır.
    v.push(opts(e, "talimat-desteksiz", json!({"instructions_user": true, "instructions_max_kib": 64}))
        .facts(json!({"ucli_help": help(&["--instructions-user", "--instructions-max-kib"], &[], false)})));
    // Web bayrakları: kabuk metakarakterli adres, salt okunur oturum, anahtar sarmalı (sır argv'ye girmez).
    let web = json!({"search_url": "http://127.0.0.1:8888/search?lang=tr&safe=1", "allow_fetch_domains": "en.wikipedia.org, docs.rs"});
    v.push(
        ucase(e, "web-metakarakter", json!({"perm": "allow-edit"})).settings_json(
            json!({"ucli_web": {"search_url": "http://127.0.0.1:8888/search?q=a&b=$(x);c"}}),
        ),
    );
    v.push(
        ucase(e, "web-salt-okunur", json!({"perm": "read-only"}))
            .settings_json(json!({"ucli_web": {"allow_fetch_domains": "docs.rs"}})),
    );
    v.push(
        ucase(e, "web-anahtar-sarmal", json!({"perm": "allow-edit"})).settings_json(
            json!({"byok": {"ucli": {"UCLI_API_KEY": "sk-gizli-deger"}}, "ucli_web": web}),
        ),
    );
    // Doğrulanmamış (kayıttan gelen) cli_opts: float dönüşümü.
    v.push(ucase(
        e,
        "ham-cost-yazi",
        json!({"cli_opts": {"max_cost_usd": "abc"}}),
    ));
    v.push(ucase(
        e,
        "ham-cost-liste",
        json!({"cli_opts": {"max_session_usd": [1]}}),
    ));
    v.push(ucase(
        e,
        "ham-cost-bool",
        json!({"cli_opts": {"max_session_usd": true}}),
    ));
    v.push(ucase(
        e,
        "ham-cost-bosluk",
        json!({"cli_opts": {"max_session_usd": " 3\u{2003}"}}),
    ));
    v.push(ucase(
        e,
        "ham-service-evren",
        json!({"cli_opts": {"service": "evren", "max_session_usd": 4}}),
    ));
    v.push(ucase(
        e,
        "ham-hook-int",
        json!({"cli_opts": {"exec_cmds": ["git"], "exec_timeout": 2.9}}),
    ));
    v
}

fn rs_ucli_mcp(e: &Env, c: &Case) -> RsOut {
    with(e, c, |p, probe| {
        let spec = spec_of(&c.args["spec"]);
        let mut out = BuildOutput::default();
        let launch = p.mcp_launch_args(Cli::Ucli, &spec, c.args["cwd"].as_str().unwrap(), &mut out);
        let mut rs =
            RsOut::ret(json!({"launch": launch, "setup": p.mcp_setup_command(Cli::Ucli, &spec)}));
        rs.out = out;
        rs.mcp_calls = probe.mcp_calls.borrow().clone();
        rs
    })
}

fn mcp_cases(e: &Env) -> Vec<Case> {
    let w = format!("{}/p1", e.work);
    let spec = json!({"name": "cops-steward", "command": "/r/py/cops", "args": ["mcp-steward", "--steward", "abc"],
                      "allowed_tools": ["ask", "bad tool", "x.y-z_1", "", "a".repeat(65), "ok\n"]});
    let m = |id: &str, cwd: &str| {
        Case::new(
            format!("ucli-mcp-{id}"),
            "mcp",
            json!({"cli": "ucli", "spec": spec, "cwd": cwd}),
        )
        .facts(json!({"ucli_help": full_help()}))
    };
    vec![
        m("ok", &w),
        m("eski-dosya", &w).file(file("work/p1/.ucli/mcp.json", "{}", 0o600)),
        m("eski-symlink", &w).file(Fx::Link("work/p1/.ucli/mcp.json".into(), "/etc/passwd".into())),
        m("ucli-symlink", &w).file(Fx::Link("work/p1/.ucli".into(), "/tmp".into())),
        m("rc", &w).facts(json!({"mcp_register": {"rc": 2, "stderr": "", "stdout": format!("{}SON", "x".repeat(400))}})),
        m("rc-stderr", &w).facts(json!({"mcp_register": {"rc": 1, "stderr": "hata: ğ", "stdout": "o"}})),
        m("calismadi", &w).facts(json!({"mcp_register": {"raise": "boom"}})),
        m("goreli", "p1"),
        m("bos", ""),
        m("yok", &format!("{w}/yok")),
        m("dosya", &format!("{w}/f")).file(file("work/p1/f", "x", 0o644)),
        m("bayraksiz", &w).facts(json!({"ucli_help": help(&["--with-mcp"], &[], false)})),
        m("ikili-yok", &w).env("PATH", ""),
        Case::new("ucli-mcp-aracsiz", "mcp", json!({"cli": "ucli", "spec": {"name": "x", "command": "c", "allowed_tools": ["bad tool"]}, "cwd": w}))
            .facts(json!({"ucli_help": full_help()})),
        Case::new("ucli-mcp-ad", "mcp", json!({"cli": "ucli", "spec": {"name": "çok-uzun-ad.ile/özel karakterler-xxxxxxxxxx", "command": "c",
            "args": ["--", "-x"], "allowed_tools": ["t"]}, "cwd": w}))
            .facts(json!({"ucli_help": full_help()})),
        Case::new("ucli-mcp-ad-bos", "mcp", json!({"cli": "ucli", "spec": {"name": "", "command": "c", "allowed_tools": ["t"]}, "cwd": w}))
            .facts(json!({"ucli_help": full_help()})),
    ]
}

pub fn run() {
    let mut r = Runner::new();
    let cases = build_cases(&r.e);
    r.run(cases, &[], rs_build);
    let cases = opts_cases(&r.e);
    r.run(cases, &[], rs_build);
    let cases = mcp_cases(&r.e);
    r.run(cases, &[], rs_ucli_mcp);
    r.finish("ucli");
    // Boşluklu ve tek tırnaklı HOME/durum dizini: anahtar ve token yolları kabuk satırında tırnaklı.
    let mut r = Runner::with_env(Env::with_prefix("cops-parity a b'c-"));
    let cases = quoting_cases(&r.e);
    r.run(cases, &[], rs_build);
    r.finish("ucli-tirnak");
}

fn quoting_cases(e: &Env) -> Vec<Case> {
    let byok = json!({"byok": {"ucli": {"UCLI_API_KEY": "k", "ANTHROPIC_API_KEY": "a"}, "copilot": {"X_KEY": "c"}}});
    let token = json!({"ucli_help": full_help(), "panel_port": 8765,
                       "agent_token": {"path": format!("{}/ucli_agent_tokens/s1", e.state)}});
    let mut v = vec![
        ucase(e, "tirnak-anahtar", json!({})).settings_json(byok.clone()),
        ucase(e, "tirnak-ajan", json!({}))
            .settings_json(byok.clone())
            .facts(token),
        ucase(
            e,
            "tirnak-hizmet",
            json!({"validate": true, "raw_opts": {"service": "claude"}}),
        )
        .settings_json(byok.clone()),
    ];
    for cli in ["copilot", "claude"] {
        let args = json!({"cli": cli, "cwd": format!("{}/p1", e.work), "model": "m", "perm": "auto", "effort": "high", "name": "s1"});
        v.push(Case::new(format!("tirnak-{cli}"), "build", args).settings_json(byok.clone()));
    }
    v
}
