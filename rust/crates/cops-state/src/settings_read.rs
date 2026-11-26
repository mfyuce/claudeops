//! `settings.py` okuyucuları (yazım Python'da): `resolved_binary`, `byok_env_for`, `ucli_*`, `normalize_ucli_services`,
//! `_valid_http_url`, `_daemon_config`/`uzakgoz_config`/`derbent_config`, `reader_config`. Elle düzenlenebilen değerler
//! Python'daki `str(x)` / `int(...)` / `float(...)` zinciriyle AYNEN yorumlanır (`pycompat`); parite testi:
//! `tests/parity_settings.rs::settings_readers_match_python`. Model/effort varsayılanları (`default_model_for` ...)
//! sağlayıcı bilgisini PARAMETRE alır (bu crate sağlayıcılara bağlı değil); parite: `tests/parity_steward.rs`.
//!
//! Python'un İSTİSNA fırlattığı iki tip hatası (bkz. `docs/rs-state.md` "Sahibe soruldu") burada [`SettingsTypeError`]
//! döner: sessizce yutulmaz, sessizce düzeltilmez.
use crate::json::{Json, Map};
use crate::paths::{expanduser_with, home_env, is_executable_file, realpath};
use crate::pycompat::{self as py, PyInt};
use crate::settings::Settings;
use indexmap::IndexMap;
use std::ffi::OsString;
use std::path::Path;
use std::sync::OnceLock;

/// Python `_ON_WORDS`.
pub const ON_WORDS: [&str; 9] = [
    "on", "1", "true", "yes", "y", "evet", "acik", "açık", "enabled",
];
/// Python `_OFF_WORDS` (`settings::OFF_WORDS` ile aynı).
pub use crate::settings::OFF_WORDS;
/// Python `UCLI_REASONING_LEVELS` / `_REASONING_LEVELS`.
pub const UCLI_REASONING_LEVELS: [&str; 4] = ["low", "medium", "high", "max"];
pub const UCLI_STREAM_DEFAULT: bool = true;
pub const UCLI_SHOW_REASONING_DEFAULT: bool = false;
pub const UCLI_STATE_DIR_DEFAULT: bool = false;
/// Python `USAGE_WARN_DEFAULTS` (amber, red).
pub const USAGE_WARN_DEFAULTS: (i64, i64) = (1_000_000, 3_000_000);
pub const MAX_FETCH_DOMAINS: usize = 64;
pub const UZAKGOZ_DEFAULT_DIR: &str = "~/work/projects/tmp/uzakgoz";
pub const DERBENT_DEFAULT_DIR: &str = "~/work/projects/tmp/derbent";
/// Python `ucli_limit_overrides` alanları (sıra Python ile aynı).
pub const UCLI_LIMIT_KEYS: [&str; 6] = [
    "max_steps",
    "max_context_kib",
    "max_tool_calls",
    "max_output_tokens",
    "request_timeout_secs",
    "max_history_kib",
];
/// Python `_KNOWN_BINARY_PATHS`.
pub fn known_binary_paths(cli: &str) -> &'static [&'static str] {
    match cli {
        "claude" => &[
            "~/cc/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
            "~/cc/node_modules/.bin/claude",
            "~/.local/bin/claude",
            "~/.claude/local/claude",
            "~/.npm-global/bin/claude",
            "/usr/local/bin/claude",
        ],
        _ => &[],
    }
}

/// Python `DEFAULT_UCLI_SERVICES` (`default_ucli_services.json`; parite testi denetler).
pub fn default_ucli_services() -> &'static [Json] {
    static D: OnceLock<Vec<Json>> = OnceLock::new();
    D.get_or_init(
        || match Json::parse(include_str!("default_ucli_services.json")) {
            Ok(Json::Array(a)) => a,
            _ => unreachable!(
                "default_ucli_services.json derleme zamanı sabiti; birim testi denetler"
            ),
        },
    )
}

