//! `settings.json`ın bu crate'i ilgilendiren alanları (`py/claudeops/settings.py` okuma tarafı). Dosyayı okumak
//! çağıranın işi (cops-state); burada yalnız ayrıştırılmış nesne yorumlanır. Bozuk değer asla hata vermez.

use crate::pyfmt::{parse_float, parse_int, str_of, str_or_empty, strip, truthy};
use regex::Regex;
use serde_json::{Map, Value};
use std::sync::LazyLock;

const OFF_WORDS: [&str; 11] =
    ["off", "0", "false", "no", "n", "hayir", "hayır", "kapali", "kapalı", "disabled", "none"];
const ON_WORDS: [&str; 9] = ["on", "1", "true", "yes", "y", "evet", "acik", "açık", "enabled"];
const REASONING_LEVELS: [&str; 4] = ["low", "medium", "high", "max"];
const MAX_FETCH_DOMAINS: usize = 64;
/// `ucli_max_session_usd` boş/bozukken.
pub const DEFAULT_MAX_SESSION_USD: f64 = 8.0;

pub(crate) fn is_off(word: &str) -> bool {
    OFF_WORDS.contains(&word)
}

/// Ayrıştırılmış `settings.json` nesnesi (dosya yok/bozuksa boş).
#[derive(Debug, Clone, Default)]
pub struct Settings(Map<String, Value>);

/// Güvenli ortam değişkeni adı (`[A-Z_][A-Z0-9_]*`, tam eşleşme).
pub fn is_safe_env_name(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && (b[0] == b'_' || b[0].is_ascii_uppercase())
        && b.iter().all(|c| *c == b'_' || c.is_ascii_uppercase() || c.is_ascii_digit())
}

/// ucli model hizmeti (`ucli_services` girdisi).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UcliService {
    pub id: String,
    /// ucli `--provider` değeri; "" = varsayılan chat-completions.
    pub wire: String,
    /// "" = ayardaki Evren uç noktası.
    pub endpoint: String,
    pub env: String,
    /// model kimliğinde geçen parça -> geçerli effort seviyeleri.
    pub efforts: Vec<(String, Vec<String>)>,
}

fn builtin_services() -> Vec<UcliService> {
    let s = |id: &str, wire: &str, endpoint: &str, env: &str| UcliService {
        id: id.into(),
        wire: wire.into(),
        endpoint: endpoint.into(),
        env: env.into(),
        efforts: Vec::new(),
    };
    let mut claude = s("claude", "anthropic-messages", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY");
    let lv = |l: &[&str]| l.iter().map(|x| x.to_string()).collect::<Vec<_>>();
    claude.efforts = vec![
        ("haiku".into(), lv(&[])),
        ("sonnet".into(), lv(&["low", "medium", "high"])),
        ("opus".into(), lv(&["low", "medium", "high", "max"])),
        ("fable".into(), lv(&["low", "medium", "high", "max"])),
    ];
    vec![
        s("evren", "", "", "UCLI_API_KEY"),
        claude,
        s("grok", "", "https://api.x.ai/v1", "XAI_API_KEY"),
        s("openrouter", "", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        s("groq", "", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ]
}

/// `ucli_web` yorumu.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UcliWeb {
    pub search_url: Option<String>,
    pub search_docker: bool,
    pub allow_fetch_domains: Vec<String>,
}

static SVC_ID: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_-]{1,19}$").unwrap());
static SVC_ENV: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Z][A-Z0-9_]{2,39}$").unwrap());
static SVC_EP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^https?://[^\s]+$").unwrap());
static HOST: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$").unwrap()
});

