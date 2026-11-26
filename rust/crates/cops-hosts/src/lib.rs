//! Federasyon istemcisi: bu panelin uzak claudeops panellerine konuştuğu taraf (Python `web_hosts` + `hosts` +
//! `web_grpc` istemci tarafı). Durum dosyalarına dokunmaz: host kayıtları parametre/[`HostSource`] ile verilir.
//! Kararlar ve ders listesi karşılıkları: `docs/rs-hosts.md`.

pub mod consts;
pub mod endpoint;
pub mod events;
pub mod federation;
pub mod flight;
pub mod grpc;
pub mod guard;
pub mod health;
pub mod http;
pub mod net;
pub mod proxy;
pub mod push;
pub mod record;
pub mod relay;
pub mod sign;
pub mod status;
pub mod tier;
mod ws;

pub use federation::{Federation, HostSource, PollerHealth, Running};
pub use proxy::{GetOpts, HostClient, Reply};
pub use record::{HostRecord, Secret};
pub use relay::TermOpts;
pub use sign::{Caller, OutboundRefused, OutboundSigner};
pub use tier::Tier;
