//! Çekirdek yerel uçlarının kayıt yeri: her strangler izi crate'ini `copsd/Cargo.toml`a ekler ve [`register`]e TEK satır yazar.
//!
//! ```ignore
//! table.get("/api/files/*", cops_files::hook(&ctx.state_dir));                  // kimliği vekil denetler (yalnız GET)
//! table.own_auth("POST", "/api/start", cops_sessions::hook(&ctx.state_dir));    // kimlik + yetki kancada
//! ```
//!
//! Sözleşme [`cops_proxy::routes::RouteTable`] belgesinde; uç `front_force_proxy` dosyasıyla Python'a geri verilebilir.

use cops_proxy::routes::RouteTable;
use std::path::PathBuf;

/// Kanca kurucularına verilen, copsd'nin çözdüğü ayarlar.
#[derive(Debug, Clone)]
pub struct RouteCtx {
    /// Durum dizini ([`crate::state_dir`]).
    pub state_dir: PathBuf,
    /// `claudeops.db` (`--db`).
    pub db: PathBuf,
    /// `instances.json` (`--instances`).
    pub instances: PathBuf,
}

/// Çekirdek rota tablosu. Şimdilik boş: Dalga 1 izleri satırlarını buraya ekler.
pub fn register(_table: &mut RouteTable, _ctx: &RouteCtx) {}
