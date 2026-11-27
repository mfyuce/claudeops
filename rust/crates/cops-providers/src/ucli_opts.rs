//! `ucli_session_opts.py`: ucli başlatma seçenekleri (`cli_opts`) doğrulaması ve exec bayrakları.
//! Güvenlik duruşu: geçersiz değer sessizce atılmaz, HATA döner; yasaklı komutlar desenle de açılmaz.

use crate::model_sources::{
    bounded, lock, HttpRequest, ModelIo, SecretValue, HTTP_MAX_BYTES, SERVICE_MODELS_TIMEOUT,
};
use crate::pyfmt::{
    basename, fmt_g, parse_float, parse_int, py_int, str_of, str_or_empty, strip, truthy,
};
use crate::pyjson::Py;
use crate::settings::{is_safe_env_name, Settings};
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap};
use std::sync::{LazyLock, Mutex};

/// Kabuk ya da "başka komut çalıştıran" adlar: exec izin listesine giremez.
const FORBIDDEN: &str = "sh bash zsh dash fish ksh csh tcsh ash busybox env xargs find sudo doas su nohup timeout nice \
time strace ltrace ssh scp nc ncat socat perl ruby node nodejs deno bun php lua luajit tclsh wish expect julia Rscript \
awk gawk mawk nawk sed pwsh powershell osascript groovy jshell guile emacs flock chroot setsid stdbuf watch parallel \
tmux screen script unshare nsenter setpriv taskset ionice systemd-run at batch crontab run-parts bwrap docker podman \
gdb lldb vi vim nvim ed ex less more man curl wget";

static FORBIDDEN_VERSIONED: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)^(?:python|pypy|perl|ruby|node|php|lua|tclsh|busybox)[0-9._-]*\n?$").unwrap()
});
static CMD: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$").unwrap());
static GLOB: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9_./*?-]{1,120}$").unwrap());
static PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z0-9._+*?\[\]!-]{1,64}$").unwrap());
static BIND: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^/[A-Za-z0-9_./+@-]{1,200}$").unwrap());

const MAX_CMDS: usize = 12;
const MAX_EXPANDED: usize = 4000;
const MAX_GLOBS: usize = 4;
const MAX_BINDS: usize = 6;
const TIMEOUT_RANGE: (i64, i64) = (1, 600);
const MAX_COST_USD: f64 = 100.0;
const PRICE_MAX: f64 = 1000.0;
const INT_LIMITS: [(&str, i64); 6] = [
    ("max_prompt_tokens", 100_000_000),
    ("max_repeated_calls", 1000),
    ("max_consecutive_failures", 1000),
    ("max_continuation_steps", 1000),
    ("exec_per_script", 1000),
    ("instructions_max_kib", 256),
];
/// Yalnız `accept_risk` ile kabul edilen çok geniş desenler.
pub const BROAD_GLOBS: [&str; 3] = ["*", "**", "**/*"];

/// Kafese verilecek Rust araç zinciri (bulmak çağıranın işi, bkz. [`crate::Probe::rust_toolchain`]).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Toolchain {
    pub root: String,
    pub cargo: String,
    pub rustc: String,
    pub registry: String,
    pub git: String,
    pub rustup_home: String,
    pub cargo_home: String,
}

pub fn is_forbidden_cmd(name: &str) -> bool {
    let n = name.to_lowercase();
    FORBIDDEN.split_whitespace().any(|f| f.to_lowercase() == n) || FORBIDDEN_VERSIONED.is_match(&n)
}

fn is_glob(c: &str) -> bool {
    c.contains(['*', '?', '['])
}

fn items(v: Option<&Value>) -> Vec<String> {
    let raw: Vec<String> = match v {
        Some(Value::Array(a)) => a.iter().map(str_of).collect(),
        v => str_or_empty(v)
            .replace('\n', ",")
            .split(',')
            .map(str::to_string)
            .collect(),
    };
    raw.iter()
        .map(|x| strip(x))
        .filter(|x| !x.is_empty())
        .map(str::to_string)
        .collect()
}

