//! `settings.json`ın bu crate'i ilgilendiren alanları (`py/claudeops/settings.py` okuma tarafı). Dosyayı okumak
//! çağıranın işi (cops-state); burada yalnız ayrıştırılmış nesne yorumlanır. Bozuk değer asla hata vermez.

use crate::ojson::OValue;
use crate::pyfmt::{
    decimal_value, parse_float, parse_int, py_float, str_of, str_or_empty, strip, truthy,
};
use regex::Regex;
use serde_json::{Map, Value};
use std::sync::LazyLock;

const OFF_WORDS: [&str; 11] = [
    "off", "0", "false", "no", "n", "hayir", "hayır", "kapali", "kapalı", "disabled", "none",
];
const AGENTS_OFF_WORDS: [&str; 8] = [
    "off", "0", "false", "no", "none", "disabled", "kapali", "kapalı",
];
const ON_WORDS: [&str; 9] = [
    "on", "1", "true", "yes", "y", "evet", "acik", "açık", "enabled",
];
const REASONING_LEVELS: [&str; 4] = ["low", "medium", "high", "max"];
const MAX_FETCH_DOMAINS: usize = 64;
/// `ucli_max_session_usd` boş/bozukken.
pub const DEFAULT_MAX_SESSION_USD: f64 = 8.0;

pub(crate) fn is_off(word: &str) -> bool {
    OFF_WORDS.contains(&word)
}

/// Ayrıştırılmış `settings.json` nesnesi (dosya yok/bozuksa boş).
#[derive(Debug, Clone)]
pub struct Settings {
    map: Map<String, Value>,
    /// Aynı belge, dosyadaki anahtar sırasıyla (Python `dict`); sıranın anlamlı olduğu okuyucular kullanır.
    ord: OValue,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            map: Map::new(),
            ord: OValue::Object(Vec::new()),
        }
    }
}

/// Güvenli ortam değişkeni adı (`[A-Z_][A-Z0-9_]*`, tam eşleşme).
pub fn is_safe_env_name(name: &str) -> bool {
    let b = name.as_bytes();
    !b.is_empty()
        && (b[0] == b'_' || b[0].is_ascii_uppercase())
        && b.iter()
            .all(|c| *c == b'_' || c.is_ascii_uppercase() || c.is_ascii_digit())
}

/// ucli model hizmeti (`ucli_services` girdisi).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UcliService {
    pub id: String,
    /// Panelde gösterilen ad (boşsa `id`, en çok 40 karakter).
    pub label: String,
    /// ucli `--provider` değeri; "" = varsayılan chat-completions.
    pub wire: String,
    /// "" = ayardaki Evren uç noktası.
    pub endpoint: String,
    pub env: String,
    /// Elle girilmiş model listesi (tekrarsız, her biri en çok 80 karakter, en çok 60 model).
    pub models: Vec<String>,
    /// model kimliğinde geçen parça -> geçerli effort seviyeleri.
    pub efforts: Vec<(String, Vec<String>)>,
}

fn builtin_services() -> Vec<UcliService> {
    let s = |id: &str, label: &str, wire: &str, endpoint: &str, env: &str| UcliService {
        id: id.into(),
        label: label.into(),
        wire: wire.into(),
        endpoint: endpoint.into(),
        env: env.into(),
        models: Vec::new(),
        efforts: Vec::new(),
    };
    let mut claude = s(
        "claude",
        "Claude (Anthropic)",
        "anthropic-messages",
        "https://api.anthropic.com/v1",
        "ANTHROPIC_API_KEY",
    );
    let lv = |l: &[&str]| l.iter().map(|x| x.to_string()).collect::<Vec<_>>();
    claude.models = lv(&[
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
    ]);
    claude.efforts = vec![
        ("haiku".into(), lv(&[])),
        ("sonnet".into(), lv(&["low", "medium", "high"])),
        ("opus".into(), lv(&["low", "medium", "high", "max"])),
        ("fable".into(), lv(&["low", "medium", "high", "max"])),
    ];
    vec![
        s("evren", "Evren", "", "", "UCLI_API_KEY"),
        claude,
        s(
            "grok",
            "Grok (xAI)",
            "",
            "https://api.x.ai/v1",
            "XAI_API_KEY",
        ),
        s(
            "openrouter",
            "OpenRouter",
            "",
            "https://openrouter.ai/api/v1",
            "OPENROUTER_API_KEY",
        ),
        s(
            "groq",
            "Groq (groq.com)",
            "",
            "https://api.groq.com/openai/v1",
            "GROQ_API_KEY",
        ),
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
// Python `\\s` (str) `\\x1c-\\x1f`i de kapsar.
static SVC_EP: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^https?://[^\s\x1c-\x1f]+$").unwrap());
static HOST: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
        .unwrap()
});

