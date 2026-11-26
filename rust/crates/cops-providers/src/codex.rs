//! codex sağlayıcısı.

use crate::effort::sort_levels;
use crate::provider::{BuildArgs, McpSpec, Providers};
use crate::pyfmt::{json_ascii, quote, truthy};
use serde_json::{Map, Value};

pub const PERMISSION_MODES: [&str; 4] = ["auto", "acceptEdits", "manual", "plan"];
pub const EFFORT_LEVELS: [&str; 4] = ["low", "medium", "high", "xhigh"];
/// Tur işlenirken durum çubuğunda görünen metin.
pub const BUSY_STATUS_PATTERN: &str = "esc to interrupt";
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

/// Python `sort` anahtarı: sayılar (bool dahil) kendi aralarında, dizeler kendi aralarında karşılaştırılabilir; başka her
/// karışım (None dahil) `TypeError`.
#[derive(Clone)]
enum PrioKey {
    Num(f64),
    Str(String),
    Other,
}

fn prio_key(m: &Map<String, Value>) -> PrioKey {
    match m.get("priority") {
        None => PrioKey::Num(999.0),
        Some(Value::Number(n)) => PrioKey::Num(n.as_f64().unwrap_or(0.0)),
        Some(Value::Bool(b)) => PrioKey::Num(if *b { 1.0 } else { 0.0 }),
        Some(Value::String(s)) => PrioKey::Str(s.clone()),
        Some(_) => PrioKey::Other,
    }
}

/// `models_cache.json`: `visibility == "list"`, `priority` sırasıyla; boşsa sabit liste. Python'da `models` girdisi sözlük
/// değilse (AttributeError) ya da öncelikler karşılaştırılamazsa (TypeError) önbellek kullanılmaz, sabit listeye düşülür.
pub fn model_choices(cache: Option<&Value>) -> Vec<String> {
    let fallback = || FALLBACK_MODELS.iter().map(|s| s.to_string()).collect();
    let Some(Value::Object(data)) = cache else { return fallback() };
    let models: Vec<&Value> = match data.get("models") {
        None => Vec::new(),
        Some(Value::Array(a)) => a.iter().collect(),
        // sözlük/dize üzerinde yineleme dize verir: `m.get` AttributeError; sayı/None/bool: TypeError.
        Some(Value::Object(o)) if o.is_empty() => Vec::new(),
        Some(Value::String(s)) if s.is_empty() => Vec::new(),
        Some(_) => return fallback(),
    };
    let mut listed: Vec<(PrioKey, String)> = Vec::new();
    for m in models {
        let Value::Object(m) = m else { return fallback() };
        if m.get("visibility").and_then(Value::as_str) != Some("list") || !m.get("slug").is_some_and(truthy) {
            continue;
        }
        // Dize olmayan (ama doğru değerli) slug Python'da listeye OLDUĞU GİBİ girer; burada temsil edilemez, atlanır.
        let Some(slug) = m.get("slug").and_then(Value::as_str) else { continue };
        listed.push((prio_key(m), slug.to_string()));
    }
    if listed.len() > 1 {
        let all_num = listed.iter().all(|(k, _)| matches!(k, PrioKey::Num(_)));
        let all_str = listed.iter().all(|(k, _)| matches!(k, PrioKey::Str(_)));
        if !all_num && !all_str {
            return fallback();
        }
        listed.sort_by(|a, b| match (&a.0, &b.0) {
            (PrioKey::Num(x), PrioKey::Num(y)) => x.total_cmp(y),
            (PrioKey::Str(x), PrioKey::Str(y)) => x.cmp(y),
            _ => std::cmp::Ordering::Equal,
        });
    }
    if listed.is_empty() {
        fallback()
    } else {
        listed.into_iter().map(|(_, s)| s).collect()
    }
}

/// Python yinelemesi: liste öğeleri, sözlük anahtarları, dize karakterleri; başka tip (sayı, bool) `TypeError`.
fn py_iter(v: &Value) -> Option<Vec<Value>> {
    match v {
        Value::Array(a) => Some(a.clone()),
        Value::Object(o) => Some(o.keys().map(|k| Value::String(k.clone())).collect()),
        Value::String(s) => Some(s.chars().map(|c| Value::String(c.to_string())).collect()),
        _ => None,
    }
}

pub fn model_effort_levels(model: &str, cache: Option<&Value>) -> Option<Vec<String>> {
    if model.is_empty() {
        return None;
    }
    let Value::Object(data) = cache? else { return None };
    let models = py_iter(data.get("models")?)?;
    for m in &models {
        let Value::Object(m) = m else { return None };
        if m.get("slug").and_then(Value::as_str) != Some(model) {
            continue;
        }
        let raw = match m.get("supported_reasoning_levels").filter(|v| truthy(v)) {
            None => Vec::new(),
            Some(v) => py_iter(v)?,
        };
        let levels = raw.iter().filter_map(|x| match x {
            Value::Object(o) => o.get("effort").and_then(Value::as_str),
            v => v.as_str(),
        });
        return Some(sort_levels(levels.map(str::to_string))).filter(|l| !l.is_empty());
    }
    None
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
