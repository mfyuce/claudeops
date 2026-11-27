//! Crate'in G/Ç sınırlarının GERÇEK uygulaması: [`crate::Probe`]/[`crate::LiveProbe`] ([`probe::RealProbe`]),
//! [`crate::Effect`] uygulayıcısı ([`effects`]), [`crate::ModelIo`] ([`modelio::RealModelIo`]) ve
//! [`crate::AgySidStore`] ([`docs::DocAgySidStore`]). Çekirdek modüller saf kalır; dosya, süreç, ağ ve saat yalnız
//! buradadır.
//!
//! Tek atımlık çağrı ([`oneshot::OneShot`]) ve onay kaydının yazılan kısmı ([`approval::ApprovalStore`]). Canlı
//! pane ([`crate::tui::Pane`]): [`pane::TmuxPane`] (G4).
//!
//! [`probe::CostGate`] (gerçek: [`ledger::CostLedger`]) ve [`probe::SearchUrl`] (gerçek:
//! [`searxng::ManagedSearch`]) kurucuya dışarıdan verilir (süreç başına tek örnek). Başka ize ait bağımlılıklar:
//! [`probe::ProjectDirs`] (rs/proc `encode_cwd`), [`docs::DocStore`]un `db` kipi (rs/state `statedocs`).

pub mod agents;
pub mod approval;
pub mod checks;
pub mod diaglog;
pub mod docs;
pub mod effects;
pub mod env;
pub mod fsio;
pub mod help;
pub mod http;
pub mod launch;
pub mod ledger;
pub mod lock;
pub mod modelio;
pub mod oneshot;
pub mod oserr;
pub mod pane;
pub mod pathexec;
pub mod probe;
pub mod process;
pub mod proxy;
pub mod routing_sync;
pub mod runtime;
pub mod scan;
pub mod searxng;
pub mod sqlite;
pub mod startup_desktop;
pub mod tmux;

pub use env::Env;
pub use probe::{RealDeps, RealProbe};
