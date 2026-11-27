//! `settings.steward_ids` / `settings.steward_config` (ve dayandıkları `steward.Config` varsayılanları, kimlik kuralı,
//! beyin adı). YALNIZ ayar okuma: değnekçi kararları bu crate'te değil (rs/stew). Varsayılanlar
//! `default_steward_config.json` (Python `dataclasses.asdict(steward.Config())`; parite testi ayrışmayı yakalar); bir
//! alanın tipi varsayılan değerinin tipidir.
use crate::json::{Json, Map};
use crate::pycompat::{self as py, PyInt};
use crate::settings::Settings;
use std::sync::OnceLock;

const DEFAULTS: &str = include_str!("default_steward_config.json");

/// Python `steward.MODES`.
pub const MODES: [&str; 2] = ["observe", "act"];
/// Python `steward.ROLES`.
pub const ROLES: [&str; 3] = ["steward", "reviewer", "generic"];
/// Python `steward.MACHINE_KEYS`: yalnız `settings.steward` bloğunda okunan makine geneli anahtarlar.
pub const MACHINE_KEYS: [&str; 8] = [
    "tick_seconds",
    "card_refresh",
    "card_cli",
    "card_model",
    "card_max_age_hours",
    "cards_per_tick",
    "max_active_total",
    "max_starts_total",
];
/// Python `steward.RESERVED_IDS`.
pub const RESERVED_IDS: [&str; 6] = [
    "default", "all", "services", "service", "steward", "stewards",
];
/// Python `steward.BRAIN_PREFIX`.
pub const BRAIN_PREFIX: &str = "degnekci";
/// Python `steward.GENERIC_MODEL` / `GENERIC_EFFORT`.
pub const GENERIC_MODEL: &str = "claude-sonnet-5-5";
pub const GENERIC_EFFORT: &str = "medium";

/// `dataclasses.asdict(steward.Config())` (alan sırası Python ile aynı).
pub fn defaults() -> &'static Map {
    static D: OnceLock<Map> = OnceLock::new();
    D.get_or_init(|| match Json::parse(DEFAULTS) {
        Ok(Json::Object(m)) => m,
        _ => {
            unreachable!("default_steward_config.json derleme zamanı sabiti; birim testi denetler")
        }
    })
}

/// `valid_custom_id`: `^[a-z]{2,16}$` (tam eşleşme, TBD#379 S11), rezerve değil, beyin öneki değil.
pub fn valid_custom_id(sid: &str) -> bool {
    (2..=16).contains(&sid.len())
        && sid.bytes().all(|b| b.is_ascii_lowercase())
        && !RESERVED_IDS.contains(&sid)
        && !sid.starts_with(BRAIN_PREFIX)
}

/// `valid_steward_id`: `default` ya da geçerli özel kimlik.
pub fn valid_steward_id(sid: &str) -> bool {
    sid == "default" || valid_custom_id(sid)
}

/// `brain_name_for`.
pub fn brain_name_for(sid: &str) -> String {
    if sid == "default" {
        BRAIN_PREFIX.into()
    } else {
        format!("{BRAIN_PREFIX}_{sid}")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StewardConfigError {
    /// Python `ValueError`: geçersiz kimlik (sessizce `default`a düşülmez).
    InvalidSid(String),
}

impl std::fmt::Display for StewardConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StewardConfigError::InvalidSid(s) => write!(f, "geçersiz değnekçi kimliği: {s:?}"),
        }
    }
}
impl std::error::Error for StewardConfigError {}

/// `steward.Config` değeri: her zaman TÜM alanlar, Python sırasıyla. `ntfy_topic` sır sayılır: `Debug` yalnız kimliği
/// gösterir.
#[derive(Clone, PartialEq)]
pub struct StewardConfig(Map);

impl std::fmt::Debug for StewardConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "StewardConfig({:?}, ..)", self.str_of("sid"))
    }
}