fn dedup(list: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    list.into_iter()
        .filter(|x| seen.insert(x.clone()))
        .collect()
}

/// Python `v in (True, 1, "true", "on", "1", ["yes"])`.
fn is_true(v: &Value, yes: bool) -> bool {
    match v {
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() == Some(1.0),
        Value::String(s) => matches!(s.as_str(), "true" | "on" | "1") || (yes && s == "yes"),
        _ => false,
    }
}

/// Python `v in (None, "", False, 0, "0", "false", "no", "off")` (`words` false ise yalnız ilk dördü ve `{}` yok).
fn is_unset(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => true,
        Some(Value::Bool(b)) => !*b,
        Some(Value::Number(n)) => n.as_f64() == Some(0.0),
        Some(Value::String(s)) => matches!(s.as_str(), "" | "0" | "false" | "no" | "off"),
        _ => false,
    }
}

fn present(v: Option<&Value>) -> Option<&Value> {
    v.filter(|v| !v.is_null() && v.as_str() != Some(""))
}

fn usd_limit(raw: &Map<String, Value>, key: &str, max: f64) -> Result<Option<f64>, String> {
    let Some(v) = present(raw.get(key)) else {
        return Ok(None);
    };
    let usd = parse_float(&strip(&str_of(v)).replace(',', "."))
        .ok_or_else(|| format!("{key} sayı olmalı"))?;
    if !(0.0..=max).contains(&usd) {
        return Err(format!("{key} 0-{} USD arası", fmt_g(max)));
    }
    Ok(Some(usd).filter(|u| *u > 0.0))
}

