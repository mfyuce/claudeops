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
use cops_state::{StateDir, StateDocs};
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
    /// B1: `cops-state` okuyucuları (`Instances`, ayarlar) için SALT OKUMA kipindeki `StateDocs`
    /// ([`StateDocs::into_read_only`]: içe aktarma/uydurma/günlük/yan dosya yok, yazım reddedilir). `docs`taki ile aynı
    /// dizin ve kip kuralı; ayrı nesne çünkü `ReadDocs` içindekini dışarı vermez (`state.rs` B1 yol listesinde değil).
    pub state: Arc<StateDocs>,
    /// `HOME`/`PATH` okuyan `cops-state` okuyucuları için süreç ortamı (açılışta bir kez alınır).
    pub env: SysEnv,
}

impl RouteCtx {
    /// `state_dir` altındaki durum belgeleri + süreç ortamı. Dosya/DB'ye dokunmaz.
    pub fn new(state_dir: PathBuf, db: PathBuf, instances: PathBuf) -> RouteCtx {
        RouteCtx {
            docs: Arc::new(ReadDocs::new(StateDir::at(&state_dir))),
            state: Arc::new(
                StateDocs::new(StateDir::at(&state_dir))
                    .into_read_only()
                    .with_logger(|m| eprintln!("copsd: statedocs {m}")),
            ),
            env: SysEnv::from_process(),
            state_dir,
            db,
            instances,
        }
    }
}

/// Çekirdek rota tablosu (Dalga 2 izleri satırlarını buraya ekler).
///
/// B1 (`cops-ep-state`, `docs/rs-ep-state.md`): `GET /api/instances` (yalnız yerel `host`; uzak istek Python'a) ve
/// `GET /api/diag/log`. `--instances` durum dizinindeki `instances.json`dan farklıysa `/api/instances` KAYDEDİLMEZ (Python
/// `instances.json`u yalnız durum dizininde bilir).
pub fn register(table: &mut RouteTable, ctx: &RouteCtx) {
    let dir = StateDir::at(&ctx.state_dir);
    if ctx.instances == dir.instances_json() {
        let scan = ctx
            .env
            .home
            .as_deref()
            .filter(|h| !h.is_empty())
            .map(|h| cops_procscan::Config::for_dirs(std::path::Path::new(h), &ctx.state_dir));
        table.get(
            cops_ep_state::INSTANCES_PATH,
            Arc::new(cops_ep_state::InstancesHook::new(ctx.state.clone(), scan)),
        );
    } else {
        eprintln!(
            "copsd: /api/instances Python'da: --instances {} durum dizini dışında",
            ctx.instances.display()
        );
    }
    let diag =
        cops_ep_state::diag::diag_log_path(&ctx.state_dir, std::env::var_os("CLAUDEOPS_DIAG_LOG"));
    table.get(
        cops_ep_state::DIAG_LOG_PATH,
        Arc::new(cops_ep_state::DiagLogHook::new(diag)),
    );
}
