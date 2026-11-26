//! Crate'in G/Ç sınırlarının GERÇEK uygulaması: [`crate::Probe`]/[`crate::LiveProbe`] ([`probe::RealProbe`]),
//! [`crate::Effect`] uygulayıcısı ([`effects`]) ve
//! [`crate::AgySidStore`] ([`docs::DocAgySidStore`]). Çekirdek modüller saf kalır; dosya, süreç, ağ ve saat yalnız
//! buradadır.
//!
//! Henüz burada OLMAYAN (ikinci parça / başka iz) bağımlılıklar kurucuya dışarıdan verilir:
//! [`probe::CostGate`] (maliyet defteri), [`probe::SearchUrl`] (SearXNG), [`probe::ProjectDirs`] (rs/proc
//! `encode_cwd`), [`docs::DocStore`]un `db` kipi (rs/state `statedocs`).

pub mod agents;
pub mod checks;
pub mod diaglog;
pub mod docs;
pub mod effects;
pub mod env;
pub mod fsio;
pub mod help;
pub mod lock;
pub mod oserr;
pub mod pathexec;
pub mod probe;
pub mod process;
pub mod sqlite;

pub use env::Env;
pub use probe::{RealDeps, RealProbe};
