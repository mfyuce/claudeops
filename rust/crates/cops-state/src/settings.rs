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
        // Python `json.load` eşlenmemiş vekili kabul eder: okuma için U+FFFD (ayarlar Rust'ta yazılmaz)
        if let Some(Ok((Json::Object(stored), _))) = text.map(Json::parse_lossy) {
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
    /// Son başarılı okumadaki `store_backend` (Python `_LAST_BACKEND`).
    last_backend: Mutex<Option<Json>>,
}

impl SettingsReader {
    pub fn new(dir: StateDir) -> SettingsReader {
        SettingsReader {
            dir,
            cache: Mutex::new(None),
            last_backend: Mutex::new(None),
        }
    }
    /// İmza aynıysa önbellek; değilse okunur. OKUNAMAYAN dosya (yok dışındaki G/Ç hatası: EACCES, EMFILE, EIO...)
    /// varsayılanları döndürür ama önbelleğe ALINMAZ: son iyi değer önbellekte kalır, hata geçince yeni içerik okunur.
    /// Okunamayan ya da bozuk dosyada `store_backend` son başarılı okumadaki değerini korur (Python ile aynı).
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
        let Loaded {
            mut val,
            cacheable,
            state,
        } = read(&self.dir);
        {
            let mut last = self.last_backend.lock().unwrap_or_else(|e| e.into_inner());
            match state {
                FileState::Good => *last = val.get("store_backend").cloned(),
                FileState::Bad => {
                    if let Some(b) = last.as_ref() {
                        val.0.insert("store_backend".into(), b.clone());
                    }
                }
                FileState::Missing => {}
            }
        }
        let val = Arc::new(val);
        if let (Some(b), true) = (before, cacheable) {
            if sig() == Some(b) {
                *cache = Some((b, val.clone()));
            }
        }
        val
    }

    /// Önbellekteki son iyi değer (tanı/test).
    pub fn last_good(&self) -> Option<Arc<Settings>> {
        self.cache
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
            .map(|(_, v)| v.clone())
    }
}

enum FileState {
    /// JSON nesnesi okundu.
    Good,
    /// Dosya yok.
    Missing,
    /// Okunamıyor, UTF-8 / JSON değil ya da nesne değil.
    Bad,
}

struct Loaded {
    val: Settings,
    /// İçerikten belirlenen sonuç önbelleğe alınır; G/Ç hatası alınmaz.
    cacheable: bool,
    state: FileState,
}

fn read(dir: &StateDir) -> Loaded {
    let (text, cacheable, state) = match std::fs::read_to_string(dir.settings_json()) {
        Ok(t) => {
            let state = if matches!(Json::parse_lossy(&t), Ok((Json::Object(_), _))) {
                FileState::Good
            } else {
                FileState::Bad
            };
            (Some(t), true, state)
        }
        Err(e) if e.kind() == std::io::ErrorKind::InvalidData => (None, true, FileState::Bad),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (None, false, FileState::Missing),
        Err(_) => (None, false, FileState::Bad),
    };
    Loaded {
        val: Settings::from_text(text.as_deref()),
        cacheable,
        state,
    }
}

/// `settings._backup_if_corrupt`: `settings.json` VAR, boş değil ve JSON nesnesi değilse ham içerik
/// `settings.json.corrupt-<sha8>` olarak (0600, bir kez) yedeklenir. Dönüş: `None` = bozuk değil/yok; `Some(Ok(yol))`;
/// `Some(Err)` = yedeklenemedi (Python "(yedeklenemedi)" yazar). Settings yazan Rust kodu yazımdan ÖNCE çağırmalı.
pub fn backup_if_corrupt(dir: &StateDir) -> Option<std::io::Result<std::path::PathBuf>> {
    let path = dir.settings_json();
    let raw = std::fs::read(&path).ok()?;
    if raw.trim_ascii().is_empty() {
        return None;
    }
    if let Ok(t) = std::str::from_utf8(&raw) {
        if matches!(Json::parse_lossy(t), Ok((Json::Object(_), _))) {
            return None;
        }
    }
    Some(crate::fsutil::write_corrupt_copy(&path, &raw))
}

/// Önbelleksiz tek okuma (son iyi değer tutmaz; uzun yaşayan süreç [`SettingsReader`] kullanır).
pub fn load(dir: &StateDir) -> Settings {
    read(dir).val
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

    /// H12: sır taşıyan ayar nesnesi `Debug`ta içerik göstermez.
    #[test]
    fn debug_hides_secrets() {
        let s = Settings::from_text(Some(
            r#"{"byok": {"claude": {"ANTHROPIC_API_KEY": "sk-gizli"}}}"#,
        ));
        let d = format!("{s:?} {:?}", std::sync::Arc::new(s.clone()));
        assert!(!d.contains("sk-gizli"), "{d}");
    }
}