/// Python'un `TypeError`/`AttributeError` fırlattığı elle bozulmuş değer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SettingsTypeError {
    /// Hangi alan (ör. `ucli_services[2].models`).
    pub field: String,
    /// Python istisna türü.
    pub python: &'static str,
}

impl std::fmt::Display for SettingsTypeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "settings {}: Python {}", self.field, self.python)
    }
}
impl std::error::Error for SettingsTypeError {}

/// Süreç ortamından gelen ve okuyucuların kullandığı değerler (`HOME`, `PATH`). Testler açık değer verir.
#[derive(Debug, Clone, Default)]
pub struct SysEnv {
    /// `None` = `HOME` tanımsız (o zaman passwd kaydı).
    pub home: Option<String>,
    /// `None` = `PATH` tanımsız (o zaman `CS_PATH`).
    pub path: Option<OsString>,
}

impl SysEnv {
    pub fn from_process() -> SysEnv {
        SysEnv {
            home: home_env().map(|h| h.to_string_lossy().into_owned()),
            path: std::env::var_os("PATH"),
        }
    }
    fn expand(&self, p: &str) -> String {
        expanduser_with(p, self.home.as_deref())
    }
}

/// `shutil.which(cmd)` (posix, `mode=X_OK`).
pub fn which(cmd: &str, path_env: Option<&OsString>) -> Option<String> {
    let check = |p: &str| {
        let m = std::fs::metadata(p);
        m.as_ref().is_ok_and(|m| !m.is_dir()) && crate::paths::access_x(p)
    };
    if cmd.contains('/') {
        return check(cmd).then(|| cmd.to_string());
    }
    let path = match path_env {
        Some(p) => p.to_string_lossy().into_owned(),
        None => cs_path(),
    };
    if path.is_empty() {
        return None;
    }
    let mut seen = std::collections::HashSet::new();
    for dir in path.split(':') {
        if !seen.insert(dir) {
            continue;
        }
        let name = if dir.is_empty() || dir.ends_with('/') {
            format!("{dir}{cmd}")
        } else {
            format!("{dir}/{cmd}")
        };
        if check(&name) {
            return Some(name);
        }
    }
    None
}

/// `os.confstr("CS_PATH")`.
fn cs_path() -> String {
    let mut buf = vec![0u8; 256];
    // SAFETY: tampon boyutu doğru verilir; dönüş gereken boyut (NUL dahil).
    let n = unsafe { libc::confstr(libc::_CS_PATH, buf.as_mut_ptr().cast(), buf.len()) };
    if n == 0 || n > buf.len() {
        return "/bin:/usr/bin".into(); // os.defpath (":/bin:/usr/bin" değil: Python önce CS_PATH dener)
    }
    buf.truncate(n - 1);
    String::from_utf8_lossy(&buf).into_owned()
}

/// `_valid_http_url`: http(s) şeması + host adı; boşluk/denetim karakteri yok; `urlsplit` ve `.port` `ValueError` vermez.
pub fn valid_http_url(url: &str) -> bool {
    if url.is_empty()
        || url
            .chars()
            .any(|c| py::is_space(c) || (c as u32) < 32 || c as u32 == 127)
    {
        return false;
    }
    let Some((scheme, netloc)) = urlsplit_netloc(url) else {
        return false;
    };
    let (host, port) = hostinfo(&netloc);
    if let Some(p) = port {
        if !p.bytes().all(|b| b.is_ascii_digit()) || p.is_empty() {
            return false;
        }
        if py::parse_int(p)
            .and_then(|n| n.as_i64())
            .is_none_or(|n| n > 65535)
        {
            return false;
        }
    }
    (scheme == "http" || scheme == "https") && !host.is_empty()
}

const SCHEME_CHARS: &str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.";

