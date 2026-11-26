//! ucli durum dosyası ve hata kayıtları (`ucli_client.chat_session_dirs`..`read_status_file`,
//! `UcliProvider.live_*`). Dosyalar çağıranın [`LiveProbe`]u ile okunur.
//!
//! Okuma sınırları (Python sınırsız okur): durum dosyası [`STATUS_MAX_BYTES`], hata kaydı [`RECORD_MAX_BYTES`]; aşan
//! dosya "okunamadı" sayılır.

use crate::live::Live;
use crate::pyfmt::{decimal_value, join_path, py_isspace, strip};
use crate::pyjson::Py;
use crate::ucli::state_dir_for;

/// Durum dosyası küçük bir JSON nesnesidir.
pub const STATUS_MAX_BYTES: u64 = 8 * 1024 * 1024;
/// Hata kaydı istem ve kısmi transkript taşır.
pub const RECORD_MAX_BYTES: u64 = 64 * 1024 * 1024;

/// `usage` nesnesinin alanları, [`LiveUsage`] alan sırasıyla.
pub const USAGE_FIELDS: [&str; 9] = [
    "requests",
    "reported",
    "prompt_tokens",
    "cached_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "request_bytes",
    "unmetered",
    "unmetered_bytes",
];

/// `phase` nesnesinin tam sayı alanları.
pub const PHASE_INT_FIELDS: [&str; 5] = ["since_unix", "attempt", "max_attempts", "wait_secs", "streamed_bytes"];

/// Süreç boyunca biriken sayaçlar ([`USAGE_FIELDS`]; eksik ya da bozuk alan 0).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct LiveUsage {
    pub requests: u64,
    pub reported: u64,
    pub prompt_tokens: u64,
    pub cached_tokens: u64,
    pub completion_tokens: u64,
    pub reasoning_tokens: u64,
    pub request_bytes: u64,
    pub unmetered: u64,
    pub unmetered_bytes: u64,
}

impl LiveUsage {
    /// Değerler [`USAGE_FIELDS`] sırasıyla.
    pub fn values(&self) -> [u64; 9] {
        [
            self.requests,
            self.reported,
            self.prompt_tokens,
            self.cached_tokens,
            self.completion_tokens,
            self.reasoning_tokens,
            self.request_bytes,
            self.unmetered,
            self.unmetered_bytes,
        ]
    }
}

/// Süren model çağrısının aşaması. Bilinmeyen sayı `None` kalır (0'a çekilmez).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LivePhase {
    pub name: String,
    /// [`PHASE_INT_FIELDS`] sırasıyla.
    pub ints: [Option<u64>; 5],
    pub detail: Option<String>,
    pub last_unix: Option<u64>,
}

/// Hatayla ölen tur kayıtlarının özeti.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FailedTurns {
    pub count: u64,
    pub last_unix: u64,
    pub last_error: Option<String>,
}

/// Durum dosyası meşgul mü: `waiting_for_stdin` boşta, geri kalan her şey (alan yoksa da) bir tur işliyor.
pub fn status_is_busy(status: &Py) -> bool {
    status.get("activity").and_then(Py::as_str) != Some("waiting_for_stdin")
}

/// `str.isdigit()` dizgisi mi ve değeri (yalnız ondalık rakamlar; Python üst simge rakamında istisna atar).
fn decimal_number(s: &str) -> Option<u64> {
    if s.is_empty() {
        return None;
    }
    s.chars().try_fold(0u64, |acc, c| Some(acc.saturating_mul(10).saturating_add(u64::from(decimal_value(c)?))))
}

fn capped(s: &str, max: usize) -> String {
    s.chars().take(max).collect()
}

