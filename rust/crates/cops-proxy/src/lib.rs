//! D0 saf vekil: dış porttaki HTTP istek ve WebSocket yükseltmelerini Python'un iç portuna aktarır.
//! Kimlik, yetki ve yönlendirme KARARI vermez; yalnız başlık temizler ve `X-Forwarded-For` ekler.

use bytes::Bytes;
use http_body_util::{combinators::BoxBody, BodyExt};
use hyper::body::Incoming;
use hyper::header::{HeaderName, HeaderValue, CONNECTION, UPGRADE};
use hyper::{Request, Response, StatusCode};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::{TokioExecutor, TokioIo};
use std::net::SocketAddr;
use std::sync::Arc;

pub type Body = BoxBody<Bytes, hyper::Error>;

/// Hop-by-hop başlıklar (RFC 9110 7.6.1); vekil iki yönde de düşürür (yükseltmede Connection/Upgrade korunur).
const HOP: [&str; 7] = ["keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "proxy-connection"];

// Upstream bağlantı HAVUZU KAPALI (pool_max_idle_per_host(0)): Python bazı POST uçlarında gövdeyi okumadan yanıtlıyor (ör. /api/ws-ticket),
// artık baytlar keep-alive bağlantıda sonraki isteğin başına yapışırdı ('{}GET' -> 501). Loopback'te yeni bağlantı maliyeti ihmal edilebilir.
/// Rust'un kendi cevapladığı yerel uçların bağımlılıkları (yoksa tüm istekler Python'a gider).
pub struct LocalCfg {
    pub token: cops_auth::Token,
    pub db: std::path::PathBuf,
}

pub struct Proxy {
    local: Option<LocalCfg>,
    upstream: SocketAddr,
    dist: Option<std::path::PathBuf>,
    secret: Option<HeaderValue>,
    client: Client<HttpConnector, Incoming>,
}

fn strip_hop(h: &mut hyper::HeaderMap, keep_upgrade: bool) {
    for n in HOP {
        h.remove(n);
    }
    if !keep_upgrade {
        h.remove(CONNECTION);
        h.remove(UPGRADE);
    }
}

fn is_upgrade(h: &hyper::HeaderMap) -> bool {
    h.get(CONNECTION).and_then(|v| v.to_str().ok()).map(|v| v.to_ascii_lowercase().contains("upgrade")).unwrap_or(false) && h.contains_key(UPGRADE)
}

fn err(code: StatusCode, msg: &str) -> Response<Body> {
    let b = http_body_util::Full::new(Bytes::from(msg.to_string())).map_err(|never| match never {}).boxed();
    Response::builder().status(code).header("content-type", "text/plain; charset=utf-8").body(b).unwrap()
}

fn json_resp(code: StatusCode, v: serde_json::Value) -> Response<Body> {
    let b = http_body_util::Full::new(Bytes::from(v.to_string())).map_err(|never| match never {}).boxed();
    Response::builder().status(code).header("content-type", "application/json; charset=utf-8").header("cache-control", "no-store").body(b).unwrap()
}

/// Python `end_headers`taki CSP ile BİREBİR aynı olmalı (py/tests/test_front_internal.py eşitlik testi okur).
pub const CSP: &str = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'";

fn mime(path: &std::path::Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "js" | "mjs" => "application/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "svg" => "image/svg+xml; charset=utf-8",
        "html" => "text/html; charset=utf-8",
        "json" | "map" => "application/json; charset=utf-8",
        "txt" => "text/plain; charset=utf-8",
        "png" => "image/png",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "webp" => "image/webp",
        _ => "application/octet-stream",
    }
}

/// `url_path` -> dist altında GERÇEK dosya (symlink/`..` kaçışı dist dışına çıkarsa None). Yalnız `/assets/*` ve `/favicon.svg`.
pub fn resolve_static(dist: &std::path::Path, url_path: &str) -> Option<std::path::PathBuf> {
    if !(url_path.starts_with("/assets/") || url_path == "/favicon.svg") {
        return None;
    }
    let root = dist.canonicalize().ok()?;
    let cand = root.join(url_path.trim_start_matches('/')).canonicalize().ok()?;
    if cand.starts_with(&root) && cand.is_file() { Some(cand) } else { None }
}