/// `urllib.parse.urlsplit` (Python 3.10): (şema, netloc); `ValueError` = `None`. Girdi boşluk/denetim karakteri taşımaz.
fn urlsplit_netloc(url: &str) -> Option<(String, String)> {
    let mut scheme = String::new();
    let mut rest = url;
    if let Some(i) = url.find(':') {
        if i > 0 && url[..i].chars().all(|c| SCHEME_CHARS.contains(c)) {
            scheme = url[..i].to_ascii_lowercase();
            rest = &url[i + 1..];
        }
    }
    let mut netloc = String::new();
    if let Some(after) = rest.strip_prefix("//") {
        let end = after.find(['/', '?', '#']).unwrap_or(after.len());
        netloc = after[..end].to_string();
        let (o, c) = (netloc.contains('['), netloc.contains(']'));
        if o != c {
            return None;
        }
        if o && !check_bracketed_netloc(&netloc) {
            return None;
        }
    }
    if !netloc.is_ascii() {
        // `_checknetloc`: NFKC'de `/?#@:` üreten karakter (`@:#?` kendisi sayılmaz)
        if netloc.chars().any(py::nfkc_netloc_bad) {
            return None;
        }
    }
    Some((scheme, netloc))
}

fn rpartition_at(netloc: &str) -> &str {
    netloc.rsplit_once('@').map_or(netloc, |(_, h)| h)
}

fn check_bracketed_netloc(netloc: &str) -> bool {
    let hp = rpartition_at(netloc);
    let hostname = match hp.split_once('[') {
        Some((before, bracketed)) => {
            if !before.is_empty() {
                return false;
            }
            let (h, port) = bracketed.split_once(']').unwrap_or((bracketed, ""));
            if !port.is_empty() && !port.starts_with(':') {
                return false;
            }
            h
        }
        None => hp.split_once(':').map_or(hp, |(h, _)| h),
    };
    if let Some(v) = hostname.strip_prefix('v') {
        // \Av[a-fA-F0-9]+\..+\Z
        let hex = v.bytes().take_while(u8::is_ascii_hexdigit).count();
        return hex > 0 && v[hex..].strip_prefix('.').is_some_and(|r| !r.is_empty());
    }
    ipv6_with_scope(hostname)
}

/// `ipaddress.ip_address(s)` IPv6 ise (IPv4 ya da geçersiz = yanlış). Kapsam (`%ad`) desteklenir.
fn ipv6_with_scope(s: &str) -> bool {
    let (addr, scope) = match s.split_once('%') {
        Some((a, z)) => (a, Some(z)),
        None => (s, None),
    };
    if scope.is_some_and(|z| z.is_empty() || z.contains('%')) {
        return false;
    }
    addr.parse::<std::net::Ipv6Addr>().is_ok()
}

/// `_hostinfo`: (host adı, port); port boşsa `None`.
fn hostinfo(netloc: &str) -> (&str, Option<&str>) {
    let hi = rpartition_at(netloc);
    let (host, port) = match hi.split_once('[') {
        Some((_, bracketed)) => {
            let (h, p) = bracketed.split_once(']').unwrap_or((bracketed, ""));
            (h, p.split_once(':').map_or("", |(_, p)| p))
        }
        None => hi.split_once(':').unwrap_or((hi, "")),
    };
    (host, (!port.is_empty()).then_some(port))
}

/// `_HOST_RE` (tam host adı: etiket `[a-z0-9-]`, tire uçta değil, toplam <= 253).
fn valid_host(tok: &str) -> bool {
    if tok.is_empty() || tok.chars().count() > 253 {
        return false;
    }
    tok.split('.').all(|l| {
        let b = l.as_bytes();
        let ok = |c: &u8| c.is_ascii_lowercase() || c.is_ascii_digit();
        !b.is_empty()
            && b.len() <= 63
            && b.first().is_some_and(ok)
            && b.last().is_some_and(ok)
            && b.iter().all(|c| ok(c) || *c == b'-')
    })
}

/// `^\d{4}-\d{2}-\d{2}$` (`\d` Unicode ondalık rakam).
fn date_like(v: &str) -> bool {
    let c: Vec<char> = v.chars().collect();
    c.len() == 10
        && c.iter().enumerate().all(|(i, &ch)| {
            if i == 4 || i == 7 {
                ch == '-'
            } else {
                py::is_re_digit(ch)
            }
        })
}

