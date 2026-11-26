//! copilot sağlayıcısı. BYOK anahtarları argv'ye girmez: 0600 dosya `exec`ten önce source edilir.

use crate::probe::{BuildOutput, Effect};
use crate::provider::{BuildArgs, Providers};
use crate::pyfmt::quote;
use crate::settings::is_safe_env_name;
use regex::Regex;
use std::sync::LazyLock;

pub const MODEL_CHOICES: [&str; 17] = [
    "gpt-5.6-terra",
    "claude-sonnet-5",
    "gemini-3.8-flash",
    "grok-4.6",
    "gpt-5.6-luna",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5-mini",
    "claude-haiku-4.5",
    "mai-code-1.1-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "grok-4.5",
    "kimi-k3",
    "kimi-k2.7-code",
];
pub const PERMISSION_MODES: [&str; 4] = ["auto", "manual", "plan", "autopilot"];
pub const EFFORT_LEVELS: [&str; 4] = ["low", "medium", "high", "xhigh"];

fn permission_flags(mode: &str) -> &'static [&'static str] {
    match if mode.is_empty() { "auto" } else { mode } {
        "auto" => &["--allow-all-tools", "--allow-all-paths", "--allow-all-urls"],
        "manual" => &[],
        "autopilot" => &["--autopilot", "--allow-all-tools", "--allow-all-paths", "--allow-all-urls"],
        // Tanınmayan mod en kısıtlıya düşer.
        _ => &["--mode", "plan"],
    }
}

static TRUSTED: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#""trustedFolders"\s*:\s*\["#).unwrap());

/// `config.json` (JSONC) metnine `cwd`yi `trustedFolders`a ekler; değişiklik yoksa None.
pub fn trust_folder_edit(text: &str, cwd: &str) -> Option<String> {
    let m = TRUSTED.find(text)?;
    let after = &text[m.end()..];
    // Python `text[m.end():text.find("]", m.end())]`: `]` yoksa -1, yani son karakter hariç.
    let rest = match after.find(']') {
        Some(i) => &after[..i],
        None => &after[..after.len().saturating_sub(after.chars().last().map_or(0, char::len_utf8))],
    };
    let entry = crate::pyfmt::json_ascii(cwd);
    if rest.contains(&entry) {
        return None;
    }
    let sep = if crate::pyfmt::strip(rest).is_empty() { "" } else { "," };
    Some(format!("{}\n    {entry}{sep}{after}", &text[..m.end()]))
}

fn trust_folder(p: &Providers<'_>, cwd: &str, out: &mut BuildOutput) {
    if !cwd.starts_with('/') {
        return;
    }
    let dir = p.probe.env_var("COPILOT_HOME").filter(|s| !s.is_empty());
    let path = format!("{}/config.json", dir.unwrap_or_else(|| format!("{}/.copilot", p.paths.home)));
    let Some(text) = p.probe.read_text(&path) else { return };
    if let Some(content) = trust_folder_edit(&text, cwd) {
        out.effects.push(Effect::WriteAtomic { path: p.probe.realpath(&path), content });
    }
}

/// BYOK env dosyasını eşitle; true = source edilmeli.
fn sync_byok_env_file(p: &Providers<'_>, out: &mut BuildOutput) -> bool {
    let file = p.paths.copilot_env_file();
    let marker = format!("{file}.managed");
    let lines: String = p
        .settings
        .byok_env("copilot")
        .iter()
        .filter(|(k, _)| is_safe_env_name(k))
        .map(|(k, v)| format!("export {k}={}\n", quote(v)))
        .collect();
    if lines.is_empty() {
        // Dosyayı yalnız biz yazdıysak sileriz; elle bırakılana dokunulmaz.
        if p.probe.is_file(&marker) {
            out.effects.push(Effect::Remove { path: file });
            out.effects.push(Effect::Remove { path: marker });
            return false;
        }
        return p.probe.is_file(&file);
    }
    out.effects.push(Effect::WriteSecret { path: file, content: lines });
    out.effects.push(Effect::Touch { path: marker });
    true
}

pub(crate) fn build_inner_command(p: &Providers<'_>, a: &BuildArgs<'_>, out: &mut BuildOutput) -> String {
    let binary = p.resolved_binary("copilot");
    trust_folder(p, a.cwd, out);
    let mut parts = vec![quote(&binary)];
    if let Some(r) = a.resume_id.filter(|r| !r.is_empty()) {
        parts.extend(["--resume".into(), quote(r)]);
    }
    parts.extend(["--model".into(), quote(a.model)]);
    parts.extend(["--effort".into(), quote(if a.effort.is_empty() { "medium" } else { a.effort })]);
    parts.extend(permission_flags(a.permission_mode).iter().map(|s| s.to_string()));
    parts.extend(a.extra_args.iter().map(|x| quote(x)));
    if let Some(pr) = a.prompt.filter(|s| !s.is_empty()) {
        parts.extend(["-i".into(), quote(pr)]);
    }
    let inner = parts.join(" ");
    if sync_byok_env_file(p, out) {
        let wrapped = format!(". {} && exec {inner}", quote(&p.paths.copilot_env_file()));
        return format!("sh -c {}", quote(&wrapped));
    }
    inner
}
