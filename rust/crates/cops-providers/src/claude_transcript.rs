//! claude transkriptinden canlı model/effort ve istem önbelleği sıcaklığı (`claude_provider.py`:
//! `_last_assistant_value` ailesi, `last_real_request_epoch`, `live_or_spawn_*`, önbellek ömrü ve effort kuralı).
//!
//! Transkript 20 MB'ı aşabilir: dosya SONDAN, büyüyen bir pencereyle okunur ([`FIRST_WINDOW_BYTES`] x4, en çok
//! [`MAX_WINDOW_BYTES`]); daha geride kalan satır "bilinmiyor"dur. Boyut BİR kez okunur: tarama sırasında eklenen satır
//! görülmez (Python gibi).
//!
//! Python'dan bilerek ayrılan yerler (güvenli yön; parite testinde `known` kaydı): tipi beklenmedik satır yalnız o satırı
//! atlatır (Python istisna atar) ve `<synthetic>` yer tutucusu model sayılmaz.

use crate::bg_work::iso_epoch;
use crate::live::Live;
use crate::provider::Cli;
use crate::pyfmt::strip;
use crate::pyjson::Py;
use fancy_regex::Regex;
use std::sync::LazyLock;

/// İlk okunan pencere (`_LAST_MODEL_CHUNK_BYTES`).
pub const FIRST_WINDOW_BYTES: u64 = 65_536;
/// Pencerenin büyümeyi bıraktığı boyut (`_LAST_MODEL_MAX_BYTES`).
pub const MAX_WINDOW_BYTES: u64 = 4_194_304;
/// claude istem önbelleğinin ömrü (1 saatlik sınıf; `PROMPT_CACHE_TTL_SECONDS`).
pub const PROMPT_CACHE_TTL_SECONDS: u64 = 3600;
/// API isteği olmayan yer tutucu satırın modeli (hata/iptal).
const SYNTHETIC_MODEL: &str = "<synthetic>";

/// Canlı effort değişiminin önbelleği BOZDUĞU modeller (`_EFFORT_BUSTS_CACHE_RE`, küçük harfe çevrilmiş ada baştan).
static EFFORT_BUSTS_CACHE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^claude-(?:(?:sonnet|fable|mythos)-5(?!-\d(?!\d))|(?:opus|sonnet|haiku)-4|3)").expect("sabit desen")
});

impl Cli {
    /// Sunucu tarafı istem önbelleğinin ömrü (sn); None = bilinmiyor/ilgisiz (önbellek bilinçli devir uygulanmaz).
    pub fn prompt_cache_ttl_seconds(self) -> Option<u64> {
        match self {
            Cli::Claude => Some(PROMPT_CACHE_TTL_SECONDS),
            Cli::Agy | Cli::Codex | Cli::Copilot | Cli::Ucli | Cli::Shell => None,
        }
    }

    /// `model` oturumunda canlı effort değişimi önbelleği korur mu (varsayılan: korur).
    pub fn effort_switch_keeps_cache(self, model: Option<&str>) -> bool {
        match self {
            Cli::Claude => !EFFORT_BUSTS_CACHE.is_match(&model.unwrap_or("").to_lowercase()).unwrap_or(false),
            Cli::Agy | Cli::Codex | Cli::Copilot | Cli::Ucli | Cli::Shell => true,
        }
    }
}

/// `message.model`: boş olmayan metin ve gerçek bir model.
fn assistant_model(row: &Py) -> Option<String> {
    let model = row.get("message")?.get("model")?.as_str()?;
    (!model.is_empty() && model != SYNTHETIC_MODEL).then(|| model.to_string())
}

/// Satırın üst düzey `effort`u; yalnız boş olmayan metin (sayısal/özel değer "bilinmiyor").
fn assistant_effort(row: &Py) -> Option<String> {
    row.get("effort")?.as_str().filter(|e| !e.is_empty()).map(String::from)
}

/// Satır gerçek bir API isteğinin yanıtıysa damgası: alt ajan satırı, yer tutucu ve token saymayan satır değil.
/// Damga tam 0 ise Python gibi yok sayılır.
fn real_request_epoch(row: &Py, utc_offset_secs: i64) -> Option<f64> {
    if row.get("isSidechain").is_some_and(Py::truthy) {
        return None;
    }
    let message = row.get("message").filter(|m| m.is_object())?;
    match message.get("model") {
        None | Some(Py::Null) => return None,
        Some(Py::Str(m)) if m.is_empty() || m == SYNTHETIC_MODEL => return None,
        Some(_) => {}
    }
    let usage = message.get("usage").filter(|u| u.is_object())?;
    let tokens = ["input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"]
        .iter()
        .map(|key| match usage.get(key) {
            Some(Py::Int(n)) => i128::from(*n),
            Some(Py::BigInt(s)) => {
                s.parse().unwrap_or(if s.starts_with('-') { i128::MIN } else { i128::MAX })
            }
            _ => 0,
        })
        .fold(0i128, i128::saturating_add);
    if tokens <= 0 {
        return None;
    }
    iso_epoch(row.get("timestamp")?, utc_offset_secs).filter(|t| *t != 0.0)
}

