//! Model kaynakları: `agy models`, claude/codex model belgeleri, ucli `/models` ve hizmet listeleri; TTL'li ve bayatta
//! arka planda tazelenen önbellekler (Python `AgyProvider`/`CodexProvider.model_choices`, `ucli_provider._live_models`,
//! `ucli_session_opts.service_models`).
//!
//! Crate yine G/Ç yapmaz: süreç, HTTP, dosya, belge deposu ve saat [`ModelIo`] ile çağırandadır. Önbellek politikası
//! (TTL, hatada eski değer, soğukta bloklayan / bayatta arka plan) ve okuma üst sınırlarının ikinci denetimi buradadır.
//! Python'da bu önbellekler süreç geneline aittir: süreç başına TEK [`ModelSources`] kurulmalı.
//!
//! Hata metni YOKTUR: her G/Ç hatası `None`dır (Python da hepsini yutar), böylece API anahtarı hata/log yoluna giremez.

use crate::probe::{Paths, Probe};
use crate::provider::{Cli, ModelCatalog, Providers};
use crate::settings::Settings;
use crate::{agy, codex, ucli, ucli_opts};
use serde_json::Value;
use std::fmt;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

/// `agy models` zaman aşımı.
pub const AGY_MODELS_TIMEOUT: Duration = Duration::from_secs(5);
/// `agy models` stdout üst sınırı (Python'da sınır yok).
pub const AGY_MODELS_MAX_BYTES: u64 = 1 << 20;
/// ucli `GET /models` zaman aşımı.
pub const LIVE_MODELS_TIMEOUT: Duration = Duration::from_secs(5);
/// Hizmet `GET /models` zaman aşımı.
pub const SERVICE_MODELS_TIMEOUT: Duration = Duration::from_secs(8);
/// `/models` yanıt gövdesi üst sınırı (Python'da sınır yok).
pub const HTTP_MAX_BYTES: u64 = 8 << 20;
/// codex `models_cache.json` üst sınırı (Python'da sınır yok).
pub const CODEX_CACHE_MAX_BYTES: u64 = 8 << 20;

/// Alt süreç isteği (kabuk YOK, argv olduğu gibi).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunRequest {
    pub argv: Vec<String>,
    pub timeout: Duration,
    pub max_stdout: u64,
}

/// Sır olabilen başlık değeri (latin-1 baytları, CR/LF yok); `Debug` maskeler.
#[derive(Clone, PartialEq, Eq)]
pub struct SecretValue(Vec<u8>);

impl SecretValue {
    /// Python `http.client` gibi latin-1'e çevrilemeyen ya da satır sonu taşıyan değer gönderilemez (None). Python
    /// katlanmış satırı (`\r\n `) kabul eder; burada her CR/LF reddedilir.
    pub fn new(value: &str) -> Option<SecretValue> {
        value.chars().map(|c| u8::try_from(c).ok().filter(|b| *b != b'\r' && *b != b'\n')).collect::<Option<_>>().map(Self)
    }

    /// Yalnız HTTP uygulayıcısı içindir: loglanmaz.
    pub fn expose(&self) -> &[u8] {
        &self.0
    }
}

impl fmt::Debug for SecretValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("<redacted>")
    }
}

/// Tek `GET` isteği. API anahtarı yalnız `headers`tadır, URL'de değil.
#[derive(Clone, PartialEq, Eq)]
pub struct HttpRequest {
    pub url: String,
    pub headers: Vec<(&'static str, SecretValue)>,
    pub timeout: Duration,
    pub max_body: u64,
}

impl fmt::Debug for HttpRequest {
    /// Elle girilen uç nokta `kullanıcı:parola@` taşıyabilir: o parça da maskelenir.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let url = match self.url.split_once("://") {
            Some((scheme, rest)) => {
                let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
                match rest[..end].rfind('@') {
                    Some(at) => format!("{scheme}://<redacted>{}", &rest[at..]),
                    None => self.url.clone(),
                }
            }
            None => self.url.clone(),
        };
        f.debug_struct("HttpRequest")
            .field("url", &url)
            .field("headers", &self.headers)
            .field("timeout", &self.timeout)
            .field("max_body", &self.max_body)
            .finish()
    }
}

