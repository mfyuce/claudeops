//! `spawn.py`nin saf kısmı: effort çözümü, ortam öneki, nice, kabuk satırı, alt süreç ortamı, pencere argv'si.
//! Süreç başlatma ve tmux komutları burada YOK (tmux: `cops-tmux`).

use crate::probe::{BuildOutput, SpawnError};
use crate::provider::{BuildArgs, Cli, McpSpec, Providers};
use crate::pyfmt::{join_quoted, parse_float, py_float, quote, strip, truthy};
use crate::settings::{is_safe_env_name, Settings};
use serde_json::{json, Map, Value};

/// Süreç/kabuk davranışını ele geçirebilen değişkenler: `env_overrides` ile ASLA taşınmaz.
const DANGEROUS_ENV: [&str; 10] = [
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "BASH_ENV", "ENV", "PROMPT_COMMAND", "SHELLOPTS", "BASHOPTS", "PS4",
    "IFS",
];
const DRY_RUN_PREVIEW_MAX: usize = 600;
const SECRET_WORDS: [&str; 6] = ["key", "token", "secret", "passw", "credential", "auth"];

/// `re.IGNORECASE` karakter katlaması (sre: basit küçük harf + `_equivalences`: ı~i, ſ~s, İ->i, K(U+212A)->k).
fn fold_char(c: char) -> char {
    match c {
        '\u{131}' | '\u{130}' => 'i',
        '\u{17f}' => 's',
        c => {
            let mut l = c.to_lowercase();
            match (l.next(), l.next()) {
                (Some(x), None) => x,
                _ => c,
            }
        }
    }
}
/// Değnekçi beyni düşük öncelikli açılmaz.
const BRAIN_NAME_PREFIX: &str = "degnekci";
pub const SESSION_USD_CAP_KEY: &str = "CLAUDEOPS_SESSION_USD_CAP";

/// Geçerli ad + tehlikeli listede değil.
pub fn filter_env_overrides(overrides: Vec<(String, String)>) -> Vec<(String, String)> {
    overrides.into_iter().filter(|(k, _)| is_safe_env_name(k) && !DANGEROUS_ENV.contains(&k.as_str())).collect()
}

/// Kabuğa gömülecek `renice/ionice` öneki ("" = yok).
pub fn priority_prefix(settings: &Settings, name: &str) -> String {
    match settings.spawn_nice() {
        Some(n) if !name.starts_with(BRAIN_NAME_PREFIX) => format!(
            "{{ renice -n {n} -p $$ >/dev/null 2>&1; ionice -c2 -n7 -p $$ >/dev/null 2>&1; true; }} && "
        ),
        _ => String::new(),
    }
}

/// Dry-run satırı: sır adlı ortam değeri maskelenir, uzun komut kesilir.
pub fn dry_run_preview(cwd: &str, overrides: &[(String, String)], invocation: &str) -> String {
    let env: String = overrides
        .iter()
        .map(|(k, v)| {
            let folded: String = k.chars().map(fold_char).collect();
            let value = if SECRET_WORDS.iter().any(|w| folded.contains(w)) { "***".to_string() } else { quote(v) };
            format!("{k}={value} ")
        })
        .collect();
    let out = format!("cd {} && {env}{invocation}", quote(cwd));
    if out.chars().count() <= DRY_RUN_PREVIEW_MAX {
        out
    } else {
        out.chars().take(DRY_RUN_PREVIEW_MAX).collect::<String>() + "..."
    }
}

/// Kanca ortamındaki kalan günlük USD tavanını ayıklar; ucli'de `max_session_usd` = min(kayıt/ayar, kanca).
pub fn apply_hook_session_cap(
    hook_env: &mut Vec<(String, String)>,
    cli_opts: Option<Map<String, Value>>,
    cli: Cli,
    settings: &Settings,
) -> Option<Map<String, Value>> {
    let Some(i) = hook_env.iter().position(|(k, _)| k == SESSION_USD_CAP_KEY) else { return cli_opts };
    let raw = hook_env.remove(i).1;
    if !cli.accepts_cli_opts() {
        return cli_opts;
    }
    let Some(cap) = parse_float(strip(&raw)).filter(|c| *c > 0.0 && c.is_finite()) else { return cli_opts };
    let cap = cap.max(0.01);
    let mut opts = cli_opts.unwrap_or_default();
    let mut cur = opts
        .get("max_session_usd")
        .filter(|v| truthy(v))
        .and_then(py_float)
        .unwrap_or(0.0);
    if cur == 0.0 {
        cur = settings.default_max_session_usd();
    }
    opts.insert("max_session_usd".into(), json!(if cur > 0.0 { cur.min(cap) } else { cap }));
    Some(opts)
}

