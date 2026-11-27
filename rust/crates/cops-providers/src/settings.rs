//! `settings.json`ın bu crate'i ilgilendiren alanları (`py/claudeops/settings.py` okuma tarafı). Dosyayı okumak
//! çağıranın işi; belge rs/state okuyucusuyla ([`cops_state::settings::Settings`]) yorumlanır: Python `load_settings`
//! gibi varsayılanlarla birleşir, bilinmeyen anahtar atılır, sözlük beklenen anahtar `{}`e düşer. rs/state'te karşılığı
//! olan okuyucular ona devreder; kalanlar burada. Bozuk değer asla hata vermez.

use crate::pyfmt::{parse_float, parse_int, py_float, str_of, str_or_empty, strip, truthy};
use cops_state::json::Json;
use cops_state::settings::Settings as StateSettings;
use serde_json::{Map, Value};

pub use cops_state::settings_read::{is_safe_env_name, valid_http_url};

const AGENTS_OFF_WORDS: [&str; 8] = [
    "off", "0", "false", "no", "none", "disabled", "kapali", "kapalı",
];
/// `ucli_max_session_usd` boş/bozukken.
pub const DEFAULT_MAX_SESSION_USD: f64 = 8.0;

/// Ayrıştırılmış `settings.json` (dosya yok/bozuksa varsayılanlar). `byok` SIR taşır: `Debug` içerik yazmaz.
#[derive(Clone)]
pub struct Settings {
    state: StateSettings,
    /// Birleştirilmiş belge ([`Settings::get`]; sonlu olmayan sayı `null`).
    map: Map<String, Value>,
    /// Ham belgeden: birleştirme sözlük olmayan `ucli_cost`u `{}` yapar, tavan denetimi onu görmelidir.
    cap_problem: Option<&'static str>,
}

impl std::fmt::Debug for Settings {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Settings(..)")
    }
}

impl Default for Settings {
    fn default() -> Self {
        Settings::from_json("")
    }
}

fn to_value(v: &Json) -> Value {
    match v {
        Json::Null => Value::Null,
        Json::Bool(b) => Value::Bool(*b),
        Json::Int(i) => Value::from(*i),
        Json::BigInt(s) => s.parse::<f64>().map(Value::from).unwrap_or(Value::Null),
        Json::Float(f) => Value::from(*f),
        Json::Str(s) => Value::String(s.clone()),
        Json::Array(a) => Value::Array(a.iter().map(to_value).collect()),
        Json::Object(m) => Value::Object(m.iter().map(|(k, v)| (k.clone(), to_value(v))).collect()),
    }
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

/// `ucli_web` yorumu.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UcliWeb {
    pub search_url: Option<String>,
    pub search_docker: bool,
    pub allow_fetch_domains: Vec<String>,
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
    /// `settings._ucli_cap_problem`: tavan güvenle okunamıyorsa nedeni (`daily_cap_usd` o zaman 0 görünür; başlatma
    /// kapısı reddeder).
    pub cap_problem: Option<&'static str>,
}

pub(crate) const BAD_COST_BLOCK: &str = "ucli_cost ayarı geçersiz";
pub(crate) const BAD_CAP: &str = "ucli_cost.daily_cap_usd geçersiz";

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

fn strings(v: Option<&Json>) -> Vec<String> {
    v.and_then(Json::as_array).map_or_else(Vec::new, |a| {
        a.iter()
            .filter_map(Json::as_str)
            .map(String::from)
            .collect()
    })
}

/// `_ucli_cap_problem`in belge içi yarısı (ham `ucli_cost`): blok/anahtar yok, boş ve 0 "tavan yok"; sözlük olmayan
/// blok ya da sayı olmayan, negatif, sonlu olmayan değer sorundur.
fn cap_problem(block: Option<Value>) -> Option<&'static str> {
    let block = match block {
        None | Some(Value::Null) => return None,
        Some(Value::String(s)) if s.is_empty() => return None,
        Some(Value::Object(block)) => block,
        Some(_) => return Some(BAD_COST_BLOCK),
    };
    let valid = match block.get("daily_cap_usd") {
        None | Some(Value::Null) => true,
        Some(Value::String(s)) if strip(s).is_empty() => true,
        Some(v @ (Value::Number(_) | Value::String(_))) => {
            parse_float(&str_of(v).replace(',', ".")).is_some_and(|f| f >= 0.0 && f.is_finite())
        }
        Some(_) => false,
    };
    (!valid).then_some(BAD_CAP)
}

