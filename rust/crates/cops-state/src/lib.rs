//! claudeops durum katmanı (Rust): Python `paths.py`, `store.py`, `statedocs.py`, `settings.py` (okuma), `roster.py` +
//! `web.py` TSV yazımı ve `instances.py` karşılığı. Aynı dosyaları Python ile BİRLİKTE kullanır: aynı kilit dosyaları, aynı
//! bayt biçimi, DB göçü YOK (yalnız sürüm denetimi). Genel API ve Python'dan bilinçli sapmalar: `docs/rs-state.md`.
mod diaglog;
pub mod fsutil;
pub mod instances;
pub mod json;
pub mod paths;
pub mod pycompat;
pub mod pytime;
pub mod roster;
pub mod settings;
pub mod settings_read;
mod sha256;
pub mod statedocs;
pub mod steward_settings;
pub mod store;
mod unicode_tables;

pub use json::{Json, Map};
pub use paths::{StateDir, TestEnv};
pub use statedocs::{Backend, StateDocs, WriteOutcome};
pub use store::{Store, StoreError};

/// `time.time()` karşılığı (epoch saniye, kesirli).
pub fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}