impl Proxy {
    fn try_static(&self, req: &Request<Incoming>) -> Option<Response<Body>> {
        let dist = self.dist.as_ref()?;
        let head = req.method() == hyper::Method::HEAD;
        if req.method() != hyper::Method::GET && !head {
            return None;
        }
        let f = resolve_static(dist, req.uri().path())?;
        let data = std::fs::read(&f).ok()?;
        let cache = if f.starts_with(dist.canonicalize().ok()?.join("assets")) { "public, max-age=31536000, immutable" } else { "no-cache" };
        let len = data.len();
        let body = if head { Bytes::new() } else { Bytes::from(data) };
        let b = http_body_util::Full::new(body).map_err(|n| match n {}).boxed();
        Some(
            Response::builder()
                .status(StatusCode::OK)
                .header("content-type", mime(&f))
                .header("content-length", len.to_string())
                .header("cache-control", cache)
                .header("x-content-type-options", "nosniff")
                .header("referrer-policy", "no-referrer")
                .header("x-frame-options", "DENY")
                .header("content-security-policy", CSP)
                .body(b)
                .unwrap(),
        )
    }

    pub fn new(upstream: SocketAddr) -> Arc<Self> {
        let client = Client::builder(TokioExecutor::new()).pool_max_idle_per_host(0).build_http();
        Arc::new(Proxy { local: None, upstream, dist: None, secret: None, client })
    }

    /// `dist` (py/webui/dist) verilirse `/assets/*` ve `/favicon.svg` (token'sız taşınan statikler) diskten Rust'ta sunulur; dosya yoksa
    /// istek Python'a aktarılır (404 kararı Python'da kalır). Gömülü DEĞİL: dist değişince yeniden başlatma gerekmez.
    pub fn with_dist(self: Arc<Self>, dist: std::path::PathBuf) -> Arc<Self> {
        let me = Arc::try_unwrap(self).ok().expect("tek sahip");
        Arc::new(Proxy { dist: Some(dist), ..me })
    }

    /// Yerel uçları aç (şimdilik `GET /api/steward/questions`): kimlik tek kullanıcı token'ı, veri `claudeops.db` (salt okunur).
    pub fn with_local(self: Arc<Self>, local: LocalCfg) -> Arc<Self> {
        let me = Arc::try_unwrap(self).ok().expect("tek sahip");
        Arc::new(Proxy { local: Some(local), ..me })
    }