/// `str(raw.get(key) or "").strip().lower()`.
fn word(blk: Option<&Json>, key: &str) -> String {
    py::lower(py::strip(&py::str_or_empty(blk.and_then(|b| b.get(key)))))
}

fn positive_float(v: Option<&Json>) -> f64 {
    let text = match v {
        Some(x) if x.truthy() => py::str_of(x),
        _ => "0".into(),
    };
    let f = py::parse_float(&text.replace(',', ".")).unwrap_or(0.0);
    if f > 0.0 && f.is_finite() {
        f
    } else {
        0.0
    }
}

/// `ucli_cost_config` sonucu.
#[derive(Debug, Clone, PartialEq)]
pub struct UcliCost {
    pub daily_cap_usd: f64,
    pub cache_ttl: String,
    pub credit_total_usd: f64,
    pub credit_since: String,
    pub credit_until: String,
}

impl UcliCost {
    /// Python sözlüğüyle aynı anahtar sırası.
    pub fn to_json(&self) -> Json {
        let mut m = Map::new();
        m.insert("daily_cap_usd".into(), Json::Float(self.daily_cap_usd));
        m.insert("cache_ttl".into(), self.cache_ttl.as_str().into());
        m.insert(
            "credit_total_usd".into(),
            Json::Float(self.credit_total_usd),
        );
        m.insert("credit_since".into(), self.credit_since.as_str().into());
        m.insert("credit_until".into(), self.credit_until.as_str().into());
        Json::Object(m)
    }
}

/// `_daemon_config` sonucu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaemonConfig {
    pub dir: String,
    pub bin: String,
    pub port: Option<u16>,
}

impl DaemonConfig {
    pub fn to_json(&self) -> Json {
        let mut m = Map::new();
        m.insert("dir".into(), self.dir.as_str().into());
        m.insert("bin".into(), self.bin.as_str().into());
        m.insert(
            "port".into(),
            self.port.map_or(Json::Null, |p| Json::Int(i64::from(p))),
        );
        Json::Object(m)
    }
}