impl Settings {
    /// Ayrıştırılmış nesneden (anahtar sırası `Map` sırasıdır). Sıra önemliyse [`Settings::from_json`].
    pub fn new(map: Map<String, Value>) -> Self {
        Settings::from_json(&Value::Object(map).to_string())
    }

    /// `settings.json` metni; nesne değilse ya da bozuksa varsayılanlar (Python `load_settings` toleransı).
    pub fn from_json(text: &str) -> Self {
        let state = StateSettings::from_text(Some(text));
        let map = state
            .as_map()
            .iter()
            .map(|(k, v)| (k.clone(), to_value(v)))
            .collect();
        let cap_problem = match Json::parse_lossy(text) {
            Ok((raw @ Json::Object(_), _)) => cap_problem(raw.get("ucli_cost").map(to_value)),
            _ => None,
        };
        Settings {
            state,
            map,
            cap_problem,
        }
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.map.get(key)
    }

    fn block(&self, key: &str) -> Option<&Map<String, Value>> {
        self.map.get(key).and_then(Value::as_object)
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
        self.state.byok_env_for(cli).into_iter().collect()
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

    /// `ucli_limits` içindeki geçerli (pozitif tam sayı, i64'e sığan) sayısal override'lar.
    pub fn ucli_limit_overrides(&self) -> Vec<(&'static str, i64)> {
        self.state
            .ucli_limit_overrides()
            .into_iter()
            .filter_map(|(k, n)| n.as_i64().map(|n| (k, n)))
            .collect()
    }

    pub fn ucli_reasoning_mode(&self) -> String {
        self.state.ucli_reasoning_mode()
    }

    pub fn ucli_stream(&self) -> bool {
        self.state.ucli_stream_enabled()
    }

    pub fn ucli_show_reasoning(&self) -> bool {
        self.state.ucli_show_reasoning_enabled()
    }

    pub fn ucli_state_dir(&self) -> bool {
        self.state.ucli_state_dir_enabled()
    }

    pub fn ucli_script_mode(&self) -> String {
        self.state.ucli_script_mode()
    }

    /// Geçerli `ucli_endpoint` (sondaki `/` atılmış) ya da "".
    pub fn ucli_endpoint(&self) -> String {
        self.state.ucli_endpoint()
    }

    pub fn ucli_web(&self) -> UcliWeb {
        let web = self.state.ucli_web_config();
        UcliWeb {
            search_url: web
                .get("search_url")
                .and_then(Json::as_str)
                .map(String::from),
            search_docker: web.get("search_docker").is_some_and(Json::truthy),
            allow_fetch_domains: strings(web.get("allow_fetch_domains")),
        }
    }

    /// `normalize_ucli_services`: geçersiz girdiler atılır, `evren` her zaman vardır.
    pub fn ucli_services(&self) -> Vec<UcliService> {
        self.state
            .ucli_services()
            .iter()
            .map(|d| {
                let text = |k: &str| d.get(k).and_then(Json::as_str).unwrap_or("").to_string();
                let efforts = d.get("efforts").and_then(Json::as_object);
                UcliService {
                    id: text("id"),
                    label: text("label"),
                    wire: text("wire"),
                    endpoint: text("endpoint"),
                    env: text("env"),
                    models: strings(d.get("models")),
                    efforts: efforts.map_or_else(Vec::new, |m| {
                        m.iter()
                            .map(|(k, v)| (k.clone(), strings(Some(v))))
                            .collect()
                    }),
                }
            })
            .collect()
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
        let c = self.state.ucli_cost_config();
        UcliCostConfig {
            daily_cap_usd: c.daily_cap_usd,
            cache_ttl: if c.cache_ttl == "5m" { "5m" } else { "1h" },
            credit_total_usd: c.credit_total_usd,
            credit_since: c.credit_since,
            credit_until: c.credit_until,
            cap_problem: self.cap_problem,
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
        self.state.routing_guidance_enabled()
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
