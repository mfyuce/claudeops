//! Dalga 2 İz B1: salt okuma durum uçları, copsd rota tablosuna bağlanır (`copsd::routes::register`).
//!
//! - `GET /api/instances` YALNIZ yerel (`host` yok, boş ya da `local`): web.py `_instances_list()` + değnekçi rozeti.
//!   Uzak `host` için [`RouteHook::route`] `None` döner, istek bugünkü gibi Python'a gider (uzak vekil Python'da).
//! - `GET /api/diag/log`: web.py `{"lines": diag_log_tail(30)}`.
//!
//! Kimlik: ikisi de `RouteTable::get` (vekil denetler). Python eylem tablosunda `/api/instances` = `fleet.admin`,
//! `/api/diag/` = `admin.config`, kaynak `global`; enterprise yetkilendiricisinde global kaynakta bu eylemler yalnız
//! yöneticiye açık, K3 durum süzgeci bu uçlara UYGULANMAZ (web.py yanıtı süzmeden yazar). Kullanıcıya göre süzülen veri
//! olmadığı için vekil kimliği yeterli (gerekçe `docs/rs-ep-state.md` "Kimlik kararı").
//!
//! Yazım YOK (R2): durum [`StateDocs::into_read_only`] ile okunur; süreç taraması (`cops-procscan`) durum yazmaz, öğrenilen
//! agy eşlemesi (`Scan::agy_learned`) kalıcılaştırılmaz. Engelleyen G/Ç `spawn_blocking`te (R5).
pub mod badge;
pub mod diag;
pub mod instances;
pub mod pyjson;

use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::gate::{RouteHook, RouteRequest, RouteResponse};
use cops_state::{Json, StateDocs};
use std::path::PathBuf;
use std::sync::Arc;

/// Kayıt desenleri (copsd `register` ve testler).
pub const INSTANCES_PATH: &str = "/api/instances";
pub const DIAG_LOG_PATH: &str = "/api/diag/log";

/// GET gövdesi okunur ve atılır (Python `do_GET` gövdeyi okumaz, `end_headers` boşaltır).
const BODY_LIMIT: usize = 64 * 1024;

/// web.py `_json(obj)`: 200, `Content-Type: application/json; charset=utf-8`, gövde `json.dumps(obj)`.
pub fn json_response(v: &Json) -> RouteResponse {
    RouteResponse {
        status: 200,
        headers: vec![(
            "Content-Type".into(),
            "application/json; charset=utf-8".into(),
        )],
        body: pyjson::dumps(v).into_bytes(),
    }
}

/// web.py `_host_from_qs`: `(parse_qs(q).get("host") or ["local"])[0].strip() or "local"` yerel mi.
pub fn local_host(raw_query: &str) -> bool {
    match cops_auth::query_param(raw_query, "host") {
        None => true,
        Some(v) => {
            let h = cops_state::pycompat::strip(&v);
            h.is_empty() || h == "local"
        }
    }
}

/// `spawn_blocking`te hesaplar; panik ya da hata 500 (Python'un istisna verdiği durumlar, bkz. [`instances::ListError`]).
async fn blocking(
    what: &'static str,
    f: impl FnOnce() -> Result<Json, String> + Send + 'static,
) -> RouteResponse {
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(v)) => json_response(&v),
        Ok(Err(e)) => {
            eprintln!("copsd: {what}: {e}");
            RouteResponse::error(500, "internal error")
        }
        Err(e) => {
            eprintln!("copsd: {what}: görev düştü: {e}");
            RouteResponse::error(500, "internal error")
        }
    }
}

/// `GET /api/instances` (yerel dal).
pub struct InstancesHook {
    docs: Arc<StateDocs>,
    /// `None` (ör. `HOME` yok: Python parola veritabanına düşer, `docs/rs-proc.md` madde 12) = her istek Python'a.
    scan: Option<cops_procscan::Config>,
}

impl InstancesHook {
    /// `docs` SALT OKUMA kipinde olmalı (değilse panik: R2 ihlali açılışta görünür).
    pub fn new(docs: Arc<StateDocs>, scan: Option<cops_procscan::Config>) -> InstancesHook {
        assert!(
            docs.is_read_only(),
            "cops-ep-state: StateDocs salt okuma kipinde değil"
        );
        InstancesHook { docs, scan }
    }
}

impl RouteHook for InstancesHook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        if view.method != "GET" || view.path != INSTANCES_PATH || self.scan.is_none() {
            return None;
        }
        local_host(&view.raw_query).then_some(BODY_LIMIT)
    }

    fn handle(&self, _req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        let docs = self.docs.clone();
        let scan = self.scan.clone();
        Box::pin(blocking("/api/instances", move || {
            let cfg = scan.ok_or("süreç taraması yapılandırılmadı")?;
            let live = instances::live_names(&cfg).map_err(|e| e.to_string())?;
            instances::payload(&docs, &live).map_err(|e| e.to_string())
        }))
    }
}

/// `GET /api/diag/log`.
pub struct DiagLogHook {
    path: PathBuf,
}

impl DiagLogHook {
    /// `path` = [`diag::diag_log_path`].
    pub fn new(path: PathBuf) -> DiagLogHook {
        DiagLogHook { path }
    }
}

impl RouteHook for DiagLogHook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (view.method == "GET" && view.path == DIAG_LOG_PATH).then_some(BODY_LIMIT)
    }

    fn handle(&self, _req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        let path = self.path.clone();
        Box::pin(blocking("/api/diag/log", move || Ok(diag::payload(&path))))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn host_query_like_python() {
        for (q, want) in [
            ("", true),
            ("host=local", true),
            ("host=", true),
            ("host=%20", true),
            ("host=+local+", true),
            ("lang=en&host=&host=local", true),
            ("host=yuhem", false),
            ("host=&host=yuhem", false),
            ("ho%73t=yuhem", false),
            ("host=Local", false),
            ("host=local&host=yuhem", true),
            ("host=%1flocal", true), // Python strip U+001F'i de kırpar
        ] {
            assert_eq!(local_host(q), want, "{q}");
        }
    }
}