impl StewardConfig {
    pub fn as_map(&self) -> &Map {
        &self.0
    }
    pub fn to_json(&self) -> Json {
        Json::Object(self.0.clone())
    }
    pub fn get(&self, key: &str) -> Option<&Json> {
        self.0.get(key)
    }
    /// Dize alan; bilinmeyen ya da dize olmayan alan `""`.
    pub fn str_of(&self, key: &str) -> &str {
        self.get(key).and_then(Json::as_str).unwrap_or("")
    }
    /// Bayrak alanı; bilinmeyen alan `false`.
    pub fn bool_of(&self, key: &str) -> bool {
        matches!(self.get(key), Some(Json::Bool(true)))
    }
    /// Tam sayı alanı; `i64`e sığmayan değer uca doyurulur, bilinmeyen alan 0.
    pub fn int_of(&self, key: &str) -> i64 {
        match self.get(key) {
            Some(Json::Int(i)) => *i,
            Some(Json::BigInt(t)) if t.starts_with('-') => i64::MIN,
            Some(Json::BigInt(_)) => i64::MAX,
            _ => 0,
        }
    }
    /// Kesirli alan; bilinmeyen alan 0.
    pub fn float_of(&self, key: &str) -> f64 {
        match self.get(key) {
            Some(Json::Float(f)) => *f,
            _ => 0.0,
        }
    }

    fn set(&mut self, key: &str, v: impl Into<Json>) {
        if let Some(slot) = self.0.get_mut(key) {
            *slot = v.into();
        }
    }

    /// Ham ayar değerini alanın tipine çevir; Python `TypeError`/`ValueError` = alan değişmez.
    fn assign(&mut self, key: &str, val: &Json) {
        let text = py::str_of(val);
        let text = py::strip(&text);
        let new = match self.get(key) {
            Some(Json::Bool(_)) => Some(Json::Bool(matches!(
                py::lower(text).as_str(),
                "on" | "1" | "true" | "yes" | "evet"
            ))),
            Some(Json::Int(_) | Json::BigInt(_)) => py::parse_int(text).map(|n| {
                if n.is_positive() {
                    n.to_json()
                } else {
                    Json::Int(0)
                }
            }),
            // `max(0.0, x)`: NaN ve negatif (-0.0 dahil) 0.0
            Some(Json::Float(_)) => {
                py::parse_float(text).map(|f| Json::Float(if f > 0.0 { f } else { 0.0 }))
            }
            Some(_) => Some(Json::from(text)),
            None => None,
        };
        if let Some(v) = new {
            self.set(key, v);
        }
    }
}

/// `int(x)` (`history_warn_at`): `None` = `TypeError`/`ValueError`/`OverflowError` (sonsuz, TBD#379 S12).
fn history_int(v: &Json) -> Option<PyInt> {
    match v {
        Json::Bool(b) => Some(PyInt::from_i64(i64::from(*b))),
        Json::Int(i) => Some(PyInt::from_i64(*i)),
        Json::BigInt(t) => py::parse_int(t),
        Json::Float(f) if !f.is_finite() => None,
        // `{:.0}` kayan noktanın tam ondalık açılımını yazar (`int(1e300)` ile aynı)
        Json::Float(f) => py::parse_int(&format!("{:.0}", f.trunc())),
        Json::Str(s) => py::parse_int(s),
        Json::Null | Json::Array(_) | Json::Object(_) => None,
    }
}

impl Settings {
    /// `steward_ids`: `["default"]` + sıralı geçerli `stewards` anahtarları (değeri sözlük olanlar).
    pub fn steward_ids(&self) -> Vec<String> {
        let mut ids: Vec<String> = self
            .get("stewards")
            .and_then(Json::as_object)
            .map(|m| {
                m.iter()
                    .filter(|(k, v)| v.as_object().is_some() && valid_custom_id(k))
                    .map(|(k, _)| k.clone())
                    .collect()
            })
            .unwrap_or_default();
        ids.sort();
        ids.insert(0, "default".into());
        ids
    }