impl Live<'_> {
    /// Okuyucuların sırayla bakacağı sohbet dizinleri: `--state-dir` açıksa ya da yeni dizin zaten varsa yeni + eski.
    pub fn chat_session_dirs(&self, cwd: &str) -> Vec<String> {
        let new = state_dir_for(&self.paths.ucli_state_root(), &self.probe.realpath(cwd));
        let old = join_path(&join_path(cwd, ".ucli"), "chat");
        if self.settings.ucli_state_dir() || self.probe.is_dir(&new) {
            vec![new, old]
        } else {
            vec![old]
        }
    }

    /// `filename`in var olan ilk yolu; yoksa birincil dizindeki yol.
    pub fn find_chat_file(&self, cwd: &str, filename: &str) -> String {
        let dirs = self.chat_session_dirs(cwd);
        dirs.iter()
            .map(|d| join_path(d, filename))
            .find(|p| self.probe.exists(p))
            .unwrap_or_else(|| join_path(&dirs[0], filename))
    }

    /// `{session}.status.json`; yok/bozuk/UTF-8 değil/nesne değilse None.
    pub fn read_status_file(&self, cwd: &str, session: &str) -> Option<Py> {
        let path = self.find_chat_file(cwd, &format!("{session}.status.json"));
        self.read_json(&path, STATUS_MAX_BYTES).filter(Py::is_object)
    }

    fn read_json(&self, path: &str, max: u64) -> Option<Py> {
        let data = self.probe.read_bytes(path, max)?;
        Py::parse(std::str::from_utf8(&data).ok()?)
    }

    /// `failed/<oturum>-<unix>-<n>.json` kayıtları `(unix, yol)`, eskiden yeniye. Ad TAM ayrıştırılır (ön ek eşlemesi yok).
    pub fn failed_turn_records(&self, cwd: &str, session: &str) -> Vec<(u64, String)> {
        let mut out: Vec<(u64, u64, String)> = Vec::new();
        for dir in self.chat_session_dirs(cwd) {
            let failed = join_path(&dir, "failed");
            let Some(names) = self.probe.list_dir(&failed) else { continue };
            for name in names {
                let Some(stem) = name.strip_suffix(".json") else { continue };
                let mut parts = stem.rsplitn(3, '-');
                let (Some(n), Some(unix), Some(owner)) = (parts.next(), parts.next(), parts.next()) else { continue };
                if owner != session {
                    continue;
                }
                let (Some(unix), Some(n)) = (decimal_number(unix), decimal_number(n)) else { continue };
                out.push((unix, n, join_path(&failed, &name)));
            }
        }
        out.sort();
        out.into_iter().map(|(unix, _, path)| (unix, path)).collect()
    }

    /// Oturum kimliği boş değilse durum dosyası.
    fn status_for(&self, cwd: &str, sid: Option<&str>) -> Option<Py> {
        self.read_status_file(cwd, sid.filter(|s| !s.is_empty())?)
    }

    pub(crate) fn ucli_busy(&self, cwd: &str, sid: Option<&str>) -> Option<bool> {
        self.status_for(cwd, sid).map(|s| status_is_busy(&s))
    }

    pub(crate) fn ucli_background_work(&self, cwd: &str, sid: Option<&str>) -> Option<u64> {
        self.status_for(cwd, sid)?.get("background_tasks")?.non_negative_int()
    }

    pub(crate) fn ucli_tools(&self, cwd: &str, sid: Option<&str>) -> Option<Vec<String>> {
        let status = self.status_for(cwd, sid)?;
        let Py::Array(names) = status.get("tools")? else { return None };
        names.iter().map(|n| n.as_str().filter(|s| !s.is_empty()).map(str::to_string)).collect()
    }

    /// `context_bytes / 4` (kaba token tahmini).
    pub(crate) fn ucli_context(&self, cwd: &str, sid: Option<&str>) -> Option<u64> {
        Some(self.status_for(cwd, sid)?.get("context_bytes")?.non_negative_int()? / 4)
    }

    pub(crate) fn ucli_usage(&self, cwd: &str, sid: Option<&str>) -> Option<LiveUsage> {
        let status = self.status_for(cwd, sid)?;
        let raw = status.get("usage").filter(|u| u.is_object())?;
        let v = USAGE_FIELDS.map(|k| raw.get(k).and_then(Py::non_negative_int).unwrap_or(0));
        let [requests, reported, prompt_tokens, cached_tokens, completion_tokens, reasoning_tokens, request_bytes, unmetered, unmetered_bytes] =
            v;
        Some(LiveUsage {
            requests,
            reported,
            prompt_tokens,
            cached_tokens,
            completion_tokens,
            reasoning_tokens,
            request_bytes,
            unmetered,
            unmetered_bytes,
        })
    }

    pub(crate) fn ucli_phase(&self, cwd: &str, sid: Option<&str>) -> Option<LivePhase> {
        let status = self.status_for(cwd, sid)?;
        let raw = status.get("phase").filter(|p| p.is_object())?;
        let name = strip(raw.get("name")?.as_str()?);
        if name.is_empty() {
            return None;
        }
        let detail = raw.get("detail").and_then(Py::as_str).map(strip).filter(|d| !d.is_empty());
        Some(LivePhase {
            name: capped(name, 40),
            ints: PHASE_INT_FIELDS.map(|k| raw.get(k).and_then(Py::non_negative_int)),
            detail: detail.map(|d| capped(d, 160)),
            last_unix: status.get("last_activity_unix").and_then(Py::non_negative_int),
        })
    }

    pub(crate) fn ucli_failed_turns(&self, cwd: &str, sid: Option<&str>) -> Option<FailedTurns> {
        let records = self.failed_turn_records(cwd, sid.filter(|s| !s.is_empty())?);
        let (last_unix, path) = records.last()?;
        Some(FailedTurns {
            count: records.len() as u64,
            last_unix: *last_unix,
            last_error: self.record_error(path),
        })
    }

    /// Kaydın `error` alanı tek satıra indirilmiş (160 karakter); okunamazsa ya da boşsa None.
    fn record_error(&self, path: &str) -> Option<String> {
        let record = self.read_json(path, RECORD_MAX_BYTES)?;
        let mut err = record.get("error")?.clone();
        if err.is_object() {
            err = match ["message", "error"].iter().find_map(|k| err.get(k).filter(|v| v.truthy())) {
                Some(v) => v.clone(),
                None => Py::Str(err.dumps()),
            };
        }
        if !err.truthy() {
            return None;
        }
        let text = err.py_str();
        let joined = text.split(py_isspace).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ");
        Some(capped(&joined, 160))
    }
}