fn take_chars(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// `normalize_ucli_services` `models` alanı: dize ise `\n` ve `,` ile bölünür; liste ögeleri (sözlükte anahtarlar)
/// `str()` + `strip()`, boşlar atılır, en çok 80 karakter, ilk görülen sırayla tekrarsız, en çok 60.
/// Liste ya da metin olmayan değer (elle düzenlenmiş sayı/sözlük) yok sayılır (TBD#374 S8).
fn service_models(raw: Option<&OValue>) -> Vec<String> {
    let items: Vec<String> = match raw {
        Some(OValue::String(s)) => s.replace('\n', ",").split(',').map(String::from).collect(),
        Some(OValue::Array(a)) => a.iter().map(|v| str_of(&v.to_value())).collect(),
        _ => Vec::new(),
    };
    let mut out: Vec<String> = Vec::new();
    for it in items {
        let s = strip(&it);
        if s.is_empty() {
            continue;
        }
        let s = take_chars(s, 80);
        if !out.contains(&s) {
            out.push(s);
        }
    }
    out.truncate(60);
    out
}

/// `ucli_cost` ayarının yorumu (`settings.ucli_cost_config`).
#[derive(Debug, Clone, PartialEq)]
pub struct UcliCostConfig {
    /// 0 = tavan yok.
    pub daily_cap_usd: f64,
    /// `5m` | `1h`.
    pub cache_ttl: &'static str,
    /// 0 = toplam kredi gösterilmez.
    pub credit_total_usd: f64,
    /// `YYYY-MM-DD` ya da "".
    pub credit_since: String,
    pub credit_until: String,
}

/// `float(str(v or "0").replace(",", "."))`; bozuk, pozitif olmayan, sonsuz ya da NaN = 0.
fn cost_amount(v: Option<&Value>) -> f64 {
    let s = match v {
        Some(v) if truthy(v) => str_of(v),
        _ => "0".to_string(),
    };
    match parse_float(&s.replace(',', ".")) {
        Some(f) if f > 0.0 && f.is_finite() => f,
        _ => 0.0,
    }
}

/// `re.match(r"^\d{4}-\d{2}-\d{2}$", v)` (Python `\d` = Unicode ondalık rakam; `v` kırpılmış, sondaki `\n` olamaz).
fn is_iso_date(v: &str) -> bool {
    let c: Vec<char> = v.chars().collect();
    c.len() == 10
        && c.iter().enumerate().all(|(i, ch)| {
            if i == 4 || i == 7 {
                *ch == '-'
            } else {
                decimal_value(*ch).is_some()
            }
        })
}

/// `ucli_metrics` ayarının yorumu (`ucli_metrics.get_config`).
#[derive(Debug, Clone, PartialEq)]
pub struct MetricsConfig {
    pub enabled: bool,
    pub interval_s: f64,
    pub retention_days: f64,
}

/// `ucli_metrics.DEFAULTS`.
pub const METRICS_DEFAULTS: MetricsConfig = MetricsConfig {
    enabled: true,
    interval_s: 15.0,
    retention_days: 30.0,
};

/// `ucli_metrics._num`: `float(v)` (olmayan/bozuk = varsayılan), sonra `min(max(f, lo), hi)`. Python `max`/`min`
/// karşılaştırma sırası korunur: NaN SINIRLANMADAN döner (Python davranışı, bkz. parite `metrics-nan`).
fn metrics_num(v: Option<&Value>, default: f64, lo: f64, hi: f64) -> f64 {
    let Some(f) = v.and_then(py_float).filter(|f| !f.is_nan()) else {
        return default; // NaN sınırlanamaz (`max(nan, lo)` = nan): varsayılan
    };
    let f = if lo > f { lo } else { f };
    if hi < f {
        hi
    } else {
        f
    }
}

/// `ucli_metrics.get_config(raw)`: `raw` sözlük değilse varsayılanlar. `enabled` dize ise kırpılıp küçültülür ve
/// `off/false/0/no/hayır` dışındaki her şey açık; dize değilse Python doğruluk değeri (`null` = kapalı).
pub fn metrics_config(raw: &Value) -> MetricsConfig {
    let Some(m) = raw.as_object() else {
        return METRICS_DEFAULTS;
    };
    let enabled = match m.get("enabled") {
        None => METRICS_DEFAULTS.enabled,
        Some(Value::String(s)) => {
            !["off", "false", "0", "no", "hayır"].contains(&strip(s).to_lowercase().as_str())
        }
        Some(v) => truthy(v),
    };
    MetricsConfig {
        enabled,
        interval_s: metrics_num(
            m.get("interval_s"),
            METRICS_DEFAULTS.interval_s,
            1.0,
            3600.0,
        ),
        retention_days: metrics_num(
            m.get("retention_days"),
            METRICS_DEFAULTS.retention_days,
            1.0,
            3650.0,
        ),
    }
}

/// `_valid_http_url` (Python 3.10 `urllib.parse.urlsplit` + `.port` + `.hostname`): http(s) + boş olmayan host adı,
/// boşluk/denetim karakteri yok, köşeli parantezli host geçerli IPv6 (ya da `vX.` IPvFuture), port yalnız ASCII rakam ve
/// 0-65535 (boş port = yok). Python'un ASCII dışı ağ konumu için NFKC denetimi TAŞINMADI.
pub fn valid_http_url(url: &str) -> bool {
    if url.is_empty()
        || url
            .chars()
            .any(|c| crate::pyfmt::py_isspace(c) || (c as u32) < 32 || c as u32 == 127)
    {
        return false;
    }
    let Some(i) = url.find(':') else { return false };
    let scheme = &url[..i];
    let scheme_ok = i > 0
        && scheme
            .chars()
            .next()
            .is_some_and(|c| c.is_ascii_alphabetic())
        && scheme
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c));
    if !scheme_ok || !(scheme.eq_ignore_ascii_case("http") || scheme.eq_ignore_ascii_case("https"))
    {
        return false;
    }
    let Some(rest) = url[i + 1..].strip_prefix("//") else {
        return false;
    };
    let netloc = rest.split(['/', '?', '#']).next().unwrap_or("");
    let (open, close) = (netloc.contains('['), netloc.contains(']'));
    if open != close {
        return false;
    }
    let hostinfo = netloc.rsplit_once('@').map_or(netloc, |(_, h)| h);
    if open {
        let host = match hostinfo.split_once('[') {
            Some((before, bracketed)) => {
                let (host, after) = bracketed.split_once(']').unwrap_or((bracketed, ""));
                if !before.is_empty() || (!after.is_empty() && !after.starts_with(':')) {
                    return false;
                }
                host
            }
            None => hostinfo.split_once(':').map_or(hostinfo, |(h, _)| h),
        };
        if !bracketed_host_ok(host) {
            return false;
        }
    }
    let (host, port) = match hostinfo.split_once('[') {
        Some((_, bracketed)) => {
            let (h, after) = bracketed.split_once(']').unwrap_or((bracketed, ""));
            (h, after.split_once(':').map_or("", |(_, p)| p))
        }
        None => hostinfo.split_once(':').unwrap_or((hostinfo, "")),
    };
    let digits = port.trim_start_matches('0');
    let port_ok = port.is_empty()
        || (port.bytes().all(|b| b.is_ascii_digit())
            && digits.len() <= 5
            && digits.parse::<u32>().unwrap_or(0) <= 65535);
    !host.is_empty() && port_ok
}