    /// `steward_config(sid)`: `steward` (default) ya da `stewards.<sid>` + makine geneli anahtarlar.
    pub fn steward_config(&self, sid: &str) -> Result<StewardConfig, StewardConfigError> {
        if !valid_steward_id(sid) {
            return Err(StewardConfigError::InvalidSid(sid.into()));
        }
        let block = |v: Option<&'_ Json>| v.and_then(Json::as_object).cloned();
        let base = block(self.get("steward")).unwrap_or_default();
        let mut cfg = StewardConfig(defaults().clone());
        cfg.set("sid", sid);
        let default = sid == "default";
        // (blok, atlanacak alan mı): önce makine geneli (yalnız `steward`), sonra kimliğin kendi bloğu
        type Skip = fn(&str) -> bool;
        let mut sources: Vec<(Map, Skip)> = Vec::new();
        if default {
            sources.push((base, |k| k == "sid"));
        } else {
            let own = block(self.get("stewards").and_then(|s| s.get(sid))).unwrap_or_default();
            sources.push((base, |k| !MACHINE_KEYS.contains(&k)));
            sources.push((own, |k| {
                MACHINE_KEYS.contains(&k) || k == "sid" || k == "brain_name"
            }));
        }
        for (raw, skip) in &sources {
            for key in defaults().keys() {
                if key == "history_warn_at" || skip(key) {
                    continue;
                }
                if let Some(val) = raw.get(key) {
                    cfg.assign(key, val);
                }
            }
        }
        if let Some(raw) = self.get("history_warn_at").filter(|v| v.truthy()) {
            if let Some(n) = history_int(raw) {
                let small = n.saturating_i64() < 100;
                cfg.set(
                    "history_warn_at",
                    if small { Json::Int(100) } else { n.to_json() },
                );
            }
        } // yok ya da yanlış (falsy): `Config.history_warn_at` (zaten varsayılan)
        if !["tr", "en"].contains(&cfg.str_of("lang")) {
            cfg.set("lang", "tr");
        }
        let gate = py::lower(cfg.str_of("ask_gate"));
        let gate = if gate == "shadow" || gate == "on" {
            gate
        } else {
            "off".into()
        };
        cfg.set("ask_gate", gate);
        if !MODES.contains(&cfg.str_of("mode")) {
            cfg.set("mode", "observe");
        }
        if cfg.int_of("summary_hour") > 23 {
            cfg.set("summary_hour", Json::Int(23));
        }
        if default || !ROLES.contains(&cfg.str_of("role")) {
            cfg.set("role", "steward");
        }
        if cfg.str_of("role") == "generic" {
            for (key, val) in [
                ("planning_model", GENERIC_MODEL),
                ("planned_model", GENERIC_MODEL),
                ("planning_effort", GENERIC_EFFORT),
                ("planned_effort", GENERIC_EFFORT),
            ] {
                if cfg.str_of(key).is_empty() {
                    cfg.set(key, val);
                }
            }
        }
        if cfg.int_of("review_timeout_minutes") < 1 {
            cfg.set("review_timeout_minutes", Json::Int(1));
        }
        let hours = cfg.int_of("review_window_hours");
        if !(1..=8760).contains(&hours) {
            cfg.set("review_window_hours", Json::Int(hours.clamp(1, 8760)));
        }
        if cfg.int_of("tick_seconds") < 15 {
            cfg.set("tick_seconds", Json::Int(15));
        }
        if !default {
            cfg.set("brain_name", brain_name_for(sid));
        } else if !py::is_alnum_str(&cfg.str_of("brain_name").replace('_', "")) {
            cfg.set("brain_name", BRAIN_PREFIX);
        }
        Ok(cfg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_parse() {
        assert!(defaults().len() > 100);
        assert_eq!(defaults().get("brain_name"), Some(&Json::from("degnekci")));
    }
}
