//! `settings.json` OKUMA (Python `settings.load_settings`). Yazım Python'da kalır. Varsayılanlar `default_settings.json`
//! (Python `DEFAULT_SETTINGS`in aynısı; parite testi farkı yakalar). Dosya `store_backend` kipinden bağımsız okunur.
use crate::json::{Json, Map};
use crate::paths::StateDir;
use crate::pycompat;
use std::os::unix::fs::MetadataExt;
use std::sync::{Arc, Mutex, OnceLock};

const DEFAULTS: &str = include_str!("default_settings.json");

/// Dosyada sözlük olmayan değer taşırsa `{}`e düşen anahtarlar.
const DICT_KEYS: [&str; 12] = [
    "default_model",
    "default_effort",
    "provider_bin",
    "byok",
    "ucli_limits",
    "ucli_web",
    "ucli_script",
    "ucli_cost",
    "ucli_metrics",
    "ucli_usage_warn",
    "cli_managed",
    "stewards",
];

/// Python `settings._OFF_WORDS`.
pub const OFF_WORDS: [&str; 11] = [
    "off", "0", "false", "no", "n", "hayir", "hayır", "kapali", "kapalı", "disabled", "none",
];

/// Varsayılan ayarlar (anahtar sırası Python ile aynı).
pub fn defaults() -> &'static Map {
    static D: OnceLock<Map> = OnceLock::new();
    D.get_or_init(|| match Json::parse(DEFAULTS) {
        Ok(Json::Object(m)) => m,
        _ => unreachable!("default_settings.json derleme zamanı sabiti; birim testi denetler"),
    })
}

/// Her zaman TÜM varsayılan anahtarları taşır; bilinmeyen anahtarlar atılır. `byok` SIR taşır: bu nesneyi loglama/yanıtlama.
#[derive(Clone, PartialEq)]
pub struct Settings(Map);

impl std::fmt::Debug for Settings {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Settings(..)")
    }
}

impl Settings {
    /// Dosya içeriğinden (`None` / bozuk / nesne değil = varsayılanlar).
    pub fn from_text(text: Option<&str>) -> Settings {
        let mut out = defaults().clone();
        if let Some(Ok(Json::Object(stored))) = text.map(Json::parse) {
            for (k, v) in stored {
                if let Some(slot) = out.get_mut(&k) {
                    *slot = v;
                }
            }
            for k in DICT_KEYS {
                if let Some(v) = out.get_mut(k) {
                    if v.as_object().is_none() {
                        *v = Json::object();
                    }
                }
            }
        }
        Settings(out)
    }
    pub fn as_map(&self) -> &Map {
        &self.0
    }
    pub fn get(&self, key: &str) -> Option<&Json> {
        self.0.get(key)
    }
    /// Dize değer; dize değilse `""`.
    pub fn str_of(&self, key: &str) -> &str {
        self.get(key).and_then(Json::as_str).unwrap_or("")
    }
    /// `settings[block][key]` dizesi (ör. `default_model`/`claude`); yoksa `""`.
    pub fn sub_str(&self, block: &str, key: &str) -> &str {
        self.get(block)
            .and_then(|b| b.get(key))
            .and_then(Json::as_str)
            .unwrap_or("")
    }
    /// Varsayılanı AÇIK bayrak (`tunnel_watch`, `routing_guidance`): `("on" if v is None else str(v)).strip().lower()`
    /// kapatma sözcüğü değilse açık.
    pub fn flag_default_on(&self, key: &str) -> bool {
        let text = match self.get(key) {
            None | Some(Json::Null) => "on".to_string(),
            Some(v) => pycompat::str_of(v),
        };
        !OFF_WORDS.contains(&pycompat::lower(pycompat::strip(&text)).as_str())
    }
    /// `routing_guidance_enabled`.
    pub fn routing_guidance_enabled(&self) -> bool {
        self.flag_default_on("routing_guidance")
    }
    /// `tunnel_watch_enabled`.
    pub fn tunnel_watch_enabled(&self) -> bool {
        self.flag_default_on("tunnel_watch")
    }
}

type Sig = (i64, i64, u64, u64);

/// Dosya imzasına (mtime, boyut, inode) bağlı önbellekli okuyucu.
#[derive(Debug)]
pub struct SettingsReader {
    dir: StateDir,
    cache: Mutex<Option<(Sig, Arc<Settings>)>>,
}

impl SettingsReader {
    pub fn new(dir: StateDir) -> SettingsReader {
        SettingsReader {
            dir,
            cache: Mutex::new(None),
        }
    }
    pub fn load(&self) -> Arc<Settings> {
        let path = self.dir.settings_json();
        let sig = || {
            std::fs::metadata(&path)
                .ok()
                .map(|m| (m.mtime(), m.mtime_nsec(), m.size(), m.ino()))
        };
        let before = sig();
        let mut cache = self.cache.lock().unwrap_or_else(|e| e.into_inner());
        if let (Some(b), Some((s, v))) = (before, cache.as_ref()) {
            if *s == b {
                return v.clone();
            }
        }
        let val = Arc::new(load(&self.dir));
        if let Some(b) = before {
            if sig() == Some(b) {
                *cache = Some((b, val.clone()));
            }
        }
        val
    }
}

/// Önbelleksiz tek okuma.
pub fn load(dir: &StateDir) -> Settings {
    let text = std::fs::read_to_string(dir.settings_json()).ok();
    Settings::from_text(text.as_deref())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_parse() {
        assert!(defaults().len() > 40);
        assert_eq!(Settings::from_text(None).str_of("store_backend"), "files");
    }

    #[test]
    fn merge_rules() {
        let s = Settings::from_text(Some(
            r#"{"theme":"dark","x":1,"byok":5,"steward":7,"tunnel_watch":"HAYIR","routing_guidance":""}"#,
        ));
        assert_eq!(s.str_of("theme"), "dark");
        assert!(s.get("x").is_none());
        assert_eq!(s.get("byok"), Some(&Json::object()));
        assert_eq!(s.get("steward"), Some(&Json::Int(7)));
        assert!(!s.flag_default_on("tunnel_watch"));
        assert!(s.flag_default_on("routing_guidance"));
        assert_eq!(Settings::from_text(Some("[1]")), Settings::from_text(None));
    }
}