/// `urllib.parse._check_bracketed_host`.
fn bracketed_host_ok(h: &str) -> bool {
    if let Some(rest) = h.strip_prefix('v') {
        // `\Av[a-fA-F0-9]+\..+\Z`
        return match rest.split_once('.') {
            Some((hex, tail)) => {
                !hex.is_empty()
                    && hex.chars().all(|c| c.is_ascii_hexdigit())
                    && !tail.is_empty()
                    && !tail.contains('\n')
            }
            None => false,
        };
    }
    // `ipaddress.ip_address`: IPv4 köşeli parantezde reddedilir; IPv6 kapsam kimliği (`%eth0`) kabul edilir.
    let addr = match h.split_once('%') {
        Some((_, sc)) if sc.is_empty() || sc.contains('%') => return false,
        Some((a, _)) => a,
        None => h,
    };
    addr.parse::<std::net::Ipv6Addr>().is_ok()
}

impl Settings {
    /// Ayrıştırılmış nesneden (anahtar sırası bilinmiyor: `Map` sırası kullanılır). Sıra önemliyse [`Settings::from_json`].
    pub fn new(map: Map<String, Value>) -> Self {
        let ord = OValue::from_value(&Value::Object(map.clone()));
        Settings { map, ord }
    }

    /// `settings.json` metni; nesne değilse ya da bozuksa boş (Python `load_settings` toleransı).
    pub fn from_json(text: &str) -> Self {
        match OValue::parse(text) {
            Some(ord @ OValue::Object(_)) => match ord.to_value() {
                Value::Object(map) => Settings { map, ord },
                _ => Settings::default(),
            },
            _ => Settings::default(),
        }
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.map.get(key)
    }