/// `normalize_ucli_services(raw)`: doğrulanmış hizmet listesi; `evren` her zaman var. Python'un `TypeError` verdiği
/// `models` değeri (sıfır olmayan sayı / `true`) hata döner.
pub fn normalize_ucli_services(raw: Option<&Json>) -> Result<Vec<Json>, SettingsTypeError> {
    let defaults = default_ucli_services();
    let rows = match raw {
        Some(Json::Array(a)) if !a.is_empty() => a,
        _ => return Ok(defaults.to_vec()),
    };
    let mut out: Vec<Json> = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for (idx, r) in rows.iter().enumerate() {
        let Some(m) = r.as_object() else { continue };
        let field = |k: &str| py::str_or_empty(m.get(k));
        let sid = py::lower(py::strip(&field("id")));
        let env = py::strip(&field("env")).to_string();
        let wire = py::strip(&field("wire")).to_string();
        let ep = py::strip(&field("endpoint"))
            .trim_end_matches('/')
            .to_string();
        let id_ok = {
            let b = sid.as_bytes();
            (2..=20).contains(&b.len())
                && b[0].is_ascii_lowercase()
                && b[1..].iter().all(|c| {
                    c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-'
                })
        };
        let env_ok = {
            let b = env.as_bytes();
            (3..=40).contains(&b.len())
                && b[0].is_ascii_uppercase()
                && b[1..]
                    .iter()
                    .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || *c == b'_')
        };
        if !id_ok
            || seen.contains(&sid)
            || !env_ok
            || !(wire.is_empty() || wire == "anthropic-messages")
        {
            continue;
        }
        if !ep.is_empty() {
            // ^https?://[^\s]+$
            let rest = ep
                .strip_prefix("https://")
                .or_else(|| ep.strip_prefix("http://"));
            if !rest.is_some_and(|r| !r.is_empty() && !r.chars().any(py::is_space)) {
                continue;
            }
        }
        if ep.is_empty() && sid != "evren" {
            continue;
        }
        let items: Vec<String> = match m.get("models") {
            Some(Json::Str(s)) => s.replace('\n', ",").split(',').map(String::from).collect(),
            Some(Json::Array(a)) => a.iter().map(py::str_of).collect(),
            Some(Json::Object(o)) => o.keys().cloned().collect(),
            Some(v) if v.truthy() => {
                return Err(SettingsTypeError {
                    field: format!("ucli_services[{idx}].models"),
                    python: "TypeError",
                })
            }
            _ => Vec::new(),
        };
        let mut models: Vec<String> = Vec::new();
        for it in items {
            let s = py::strip(&it);
            if s.is_empty() {
                continue;
            }
            let s = py::prefix_chars(s, 80).to_string();
            if !models.contains(&s) {
                models.push(s);
            }
        }
        models.truncate(60);
        let mut efforts = Map::new();
        if let Some(Json::Object(eff)) = m.get("efforts") {
            for (ek, ev) in eff.iter().take(20) {
                let ek = py::prefix_chars(&py::lower(py::strip(ek)), 40).to_string();
                let Some(list) = ev.as_array() else { continue };
                if ek.is_empty() {
                    continue;
                }
                let mut vals: Vec<String> = Vec::new();
                for v in list {
                    let s = py::strip(&py::str_of(v)).to_string();
                    if !vals.contains(&s) {
                        vals.push(s);
                    }
                }
                let levels = vals
                    .into_iter()
                    .filter(|x| UCLI_REASONING_LEVELS.contains(&x.as_str()))
                    .map(Json::from)
                    .collect();
                efforts.insert(ek, Json::Array(levels));
            }
        }
        let label = py::strip(&field("label")).to_string();
        let label = py::prefix_chars(if label.is_empty() { &sid } else { &label }, 40).to_string();
        let mut o = Map::new();
        o.insert("id".into(), sid.as_str().into());
        o.insert("label".into(), label.into());
        o.insert("wire".into(), wire.into());
        o.insert("endpoint".into(), ep.into());
        o.insert("env".into(), env.into());
        o.insert(
            "models".into(),
            Json::Array(models.into_iter().map(Json::from).collect()),
        );
        o.insert("efforts".into(), Json::Object(efforts));
        seen.push(sid);
        out.push(Json::Object(o));
    }
    if !seen.iter().any(|s| s == "evren") {
        out.insert(0, defaults[0].clone());
    }
    Ok(out)
}

impl Settings {
    fn block(&self, key: &str) -> Option<&Json> {
        self.get(key).filter(|b| b.as_object().is_some())
    }

    /// `settings[block][cli]` seçimi `choices` içindeyse o (Python `(x.get(cli) or "") in choices`: dize olmayan doğru
    /// değer hiçbir seçeneğe eşit değil).
    fn chosen_override(&self, block: &str, cli: &str, choices: &[String]) -> Option<String> {
        let v = match self.block(block).and_then(|b| b.get(cli)) {
            Some(Json::Str(s)) => s.as_str(),
            Some(v) if v.truthy() => return None,
            _ => "",
        };
        choices.iter().any(|c| c == v).then(|| v.to_string())
    }

    /// `default_model_for(provider)`: ayardaki `default_model[cli]` (listede geçerliyse) > `preferred` (listedeyse) >
    /// listenin ilki > `""`. `choices` = `model_choices()`, `preferred` = `preferred_default_model()`.
    pub fn default_model_for(
        &self,
        cli: &str,
        choices: &[String],
        preferred: Option<&str>,
    ) -> String {
        if let Some(m) = self.chosen_override("default_model", cli, choices) {
            return m;
        }
        match preferred.filter(|p| choices.iter().any(|c| c == p)) {
            Some(p) => p.to_string(),
            None => choices.first().cloned().unwrap_or_default(),
        }
    }

    /// `default_effort_for(provider)`: ayardaki `default_effort[cli]` (`levels` içindeyse), yoksa `provider_default`
    /// (`default_effort()`).
    pub fn default_effort_for(
        &self,
        cli: &str,
        levels: &[String],
        provider_default: &str,
    ) -> String {
        self.chosen_override("default_effort", cli, levels)
            .unwrap_or_else(|| provider_default.to_string())
    }

