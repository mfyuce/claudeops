//! Aile (G5): kota/bağlam komutları ve ayrıştırıcıları (`usage_command`, `usage_needs_dismiss`, `context_command`,
//! `context_needs_dismiss`, `usage_fresh_argv`, `usage_fresh_tui_argv`, `usage_auth_missing`, `parse_usage_text`,
//! `parse_fresh_usage`, `parse_context_text`) her sağlayıcı için aynı metin kümesiyle. Metinler: `py/tests`teki gerçek
//! örnekler (test_usage_fresh.py, test_usage_fresh_tui.py), Python docstring'lerindeki canlı ekran örnekleri ve
//! boş/bozuk/Unicode/ANSI/CRLF/Python satır sınırı sınırları.

use crate::common::*;
use cops_providers::usage::UsageEntry;
use cops_providers::{Cli, Providers};
use serde_json::{json, Value};

fn entries(v: Option<Vec<UsageEntry>>) -> Value {
    match v {
        None => Value::Null,
        Some(es) => json!(es
            .iter()
            .map(|e| json!({"label": e.label, "percent": e.percent, "detail": e.detail}))
            .collect::<Vec<_>>()),
    }
}

fn rs_usage(e: &Env, c: &Case) -> RsOut {
    let cli = Cli::parse(c.args["cli"].as_str().unwrap());
    let s = e.settings();
    let cat = e.catalog(c);
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let p = Providers { settings: &s, catalog: &cat, paths: &paths, probe: &probe };
    let texts = strs(c.args.get("texts"));
    RsOut::ret(json!({
        "usage_command": cli.usage_command(),
        "usage_needs_dismiss": cli.usage_needs_dismiss(),
        "context_command": cli.context_command(),
        "context_needs_dismiss": cli.context_needs_dismiss(),
        "usage_fresh_argv": p.usage_fresh_argv(cli),
        "usage_fresh_tui_argv": p.usage_fresh_tui_argv(cli),
        "parse_usage_text": texts.iter().map(|t| entries(cli.parse_usage_text(t))).collect::<Vec<_>>(),
        "parse_fresh_usage": texts.iter().map(|t| entries(cli.parse_fresh_usage(t))).collect::<Vec<_>>(),
        "parse_context_text": texts.iter().map(|t| entries(cli.parse_context_text(t))).collect::<Vec<_>>(),
        "usage_auth_missing": texts.iter().map(|t| cli.usage_auth_missing(t)).collect::<Vec<_>>(),
    }))
}

/// test_usage_fresh.py `SAMPLE`.
const CLAUDE_FRESH: &str = "You are currently using your subscription to power your Claude Code usage\n\nCurrent week (all models): 48% used · resets Nov 16, 6pm (Europe/Istanbul)\nCurrent week (Fable): 8% used · resets Nov 16, 6pm (Europe/Istanbul)\n\nWhat's contributing to your usage?\n";

/// claude_provider.py `parse_usage_text` docstring (canlı, 13 Eyl).
const CLAUDE_TUI: &str = "Current session\n█  2% used\nResets 12am (Europe/Istanbul)\n\nCurrent week (all models)\n██████  92% used\nResets Sep 14, 6pm (Europe/Istanbul)\n+50% weekly limits promo through Sep 13 · clau.de/cc-50-promo\n\nCurrent week (Fable)\n█████  75% used\nResets Sep 14, 6pm (Europe/Istanbul)\n";

/// claude_provider.py `parse_context_text` docstring (canlı, v2.1.278).
const CLAUDE_CONTEXT: &str = "  ⎿  Context Usage
     ⛁ ⛁ ⛁ ⛁ ⛁ ⛀ ⛁ ⛁ ⛁ ⛁ ⛀ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   Fable 5.1
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   claude-fable-5-1
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   42.9k/1m tokens (4%)
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   Estimated usage by category
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   ⛁ System prompt: 4.3k tokens (0.4%)
     ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶ ⛶   ⛁ System tools: 19.2k tokens (1.9%)
                                                ⛁ MCP tools: 645 tokens (0.1%)
                                                ⛁ Memory files: 14.4k tokens (1.4%)
                                                ⛁ Skills: 4.3k tokens (0.4%)
                                                ⛁ Messages: 10 tokens (0.0%)
                                                ⛶ Free space: 924.1k (92.4%)
                                                ⛝ Autocompact buffer: 33k tokens (3.3%)

     MCP tools · /mcp (loaded on-demand)
     └ mcp__steward__ask: 120 tokens
     └ mcp__steward__answer: 98 tokens
