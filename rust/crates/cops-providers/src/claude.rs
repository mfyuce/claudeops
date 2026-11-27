//! claude sağlayıcısı.

use crate::probe::BuildOutput;
use crate::probe::Effect;
use crate::provider::{BuildArgs, McpSpec, Providers};
use crate::pyfmt::quote;
use crate::routing;
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

pub const MODEL_CHOICES: [&str; 4] = [
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5-2",
    "claude-haiku-5-5",
];
pub const PERMISSION_MODES: [&str; 6] = [
    "auto",
    "acceptEdits",
    "bypassPermissions",
    "manual",
    "dontAsk",
    "plan",
];
pub const EFFORT_LEVELS: [&str; 5] = ["low", "medium", "high", "xhigh", "max"];
/// Tur işlenirken durum çubuğunda görünen metin.
pub const BUSY_STATUS_PATTERN: &str = "esc to interrupt";
/// Durum çubuğunda aktif izin modunu veren metinler (Python dict sırası).
pub const MODE_STATUS_PATTERNS: [(&str, &str); 4] = [
    ("plan", "plan mode on"),
    ("acceptEdits", "accept edits on"),
    ("auto", "auto mode on"),
    ("manual", "manual mode on"),
];
/// Shift+Tab ile hedeflenebilen modlar (döngü sırası varsayılmaz).
pub const CYCLABLE_MODES: [&str; 4] = ["manual", "acceptEdits", "plan", "auto"];

static SONNET_PIN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(claude-sonnet-)(\d{1,2}(?:-\d{1,2})?)(\[[^\]]*\])?\n?$").unwrap()
});

fn sonnet_version(id: &str) -> Vec<u32> {
    SONNET_PIN
        .captures(id)
        .map(|c| {
            c[2].split('-')
                .map(|p| crate::pyfmt::parse_int(p).unwrap_or(0) as u32)
                .collect()
        })
        .unwrap_or_default()
}

/// Python `max`: eşitlikte İLK en büyük.
pub fn newest_sonnet(choices: &[String]) -> Option<String> {
    let mut best: Option<&String> = None;
    for c in choices.iter().filter(|c| SONNET_PIN.is_match(c)) {
        if best.is_none_or(|b| sonnet_version(c) > sonnet_version(b)) {
            best = Some(c);
        }
    }
    best.cloned()
}

/// `claude_models` belgesinin `enabled` modelleri (sıralı); yoksa sabit liste.
pub fn model_choices(state: Option<&Value>) -> Vec<String> {
    let mut enabled: Vec<String> = state
        .and_then(|s| s.get("models"))
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .filter(|(_, v)| v.as_str() == Some("enabled"))
                .map(|(k, _)| k.clone())
                .collect()
        })
        .unwrap_or_default();
    if enabled.is_empty() {
        return MODEL_CHOICES.iter().map(|s| s.to_string()).collect();
    }
    enabled.sort();
    enabled
}

/// Sabitlenmiş sonnet id'sini en yeni sonnet'e taşır (`[..]` eki korunur).
pub fn refresh_stored_model(stored: &str, choices: &[String]) -> String {
    let Some(m) = SONNET_PIN.captures(stored) else {
        return stored.into();
    };
    match newest_sonnet(choices) {
        Some(fresh) if sonnet_version(&fresh) > sonnet_version(stored) => {
            let f = SONNET_PIN
                .captures(&fresh)
                .expect("newest_sonnet pinned id döndürür");
            format!("{}{}{}", &f[1], &f[2], m.get(3).map_or("", |s| s.as_str()))
        }
        _ => stored.into(),
    }
}