    /// `resolved_model_for(provider, stored)`: `stored` boşsa [`Self::default_model_for`], doluysa `refresh`
    /// (`refresh_stored_model`; genel varsayılan ayarı karışmaz).
    pub fn resolved_model_for(
        &self,
        cli: &str,
        stored: &str,
        choices: &[String],
        preferred: Option<&str>,
        refresh: impl FnOnce(&str) -> String,
    ) -> String {
        if stored.is_empty() {
            self.default_model_for(cli, choices, preferred)
        } else {
            refresh(stored)
        }
    }

    /// `resolved_binary(cli)`: `provider_bin[cli]` (çalıştırılabilirse) > `shutil.which` > bilinen konumlar > çıplak ad.
    /// `provider_bin[cli]` dize değilse Python `AttributeError` fırlatır: burada hata.
    pub fn resolved_binary(&self, cli: &str, env: &SysEnv) -> Result<String, SettingsTypeError> {
        let over = match self.block("provider_bin").and_then(|b| b.get(cli)) {
            None => String::new(),
            Some(Json::Str(s)) => py::strip(s).to_string(),
            Some(_) => {
                return Err(SettingsTypeError {
                    field: format!("provider_bin.{cli}"),
                    python: "AttributeError",
                })
            }
        };
        if !over.is_empty() {
            let p = env.expand(&over);
            if is_executable_file(&p) {
                return Ok(p);
            }
        }
        if let Some(found) = which(cli, env.path.as_ref()) {
            return Ok(found);
        }
        for cand in known_binary_paths(cli) {
            let p = env.expand(cand);
            if is_executable_file(&p) {
                return Ok(p);
            }
        }
        Ok(cli.to_string())
    }

    /// `byok_env_for(cli)`: `{str(k): str(v)}` (yalnız doğru değerli `v`). SIR taşır: loglama.
    pub fn byok_env_for(&self, cli: &str) -> IndexMap<String, String> {
        match self.block("byok").and_then(|b| b.get(cli)) {
            Some(Json::Object(m)) => m
                .iter()
                .filter(|(_, v)| v.truthy())
                .map(|(k, v)| (k.clone(), py::str_of(v)))
                .collect(),
            _ => IndexMap::new(),
        }
    }