fn take_chars(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// `_valid_http_url`: http(s) + host adı, boşluk/denetim karakteri yok, port sayısal ve 0-65535.
pub fn valid_http_url(url: &str) -> bool {
    if url.is_empty() || url.chars().any(|c| c.is_whitespace() || (c as u32) < 32 || c as u32 == 127) {
        return false;
    }
    let Some((scheme, rest)) = url.split_once("://") else { return false };
    if !(scheme.eq_ignore_ascii_case("http") || scheme.eq_ignore_ascii_case("https")) {
        return false;
    }
    let netloc = rest.split(['/', '?', '#']).next().unwrap_or("");
    let hostport = netloc.rsplit_once('@').map_or(netloc, |(_, h)| h);
    let (host, port) = if let Some(r) = hostport.strip_prefix('[') {
        match r.split_once(']') {
            Some((h, after)) => (h, after.split_once(':').map_or("", |(_, p)| p)),
            None => return false,
        }
    } else if netloc.contains(['[', ']']) {
        return false;
    } else {
        hostport.split_once(':').unwrap_or((hostport, ""))
    };
    let port_ok = port.is_empty() || (port.bytes().all(|b| b.is_ascii_digit()) && port.parse::<u16>().is_ok());
    !host.is_empty() && port_ok
}

impl Settings {
    pub fn new(map: Map<String, Value>) -> Self {
        Settings(map)
    }

    pub fn from_json(text: &str) -> Self {
        match serde_json::from_str::<Value>(text) {
            Ok(Value::Object(m)) => Settings(m),
            _ => Settings::default(),
        }
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.0.get(key)
    }

    fn block(&self, key: &str) -> Option<&Map<String, Value>> {
        self.0.get(key).and_then(Value::as_object)
    }

    fn block_word(&self, key: &str, field: &str) -> String {
        strip(&str_or_empty(self.block(key).and_then(|b| b.get(field)))).to_lowercase()
    }

    fn block_toggle(&self, field: &str, default: bool) -> bool {
        let w = self.block_word("ucli_limits", field);
        if is_off(&w) {
            false
        } else if ON_WORDS.contains(&w.as_str()) {
            true
        } else {
            default
        }
    }

    /// `default_model[cli]` / `default_effort[cli]`.
    pub fn per_cli(&self, key: &str, cli: &str) -> String {
        self.block(key).and_then(|b| b.get(cli)).and_then(Value::as_str).unwrap_or("").to_string()
    }

    /// `provider_bin[cli]`, kırpılmış.
    pub fn provider_bin(&self, cli: &str) -> String {
        strip(&self.per_cli("provider_bin", cli)).to_string()
    }

    /// `byok[cli]`: boş olmayan değerler, `str()`e zorlanmış.
    pub fn byok_env(&self, cli: &str) -> Vec<(String, String)> {
        self.block("byok")
            .and_then(|b| b.get(cli))
            .and_then(Value::as_object)
            .map(|m| m.iter().filter(|(_, v)| truthy(v)).map(|(k, v)| (k.clone(), str_of(v))).collect())
            .unwrap_or_default()
    }

    pub fn byok_value(&self, cli: &str, env: &str) -> String {
        let v = self.byok_env(cli).into_iter().find(|(k, _)| k == env).map(|(_, v)| v).unwrap_or_default();
        strip(&v).to_string()
    }

    /// `ucli_limits` içindeki geçerli (pozitif tam sayı) sayısal override'lar.
    pub fn ucli_limit_overrides(&self) -> Vec<(&'static str, i64)> {
        ["max_steps", "max_context_kib", "max_tool_calls", "max_output_tokens", "request_timeout_secs", "max_history_kib"]
            .into_iter()
            .filter_map(|k| {
                let v = self.block("ucli_limits")?.get(k)?;
                parse_int(&str_of(v)).filter(|n| *n > 0).map(|n| (k, n))
            })
            .collect()
    }

    pub fn ucli_reasoning_mode(&self) -> String {
        let w = self.block_word("ucli_limits", "reasoning_effort");
        if is_off(&w) {
            "off".into()
        } else if REASONING_LEVELS.contains(&w.as_str()) {
            w
        } else {
            "auto".into()
        }
    }

    pub fn ucli_stream(&self) -> bool {
        self.block_toggle("stream", true)
    }

    pub fn ucli_show_reasoning(&self) -> bool {
        self.block_toggle("show_reasoning", false)
    }

    pub fn ucli_state_dir(&self) -> bool {
        self.block_toggle("state_dir", false)
    }

    pub fn ucli_script_mode(&self) -> String {
        let w = self.block_word("ucli_script", "mode");
        if w == "read" || w == "full" {
            w
        } else {
            String::new()
        }
    }

    /// Geçerli `ucli_endpoint` (sondaki `/` atılmış) ya da "".
    pub fn ucli_endpoint(&self) -> String {
        let raw = str_or_empty(self.get("ucli_endpoint"));
        let url = strip(&raw).trim_end_matches('/');
        if !url.is_empty() && valid_http_url(url) {
            url.to_string()
        } else {
            String::new()
        }
    }

    pub fn ucli_web(&self) -> UcliWeb {
        let empty = Map::new();
        let raw = self.block("ucli_web").unwrap_or(&empty);
        let mut out = UcliWeb::default();
        let url = strip(&str_or_empty(raw.get("search_url"))).to_string();
        let mut flavor = strip(&str_or_empty(raw.get("search_flavor"))).to_lowercase();
        if flavor.is_empty() {
            flavor = "searxng".into();
        }
        if !url.is_empty() && flavor == "searxng" && valid_http_url(&url) {
            out.search_url = Some(url);
        } else if url.is_empty() {
            let mode = match raw.get("search_docker") {
                None | Some(Value::Null) => String::new(),
                Some(v) => str_of(v),
            };
            out.search_docker = !is_off(&strip(&mode).to_lowercase());
        }
        let text = match raw.get("allow_fetch_domains") {
            Some(Value::Array(a)) => a.iter().map(str_of).collect::<Vec<_>>().join(","),
            v => str_or_empty(v),
        };
        for tok in text.to_lowercase().split(|c: char| c == ',' || c.is_whitespace()) {
            if !tok.is_empty() && tok.len() <= 253 && HOST.is_match(tok) && !out.allow_fetch_domains.iter().any(|d| d == tok)
            {
                out.allow_fetch_domains.push(tok.to_string());
                if out.allow_fetch_domains.len() >= MAX_FETCH_DOMAINS {
                    break;
                }
            }
        }
        out
    }

    /// `normalize_ucli_services`: geçersiz girdiler atılır, `evren` her zaman vardır.
    pub fn ucli_services(&self) -> Vec<UcliService> {
        let Some(raw) = self.get("ucli_services").and_then(Value::as_array).filter(|a| !a.is_empty()) else {
            return builtin_services();
        };
        let mut out: Vec<UcliService> = Vec::new();
        for r in raw.iter().filter_map(Value::as_object) {
            let id = strip(&str_or_empty(r.get("id"))).to_lowercase();
            let env = strip(&str_or_empty(r.get("env"))).to_string();
            let wire = strip(&str_or_empty(r.get("wire"))).to_string();
            let ep = strip(&str_or_empty(r.get("endpoint"))).trim_end_matches('/').to_string();
            if !SVC_ID.is_match(&id)
                || out.iter().any(|s| s.id == id)
                || !SVC_ENV.is_match(&env)
                || !(wire.is_empty() || wire == "anthropic-messages")
                || (!ep.is_empty() && !SVC_EP.is_match(&ep))
                || (ep.is_empty() && id != "evren")
            {
                continue;
            }
            let mut efforts = Vec::new();
            if let Some(eff) = r.get("efforts").and_then(Value::as_object) {
                for (k, v) in eff.iter().take(20) {
                    let key = take_chars(&strip(k).to_lowercase(), 40);
                    let Some(list) = v.as_array() else { continue };
                    if key.is_empty() {
                        continue;
                    }
                    let mut levels: Vec<String> = Vec::new();
                    for item in list {
                        let s = strip(&str_of(item)).to_string();
                        if REASONING_LEVELS.contains(&s.as_str()) && !levels.contains(&s) {
                            levels.push(s);
                        }
                    }
                    efforts.retain(|(k2, _)| k2 != &key);
                    efforts.push((key, levels));
                }
            }
            out.push(UcliService { id, wire, endpoint: ep, env, efforts });
        }
        if !out.iter().any(|s| s.id == "evren") {
            out.insert(0, builtin_services().remove(0));
        }
        out
    }

    /// `ucli_cost.cache_ttl` (`5m` | `1h`, varsayılan `1h`).
    pub fn ucli_cache_ttl(&self) -> &'static str {
        if self.block_word("ucli_cost", "cache_ttl") == "5m" {
            "5m"
        } else {
            "1h"
        }
    }

    /// `ucli_max_session_usd`: boş/bozuk = 8, 0 = tavan yok.
    pub fn default_max_session_usd(&self) -> f64 {
        let raw = match self.get("ucli_max_session_usd") {
            None | Some(Value::Null) => return DEFAULT_MAX_SESSION_USD,
            Some(v) => str_of(v),
        };
        if raw.is_empty() {
            return DEFAULT_MAX_SESSION_USD;
        }
        match parse_float(&raw.replace(',', ".")) {
            Some(v) if v.is_finite() && v >= 0.0 => v,
            _ => DEFAULT_MAX_SESSION_USD,
        }
    }

    pub fn ucli_metrics_enabled(&self) -> bool {
        match self.block("ucli_metrics").and_then(|b| b.get("enabled")) {
            None => true,
            Some(Value::String(s)) => !["off", "false", "0", "no", "hayır"].contains(&strip(s).to_lowercase().as_str()),
            Some(v) => truthy(v),
        }
    }

    pub fn ucli_agents_enabled(&self) -> bool {
        let w = match self.get("ucli_agents") {
            None | Some(Value::Null) => String::new(),
            Some(v) => strip(&str_of(v)).to_lowercase(),
        };
        !is_off(if w.is_empty() { "on" } else { &w })
    }

    pub fn routing_guidance_enabled(&self) -> bool {
        match self.get("routing_guidance") {
            None | Some(Value::Null) => true,
            Some(v) => !is_off(&strip(&str_of(v)).to_lowercase()),
        }
    }

    /// Doluysa paketlenmiş yönergenin yerine geçen metin (kırpılmış).
    pub fn routing_guidance_text(&self) -> String {
        strip(&str_or_empty(self.get("routing_guidance_text"))).to_string()
    }

    /// `spawn_nice` (anahtar yoksa 10); 1-19 dışı / kapalı = None.
    pub fn spawn_nice(&self) -> Option<i64> {
        let raw = self.get("spawn_nice").map_or_else(|| "10".to_string(), str_of);
        let raw = strip(&raw).to_lowercase();
        if ["", "off", "0", "no", "false"].contains(&raw.as_str()) {
            return None;
        }
        parse_int(&raw).filter(|n| (1..=19).contains(n))
    }
}