/// Ham pencere sözlüğü -> temiz sözlük ya da hata metni. `toolchain` yalnız `exec_toolchain` istenirse çağrılır.
pub fn validate_opts(
    raw: &Value,
    settings: &Settings,
    toolchain: &dyn Fn() -> Result<Toolchain, String>,
) -> Result<Map<String, Value>, String> {
    let mut out = Map::new();
    if !truthy(raw) {
        return Ok(out);
    }
    let Some(raw) = raw.as_object() else {
        return Err("cli_opts nesne olmalı".into());
    };
    let service = strip(&str_or_empty(raw.get("service"))).to_lowercase();
    if !service.is_empty() {
        if !settings.ucli_services().iter().any(|s| s.id == service) {
            return Err(format!("bilinmeyen hizmet: {service}"));
        }
        out.insert("service".into(), json!(service));
    }
    let cmds = items(raw.get("exec_cmds"));
    if !cmds.is_empty() {
        if cmds.len() > MAX_CMDS {
            return Err(format!("en çok {MAX_CMDS} komut"));
        }
        for c in &cmds {
            if let Some(pat) = c.strip_prefix("re:") {
                if pat.is_empty() || pat.chars().count() > 60 {
                    return Err(format!("geçersiz regex (1-60 karakter): {c}"));
                }
                // Python `re.compile` kabul/red kararı ve iletisi (lehçe çevirisi: bkz. `py_re`).
                if let Err(e) = crate::py_re::compile(pat, str::to_string) {
                    return Err(format!("geçersiz regex ({e}): {c}"));
                }
                continue;
            }
            if c.contains(':') || c.contains('/') {
                return Err(format!("yalnız çıplak komut adı, glob ya da re:<regex> (yol ve `:allow-eval` yok): {c}"));
            }
            if is_glob(c) {
                if !PATTERN.is_match(c) {
                    return Err(format!("geçersiz glob: {c}"));
                }
                continue;
            }
            if !CMD.is_match(c) {
                return Err(format!("geçersiz komut adı: {c}"));
            }
            if is_forbidden_cmd(c) {
                return Err(format!(
                    "izin listesine girmez (kabuk/komut çalıştırıcı): {c}"
                ));
            }
        }
        out.insert("exec_cmds".into(), json!(dedup(cmds.clone())));
    }
    let tcv = strip(&str_or_empty(raw.get("exec_toolchain"))).to_lowercase();
    if !tcv.is_empty() {
        if tcv != "rust" {
            return Err(format!("bilinmeyen exec_toolchain: {tcv} (yalnız rust)"));
        }
        toolchain()?;
        out.insert("exec_toolchain".into(), json!("rust"));
    }
    let globs = items(raw.get("exec_own_glob"));
    if !globs.is_empty() {
        if cmds.is_empty() {
            return Err(
                "exec_own_glob için exec_cmds gerekli (komutsuz exec hiçbir şey çalıştırmaz)"
                    .into(),
            );
        }
        if globs.len() > MAX_GLOBS {
            return Err(format!("en çok {MAX_GLOBS} glob"));
        }
        let accept = raw.get("accept_risk").is_some_and(|v| {
            truthy(v)
                && !matches!(
                    str_of(v).to_lowercase().as_str(),
                    "0" | "false" | "no" | "off"
                )
        });
        for g in &globs {
            if !GLOB.is_match(g)
                || g.starts_with('/')
                || g.starts_with('-')
                || g.split('/').any(|p| p == ".." || p.is_empty())
            {
                return Err(format!("geçersiz glob: {g}"));
            }
            if BROAD_GLOBS.contains(&g.as_str()) {
                if !accept {
                    return Err(format!(
                        "çok geniş glob: tüm dosyalara çalıştırma izni verir; kabul etmek için \"riski kabul ediyorum\" işaretle: {g}"
                    ));
                }
                out.insert("accept_risk".into(), json!(true));
            }
        }
        out.insert("exec_own_glob".into(), json!(dedup(globs)));
    }
    let binds = items(raw.get("exec_bind_ro"));
    if !binds.is_empty() {
        if cmds.is_empty() {
            return Err("exec_bind_ro için exec_cmds gerekli".into());
        }
        if binds.len() > MAX_BINDS {
            return Err(format!("en çok {MAX_BINDS} dizin"));
        }
        for b in &binds {
            if !BIND.is_match(b)
                || b.split('/').any(|p| p == "..")
                || b.contains("//")
                || b.trim_end_matches('/').matches('/').count() < 2
            {
                return Err(format!(
                    "geçersiz ya da çok geniş dizin (mutlak, kök/ev dizini olmaz): {b}"
                ));
            }
        }
        let norm = binds
            .iter()
            .map(|b| b.trim_end_matches('/').to_string())
            .collect();
        out.insert("exec_bind_ro".into(), json!(dedup(norm)));
    }
    if raw.get("exec_write").is_some_and(|v| is_true(v, false)) {
        if cmds.is_empty() {
            return Err("exec_write için exec_cmds gerekli".into());
        }
        out.insert("exec_write".into(), json!(true));
    }
    if let Some(t) = present(raw.get("exec_timeout")) {
        let n = parse_int(strip(&str_of(t))).ok_or("exec_timeout sayı olmalı")?;
        if !(TIMEOUT_RANGE.0..=TIMEOUT_RANGE.1).contains(&n) {
            return Err(format!(
                "exec_timeout {}-{} sn arası",
                TIMEOUT_RANGE.0, TIMEOUT_RANGE.1
            ));
        }
        if cmds.is_empty() {
            return Err("exec_timeout için exec_cmds gerekli".into());
        }
        out.insert("exec_timeout".into(), json!(n));
    }
    if let Some(usd) = usd_limit(raw, "max_cost_usd", MAX_COST_USD)? {
        out.insert("max_cost_usd".into(), json!(usd));
    }
    if let Some(usd) = usd_limit(raw, "max_session_usd", MAX_COST_USD * 10.0)? {
        out.insert("max_session_usd".into(), json!(usd));
    }
    for key in ["git_commit", "git_push"] {
        let v = raw.get(key);
        if is_unset(v) {
            continue;
        }
        if !v.is_some_and(|v| is_true(v, true)) {
            return Err(format!("{key} true/false olmalı"));
        }
        out.insert(key.into(), json!(true));
    }
    for (key, hi) in INT_LIMITS {
        let v = raw.get(key);
        // `v in (None, "", False)`: sayısal 0 da False'a eşittir.
        if matches!(v, None | Some(Value::Null) | Some(Value::Bool(false)))
            || v.and_then(Value::as_str) == Some("")
            || v.and_then(Value::as_f64) == Some(0.0)
        {
            continue;
        }
        let n = parse_int(strip(&str_of(v.expect("yukarıda elendi"))))
            .ok_or_else(|| format!("{key} tam sayı olmalı"))?;
        if !(0..=hi).contains(&n) {
            return Err(format!("{key} 0-{hi} arası"));
        }
        if n > 0 {
            out.insert(key.into(), json!(n));
        }
    }
    for key in [
        "no_prompt_cache",
        "show_usage",
        "instructions_user",
        "checkpoint",
    ] {
        let v = raw.get(key);
        if is_unset(v) {
            continue;
        }
        if !v.is_some_and(|v| is_true(v, true)) {
            return Err(format!("{key} true/false olmalı"));
        }
        out.insert(key.into(), json!(true));
    }
    for key in [
        "allow_image",
        "allow_scholar",
        "ask_edit",
        "ask_dir",
        "approval_dir",
    ] {
        let v = raw.get(key);
        if is_unset(v) {
            continue;
        }
        if !v.is_some_and(|v| is_true(v, true)) {
            return Err(format!("{key} true/false olmalı"));
        }
        if key == "ask_edit" && !out.contains_key("exec_write") {
            return Err("ask_edit için exec_write (--allow-edit) gerekli".into());
        }
        if key == "approval_dir" && !out.contains_key("ask_edit") {
            return Err("approval_dir için ask_edit (ve exec_write) gerekli".into());
        }
        if key == "approval_dir" && (out.contains_key("ask_dir") || !is_unset(raw.get("ask_dir"))) {
            return Err(
                "approval_dir (tek atımlık iş) ile ask_dir (REPL) birlikte kullanılamaz".into(),
            );
        }
        out.insert(key.into(), json!(true));
    }
    if let Some(v) = present(raw.get("search_token_env")) {
        let s = strip(&str_of(v)).to_string();
        if s.chars().count() > 64 || !is_safe_env_name(&s) {
            return Err("search_token_env yalnız ortam değişkeni ADI olmalı (A-Z, 0-9, _; <=64), değer değil".into());
        }
        out.insert("search_token_env".into(), json!(s));
    }
    if let Some(p) = present(raw.get("price")) {
        let text = str_of(p);
        let parts: Vec<&str> = text.split(',').map(strip).collect();
        if parts.len() != 2 && parts.len() != 4 {
            return Err(
                "price IN,OUT ya da IN,OUT,CACHE_READ,CACHE_WRITE olmalı (milyon token başına USD)"
                    .into(),
            );
        }
        let mut vals = Vec::new();
        for x in parts {
            let f = parse_float(x).ok_or("price değerleri sayı olmalı")?;
            if !(f > 0.0 && f <= PRICE_MAX) {
                return Err(format!(
                    "price değerleri 0-{} USD/milyon token arası (0 hariç)",
                    fmt_g(PRICE_MAX)
                ));
            }
            vals.push(fmt_g(f));
        }
        out.insert("price".into(), json!(vals.join(",")));
    }
    let uc = raw.get("ucli_checks");
    let uc_unset = match uc {
        None | Some(Value::Null) => true,
        Some(Value::String(s)) => s.is_empty(),
        Some(Value::Bool(b)) => !*b,
        Some(Value::Number(n)) => n.as_f64() == Some(0.0),
        Some(Value::Object(o)) => o.is_empty(),
        _ => false,
    };
    if !uc_unset {
        let Some(uc) = uc.and_then(Value::as_object) else {
            return Err("ucli_checks {mode, max, accept_risk} nesnesi olmalı".into());
        };
        let mode = strip(&str_or_empty(uc.get("mode"))).to_lowercase();
        if mode != "restricted" && mode != "full" {
            return Err("ucli_checks.mode restricted ya da full olmalı".into());
        }
        let raw_max = uc
            .get("max")
            .filter(|v| truthy(v))
            .map_or_else(|| mode.clone(), str_of);
        let max = strip(&raw_max).to_lowercase();
        if max != "restricted" && max != "full" {
            return Err("ucli_checks.max restricted ya da full olmalı".into());
        }
        if max == "restricted" && mode == "full" {
            return Err("ucli_checks.max, mode'dan düşük olamaz".into());
        }
        let risk = uc.get("accept_risk").is_some_and(|v| is_true(v, true));
        if (mode == "full" || max == "full") && !risk {
            return Err("ucli_checks full için accept_risk gerekli (yorumlayıcılar serbest kalır; yine kafeste)".into());
        }
        out.insert(
            "ucli_checks".into(),
            json!({"mode": mode, "max": max, "accept_risk": risk}),
        );
    }
    Ok(out)
}