    /// `ucli_limit_overrides`: pozitif tam sayıya çevrilebilen alanlar.
    pub fn ucli_limit_overrides(&self) -> IndexMap<&'static str, PyInt> {
        let raw = self.block("ucli_limits");
        UCLI_LIMIT_KEYS
            .iter()
            .filter_map(|k| {
                let text = py::str_opt(raw.and_then(|b| b.get(k)));
                py::parse_int(py::strip(&text))
                    .filter(PyInt::is_positive)
                    .map(|n| (*k, n))
            })
            .collect()
    }

    /// `ucli_usage_warn_thresholds`: (amber, kırmızı); 0 = kapalı.
    pub fn ucli_usage_warn_thresholds(&self) -> (PyInt, PyInt) {
        let raw = self.block("ucli_usage_warn");
        let one = |key: &str, default: i64| {
            let text = match raw.and_then(|b| b.get(key)) {
                None | Some(Json::Null) => String::new(),
                Some(v) => py::str_of(v),
            };
            let text = py::lower(py::strip(&text)).replace(['_', ','], "");
            if OFF_WORDS.contains(&text.as_str()) {
                return PyInt::from_i64(0);
            }
            py::parse_int(&text)
                .filter(PyInt::is_positive)
                .unwrap_or_else(|| PyInt::from_i64(default))
        };
        (
            one("amber", USAGE_WARN_DEFAULTS.0),
            one("red", USAGE_WARN_DEFAULTS.1),
        )
    }

    /// `ucli_reasoning_mode`: "auto" | "off" | low/medium/high/max.
    pub fn ucli_reasoning_mode(&self) -> String {
        let v = word(self.block("ucli_limits"), "reasoning_effort");
        if OFF_WORDS.contains(&v.as_str()) {
            "off".into()
        } else if UCLI_REASONING_LEVELS.contains(&v.as_str()) {
            v
        } else {
            "auto".into()
        }
    }

    /// Açma sözcüğü true, kapatma sözcüğü false, diğerleri varsayılan (iki küme ayrık: sıra önemsiz).
    fn ucli_flag(&self, key: &str, default: bool) -> bool {
        let v = word(self.block("ucli_limits"), key);
        if OFF_WORDS.contains(&v.as_str()) {
            false
        } else if ON_WORDS.contains(&v.as_str()) {
            true
        } else {
            default
        }
    }
    /// `ucli_stream_enabled`.
    pub fn ucli_stream_enabled(&self) -> bool {
        self.ucli_flag("stream", UCLI_STREAM_DEFAULT)
    }
    /// `ucli_show_reasoning_enabled`.
    pub fn ucli_show_reasoning_enabled(&self) -> bool {
        self.ucli_flag("show_reasoning", UCLI_SHOW_REASONING_DEFAULT)
    }
    /// `ucli_state_dir_enabled`.
    pub fn ucli_state_dir_enabled(&self) -> bool {
        self.ucli_flag("state_dir", UCLI_STATE_DIR_DEFAULT)
    }

    /// `ucli_services`.
    pub fn ucli_services(&self) -> Result<Vec<Json>, SettingsTypeError> {
        normalize_ucli_services(self.get("ucli_services"))
    }

    /// `ucli_cost_config`.
    pub fn ucli_cost_config(&self) -> UcliCost {
        let raw = self.block("ucli_cost");
        let ttl = word(raw, "cache_ttl");
        let date = |k: &str| {
            let v = py::strip(&py::str_or_empty(raw.and_then(|b| b.get(k)))).to_string();
            if date_like(&v) {
                v
            } else {
                String::new()
            }
        };
        UcliCost {
            daily_cap_usd: positive_float(raw.and_then(|b| b.get("daily_cap_usd"))),
            cache_ttl: if ttl == "5m" || ttl == "1h" {
                ttl
            } else {
                "1h".into()
            },
            credit_total_usd: positive_float(raw.and_then(|b| b.get("credit_total_usd"))),
            credit_since: date("credit_since"),
            credit_until: date("credit_until"),
        }
    }

    /// `ucli_script_mode`: "read" | "full" | "" (kapalı).
    pub fn ucli_script_mode(&self) -> String {
        let v = word(self.block("ucli_script"), "mode");
        if v == "read" || v == "full" {
            v
        } else {
            String::new()
        }
    }

    /// `ucli_endpoint`: geçerli http(s) adresi (sondaki `/` atılmış) ya da "".
    pub fn ucli_endpoint(&self) -> String {
        let url = py::str_or_empty(self.get("ucli_endpoint"));
        let url = py::strip(&url).trim_end_matches('/');
        if !url.is_empty() && valid_http_url(url) {
            url.into()
        } else {
            String::new()
        }
    }

    /// `ucli_web_config`: yalnız geçerli parçalar (Python sözlüğüyle aynı anahtar sırası).
    pub fn ucli_web_config(&self) -> Json {
        let raw = self.block("ucli_web");
        let get = |k: &str| raw.and_then(|b| b.get(k));
        let mut out = Map::new();
        let url = py::strip(&py::str_or_empty(get("search_url"))).to_string();
        let flavor = word(raw, "search_flavor");
        let flavor = if flavor.is_empty() {
            "searxng".to_string()
        } else {
            flavor
        };
        if !url.is_empty() && flavor == "searxng" && valid_http_url(&url) {
            out.insert("search_url".into(), url.into());
            out.insert("search_flavor".into(), "searxng".into());
        } else if url.is_empty() {
            let mode = match get("search_docker") {
                None | Some(Json::Null) => String::new(),
                Some(v) => py::str_of(v),
            };
            if !OFF_WORDS.contains(&py::lower(py::strip(&mode)).as_str()) {
                out.insert("search_docker".into(), true.into());
            }
        }
        let text = match get("allow_fetch_domains") {
            Some(Json::Array(a)) => a.iter().map(py::str_of).collect::<Vec<_>>().join(","),
            other => py::str_or_empty(other),
        };
        let mut domains: Vec<String> = Vec::new();
        for tok in py::lower(&text).split(|c: char| c == ',' || py::is_space(c)) {
            if valid_host(tok) && !domains.iter().any(|d| d == tok) {
                domains.push(tok.to_string());
                if domains.len() >= MAX_FETCH_DOMAINS {
                    break;
                }
            }
        }
        if !domains.is_empty() {
            out.insert(
                "allow_fetch_domains".into(),
                Json::Array(domains.into_iter().map(Json::from).collect()),
            );
        }
        Json::Object(out)
    }

    /// `_daemon_config(key, default_dir)`.
    pub fn daemon_config(&self, key: &str, default_dir: &str, env: &SysEnv) -> DaemonConfig {
        let raw = self.block(key);
        let get = |k: &str| raw.and_then(|b| b.get(k));
        let mut out = DaemonConfig {
            dir: String::new(),
            bin: String::new(),
            port: None,
        };
        let d = py::strip(&py::str_or_empty(get("dir"))).to_string();
        let d = env.expand(if d.is_empty() { default_dir } else { &d });
        if std::fs::metadata(py_join(&d, "Cargo.toml")).is_ok_and(|m| m.is_file()) {
            out.dir = d;
        }
        let b = env.expand(py::strip(&py::str_or_empty(get("bin"))));
        if !b.is_empty() && is_executable_file(&b) {
            out.bin = b;
        }
        let port = py::strip(&py::str_or_empty(get("port"))).to_string();
        out.port = py::parse_int(&port)
            .and_then(|n| n.as_i64())
            .filter(|n| (1024..=65535).contains(n))
            .and_then(|n| u16::try_from(n).ok());
        out
    }
    /// `uzakgoz_config`.
    pub fn uzakgoz_config(&self, env: &SysEnv) -> DaemonConfig {
        self.daemon_config("uzakgoz", UZAKGOZ_DEFAULT_DIR, env)
    }
    /// `derbent_config`.
    pub fn derbent_config(&self, env: &SysEnv) -> DaemonConfig {
        self.daemon_config("derbent", DERBENT_DEFAULT_DIR, env)
    }

    /// `reader_config`: içinde `index.html` olan dizin (gerçek yol) ya da "".
    pub fn reader_config(&self, env: &SysEnv) -> String {
        let d = env.expand(py::strip(&py::str_or_empty(
            self.block("reader").and_then(|b| b.get("dir")),
        )));
        if d.is_empty() {
            return String::new();
        }
        let d = realpath(Path::new(&d)).to_string_lossy().into_owned();
        if std::fs::metadata(py_join(&d, "index.html")).is_ok_and(|m| m.is_file()) {
            d
        } else {
            String::new()
        }
    }
}

/// `os.path.join(a, b)` (posix, `b` göreli).
fn py_join(a: &str, b: &str) -> String {
    if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_parse() {
        assert_eq!(
            default_ucli_services()[0].get("id"),
            Some(&Json::from("evren"))
        );
    }

    #[test]
    fn url_rules() {
        for ok in [
            "http://a",
            "HTTPS://Ex.com:443/x?y#z",
            "http://u:p@h:0",
            "http://[::1]:80",
            "http://[fe80::1%eth0]",
        ] {
            assert!(valid_http_url(ok), "{ok}");
        }
        for bad in [
            "",
            "ftp://a",
            "http://",
            "http://a:x",
            "http://a:99999",
            "http://[1.2.3.4]",
            "http://[::1",
            "http://a b",
            "http://ａ／b",
        ] {
            assert!(!valid_http_url(bad), "{bad}");
        }
    }
}