/// Model kaynaklarının dış dünyası. `Send + Sync`: arka plan tazelemesi başka iş parçacığından çağırır.
///
/// Uygulama sözleşmesi (gerçek uygulama G8): her yöntemde hata `None`; süreç ve HTTP için `timeout` TOPLAM süredir.
pub trait ModelIo: Send + Sync {
    /// Python `time.monotonic()` (Linux'ta `CLOCK_MONOTONIC`, açılıştan beri saniye): taban ANLAMLIDIR, süreç
    /// başlangıcından sayan bir saat verilmez (bkz. `docs/rs-prov.md` G7, ilk 300 saniye).
    fn monotonic_secs(&self) -> f64;
    /// Python `time.time()`.
    fn wall_secs(&self) -> f64;
    /// `statedocs.read_json("claude_models", paths.claude_models_json(), {})`: belge deposu kipine göre DB ya da dosya
    /// (rs/state). Crate bu dosyayı KENDİSİ OKUMAZ (db kipinde dosya bayat aynadır).
    fn claude_models_doc(&self) -> Option<Value>;
    /// Normal dosyanın tamamı; `max` bayttan büyükse ya da okunamazsa None.
    fn read_file(&self, path: &str, max: u64) -> Option<Vec<u8>>;
    /// Süreci koştur, stdout'u döndür; ÇIKIŞ KODUNA BAKILMAZ. stdin boş, stderr boşaltılır ya da atılır. Başlatılamazsa,
    /// zaman aşımında (süreç öldürülür VE beklenir) ya da stdout `max_stdout`u aşarsa None.
    fn run_stdout(&self, req: &RunRequest) -> Option<Vec<u8>>;
    /// `GET`; yalnız 2xx yanıtın gövdesi. Diğer durum, ağ hatası, zaman aşımı ya da `max_body` aşımı None. Yönlendirme
    /// kararı uygulayıcıdadır ve AÇIKTIR (Python izler ve anahtar başlığını yeni adrese de taşır).
    fn http_get(&self, req: &HttpRequest) -> Option<Vec<u8>>;
    /// Arka plan işi (Python daemon iş parçacığı). Başlatılamazsa iş düşer, eski önbellek kalır.
    fn spawn_background(&self, name: &'static str, job: Box<dyn FnOnce() + Send + 'static>) {
        let _ = std::thread::Builder::new().name(name.into()).spawn(job);
    }
}

/// Uygulayıcı sınırı aşan veri döndürürse yok sayılır.
pub(crate) fn bounded(data: Option<Vec<u8>>, max: u64) -> Option<Vec<u8>> {
    data.filter(|d| d.len() as u64 <= max)
}

/// Zehirlenmiş kilit önbelleği kalıcı olarak düşürmesin (içindeki her güncelleme tek atamadır).
pub(crate) fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Süreç genelindeki model önbellekleri. Kilit hiçbir G/Ç sırasında tutulmaz.
pub struct ModelSources {
    io: Arc<dyn ModelIo>,
    agy: agy::ModelsCache,
    codex: codex::ModelsCache,
    live: ucli::LiveCache,
    services: ucli_opts::ServiceModelsCache,
}

impl ModelSources {
    pub fn new(io: Arc<dyn ModelIo>) -> Self {
        ModelSources {
            io,
            agy: Default::default(),
            codex: Default::default(),
            live: Default::default(),
            services: Default::default(),
        }
    }

    /// `AgyProvider.model_choices`; `binary` yalnız çekim gerekirse çözülür.
    pub fn agy_models(&self, binary: impl FnOnce() -> String) -> Vec<String> {
        self.agy.get(&self.io, binary)
    }

    /// `CodexProvider.model_choices` (boş kalamaz: sabit yedek).
    pub fn codex_models(&self, paths: &Paths) -> Vec<String> {
        self.codex.get(self.io.as_ref(), paths)
    }

    /// `_live_models` + `_LIVE_CAPS` (kimlikler boş kalamaz: sabit yedek).
    pub fn ucli_live(&self, settings: &Settings) -> ucli::LiveModels {
        self.live.get(self.io.as_ref(), settings)
    }

    /// `ucli_session_opts.service_models`.
    pub fn service_models(&self, settings: &Settings, service: &str, key: &str) -> Vec<String> {
        self.services.get(self.io.as_ref(), settings, service, key)
    }

    /// `cli` için [`ModelCatalog`]; yalnız o CLI'ın kaynağına dokunur. Python'dan farkı: agy'de effort'u kimliğinde
    /// taşıyan model ya da ucli'de `reasoning_effort=off` için de liste istenir (Python o yollarda çekmez).
    pub fn catalog(&self, cli: Cli, settings: &Settings, paths: &Paths, probe: &dyn Probe) -> ModelCatalog {
        let mut c = ModelCatalog::default();
        match cli {
            Cli::Claude => c.claude_state = self.io.claude_models_doc(),
            Cli::Agy => {
                let empty = ModelCatalog::default();
                let p = Providers { settings, catalog: &empty, paths, probe };
                c.agy_models = self.agy_models(|| p.resolved_binary("agy"));
            }
            Cli::Codex => {
                c.codex_choices = Some(self.codex_models(paths));
                // `model_effort_levels` Python'da önbelleksizdir: belge her seferinde yeniden okunur.
                c.codex_cache = codex::read_models_cache(self.io.as_ref(), paths);
            }
            Cli::Ucli => c.ucli = self.ucli_live(settings),
            Cli::Copilot | Cli::Shell => {}
        }
        c
    }
}