/// `fnmatch.fnmatchcase` karşılığı regex.
fn fnmatch_regex(pat: &str) -> Option<Regex> {
    let chars: Vec<char> = pat.chars().collect();
    let mut re = String::from("(?s)^");
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        i += 1;
        match c {
            '*' => re.push_str(".*"),
            '?' => re.push('.'),
            '[' => {
                let mut j = i;
                if chars.get(j) == Some(&'!') {
                    j += 1;
                }
                if chars.get(j) == Some(&']') {
                    j += 1;
                }
                while j < chars.len() && chars[j] != ']' {
                    j += 1;
                }
                if j >= chars.len() {
                    re.push_str("\\[");
                    continue;
                }
                let mut body: &[char] = &chars[i..j];
                re.push('[');
                if body.first() == Some(&'!') {
                    re.push('^');
                    body = &body[1..];
                }
                for (k, ch) in body.iter().enumerate() {
                    let range_dash = *ch == '-' && k > 0 && k + 1 < body.len();
                    if range_dash || ch.is_alphanumeric() {
                        re.push(*ch);
                    } else {
                        re.push_str(&format!("\\x{{{:x}}}", *ch as u32));
                    }
                }
                re.push(']');
                i = j + 1;
            }
            c => re.push_str(&regex::escape(&c.to_string())),
        }
    }
    re.push('$');
    Regex::new(&re).ok()
}