/// Spawn isteği. `resume_id` çözümü (transkript taraması) çağıranın işi.
#[derive(Debug, Clone, Default)]
pub struct SpawnRequest {
    pub name: String,
    pub cwd: String,
    pub model: String,
    pub permission_mode: String,
    pub effort: String,
    pub resume_id: Option<String>,
    pub prompt: Option<String>,
    pub cli: String,
    pub mcp_server: Option<McpSpec>,
    /// Eklentinin bu cwd için verdiği MCP sunucusu (yalnız claude ve `mcp_server` yokken).
    pub extension_mcp: Option<McpSpec>,
    /// Çok kullanıcı kancasının ortamı (reddi çağıran bundan ÖNCE verir).
    pub hook_env: Vec<(String, String)>,
    pub cli_opts: Option<Map<String, Value>>,
}

/// Başlatmaya hazır plan.
#[derive(Debug)]
pub struct SpawnPlan {
    /// `new` ya da `resume:<id[:8]>`.
    pub kind: String,
    pub effort: String,
    /// `cd CWD && [nice] [ENV=..] <binary> ...`
    pub inner: String,
    /// `cd`/ortam olmadan CLI çağrısı.
    pub invocation: String,
    pub overrides: Vec<(String, String)>,
}

impl SpawnPlan {
    pub fn dry_run_line(&self, cwd: &str) -> String {
        format!("[dry-run] {}  cmd: {}", self.kind, dry_run_preview(cwd, &self.overrides, &self.invocation))
    }
}

/// `spawn_session`ın komut kuran kısmı (tek geçit: effort burada çözülür). Diag olayları ve Effect'ler `output`a
/// birikir; HATA dönse bile birikenler uygulanmalı/günlüğe yazılmalı (Python hatadan önce yazdıklarını bırakır).
pub fn plan_spawn(p: &Providers<'_>, req: &SpawnRequest, output: &mut BuildOutput) -> Result<SpawnPlan, SpawnError> {
    let cli = Cli::parse(&req.cli);
    let resume = req.resume_id.as_deref();
    let kind = match resume {
        Some(r) => format!("resume:{}", r.chars().take(8).collect::<String>()),
        None => "new".into(),
    };
    let effort = p.resolve_effort(cli, &req.model, &req.effort);
    if effort != req.effort {
        output.diag(
            "spawn_effort_adjusted",
            vec![("name", json!(&req.name)), ("cli", json!(&req.cli)), ("model", json!(&req.model)), ("requested", json!(&req.effort)), ("used", json!(&effort))],
        );
    }
    let mcp = req.mcp_server.as_ref().or_else(|| req.extension_mcp.as_ref().filter(|_| req.cli == "claude"));
    let extra = mcp.map(|s| p.mcp_launch_args(cli, s, &req.cwd, output)).unwrap_or_default();
    let mut hook_env = req.hook_env.clone();
    let cli_opts = apply_hook_session_cap(&mut hook_env, req.cli_opts.clone(), cli, p.settings);
    let args = BuildArgs {
        cwd: &req.cwd,
        model: &req.model,
        permission_mode: &req.permission_mode,
        effort: &effort,
        resume_id: resume,
        prompt: req.prompt.as_deref(),
        session_name: &req.name,
        extra_args: &extra,
        cli_opts: cli_opts.as_ref().filter(|o| cli.accepts_cli_opts() && !o.is_empty()),
    };
    let invocation = p.build_inner_command(cli, &args, output)?;
    // Python dict birleştirme: var olan anahtar yerinde güncellenir.
    let mut overrides = cli.env_overrides(&req.name);
    for (k, v) in hook_env {
        match overrides.iter_mut().find(|(have, _)| *have == k) {
            Some(slot) => slot.1 = v,
            None => overrides.push((k, v)),
        }
    }
    // Ortam komut satırına gömülür: tmux çalışan sunucuda Popen ortamını aktarmaz.
    let overrides = filter_env_overrides(overrides);
    let env_prefix: String = overrides.iter().map(|(k, v)| format!("{k}={} ", quote(v))).collect();
    let inner =
        format!("cd {} && {}{env_prefix}{invocation}", quote(&req.cwd), priority_prefix(p.settings, &req.name));
    Ok(SpawnPlan { kind, effort, inner, invocation, overrides })
}