";

/// agy_provider.py `parse_usage_text` docstring (canlı, 16 Eyl) + test_usage_fresh.py `test_agy_fresh_argv_and_tsv_parse`.
const AGY_TSV: &str = "Gemini Models\tWeekly Limit Remaining\t99%\t2026-09-23T08:47:27Z\nGemini Models\tFive Hour Limit Remaining\t93%\t2026-09-16T13:47:27Z\nClaude and GPT models\tWeekly Limit Remaining\t1%\t2026-09-16T11:55:41Z\nClaude and GPT models\tFive Hour Limit Remaining\t100%\t2026-09-16T15:50:44Z\n";
const AGY_TSV2: &str = "Gemini Models\tWeekly Limit Remaining\t81%\t2026-11-25T06:06:52Z\nClaude and GPT models\tFive Hour Limit Remaining\t0%\t2026-11-18T16:39:44Z\nGemini 4 Argon\tGemini 4 Argon Weekly Limit\t99%\t2026-11-25T12:29:11Z\n";

/// test_usage_fresh_tui.py `SCREEN` ve `test_parse_without_reset_unchanged`.
const COPILOT_SCREEN: &str = "   Active account/provider usage\n   Plan       ■■■■■■■■■■■■■■■■■■■■ 35% used • resets in 11 days\n              530 / 1,500 AIC\n /tmp\n";
const COPILOT_NORESET: &str = "Plan   ■■ 10% used\n 5 / 100 AIC\n";
/// copilot_provider.py `_USAGE_*_RE` yorumundaki canlı örnek (13 Eyl).
const COPILOT_OLD: &str = "   Plan       ■■■■■■■■■■■■■■■■■■■■ 0% used\n              11 / 1,500 AIC\n";