/// Çıplak ad | glob | `re:` girdilerini PATH üzerinde çıplak adlara açar.
pub fn expand_exec_cmds(list: &[String], available: &[String]) -> Result<Vec<String>, String> {
    let mut out: Vec<String> = Vec::new();
    for it in list {
        let hit: Vec<&String> = if let Some(pat) = it.strip_prefix("re:") {
            let rx = crate::py_re::compile(pat, |t| format!(r"\A(?:{t})\z"))
                .map_err(|e| format!("geçersiz regex ({e}): {it}"))?;
            available
                .iter()
                .filter(|n| rx.is_match(n).unwrap_or(false))
                .collect()
        } else if is_glob(it) {
            // Geçersiz sınıf (ör. ters aralık) hiçbir şeye uymaz.
            let rx = fnmatch_regex(it);
            available
                .iter()
                .filter(|n| rx.as_ref().is_some_and(|r| r.is_match(n)))
                .collect()
        } else {
            out.push(it.clone());
            continue;
        };
        let before = out.len();
        out.extend(hit.into_iter().filter(|n| !is_forbidden_cmd(n)).cloned());
        if out.len() == before {
            return Err(format!("desen hiçbir komuta uymadı: {it}"));
        }
    }
    let out = dedup(out);
    if out.len() > MAX_EXPANDED {
        return Err(format!(
            "desenler çok geniş ({} komut > {MAX_EXPANDED})",
            out.len()
        ));
    }
    Ok(out)
}

pub(crate) fn str_list(opts: &Map<String, Value>, key: &str) -> Vec<String> {
    opts.get(key)
        .and_then(Value::as_array)
        .map(|a| a.iter().map(str_of).collect())
        .unwrap_or_default()
}

