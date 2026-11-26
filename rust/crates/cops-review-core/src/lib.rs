//! Reviewer'ın saf çekirdeği (Python `claudeops/review.py` karşılığı): planlama, istem üretimi, bulgu ayrıştırma,
//! bulgu durum makinesi ve `review_pool.json` / `review_history.json` / `findings.json` depoları.
//! Koşucu (süreç başlatma, tick, API) bu crate'te YOK. Eşleme tablosu ve kararlar: `docs/rs-rev.md`.
pub mod agy;
pub mod clock;
pub mod error;
pub mod export;
pub mod flow;
pub mod limits;
pub mod parse;
pub mod paths;
pub mod planner;
pub mod prompts;
pub mod py;
pub mod redact;
pub mod report;
pub mod store;
pub mod targets;
mod unicode13;

pub use error::{Error, Result};
pub use parse::{Finding, Verdict};
pub use store::{ReviewPaths, ReviewStore};
pub use targets::{ReviewConfig, ReviewTarget};