fn texts() -> Vec<String> {
    let mut v: Vec<String> = vec![
        CLAUDE_FRESH, CLAUDE_TUI, CLAUDE_CONTEXT, AGY_TSV, AGY_TSV2, COPILOT_SCREEN, COPILOT_NORESET, COPILOT_OLD,
        // test_usage_fresh.py `test_parse_falls_back_to_tui_format`
        "Current week (all models)\n██  92% used\nResets Sep 14, 6pm (Europe/Istanbul)\n",
        // boş / bozuk
        "", "\n", "   ", "\u{0}\u{1}\u{fffd}", "Current", "Current session", "Current session\n", "% used", "Plan",
        "Plan 5%", "tokens (5%)", "\t\t\t", "a\tb\tc\td\te", "a\tb\t%\td", "a\tb\t5%%\td", "a\tb\t%5\td",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    let more = [
        // CRLF, `\r`, Python satır sınırları (`\x0b`, `\x0c`, `\x1c-\x1e`, `\x85`, ` `, ` `)
        CLAUDE_TUI.replace('\n', "\r\n"),
        CLAUDE_FRESH.replace('\n', "\r"),
        CLAUDE_CONTEXT.replace('\n', "\r\n"),
        AGY_TSV.replace('\n', "\r\n"),
        COPILOT_SCREEN.replace('\n', "\r\n"),
        "Current session\u{b}5% used\u{c}Resets now\u{1c}Current week\u{1d}7% used\u{1e}Resets x".into(),
        "Current session\u{85}6% used\u{2028}Resets a\u{2029}Current week (x)\u{2028}9% used".into(),
        "Gemini\tW\t5%\tT\u{85}G2\tW2\t6%\tT2\u{2028}G3\tW3\t7%\tT3".into(),
        // ANSI (çağıran `strip_ansi` uygulamazsa): renk kodları satır içinde
        "\u{1b}[1mCurrent session\u{1b}[0m\n\u{1b}[32m█\u{1b}[0m  3% used\nResets 1am\n".into(),
        "Current session\n\u{1b}[2m█  4% used\u{1b}[0m\n\u{1b}[2mResets 2am\u{1b}[0m\n".into(),
        "\u{1b}[1mCurrent week (all models): 48% used · resets Nov 16\u{1b}[0m\n".into(),
        "   Plan  \u{1b}[34m■■\u{1b}[0m 12% used • resets in 3 days\u{1b}[0m\n 1 / 2 AIC\n".into(),
        "  42.9k/1m tokens (4%)\u{1b}[0m\n  \u{1b}[2m⛁ Skills: 4.3k tokens (0.4%)\u{1b}[0m\n".into(),
        "G\tW\t\u{1b}[1m5%\u{1b}[0m\tT\n".into(),
        // Python `\s` = `\x1c-\x1f` ve Unicode boşlukları; `strip()` de bunları kırpar
        "\u{1f}Current session\u{1f}\n\u{1c}5%\u{1d}used\nResets\u{1e}x\n".into(),
        "\u{a0}Current\u{a0}session\n5%\u{3000}used\n".into(),
        "Current week\u{2003}(all)\n5%\u{85}used\n".into(),
        "Current week\u{1f}(z): 5%\u{1f}used\u{1f}·\u{1f}Resets\u{1f}Monday\n".into(),
        "Plan\u{1f}■\u{1f}5%\u{1f}used\u{1f}•\u{1f}resets\u{1f}in\u{1f}2\u{1f}days\u{1f}\n7\u{1f}/\u{1f}9\u{1f}AIC".into(),
        "\u{1f}G\u{1f}\t\u{1f}W\u{1f}\t\u{1f}5%\u{1f}\t\u{1f}T\u{1f}\n".into(),
        // Unicode rakamlar: Python `\d` (Unicode 13 Nd), `isdigit` (üst simge, daire içi), daha yeni Unicode rakamı
        "Current session\n٣٤% used\nResets ٢am\n".into(),
        "Current week (all models): ５% used · resets Nov 16\n".into(),
        "Current session\n\u{11F55}% used\n".into(),
        "Current session\n\u{1D7D8}\u{1D7D9}% used\n".into(),
        "G\tW\t²%\tT\nG\tW\t①%\tT\nG\tW\t½%\tT\nG\tW\t٣%\tT\nG\tW\t\u{11F55}%\tT\n".into(),
        "١٢.٥k/١m tokens (٣%)\nSkills: ٤k tokens (٠.٤%)\n".into(),
        "Plan ■ ٣٥% used\n٥٣٠ / ١,٥٠٠ AIC\n".into(),
        // claude /usage TUI kenarları: yüzde yok, Resets yüzdeden önce, 3 satırdan uzak, tekrar eden başlık
        "Current session\nResets 12am\n5% used\n".into(),
        "Current session\n\n\n\n5% used\n".into(),
        "Current session\n\n\n5% used\n".into(),
        "Current session\n5% used\n\nResets x\nCurrent session\n6% used\n".into(),
        "Current session\n5% used\n6% used\nResets y\n".into(),
        "Current session\nCurrent week\n5% used\nResets z\n".into(),
        "Current week ()\n1% used\nCurrent week (a)b\n2% used\nCurrent week(abc)\n3% used\nCurrent  session\n4% used\n".into(),
        "current session\n5% used\nCurrent Session\n6% used\nCurrent session:\n7% used\n".into(),
        "Current session\n5%used\nResetsx\nResets \n".into(),
        "Current session\n5 % used\n55%  used and more\nResets\tTAB\n".into(),
        // claude tek satır kenarları
        "Current session: 5% used\nCurrent week (Opus): 6% used · Resets Dec 1\nCurrent week (x): 7% used • reset soon\n".into(),
        "Current week (x): 7% used · \nCurrent week (y): 8% used·resets   \nCurrent week (z): 9% used ·  resets\n".into(),
        "Current week (x): 7% used extra\nCurrent week (y):8%used\n".into(),
        "Current session: 5% used\nCurrent session\n9% used\n".into(),
        // claude /context kenarları: iki çıktı (son toplam sıfırlar), toplam yok, kategoriler, bozuk sayılar
        format!("{CLAUDE_CONTEXT}\n{}", CLAUDE_CONTEXT.replace("(4%)", "(5%)").replace("(0.4%)", "(0.9%)")),
        "System prompt: 4.3k tokens (0.4%)\nFree space: 924.1k (92.4%)\n".into(),
        "x 1.2.3/4..m tokens (5%)\n a: 1 token (1%)\n ab  :  2K tokenss (2%)\n b: 3M (3.5%)\nc: 4 (4.%)\n d: 5 (5)\n".into(),
        "9: 1 tokens (1%)\n_x: 1 tokens (1%)\nŞey: 2 tokens (2%)\nA B C : 3 tokens (3%)\n  Z  : 4k tokens (44.44%)\n".into(),
        "1k/2k tokens(3%)\n1k / 2k tokens (4%)\n1k/2ktokens (5%)\n.k/.m tokens (6%)\n".into(),
        "Skills: 1k tokens (1%) Messages: 2k tokens (2%)\n".into(),
        // agy kenarları
        "G\tW\t5\tT\nG\tW\t 5% \tT\nG\tW\t5%\nG\tW\t5%\tT\tX\nG\t\t5%\t\n\t\t5%\t\n".into(),
        "G — x\tW\t5%\t2026\n".into(),
        // copilot kenarları: sıfırlama 120 kod noktası sınırı (çok baytlı karakterle), kesir yüzdeden önce, sıfırlama yok
        format!("Plan ■ 5% used {}resets in 2 days\n", "■".repeat(100)),
        format!("Plan ■ 5% used {}resets in 2 days\n", "■".repeat(95)),
        format!("Plan ■ 5% used {}resets in 2 days and more\n", "ğ".repeat(90)),
        format!("Plan ■ 5% used {}resets in 2 days\n", "x".repeat(108)),
        format!("Plan ■ 5% used {}resets in 2 days\n", "x".repeat(103)),
        "1 / 2 AIC\nPlan ■ 5% used\n".into(),
        "Plan ■ 5% used\nresets in 4 days\n".into(),
        "Plan ■ 5% used • resets in   \n".into(),
        "Plan ■ 5% used • resets in 3 days • later\n".into(),
        "Plan ■ 5% used • resets in 3 days".into(),
        "Plan\n■\n5%\nused\n7,000/8,000AIC".into(),
        "Plan5% used\nPlan  ■■50%used\nPlan 6% used\n".into(),
        "Planned 5% used\nxPlan ■ 6% used\n".into(),
        "Plan ■ 5% used resets in x\u{85}y\n".into(),
        // agy giriş yok iletileri (25 Kas yuhem)
        "Waiting for authentication (timeout 60s)...\n".into(),
        "error: authentication failed or timed out".into(),
        "WAITING FOR AUTHENTICATION".into(),
        "Authentication Failed".into(),
        "authentication ok".into(),
        "İ waiting for authentication".into(),
    ];
    v.extend(more);
    v
}

fn usage_cases(e: &Env) -> Vec<Case> {
    let t = texts();
    let mut v: Vec<Case> = Cli::ALL
        .iter()
        .map(|c| Case::new(format!("usage-{}", c.name()), "usage", json!({"cli": c.name(), "texts": t})))
        .collect();
    // `usage_fresh_argv`/`usage_fresh_tui_argv` ikili çözümü (test_usage_fresh.py `ResolvedBinaryFallback`):
    // PATH'te yok + bilinen konum; `provider_bin` override; PATH'te yok ve bilinen konum yok = çıplak ad.
    let known = ".local/bin/claude";
    for cli in ["claude", "agy", "copilot"] {
        v.push(
            Case::new(format!("usage-bin-yok-{cli}"), "usage", json!({"cli": cli}))
                .env("PATH", &format!("{}/bos", e.root))
                .file(Fx::File(format!("home/{known}"), b"#!/bin/sh\n".to_vec(), 0o755)),
        );
        v.push(
            Case::new(format!("usage-bin-override-{cli}"), "usage", json!({"cli": cli}))
                .env("PATH", &format!("{}/bos", e.root))
                .settings_json(json!({"provider_bin": {cli: format!("{}/ozel/{cli}", e.root)}}))
                .file(Fx::File(format!("ozel/{cli}"), b"#!/bin/sh\n".to_vec(), 0o755)),
        );
        v.push(
            Case::new(format!("usage-bin-tilde-{cli}"), "usage", json!({"cli": cli}))
                .settings_json(json!({"provider_bin": {cli: format!("~/x/{cli}")}}))
                .file(Fx::File(format!("home/x/{cli}"), b"#!/bin/sh\n".to_vec(), 0o755)),
        );
    }
    v.push(Case::new("usage-bilinmeyen-cli", "usage", json!({"cli": "yok", "texts": [CLAUDE_FRESH, AGY_TSV]})));
    v
}

pub fn run() {
    let mut r = Runner::new();
    let cases = usage_cases(&r.e);
    r.run(cases, &[], rs_usage);
    r.finish("usage");
}