/// Temiz `opts` -> `--allow-exec` ailesi bayrakları; komut yoksa boş.
pub fn exec_flags(
    opts: &Map<String, Value>,
    toolchain: &dyn Fn() -> Result<Toolchain, String>,
    is_dir: &dyn Fn(&str) -> bool,
) -> Vec<String> {
    let mut cmds = str_list(opts, "exec_cmds");
    let tc = (opts.get("exec_toolchain").and_then(Value::as_str) == Some("rust"))
        .then(toolchain)
        .and_then(Result::ok);
    if let Some(tc) = &tc {
        cmds.extend([tc.cargo.clone(), tc.rustc.clone()]);
    }
    if cmds.is_empty() {
        return Vec::new();
    }
    let mut argv: Vec<String> = vec![
        "--allow-exec".into(),
        "--allow-exec-cmd".into(),
        cmds.join(","),
    ];
    for g in str_list(opts, "exec_own_glob") {
        argv.extend(["--allow-exec-own-glob".into(), g]);
    }
    let mut binds = str_list(opts, "exec_bind_ro");
    if let Some(tc) = &tc {
        binds.push(tc.root.clone());
        binds.extend(
            [&tc.registry, &tc.git]
                .into_iter()
                .filter(|p| is_dir(p))
                .cloned(),
        );
        let bin_dir = tc.cargo.rsplit_once('/').map_or("", |(d, _)| d);
        for kv in [
            format!("RUSTUP_HOME={}", tc.rustup_home),
            format!("CARGO_HOME={}", tc.cargo_home),
            format!("RUSTUP_TOOLCHAIN={}", basename(&tc.root)),
            "CARGO_NET_OFFLINE=true".to_string(),
            format!("PATH={bin_dir}:/usr/local/bin:/usr/bin:/bin"),
        ] {
            argv.extend(["--exec-env".into(), kv]);
        }
        argv.extend(["--exec-memory-mib", "32768", "--exec-max-tasks", "4096"].map(String::from));
    }
    for b in dedup(binds) {
        argv.extend(["--exec-bind-ro".into(), b]);
    }
    if let Some(t) = opts.get("exec_timeout").filter(|v| truthy(v)) {
        let secs = py_int(t).unwrap_or(0);
        argv.extend(["--exec-timeout-secs".into(), secs.to_string()]);
    }
    argv
}

/// Boş olmayan hizmet listesinin ömrü (sn).
pub const SERVICE_MODELS_TTL: f64 = 86400.0;
/// Boş (başarısız) sonucun yeniden denemeden önce tutulma süresi (sn).
pub const SERVICE_MODELS_RETRY: f64 = 60.0;

/// `_MODELS_CACHE`: hizmet kimliği -> (çekim anı, kimlikler). Anahtar yalnız hizmet kimliğidir (Python gibi).
#[derive(Debug, Default)]
pub struct ServiceModelsCache(Mutex<HashMap<String, (f64, Vec<String>)>>);

impl ServiceModelsCache {
    /// `service_models`: hizmetin `/models` kimlikleri (sıralı, tekrarsız). Bilinmeyen hizmet, `evren` ya da boş anahtar:
    /// boş liste ve istek YOK. Başarısızlık da önbelleğe yazılır (eski iyi listenin ÜSTÜNE, Python gibi).
    pub(crate) fn get(
        &self,
        io: &dyn ModelIo,
        settings: &Settings,
        service: &str,
        key: &str,
    ) -> Vec<String> {
        if service == "evren" || key.is_empty() {
            return Vec::new();
        }
        let Some(svc) = settings
            .ucli_services()
            .into_iter()
            .find(|s| s.id == service)
        else {
            return Vec::new();
        };
        let now = io.wall_secs();
        if let Some((at, ids)) = lock(&self.0).get(service) {
            let ttl = if ids.is_empty() {
                SERVICE_MODELS_RETRY
            } else {
                SERVICE_MODELS_TTL
            };
            if now - at < ttl {
                return ids.clone();
            }
        }
        let ids = fetch_service_models(io, &svc.wire, &svc.endpoint, key).unwrap_or_default();
        lock(&self.0).insert(service.to_string(), (now, ids.clone()));
        ids
    }
}