impl Live<'_> {
    /// Dosyanın sonundan geriye, `extract`in değer verdiği en son `type: "assistant"` satırı; bulunamazsa ya da dosya
    /// okunamazsa None. `since` verilirse ondan eski ilk assistant satırında tarama biter (damgasız satır eski sayılmaz).
    fn last_assistant_value<T>(&self, path: &str, since: Option<f64>, extract: impl Fn(&Py) -> Option<T>) -> Option<T> {
        let size = self.probe.file_size(path)?;
        let mut window = FIRST_WINDOW_BYTES;
        loop {
            let start = size.saturating_sub(window);
            let chunk = self.probe.read_range(path, start, size - start)?;
            let text = String::from_utf8_lossy(&chunk);
            for line in text.rsplit('\n') {
                let line = strip(line);
                if line.is_empty() {
                    continue;
                }
                let Some(row) = Py::parse(line) else { continue };
                if row.get("type").and_then(Py::as_str) != Some("assistant") {
                    continue;
                }
                if let Some(since) = since {
                    let at = row.get("timestamp").and_then(|t| iso_epoch(t, self.clock.utc_offset_secs));
                    if at.is_some_and(|at| at < since) {
                        return None;
                    }
                }
                if let Some(value) = extract(&row) {
                    return Some(value);
                }
            }
            if start == 0 || window >= MAX_WINDOW_BYTES {
                return None;
            }
            window *= 4;
        }
    }

    /// En son assistant satırının modeli. `since`: yalnız o andan (epoch sn, süreç başlangıcı) sonraki satırlar.
    pub fn last_assistant_model(&self, path: &str, since: Option<f64>) -> Option<String> {
        self.last_assistant_value(path, since, assistant_model)
    }

    /// En son effort taşıyan assistant satırının effort'u (modelden daha eski bir satır olabilir).
    pub fn last_assistant_effort(&self, path: &str, since: Option<f64>) -> Option<String> {
        self.last_assistant_value(path, since, assistant_effort)
    }

    /// Dosyadaki son gerçek model isteğinin zamanı (epoch sn).
    pub fn last_real_request_epoch(&self, path: &str) -> Option<f64> {
        let offset = self.clock.utc_offset_secs;
        self.last_assistant_value(path, None, |row| real_request_epoch(row, offset))
    }

    /// Transkriptteki canlı model; belirlenemezse (claude değil, transkript ya da assistant turu yok) `fallback`.
    /// `cli` ham addır: tanınmayan ad claude SAYILMAZ.
    pub fn live_or_spawn_model(&self, cli: &str, cwd: &str, sid: Option<&str>, fallback: &str) -> String {
        self.live_transcript(cli, cwd, sid)
            .and_then(|path| self.last_assistant_model(&path, None))
            .unwrap_or_else(|| fallback.to_string())
    }

    /// [`Live::live_or_spawn_model`]ın effort karşılığı.
    pub fn live_or_spawn_effort(&self, cli: &str, cwd: &str, sid: Option<&str>, fallback: &str) -> String {
        self.live_transcript(cli, cwd, sid)
            .and_then(|path| self.last_assistant_effort(&path, None))
            .unwrap_or_else(|| fallback.to_string())
    }

    fn live_transcript(&self, cli: &str, cwd: &str, sid: Option<&str>) -> Option<String> {
        if cli != Cli::Claude.name() {
            return None;
        }
        self.probe.claude_transcript(cwd, sid)
    }

    /// Önbellek sıcaklığı için son gerçek isteğin zamanı. Yalnız TAM eşleşen `<sid>.jsonl` dosyaları okunur ("cwd'deki
    /// en yeni" düşüşü yok: kardeş oturum bunu sıcak gösterirdi). Adaylar cmdline sid'i ve sürecin kendi kayıt dosyasındaki
    /// sid; ikisi de varsa en yeni istek. claude dışında ve eşleşme yoksa None.
    pub fn last_request_epoch(&self, cli: Cli, cwd: &str, sid: Option<&str>, pid: Option<i64>) -> Option<f64> {
        if cli != Cli::Claude {
            return None;
        }
        let from_pid = pid.filter(|p| *p != 0).and_then(|p| self.probe.claude_session_sid(p));
        let first = sid.filter(|s| !s.is_empty());
        let second = from_pid.as_deref().filter(|s| !s.is_empty() && Some(*s) != first);
        let dir = self.probe.claude_project_dir(cwd);
        [first, second]
            .into_iter()
            .flatten()
            .filter_map(|candidate| {
                // `Path(dir) / ad`: mutlak ad dizini yok sayar.
                let path = if candidate.starts_with('/') {
                    format!("{candidate}.jsonl")
                } else {
                    format!("{dir}/{candidate}.jsonl")
                };
                self.probe.is_file(&path).then(|| self.last_real_request_epoch(&path)).flatten()
            })
            .reduce(f64::max)
    }
}
