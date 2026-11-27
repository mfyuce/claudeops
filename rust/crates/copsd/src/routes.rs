//! Çekirdek yerel uçlarının kayıt yeri: her strangler izi crate'ini `copsd/Cargo.toml`a ekler ve [`register`]e TEK satır yazar.
//!
//! ```ignore
//! table.get("/api/files/*", cops_files::hook(&ctx.state_dir));                  // kimliği vekil denetler (yalnız GET)
//! table.own_auth("POST", "/api/start", cops_sessions::hook(&ctx.state_dir));    // kimlik + yetki kancada
//! ```
//!
//! Sözleşme [`cops_proxy::routes::RouteTable`] belgesinde; uç `front_force_proxy` dosyasıyla Python'a geri verilebilir.
//! Yeni kayıt `cops-parity/requests/endpoints.json`a en az bir `"expect": "local"` isteği ister (`tests/route_force.rs`).

use crate::state::ReadDocs;
use cops_proxy::routes::RouteTable;
use cops_state::settings_read::SysEnv;
use cops_state::StateDir;
use std::path::PathBuf;
use std::sync::Arc;

/// Kanca kurucularına verilen, copsd'nin çözdüğü ayarlar. Süreç başına BİR kez kurulur ([`RouteCtx::new`]); kancalar
/// `docs`u `Arc` ile paylaşır (ikinci bir `StateDocs` kurmaz: kirli/eşitlendi kayıtları ve önbellekler tek yerde).
#[derive(Debug, Clone)]
pub struct RouteCtx {
    /// Durum dizini ([`crate::state_dir`]); `docs.dir()` ile aynı.
    pub state_dir: PathBuf,
    /// `claudeops.db` (`--db`).
    pub db: PathBuf,
    /// `instances.json` (`--instances`).
    pub instances: PathBuf,
    /// Durum belgeleri, YALNIZ okuma (R2: tek yazar Python; bkz. [`crate::state`]).
    pub docs: Arc<ReadDocs>,
    /// `HOME`/`PATH` okuyan `cops-state` okuyucuları için süreç ortamı (açılışta bir kez alınır).
    pub env: SysEnv,
}

impl RouteCtx {
    /// `state_dir` altındaki durum belgeleri + süreç ortamı. Dosya/DB'ye dokunmaz.
    pub fn new(state_dir: PathBuf, db: PathBuf, instances: PathBuf) -> RouteCtx {
        RouteCtx {
            docs: Arc::new(ReadDocs::new(StateDir::at(&state_dir))),
            env: SysEnv::from_process(),
            state_dir,
            db,
            instances,
        }
    }
}

/// Çekirdek rota tablosu. Şimdilik boş: Dalga 2 izleri (B1+) satırlarını buraya ekler.
pub fn register(_table: &mut RouteTable, _ctx: &RouteCtx) {}