fn fetch_service_models(
    io: &dyn ModelIo,
    wire: &str,
    endpoint: &str,
    key: &str,
) -> Option<Vec<String>> {
    let headers = if wire == "anthropic-messages" {
        vec![
            ("x-api-key", SecretValue::new(key)?),
            ("anthropic-version", SecretValue::new("2023-06-01")?),
        ]
    } else {
        vec![("Authorization", SecretValue::new(&format!("Bearer {key}"))?)]
    };
    let req = HttpRequest {
        url: format!("{}/models?limit=200", endpoint.trim_end_matches('/')),
        headers,
        timeout: SERVICE_MODELS_TIMEOUT,
        max_body: HTTP_MAX_BYTES,
    };
    let body = bounded(io.http_get(&req), req.max_body)?;
    Some(parse_service_models(&body))
}

/// Yanıt `{"data": [...]}` ya da doğrudan dizi; her nesnenin dolu `id`si `str()` ile. Bozuk gövde boş liste.
pub fn parse_service_models(body: &[u8]) -> Vec<String> {
    let Some(data) = Py::parse(&String::from_utf8_lossy(body)) else {
        return Vec::new();
    };
    let rows = if data.is_object() {
        data.get("data")
    } else {
        Some(&data)
    };
    let Some(Py::Array(rows)) = rows else {
        return Vec::new();
    };
    let ids: BTreeSet<String> = rows
        .iter()
        .filter_map(|m| m.get("id"))
        .filter(|id| id.truthy())
        .map(Py::py_str)
        .collect();
    ids.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Beklenenler Python `ucli_session_opts.validate_opts`un aynı girdideki çıktısı (27 Kas elle koşuldu; geniş kapsam
    /// `parity_ucli`). Toolchain yalnız `exec_toolchain` istenirse çağrılır.
    #[test]
    fn validate_opts_matches_python() {
        let s = Settings::default();
        let no_tc = || -> Result<Toolchain, String> { panic!("toolchain çağrılmamalı") };
        let run = |raw: Value| validate_opts(&raw, &s, &no_tc);
        assert_eq!(run(Value::Null), Ok(Map::new()));
        assert_eq!(run(json!({})), Ok(Map::new()));
        assert_eq!(run(json!([])), Ok(Map::new()));
        assert_eq!(run(json!("x")), Err("cli_opts nesne olmalı".into()));
        assert_eq!(
            run(json!({"service": "YOK"})),
            Err("bilinmeyen hizmet: yok".into())
        );
        assert_eq!(
            run(json!({"exec_cmds": ["re:"]})),
            Err("geçersiz regex (1-60 karakter): re:".into())
        );
        assert_eq!(
            run(json!({"exec_cmds": ["re:("]})),
            Err("geçersiz regex (missing ), unterminated subpattern at position 0): re:(".into())
        );
        let ok = run(json!({"exec_cmds": ["ls", "re:^git( |$)"]})).unwrap();
        assert_eq!(
            Value::Object(ok),
            json!({"exec_cmds": ["ls", "re:^git( |$)"]})
        );
        assert_eq!(
            Value::Object(run(json!({"max_cost_usd": "1,5"})).unwrap()),
            json!({"max_cost_usd": 1.5})
        );
        assert_eq!(run(json!({"max_cost_usd": "0"})), Ok(Map::new()));
        for bad in ["-1", "nan", "inf"] {
            assert_eq!(
                run(json!({"max_cost_usd": bad})),
                Err("max_cost_usd 0-100 USD arası".into()),
                "{bad}"
            );
        }
        assert_eq!(
            run(json!({"max_cost_usd": "abc"})),
            Err("max_cost_usd sayı olmalı".into())
        );
        assert_eq!(
            run(json!({"exec_toolchain": true})),
            Err("bilinmeyen exec_toolchain: true (yalnız rust)".into())
        );
    }
}
