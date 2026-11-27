//! Dalga 2 İz B2a: terminal OKUMA uçları, copsd rota tablosuna bağlanır (`copsd::routes::register`).
//!
//! - `GET /api/term/output` (web.py `_term_output` + `web_term_lite.to_lite`, `viewport=1` = `_term_output_viewport`)
//! - `GET /api/term/history` (web.py `_term_history`)
//!
//! YALNIZ yerel pane (`host` yok, boş ya da `local`); uzak `host` ve imzalı kimlik iletimi taşıyan istek (`X-Cops-Fwd*`
//! başlığı) için [`RouteHook::route`] `None` döner: istek bugünkü gibi Python'a gider. Kimlik `RouteTable::get` (vekil):
//! Python eylemi `term.read`, kaynak `session(host, name)`; yanıt kullanıcıya göre SÜZÜLMEZ (K3 `filter_status` bu uçlarda
//! yok), yetki kararı yalnız istekteki ada bağlı, vekil aynı kaynakla karar verir (`docs/rs-ep-term.md` "Kimlik kararı").
//!
//! Yazım YOK: tmux yalnız okunur (copy-mode yok, tuş yok), durum belgeleri salt okuma kipinde, süreç taraması kalıcı bir şey
//! yazmaz. Python'un bellek durumundan (R3) yalnız çözüm önbelleği taşınır: süresi Python'la AYNI (30 sn), ama Python'un
//! `/ws/term` ile paylaştığı önbellekten AYRI (yalnız bu iki ucun). Engelleyen G/Ç `spawn_blocking`te (R5), yanıt tamponlu
//! (R6). `cops-steward-core`a bağlanmaz (R1).
pub mod err;
pub mod frame;
pub mod lite;
pub mod mode;
pub mod resolve;

use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::gate::{RouteHook, RouteRequest, RouteResponse};
use cops_state::{Json, StateDocs};
use cops_tmux::Tmux;
use resolve::{Live, Probe, Resolver};
use std::sync::Arc;

pub const OUTPUT_PATH: &str = "/api/term/output";
pub const HISTORY_PATH: &str = "/api/term/history";

/// GET gövdesi okunur ve atılır (Python `do_GET` gövdeyi okumaz).
const BODY_LIMIT: usize = 64 * 1024;

/// Üretim [`Probe`]: `/proc` taraması (`cops-procscan`), `instances.json` (salt okuma), bu soketin tmux'u.
pub struct SysProbe {
    pub scan: cops_procscan::Config,
    pub docs: Arc<StateDocs>,
    pub tmux: Tmux,
}

impl Probe for SysProbe {
    fn sessions(&self) -> Result<Vec<Live>, String> {
        let scan = cops_procscan::find_sessions(&self.scan, cops_procscan::CpuMode::Skip);
        if let Some(e) = scan.diag.proc_root_error {
            return Err(format!("süreç tablosu okunamadı: {e}"));
        }
        Ok(scan
            .sessions
            .into_iter()
            .map(|s| Live {
                name: s.name,
                pid: s.pid,
                cli: s.cli,
            })
            .collect())
    }

    fn registered(&self, name: &str) -> bool {
        // Python `get_instance(name) is not None`: değeri `null` olan kayıt da "yok"
        !matches!(
            cops_state::instances::Instances::new(&self.docs).get(name),
            None | Some(Json::Null)
        )
    }

    fn tmux_backed(&self, pid: u32) -> bool {
        self.tmux.is_tmux_backed(pid)
    }

    fn has_session(&self, name: &str) -> bool {
        self.tmux.has_session(name).unwrap_or(false)
    }
}

/// İki ucun paylaştığı bağlam: tek çözüm önbelleği (Python'da da iki uç aynı önbelleği kullanır).
pub struct Term {
    probe: Box<dyn Probe>,
    tmux: Tmux,
    cache: Resolver,
}

impl Term {
    pub fn new(probe: Box<dyn Probe>, tmux: Tmux) -> Arc<Term> {
        Arc::new(Term {
            probe,
            tmux,
            cache: Resolver::default(),
        })
    }

    /// Önbellek süresi testler için.
    pub fn with_resolver(probe: Box<dyn Probe>, tmux: Tmux, cache: Resolver) -> Arc<Term> {
        Arc::new(Term { probe, tmux, cache })
    }

