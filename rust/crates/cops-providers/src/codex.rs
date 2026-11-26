//! codex sağlayıcısı.

use crate::effort::sort_levels;
use crate::provider::{BuildArgs, McpSpec, Providers};
use crate::pyfmt::{json_ascii, quote, truthy};
use serde_json::Value;

pub const PERMISSION_MODES: [&str; 4] = ["auto", "acceptEdits", "manual", "plan"];
pub const EFFORT_LEVELS: [&str; 4] = ["low", "medium", "high", "xhigh"];
pub const FALLBACK_MODELS: [&str; 4] = ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4-mini"];

fn permission_flags(mode: &str) -> &'static [&'static str] {
    match if mode.is_empty() { "auto" } else { mode } {
        "auto" => &["--dangerously-bypass-approvals-and-sandbox"],
        "acceptEdits" => &["--sandbox", "workspace-write", "--ask-for-approval", "never"],
        "manual" => &["--sandbox", "workspace-write", "--ask-for-approval", "on-request"],
        // Tanınmayan mod en kısıtlıya düşer.
        _ => &["--sandbox", "read-only", "--ask-for-approval", "on-request"],
    }
}

fn cache_models(cache: Option<&Value>) -> &[Value] {
    cache.and_then(|c| c.get("models")).and_then(Value::as_array).map_or(&[], Vec::as_slice)
}

/// `models_cache.json`: `visibility == "list"`, `priority` sırasıyla; boşsa sabit liste.
pub fn model_choices(cache: Option<&Value>) -> Vec<String> {
    let mut listed: Vec<(f64, String)> = cache_models(cache)
        .iter()
        .filter(|m| m.get("visibility").and_then(Value::as_str) == Some("list"))
        .filter_map(|m| {
            let slug = m.get("slug").and_then(Value::as_str).filter(|s| !s.is_empty())?;
            let prio = m.get("priority").and_then(Value::as_f64).unwrap_or(999.0);
            Some((prio, slug.to_string()))
        })
        .collect();
    listed.sort_by(|a, b| a.0.total_cmp(&b.0));
    if listed.is_empty() {
        FALLBACK_MODELS.iter().map(|s| s.to_string()).collect()
    } else {
        listed.into_iter().map(|(_, s)| s).collect()
    }
}

pub fn model_effort_levels(model: &str, cache: Option<&Value>) -> Option<Vec<String>> {
    if model.is_empty() {
        return None;
    }
    let entry = cache_models(cache).iter().find(|m| m.get("slug").and_then(Value::as_str) == Some(model))?;
    let raw = entry.get("supported_reasoning_levels").filter(|v| truthy(v)).and_then(Value::as_array)?;
    let levels = raw.iter().filter_map(|x| match x {
        Value::Object(o) => o.get("effort").and_then(Value::as_str),
        v => v.as_str(),
    });
    Some(sort_levels(levels.map(str::to_string))).filter(|l| !l.is_empty())
}

pub(crate) fn build_inner_command(p: &Providers<'_>, a: &BuildArgs<'_>) -> String {
    let mut parts = vec![quote(&p.resolved_binary("codex"))];
    if let Some(r) = a.resume_id.filter(|r| !r.is_empty()) {
        parts.extend(["resume".into(), quote(r)]);
    }
    parts.extend(["--model".into(), quote(a.model)]);
    let effort = if a.effort.is_empty() { "medium" } else { a.effort };
    parts.extend(["--config".into(), quote(&format!("model_reasoning_effort={effort}"))]);
    parts.extend(permission_flags(a.permission_mode).iter().map(|s| s.to_string()));
    parts.extend(a.extra_args.iter().map(|x| quote(x)));
    if let Some(pr) = a.prompt.filter(|s| !s.is_empty()) {
        parts.push(quote(pr));
    }
    parts.join(" ")
}

pub(crate) fn mcp_launch_args(spec: &McpSpec) -> Vec<String> {
    let args: Vec<String> = spec.args.iter().map(|a| json_ascii(a)).collect();
    vec![
        "-c".into(),
        format!("mcp_servers.{}.command={}", spec.name, json_ascii(&spec.command)),
        "-c".into(),
        format!("mcp_servers.{}.args=[{}]", spec.name, args.join(", ")),
    ]
}