pub(crate) fn build_inner_command(
    p: &Providers<'_>,
    a: &BuildArgs<'_>,
    out: &mut BuildOutput,
) -> String {
    let binary = p.resolved_binary("claude");
    let resume = a
        .resume_id
        .filter(|r| !r.is_empty())
        .map_or(String::new(), |r| format!("--resume {} ", quote(r)));
    // `--mcp-config` değişken sayıda değer okur: ardından mutlaka başka bir bayrak (`--model`) gelmeli.
    let extra: String = a
        .extra_args
        .iter()
        .map(|x| format!("{} ", quote(x)))
        .collect();
    let guidance = routing::claude_guidance_path(p, out).map_or(String::new(), |g| {
        format!("--append-system-prompt-file {} ", quote(&g))
    });
    let prompt = a
        .prompt
        .filter(|s| !s.is_empty())
        .map_or(String::new(), |s| format!(" {}", quote(s)));
    let name = quote(a.session_name);
    format!(
        "{} {resume}{extra}{guidance}--model {} --permission-mode {} --effort {} -n {name} --remote-control {name}{prompt}",
        quote(&binary),
        quote(a.model),
        quote(a.permission_mode),
        quote(a.effort),
    )
}

fn supports_flag(help: &str, flag: &str) -> bool {
    crate::ucli::find_flag(help, flag).is_some()
}

pub(crate) fn oneshot_argv(p: &Providers<'_>, prompt: &str, model: Option<&str>) -> Vec<String> {
    let binary = p.resolved_binary("claude");
    let mut argv = vec![binary.clone(), "-p".into(), prompt.into()];
    if let Some(m) = model.filter(|m| !m.is_empty()) {
        argv.extend(["--model".into(), m.into()]);
    }
    argv.extend(["--output-format".into(), "text".into()]);
    if supports_flag(&p.probe.claude_help(&binary), "--no-session-persistence") {
        argv.push("--no-session-persistence".into());
    }
    // `--tools` değişken sayıda değer okur: en sonda kalmalı.
    argv.extend(["--tools".into(), String::new()]);
    argv
}

/// `--mcp-config` dosyasının yolu: değnekçi beyni ve eklenti sunucuları kendi dosyasını alır.
fn mcp_config_path(p: &Providers<'_>, spec: &McpSpec) -> String {
    let base = p.paths.mcp_config();
    let stem = base.strip_suffix(".json").unwrap_or(&base);
    if let Some(i) = spec.args.iter().position(|a| a == "--steward") {
        if let Some(sid) = spec.args.get(i + 1) {
            if !sid.is_empty()
                && sid.chars().all(char::is_alphabetic)
                && crate::pyfmt::py_islower(sid)
            {
                return format!("{stem}_{sid}.json");
            }
        }
    }
    if spec.args.len() >= 2 && spec.args[0] == "mcp-ext" {
        let ext = &spec.args[1];
        let bare = ext.replace(['-', '_'], "");
        if !bare.is_empty() && bare.chars().all(char::is_alphanumeric) {
            return format!("{stem}_ext_{ext}.json");
        }
    }
    base
}

/// `json.dump(..., ensure_ascii=False, indent=2)` biçiminde yapılandırma metni.
fn mcp_config_json(spec: &McpSpec) -> String {
    let s = |v: &str| Value::String(v.into()).to_string();
    let args = if spec.args.is_empty() {
        "[]".to_string()
    } else {
        let items: Vec<String> = spec
            .args
            .iter()
            .map(|a| format!("        {}", s(a)))
            .collect();
        format!("[\n{}\n      ]", items.join(",\n"))
    };
    format!(
        "{{\n  \"mcpServers\": {{\n    {}: {{\n      \"command\": {},\n      \"args\": {args}\n    }}\n  }}\n}}",
        s(&spec.name),
        s(&spec.command)
    )
}

pub(crate) fn mcp_launch_args(
    p: &Providers<'_>,
    spec: &McpSpec,
    out: &mut BuildOutput,
) -> Vec<String> {
    let path = mcp_config_path(p, spec);
    out.effects.push(Effect::WriteAtomic {
        path: path.clone(),
        content: mcp_config_json(spec),
    });
    vec!["--mcp-config".into(), path]
}