    fn block(&self, key: &str) -> Option<&Map<String, Value>> {
        self.map.get(key).and_then(Value::as_object)
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
        self.block(key)
            .and_then(|b| b.get(cli))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    }

    /// `provider_bin[cli]`, kırpılmış.
    pub fn provider_bin(&self, cli: &str) -> String {
        strip(&self.per_cli("provider_bin", cli)).to_string()
    }

    /// `byok[cli]`: boş olmayan değerler, `str()`e zorlanmış.
    pub fn byok_env(&self, cli: &str) -> Vec<(String, String)> {
        let Some(entries) = self
            .ord
            .get("byok")
            .and_then(|b| b.get(cli))
            .and_then(OValue::entries)
        else {
            return Vec::new();
        };
        entries
            .iter()
            .map(|(k, v)| (k, v.to_value()))
            .filter(|(_, v)| truthy(v))
            .map(|(k, v)| (k.clone(), str_of(&v)))
            .collect()
    }

    pub fn byok_value(&self, cli: &str, env: &str) -> String {
        let v = self
            .byok_env(cli)
            .into_iter()
            .find(|(k, _)| k == env)
            .map(|(_, v)| v)
            .unwrap_or_default();
        strip(&v).to_string()
    }

    /// `ucli_limits` içindeki geçerli (pozitif tam sayı) sayısal override'lar.
    pub fn ucli_limit_overrides(&self) -> Vec<(&'static str, i64)> {
        [
            "max_steps",
            "max_context_kib",
            "max_tool_calls",
            "max_output_tokens",
            "request_timeout_secs",
            "max_history_kib",
        ]
        .into_iter()
        .filter_map(|k| {
            let v = self.block("ucli_limits")?.get(k)?;
            parse_int(strip(&str_of(v)))
                .filter(|n| *n > 0)
                .map(|n| (k, n))
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
        for tok in text
            .to_lowercase()
            .split(|c: char| c == ',' || crate::pyfmt::py_isspace(c))
        {
            if !tok.is_empty()
                && tok.len() <= 253
                && HOST.is_match(tok)
                && !out.allow_fetch_domains.iter().any(|d| d == tok)
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
        let Some(raw) = self
            .ord
            .get("ucli_services")
            .and_then(OValue::as_array)
            .filter(|a| !a.is_empty())
        else {
            return builtin_services();
        };
        let mut out: Vec<UcliService> = Vec::new();
        for ro in raw {
            let Some(entries) = ro.entries() else {
                continue;
            };
            let r: Map<String, Value> = entries
                .iter()
                .map(|(k, v)| (k.clone(), v.to_value()))
                .collect();
            let id = strip(&str_or_empty(r.get("id"))).to_lowercase();
            let env = strip(&str_or_empty(r.get("env"))).to_string();
            let wire = strip(&str_or_empty(r.get("wire"))).to_string();
            let ep = strip(&str_or_empty(r.get("endpoint")))
                .trim_end_matches('/')
                .to_string();
            if !SVC_ID.is_match(&id)
                || out.iter().any(|s| s.id == id)
                || !SVC_ENV.is_match(&env)
                || !(wire.is_empty() || wire == "anthropic-messages")
                || (!ep.is_empty() && !SVC_EP.is_match(&ep))
                || (ep.is_empty() && id != "evren")
            {
                continue;
            }
            let label = take_chars(
                &{
                    let l = strip(&str_or_empty(r.get("label"))).to_string();
                    if l.is_empty() {
                        id.clone()
                    } else {
                        l
                    }
                },
                40,
            );
            let models = service_models(ro.get("models"));
            let mut efforts = Vec::new();
            if let Some(eff) = ro.get("efforts").and_then(OValue::entries) {
                for (k, v) in eff.iter().take(20) {
                    let key = take_chars(&strip(k).to_lowercase(), 40);
                    let Value::Array(list) = v.to_value() else {
                        continue;
                    };
                    if key.is_empty() {
                        continue;
                    }
                    let mut levels: Vec<String> = Vec::new();
                    for item in &list {
                        let s = strip(&str_of(item)).to_string();
                        if REASONING_LEVELS.contains(&s.as_str()) && !levels.contains(&s) {
                            levels.push(s);
                        }
                    }
                    // Python `efforts[ek] = ...`: var olan anahtar YERİNDE güncellenir.
                    match efforts
                        .iter_mut()
                        .find(|(k2, _): &&mut (String, Vec<String>)| *k2 == key)
                    {
                        Some(slot) => slot.1 = levels,
                        None => efforts.push((key, levels)),
                    }
                }
            }
            out.push(UcliService {
                id,
                label,
                wire,
                endpoint: ep,
                env,
                models,
                efforts,
            });
        }
        if !out.iter().any(|s| s.id == "evren") {
            out.insert(0, builtin_services().remove(0));
        }
        out
    }

    /// `ucli_session_opts.effort_levels_for`: hizmet + model için geçerli `--effort` seviyeleri; None = kural yok. Kural =
    /// hizmetin `efforts` tablosunda model kimliğinde (küçük harf) geçen EN UZUN anahtar (eşit uzunlukta tablodaki ilki).
    pub fn ucli_effort_levels_for(&self, service: &str, model: &str) -> Option<Vec<String>> {
        let m = model.to_lowercase();
        let services = self.ucli_services();
        let svc = services.iter().find(|s| s.id == service)?;
        let mut best: Option<&(String, Vec<String>)> = None;
        for e in svc.efforts.iter().filter(|(k, _)| m.contains(k.as_str())) {
            if best.is_none_or(|b| e.0.chars().count() > b.0.chars().count()) {
                best = Some(e);
            }
        }
        best.map(|(_, l)| l.clone())
    }

    /// `ucli_cost.cache_ttl` (`5m` | `1h`, varsayılan `1h`).
    pub fn ucli_cache_ttl(&self) -> &'static str {
        self.ucli_cost_config().cache_ttl
    }

    /// `ucli_cost_config`: blok sözlük değilse hepsi varsayılan (tavan yok, `1h`, kredi yok, tarih yok). Asla hata vermez.
    pub fn ucli_cost_config(&self) -> UcliCostConfig {
        let empty = Map::new();
        let raw = self.block("ucli_cost").unwrap_or(&empty);
        let date = |k: &str| {
            let v = strip(&str_or_empty(raw.get(k))).to_string();
            if is_iso_date(&v) {
                v
            } else {
                String::new()
            }
        };
        UcliCostConfig {
            daily_cap_usd: cost_amount(raw.get("daily_cap_usd")),
            cache_ttl: if self.block_word("ucli_cost", "cache_ttl") == "5m" {
                "5m"
            } else {
                "1h"
            },
            credit_total_usd: cost_amount(raw.get("credit_total_usd")),
            credit_since: date("credit_since"),
            credit_until: date("credit_until"),
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
        match parse_float(&strip(&raw).replace(',', ".")) {
            Some(v) if v.is_finite() && v >= 0.0 => v,
            _ => DEFAULT_MAX_SESSION_USD,
        }
    }

    pub fn ucli_metrics_enabled(&self) -> bool {
        self.ucli_metrics_config().enabled
    }

    /// `ucli_metrics.get_config()` (ayardan; blok sözlük değilse `{}`).
    pub fn ucli_metrics_config(&self) -> MetricsConfig {
        metrics_config(
            self.get("ucli_metrics")
                .filter(|v| v.is_object())
                .unwrap_or(&Value::Object(Map::new())),
        )
    }

    pub fn ucli_agents_enabled(&self) -> bool {
        let w = match self.get("ucli_agents") {
            None | Some(Value::Null) => String::new(),
            Some(v) => strip(&str_of(v)).to_lowercase(),
        };
        // `ucli_agents._OFF_WORDS`: genel listeden FARKLI (`n`, `hayir`, `hayır` yok).
        !AGENTS_OFF_WORDS.contains(&if w.is_empty() { "on" } else { w.as_str() })
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
        let raw = self
            .get("spawn_nice")
            .map_or_else(|| "10".to_string(), str_of);
        let raw = strip(&raw).to_lowercase();
        if ["", "off", "0", "no", "false"].contains(&raw.as_str()) {
            return None;
        }
        parse_int(&raw).filter(|n| (1..=19).contains(n))
    }
}