    /// Yerel uç eşleşirse yanıt döner (kimlik DENETİMİ dahil); eşleşmezse None = Python'a aktar.
    async fn try_local(self: &Arc<Self>, req: &Request<Incoming>) -> Option<Response<Body>> {
        let local = self.local.as_ref()?;
        if req.method() != hyper::Method::GET || req.uri().path() != "/api/steward/questions" {
            return None;
        }
        let query = req.uri().query().unwrap_or("").to_string();
        let auth = req.headers().get("authorization").and_then(|v| v.to_str().ok());
        if !local.token.authorized(&query, auth) {
            return Some(json_resp(StatusCode::UNAUTHORIZED, serde_json::json!({"ok": false, "error": "unauthorized"})));
        }
        let db = local.db.clone();
        let out = tokio::task::spawn_blocking(move || cops_local::questions(&db, &query)).await;
        Some(match out {
            Ok(Ok(v)) => json_resp(StatusCode::OK, v),
            Ok(Err((code, m))) => json_resp(StatusCode::from_u16(code).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR), serde_json::json!({"ok": false, "error": m})),
            Err(_) => json_resp(StatusCode::INTERNAL_SERVER_ERROR, serde_json::json!({"ok": false, "error": "internal"})),
        })
    }

    /// Ön kapı gizlisi: Python'un `X-Forwarded-For`a güvenmesi için her aktarılan isteğe `X-Cops-Front` olarak eklenir;
    /// istemciden gelen aynı adlı başlık her zaman düşürülür.
    pub fn with_secret(upstream: SocketAddr, secret: &str) -> Arc<Self> {
        let client = Client::builder(TokioExecutor::new()).pool_max_idle_per_host(0).build_http();
        Arc::new(Proxy { local: None, upstream, dist: None, secret: HeaderValue::from_str(secret).ok(), client })
    }

    /// `peer`: bağlanan istemcinin adresi (X-Forwarded-For için). İstemcinin gönderdiği X-Forwarded-For'a GÜVENİLMEZ, üzerine yazılır.
    pub async fn handle(self: Arc<Self>, mut req: Request<Incoming>, peer: SocketAddr) -> Result<Response<Body>, hyper::Error> {
        // İç uçlar (`/api/_internal/*`) dışarıdan ASLA aktarılmaz: ön kapı gizlisi her aktarılan isteğe eklendiği için, aktarılırsa
        // herkes iç kimlik/bilet uçlarını güvenilir çağrıcı gibi çağırabilirdi. Yalnız Rust'un KENDİ iç çağrıları (loopback) bu yola gider.
        if req.uri().path().trim_start_matches('/').to_ascii_lowercase().starts_with("api/_internal") {
            return Ok(err(StatusCode::NOT_FOUND, "not found"));
        }
        if let Some(r) = self.try_static(&req) {
            return Ok(r);
        }
        if let Some(r) = self.try_local(&req).await {
            return Ok(r);
        }
        let upgrade = is_upgrade(req.headers());
        let pq = req.uri().path_and_query().map(|p| p.as_str().to_string()).unwrap_or_else(|| "/".into());
        let uri: hyper::Uri = match format!("http://{}{}", self.upstream, pq).parse() {
            Ok(u) => u,
            Err(_) => return Ok(err(StatusCode::BAD_REQUEST, "bad uri")),
        };
        let client_up = if upgrade { Some(hyper::upgrade::on(&mut req)) } else { None };
        *req.uri_mut() = uri;
        strip_hop(req.headers_mut(), upgrade);
        req.headers_mut().remove("x-cops-front");
        if let Some(sec) = &self.secret {
            req.headers_mut().insert(HeaderName::from_static("x-cops-front"), sec.clone());
        }
        req.headers_mut().insert(HeaderName::from_static("x-forwarded-for"), HeaderValue::from_str(&peer.ip().to_string()).unwrap());
        let mut resp = match self.client.request(req).await {
            Ok(r) => r,
            Err(e) => return Ok(err(StatusCode::BAD_GATEWAY, &format!("upstream: {e}"))),
        };
        if upgrade && resp.status() == StatusCode::SWITCHING_PROTOCOLS {
            let up_up = hyper::upgrade::on(&mut resp);
            if let Some(cu) = client_up {
                tokio::spawn(async move {
                    if let (Ok(c), Ok(u)) = (cu.await, up_up.await) {
                        let (mut c, mut u) = (TokioIo::new(c), TokioIo::new(u));
                        let _ = tokio::io::copy_bidirectional(&mut c, &mut u).await;
                    }
                });
            }
            let (parts, _b) = resp.into_parts();
            let empty = http_body_util::Empty::<Bytes>::new().map_err(|n| match n {}).boxed();
            return Ok(Response::from_parts(parts, empty));
        }
        let (mut parts, body) = resp.into_parts();
        strip_hop(&mut parts.headers, false);
        Ok(Response::from_parts(parts, body.boxed()))
    }
}

/// Dinleyici döngüsü: her bağlantıyı `Proxy::handle`a verir (HTTP/1, yükseltme açık).
pub async fn serve(listen: SocketAddr, proxy: Arc<Proxy>) -> std::io::Result<()> {
    let ln = tokio::net::TcpListener::bind(listen).await?;
    loop {
        let (sock, peer) = ln.accept().await?;
        let p = proxy.clone();
        tokio::spawn(async move {
            let svc = hyper::service::service_fn(move |r| p.clone().handle(r, peer));
            let _ = hyper::server::conn::http1::Builder::new().serve_connection(TokioIo::new(sock), svc).with_upgrades().await;
        });
    }
}