    pub fn tmux(&self) -> &Tmux {
        &self.tmux
    }
}

/// web.py `_host_from_qs` yerel mi + imzalı iletim başlığı yok mu.
fn local_and_unsigned(view: &RequestView) -> bool {
    cops_ep_state::local_host(&view.raw_query)
        && !view
            .headers
            .iter()
            .any(|(k, _)| k.to_ascii_lowercase().starts_with("x-cops-fwd"))
}

fn q(raw: &str, k: &str) -> String {
    cops_auth::query_param(raw, k).unwrap_or_default()
}

/// `name`: `(qs.get("name") or [""])[0].strip()`; `lang`: yalnız tam `"en"`.
fn name_lang(raw: &str) -> (String, bool) {
    (
        cops_state::pycompat::strip(&q(raw, "name")).to_string(),
        q(raw, "lang") == "en",
    )
}

/// web.py `_json(obj, status)`.
fn respond(status: u16, v: &Json) -> RouteResponse {
    let mut r = cops_ep_state::json_response(v);
    r.status = status;
    r
}

async fn blocking(
    what: &'static str,
    f: impl FnOnce() -> Result<Json, String> + Send + 'static,
) -> RouteResponse {
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(v)) => respond(200, &v),
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

/// `GET /api/term/output` (yerel dal).
pub struct OutputHook(pub Arc<Term>);

impl RouteHook for OutputHook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (view.method == "GET" && view.path == OUTPUT_PATH && local_and_unsigned(view))
            .then_some(BODY_LIMIT)
    }

    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        let raw = req.view.raw_query;
        let (name, en) = name_lang(&raw);
        Box::pin(async move {
            if name.is_empty() {
                return respond(400, &err::err(en, err::Key::NameRequired, "", ""));
            }
            let lite = q(&raw, "lite") == "1";
            let viewport = q(&raw, "viewport") == "1";
            let t = self.0.clone();
            blocking("/api/term/output", move || {
                frame::output_payload(&*t.probe, &t.tmux, &t.cache, &name, en, lite, viewport)
            })
            .await
        })
    }
}

/// `GET /api/term/history` (yerel dal).
pub struct HistoryHook(pub Arc<Term>);

impl RouteHook for HistoryHook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (view.method == "GET" && view.path == HISTORY_PATH && local_and_unsigned(view))
            .then_some(BODY_LIMIT)
    }

    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        let raw = req.view.raw_query;
        let (name, en) = name_lang(&raw);
        Box::pin(async move {
            if name.is_empty() {
                return respond(400, &err::err(en, err::Key::NameRequired, "", ""));
            }
            let int =
                |k: &str| cops_state::pycompat::parse_int(&q(&raw, k)).map(|n| n.saturating_i64());
            let (Some(start), Some(end)) = (int("start"), int("end")) else {
                return respond(400, &err::err(en, err::Key::InvalidRange, "", ""));
            };
            let t = self.0.clone();
            blocking("/api/term/history", move || {
                frame::term_history(&*t.probe, &t.tmux, &t.cache, &name, start, end, en)
            })
            .await
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_parsing_like_python() {
        assert_eq!(name_lang("name=%20a%20&lang=en"), ("a".into(), true));
        assert_eq!(name_lang("name=&name=b&lang=EN"), ("b".into(), false));
        assert_eq!(name_lang("name=\u{1c}x"), ("x".into(), false));
        assert_eq!(name_lang("lang=en&lang=tr"), ("".into(), true));
    }

    fn view(q: &str, headers: &[(&str, &str)]) -> RequestView {
        RequestView {
            method: "GET".into(),
            path: OUTPUT_PATH.into(),
            raw_query: q.into(),
            headers: headers
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            client_ip: std::net::IpAddr::from([127, 0, 0, 1]),
            peer_loopback: true,
        }
    }

    #[test]
    fn remote_host_and_signed_requests_go_to_python() {
        assert!(local_and_unsigned(&view("name=a", &[])));
        assert!(local_and_unsigned(&view("name=a&host=local", &[])));
        assert!(!local_and_unsigned(&view("name=a&host=yuhem", &[])));
        assert!(!local_and_unsigned(&view("name=a", &[("x-cops-fwd", "1")])));
        assert!(!local_and_unsigned(&view(
            "name=a",
            &[("X-Cops-Fwd-Sig", "1")]
        )));
    }
}