/// Başlatılacak oturumun ortamı: çağıran sürecin CLI kimlik değişkenleri süpürülür, `DISPLAY` yazılır.
/// Python dict ataması: ebeveynde `DISPLAY` varsa yerinde değişir (sıra korunur), yoksa sona eklenir.
pub fn child_env<I: IntoIterator<Item = (String, String)>>(parent: I, display: &str) -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = parent
        .into_iter()
        .filter(|(k, _)| !["CLAUDE", "GEMINI", "ANTIGRAVITY"].iter().any(|p| k.starts_with(p)))
        .collect();
    match env.iter_mut().find(|(k, _)| k == "DISPLAY") {
        Some(slot) => slot.1 = display.into(),
        None => env.push(("DISPLAY".into(), display.into())),
    }
    env
}

/// `open_mirror_window` ortamı: [`child_env`] + `CLAUDEOPS_DIR` geri konur (süpürme onu da atar; görüntüleyici token'ı
/// aynı panelin dizininden okumalı).
pub fn mirror_child_env<I: IntoIterator<Item = (String, String)>>(
    parent: I,
    display: &str,
    claudeops_dir: &str,
) -> Vec<(String, String)> {
    let mut env = child_env(parent, display);
    match env.iter_mut().find(|(k, _)| k == "CLAUDEOPS_DIR") {
        Some(slot) => slot.1 = claudeops_dir.into(),
        None => env.push(("CLAUDEOPS_DIR".into(), claudeops_dir.into())),
    }
    env
}

/// `DISPLAY`: ortam -> var olan X soketi/kilidi (`:1`, `:0`) -> `:1`.
pub fn detect_display(env_display: Option<&str>, exists: &dyn Fn(&str) -> bool) -> String {
    if let Some(d) = env_display.filter(|d| !d.is_empty()) {
        return d.into();
    }
    [":1", ":0"]
        .into_iter()
        .find(|d| exists(&format!("/tmp/.X{}-lock", &d[1..])) || exists(&format!("/tmp/.X11-unix/X{}", &d[1..])))
        .unwrap_or(":1")
        .into()
}

/// Pencerede çalışacak kabuk satırı: tmux varsa `tmux_fragment` (cops-tmux üretir), yoksa `inner`.
pub fn window_command(inner: &str, tmux_fragment: Option<&str>) -> String {
    format!("{}; exec bash", tmux_fragment.unwrap_or(inner))
}

/// `gnome-terminal` argv'si (geometri profil varsayılanından bağımsız sabit).
pub fn gnome_terminal_argv(name: &str, cwd: &str, window_cmd: &str) -> Vec<String> {
    vec![
        "gnome-terminal".into(),
        "--window".into(),
        format!("--title={name}"),
        format!("--working-directory={cwd}"),
        "--geometry=100x30".into(),
        "--".into(),
        "bash".into(),
        "-c".into(),
        window_cmd.into(),
    ]
}

/// `cops watch host:ad` aynalama penceresinin kabuk satırı.
pub fn mirror_window_command(repo_dir: &str, host: &str, name: &str, port: u16) -> String {
    let cops = format!("{}/py/cops", repo_dir.trim_end_matches('/'));
    let cmd = join_quoted(&[cops, "watch".into(), format!("{host}:{name}"), "--port".into(), port.to_string()]);
    format!(
        "{cmd}; rc=$?; if [ \"$rc\" -ne 0 ]; then echo; echo \"cops watch çıkış kodu: $rc\"; read -r -p \"Kapatmak için \
         Enter... \" _; fi"
    )
}
