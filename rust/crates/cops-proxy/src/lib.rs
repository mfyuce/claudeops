//! D0 saf vekil: dış porttaki HTTP istek ve WebSocket yükseltmelerini Python'un iç portuna aktarır.
//! Python'a aktarılan isteklerde kimlik, yetki ve yönlendirme KARARI vermez; yalnız başlık temizler ve `X-Forwarded-For` ekler.
//! İstisnalar: Rust yerel uçları ve uygulama mount'ları (`mount.rs`, `/<id>/` -> derbent): bunlarda kimliği copsd kendisi denetler.

pub mod gate;
pub mod mount;
pub mod resources;

use bytes::Bytes;
use http_body_util::{combinators::BoxBody, BodyExt};
use hyper::body::Incoming;
use hyper::header::{
    HeaderName, HeaderValue, ACCEPT, AUTHORIZATION, CACHE_CONTROL, CONNECTION, CONTENT_LENGTH,
    CONTENT_TYPE, COOKIE, LOCATION, SET_COOKIE, UPGRADE,
};
use hyper::{Request, Response, StatusCode};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::{TokioExecutor, TokioIo};
use std::net::SocketAddr;
use std::sync::Arc;

pub type Body = BoxBody<Bytes, hyper::Error>;

/// Hop-by-hop başlıklar (RFC 9110 7.6.1); vekil iki yönde de düşürür (yükseltmede Connection/Upgrade korunur).
const HOP: [&str; 7] = [
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "proxy-connection",
];

// Upstream bağlantı HAVUZU KAPALI (pool_max_idle_per_host(0)): Python bazı POST uçlarında gövdeyi okumadan yanıtlıyor (ör. /api/ws-ticket),
// artık baytlar keep-alive bağlantıda sonraki isteğin başına yapışırdı ('{}GET' -> 501). Loopback'te yeni bağlantı maliyeti ihmal edilebilir.
/// Rust'un kendi cevapladığı yerel uçların bağımlılıkları (yoksa tüm istekler Python'a gider).
pub struct LocalCfg {
    pub token: cops_auth::Token,
    pub db: std::path::PathBuf,
}

/// Metrik uçları: depo + kimlik (web.token YA DA loopback + ön kapı gizlisi `X-Cops-Front`).
pub struct MetricsCfg {
    pub store: Arc<cops_metrics::Store>,
    pub token: cops_auth::Token,
    pub front_secret: cops_auth::Token,
}

/// Uygulama mount'ları (`/<id>/` -> yerel derbent loopback portu): canlı tablo + panel kimliği (web.token ve `cops_ext` çerezi).
pub struct MountCfg {
    pub mounts: Arc<mount::Mounts>,
    pub token: cops_auth::Token,
}

pub struct Proxy {
    local_auth: Option<Arc<dyn gate::LocalAuth>>,
    mounts: Option<MountCfg>,
    metrics: Option<MetricsCfg>,
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
    h.get(CONNECTION)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_ascii_lowercase().contains("upgrade"))
        .unwrap_or(false)
        && h.contains_key(UPGRADE)
}

fn err(code: StatusCode, msg: &str) -> Response<Body> {
    let b = http_body_util::Full::new(Bytes::from(msg.to_string()))
        .map_err(|never| match never {})
        .boxed();
    Response::builder()
        .status(code)
        .header("content-type", "text/plain; charset=utf-8")
        .body(b)
        .unwrap()
}

fn json_resp(code: StatusCode, v: serde_json::Value) -> Response<Body> {
    let b = http_body_util::Full::new(Bytes::from(v.to_string()))
        .map_err(|never| match never {})
        .boxed();
    Response::builder()
        .status(code)
        .header("content-type", "application/json; charset=utf-8")
        .header("cache-control", "no-store")
        .body(b)
        .unwrap()
}

/// İstemci https mi: copsd TLS sonlandırmaz; https yalnız AYNI makinedeki ön uçtan (tünel, ters vekil: loopback eş) gelen
/// `X-Forwarded-Proto: https` ile kabul edilir. Uzak eşin gönderdiği başlığa güvenilmez (X-Forwarded-For ezme kuralıyla aynı ilke).
pub fn client_https(h: &hyper::HeaderMap, peer: SocketAddr) -> bool {
    peer.ip().is_loopback()
        && h.get("x-forwarded-proto")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.split(',').next())
            .is_some_and(|v| v.trim().eq_ignore_ascii_case("https"))
}

/// `Cf-Connecting-IP`yi yalnız AYNI makinedeki tünel (loopback eş) söyleyebilir: uzak eşinki silinir (Python giriş hız
/// sınırı istemci IP'sini bu başlıktan okur; sahtesi sınırı aşmaya yarardı).
pub fn drop_untrusted_client_ip(h: &mut hyper::HeaderMap, peer: SocketAddr) {
    if !peer.ip().to_canonical().is_loopback() {
        h.remove("cf-connecting-ip");
    }
}

/// Kimlik sağlayıcısına verilen salt okunur istek görünümü. Başlık adları küçük harf, sıra istekteki sıra; değer baytları
/// Latin-1 olarak çözülür (Python `http.server` başlıkları böyle okur). `client_ip` bağlanan eşin adresidir.
pub fn request_view<B>(req: &Request<B>, peer: SocketAddr) -> cops_auth::authz::RequestView {
    let ip = peer.ip().to_canonical();
    cops_auth::authz::RequestView {
        method: req.method().as_str().to_string(),
        path: req.uri().path().to_string(),
        raw_query: req.uri().query().unwrap_or("").to_string(),
        headers: req
            .headers()
            .iter()
            .map(|(k, v)| {
                (
                    k.as_str().to_string(),
                    v.as_bytes().iter().map(|b| char::from(*b)).collect(),
                )
            })
            .collect(),
        client_ip: ip,
        peer_loopback: ip.is_loopback(),
    }
}

fn forbidden() -> Response<Body> {
    json_resp(
        StatusCode::FORBIDDEN,
        serde_json::json!({"ok": false, "error": "forbidden"}),
    )
}

/// Python web.py ile aynı öznitelikler (`Path=/` panel ile mount arasında aynı çerez geçsin diye); `Secure` yalnız istemci https ise.
pub fn ext_cookie(value: &str, secure: bool) -> String {
    format!(
        "{}={value}; Path=/; HttpOnly; SameSite=Strict{}",
        cops_auth::COOKIE_NAME,
        if secure { "; Secure" } else { "" }
    )
}

/// Yolun ilk parçası (sorgu/fragment atılır); boşsa None.
fn first_segment(path: &str) -> Option<&str> {
    let p = path.split(['?', '#']).next()?;
    p.strip_prefix('/')?
        .split('/')
        .next()
        .filter(|s| !s.is_empty())
}

/// `/<id>/...` ya da `/<id>` yolunun kimliği.
fn path_id(path: &str) -> Option<String> {
    path.strip_prefix('/')?
        .split('/')
        .next()
        .filter(|i| !i.is_empty())
        .map(str::to_string)
}

/// Köke göre yazılan isteği taşıyan uygulama çerezi (rootrel mount kimliği).
pub const APP_COOKIE: &str = "cops_app";

/// Panelin KENDİ yolları: bu yollar `cops_app` çerezi olsa bile panele gider (Referer'lı olanlar önce uygulamaya, bkz. `handle`).
/// Kaynak: py/claudeops/commands/web.py do_GET/do_POST (`/` (5396), `/ws*`, `/api/*`, `/assets/*` + `/favicon.svg` (5347), `/q/*` (5351),
/// `/readfile/*` (5356), `/v1/*` (5029), `/desktop/*` (5419)); mount.rs `RESERVED`; enterprise `register_route` önekleri (`/readlist/`, `/missing/`);
/// `/index.html` copsd `try_static` ile aynı kökün parçası.
pub fn is_panel_path(path: &str) -> bool {
    if path == "/" || path == "/index.html" || path == "/favicon.svg" {
        return true;
    }
    let seg = path.trim_start_matches('/');
    let first = seg.split('/').next().unwrap_or("");
    mount::RESERVED.contains(&first)
}

/// İstekteki `cops_app` değerleri arasında geçerli (mount kimliği biçimli) ilk değer.
fn app_cookie_id(h: &hyper::HeaderMap) -> Option<String> {
    h.get_all(COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|c| c.split(';'))
        .filter_map(|kv| kv.trim().split_once('='))
        .find(|(k, v)| *k == APP_COOKIE && mount::valid_id(v))
        .map(|(_, v)| v.to_string())
}

/// Panel çerezlerini (`cops_*`: `cops_ext`, enterprise `cops_t`) siler, diğerlerini sırasıyla tek `Cookie` başlığında birleştirir.
pub fn strip_panel_cookies(h: &mut hyper::HeaderMap) {
    if !h.contains_key(COOKIE) {
        return;
    }
    let kept: Vec<String> = h
        .get_all(COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(';'))
        .map(|p| p.trim())
        .filter(|p| {
            !p.is_empty()
                && !p
                    .split_once('=')
                    .map_or(*p, |(k, _)| k)
                    .trim()
                    .starts_with("cops_")
        })
        .map(|p| p.to_string())
        .collect();
    h.remove(COOKIE);
    if !kept.is_empty() {
        if let Ok(v) = HeaderValue::from_str(&kept.join("; ")) {
            h.insert(COOKIE, v);
        }
    }
}

fn unauthorized(html: bool) -> Response<Body> {
    let (ct, msg) = if html {
        ("text/html; charset=utf-8", "<!doctype html><meta charset=\"utf-8\"><title>401</title><p>401: panel oturumu yok. Paneli token ile açıp bağlantıyı yeniden deneyin.</p>\n")
    } else {
        ("text/plain; charset=utf-8", "unauthorized\n")
    };
    let b = http_body_util::Full::new(Bytes::from_static(msg.as_bytes()))
        .map_err(|never| match never {})
        .boxed();
    let mut r = Response::new(b);
    *r.status_mut() = StatusCode::UNAUTHORIZED;
    let h = r.headers_mut();
    h.insert(CONTENT_TYPE, HeaderValue::from_static(ct));
    h.insert(CACHE_CONTROL, HeaderValue::from_static("no-store"));
    h.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    h.insert(
        "content-security-policy",
        HeaderValue::from_static("default-src 'none'; frame-ancestors 'none'"),
    );
    r
}

fn redirect(code: StatusCode, loc: &str, set_cookie: Option<HeaderValue>) -> Response<Body> {
    let b = http_body_util::Empty::<Bytes>::new()
        .map_err(|never| match never {})
        .boxed();
    let mut r = Response::new(b);
    *r.status_mut() = code;
    let h = r.headers_mut();
    h.insert(
        LOCATION,
        HeaderValue::from_str(loc).unwrap_or_else(|_| HeaderValue::from_static("/")),
    );
    h.insert(CACHE_CONTROL, HeaderValue::from_static("no-store"));
    h.insert(CONTENT_LENGTH, HeaderValue::from_static("0"));
    if let Some(c) = set_cookie {
        h.insert(SET_COOKIE, c);
    }
    r
}

/// Saf yönlendirici (birim testlenebilir): POST points gövdesi `[{name,key?,owner?,unit?,ts?,value,meta?}]` ya da tek nesne.
pub fn metrics_handle(
    st: &cops_metrics::Store,
    path: &str,
    query: &str,
    body: &[u8],
    now: f64,
) -> Result<serde_json::Value, (u16, String)> {
    let q = |k: &str| cops_auth::query_param(query, k);
    let num = |k: &str, d: f64| -> Result<f64, (u16, String)> {
        q(k).filter(|v| !v.is_empty()).map_or(Ok(d), |v| {
            v.parse::<f64>()
                .ok()
                .filter(|x| x.is_finite())
                .ok_or_else(|| (400, format!("bad {k}")))
        })
    };
    let e500 = |e: String| (500u16, e);
    match path {
        "/api/metrics/points" => {
            let v: serde_json::Value =
                serde_json::from_slice(body).map_err(|_| (400u16, "bad json".to_string()))?;
            let items: Vec<serde_json::Value> = match v {
                serde_json::Value::Array(a) => a,
                o @ serde_json::Value::Object(_) => vec![o],
                _ => return Err((400, "bad body".into())),
            };
            if items.is_empty() || items.len() > 5000 {
                return Err((400, "bad count".into()));
            }
            let pts = items
                .iter()
                .map(|i| cops_metrics::parse_point(i, now))
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| (400u16, e))?;
            let n = st.insert(&pts).map_err(e500)?;
            Ok(serde_json::json!({"ok": true, "inserted": n}))
        }
        "/api/metrics/series" => {
            let name = q("name")
                .filter(|n| !n.is_empty())
                .ok_or((400u16, "name required".to_string()))?;
            let limit = num("limit", 2000.0)?.clamp(1.0, 20000.0) as usize;
            st.series(
                &name,
                q("key").as_deref(),
                &q("owner").unwrap_or_default(),
                num("from", 0.0)?,
                num("to", 1e18)?,
                limit,
            )
            .map_err(e500)
        }
        "/api/metrics/names" => st.names(&q("owner").unwrap_or_default()).map_err(e500),
        _ => Err((404, "not found".into())),
    }
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
    let cand = root
        .join(url_path.trim_start_matches('/'))
        .canonicalize()
        .ok()?;
    if cand.starts_with(&root) && cand.is_file() {
        Some(cand)
    } else {
        None
    }
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
        let cache = if f.starts_with(dist.canonicalize().ok()?.join("assets")) {
            "public, max-age=31536000, immutable"
        } else {
            "no-cache"
        };
        let len = data.len();
        let body = if head {
            Bytes::new()
        } else {
            Bytes::from(data)
        };
        let b = http_body_util::Full::new(body)
            .map_err(|n| match n {})
            .boxed();
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
        let client = Client::builder(TokioExecutor::new())
            .pool_max_idle_per_host(0)
            .build_http();
        Arc::new(Proxy {
            local_auth: None,
            mounts: None,
            metrics: None,
            local: None,
            upstream,
            dist: None,
            secret: None,
            client,
        })
    }

    /// `dist` (py/webui/dist) verilirse `/assets/*` ve `/favicon.svg` (token'sız taşınan statikler) diskten Rust'ta sunulur; dosya yoksa
    /// istek Python'a aktarılır (404 kararı Python'da kalır). Gömülü DEĞİL: dist değişince yeniden başlatma gerekmez.
    pub fn with_dist(self: Arc<Self>, dist: std::path::PathBuf) -> Arc<Self> {
        let me = Arc::try_unwrap(self).ok().expect("tek sahip");
        Arc::new(Proxy {
            dist: Some(dist),
            ..me
        })
    }

    /// Yerel uçları aç (şimdilik `GET /api/steward/questions`): kimlik tek kullanıcı token'ı, veri `claudeops.db` (salt okunur).
    pub fn with_local(self: Arc<Self>, local: LocalCfg) -> Arc<Self> {
        let me = Arc::try_unwrap(self).ok().expect("tek sahip");
        Arc::new(Proxy {
            local: Some(local),
            ..me
        })
    }

    /// Yerel uç kimlik/yetki kancasını tak (enterprise). Takılmazsa yerel uçlar yalnız `web.token` kabul eder (bugünkü davranış).
    /// Kanca yalnız GET yerel uçlarında sorulur (`/api/steward/questions`, `/api/metrics/series|names`); `POST /api/metrics/points`
    /// makine kimliğiyle (web.token ya da loopback + ön kapı gizlisi) kalır. Proxy paylaşılmışsa değişmeden döner ve günlüğe yazar.
    pub fn with_local_auth(self: Arc<Self>, hook: Arc<dyn gate::LocalAuth>) -> Arc<Self> {
        match Arc::try_unwrap(self) {
            Ok(me) => Arc::new(Proxy {
                local_auth: Some(hook),
                ..me
            }),
            Err(me) => {
                eprintln!("copsd: with_local_auth: vekil paylaşılmış, kanca takılmadı");
                me
            }
        }
    }

    /// Kanca takılı değilse `Default` (bugünkü yol).
    async fn local_verdict<B>(&self, req: &Request<B>, peer: SocketAddr) -> gate::LocalVerdict {
        match &self.local_auth {
            None => gate::LocalVerdict::Default,
            Some(h) => gate::local_decide(h.clone(), request_view(req, peer)).await,
        }
    }

    /// `/api/metrics/{points,series,names}` uçlarını aç (depo + kimlik).
    pub fn with_metrics(self: Arc<Self>, m: MetricsCfg) -> Arc<Self> {
        let me = Arc::try_unwrap(self).ok().expect("tek sahip");
        Arc::new(Proxy {
            metrics: Some(m),
            ..me
        })
    }

    /// Uygulama mount'larını aç. Proxy paylaşılmışsa (Arc'ın tek sahibi yoksa) değişmeden döner ve günlüğe yazar.
    pub fn with_mounts(self: Arc<Self>, m: MountCfg) -> Arc<Self> {
        match Arc::try_unwrap(self) {
            Ok(me) => Arc::new(Proxy {
                mounts: Some(m),
                ..me
            }),
            Err(me) => {
                eprintln!("copsd: with_mounts: vekil paylaşılmış, mount açılmadı");
                me
            }
        }
    }

    /// Metrik uçları: GET series/names (web.token), POST points (web.token ya da loopback + `X-Cops-Front`). Eşleşmezse None.
    // Err = isteğin kendisi geri verilir (eşleşmeyen istek Python'a aktarılsın diye); kutulamak her istekte ayırma demek.
    #[allow(clippy::result_large_err)]
    async fn try_metrics(
        self: &Arc<Self>,
        req: Request<Incoming>,
        peer: SocketAddr,
    ) -> Result<Response<Body>, Request<Incoming>> {
        let Some(m) = self.metrics.as_ref() else {
            return Err(req);
        };
        let path = req.uri().path().to_string();
        let post = req.method() == hyper::Method::POST && path == "/api/metrics/points";
        let get = req.method() == hyper::Method::GET
            && (path == "/api/metrics/series" || path == "/api/metrics/names");
        if !post && !get {
            return Err(req);
        }
        let query = req.uri().query().unwrap_or("").to_string();
        let auth = req
            .headers()
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string());
        let front = req
            .headers()
            .get("x-cops-front")
            .and_then(|v| v.to_str().ok())
            .map(|s| format!("Bearer {s}"));
        let ok = match if post {
            gate::LocalVerdict::Default
        } else {
            self.local_verdict(&req, peer).await
        } {
            gate::LocalVerdict::Default => {
                m.token.authorized(&query, auth.as_deref())
                    || (post
                        && peer.ip().is_loopback()
                        && m.front_secret.authorized("", front.as_deref()))
            }
            gate::LocalVerdict::Allow => true,
            gate::LocalVerdict::Unauthorized => false,
            gate::LocalVerdict::Forbidden => return Ok(forbidden()),
        };
        if !ok {
            return Ok(json_resp(
                StatusCode::UNAUTHORIZED,
                serde_json::json!({"ok": false, "error": "unauthorized"}),
            ));
        }
        let store = m.store.clone();
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let body = if post {
            match http_body_util::Limited::new(req.into_body(), 1 << 20)
                .collect()
                .await
            {
                Ok(b) => b.to_bytes(),
                Err(_) => {
                    return Ok(json_resp(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        serde_json::json!({"ok": false, "error": "body too large"}),
                    ))
                }
            }
        } else {
            Bytes::new()
        };
        let out =
            tokio::task::spawn_blocking(move || metrics_handle(&store, &path, &query, &body, now))
                .await;
        Ok(match out {
            Ok(Ok(v)) => json_resp(StatusCode::OK, v),
            Ok(Err((code, m))) => json_resp(
                StatusCode::from_u16(code).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                serde_json::json!({"ok": false, "error": m}),
            ),
            Err(_) => json_resp(
                StatusCode::INTERNAL_SERVER_ERROR,
                serde_json::json!({"ok": false, "error": "internal"}),
            ),
        })
    }

    /// Yerel uç eşleşirse yanıt döner (kimlik DENETİMİ dahil); eşleşmezse None = Python'a aktar.
    async fn try_local(
        self: &Arc<Self>,
        req: &Request<Incoming>,
        peer: SocketAddr,
    ) -> Option<Response<Body>> {
        let local = self.local.as_ref()?;
        if req.method() != hyper::Method::GET || req.uri().path() != "/api/steward/questions" {
            return None;
        }
        let query = req.uri().query().unwrap_or("").to_string();
        if !cops_local::handles(&query) {
            return None;
        }
        let auth = req
            .headers()
            .get("authorization")
            .and_then(|v| v.to_str().ok());
        let ok = match self.local_verdict(req, peer).await {
            gate::LocalVerdict::Default => local.token.authorized(&query, auth),
            gate::LocalVerdict::Allow => true,
            gate::LocalVerdict::Unauthorized => false,
            gate::LocalVerdict::Forbidden => return Some(forbidden()),
        };
        if !ok {
            return Some(json_resp(
                StatusCode::UNAUTHORIZED,
                serde_json::json!({"ok": false, "error": "unauthorized"}),
            ));
        }
        let db = local.db.clone();
        let out = tokio::task::spawn_blocking(move || cops_local::questions(&db, &query)).await;
        Some(match out {
            Ok(Ok(v)) => json_resp(StatusCode::OK, v),
            Ok(Err((code, m))) => json_resp(
                StatusCode::from_u16(code).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                serde_json::json!({"ok": false, "error": m}),
            ),
            Err(_) => json_resp(
                StatusCode::INTERNAL_SERVER_ERROR,
                serde_json::json!({"ok": false, "error": "internal"}),
            ),
        })
    }

    /// Ön kapı gizlisi: Python'un `X-Forwarded-For`a güvenmesi için her aktarılan isteğe `X-Cops-Front` olarak eklenir;
    /// istemciden gelen aynı adlı başlık her zaman düşürülür.
    pub fn with_secret(upstream: SocketAddr, secret: &str) -> Arc<Self> {
        let client = Client::builder(TokioExecutor::new())
            .pool_max_idle_per_host(0)
            .build_http();
        Arc::new(Proxy {
            local_auth: None,
            mounts: None,
            metrics: None,
            local: None,
            upstream,
            dist: None,
            secret: HeaderValue::from_str(secret).ok(),
            client,
        })
    }

    /// `peer`: bağlanan istemcinin adresi (X-Forwarded-For için). İstemcinin gönderdiği X-Forwarded-For'a GÜVENİLMEZ, üzerine yazılır.
    pub async fn handle(
        self: Arc<Self>,
        mut req: Request<Incoming>,
        peer: SocketAddr,
    ) -> Result<Response<Body>, hyper::Error> {
        // İç uçlar (`/api/_internal/*`) dışarıdan ASLA aktarılmaz: ön kapı gizlisi her aktarılan isteğe eklendiği için, aktarılırsa
        // herkes iç kimlik/bilet uçlarını güvenilir çağrıcı gibi çağırabilirdi. Yalnız Rust'un KENDİ iç çağrıları (loopback) bu yola gider.
        if req
            .uri()
            .path()
            .trim_start_matches('/')
            .to_ascii_lowercase()
            .starts_with("api/_internal")
        {
            return Ok(err(StatusCode::NOT_FOUND, "not found"));
        }
        if let Some(cfg) = &self.mounts {
            if let Some(hit) = cfg.mounts.lookup(req.uri().path()) {
                return Ok(self.handle_mount(cfg, hit, req, peer, false).await);
            }
            // Köke göre yazılan istek (`/api/x`, `/maya-ui/...`): Referer'ı bir `rootrel` mount'unun altındaysa o uygulamaya
            // (`/<id>` + yol) gider; panelin kendi yollarını (`/api`) da kapsar, çünkü sayfa o uygulamanın sayfasıdır.
            let referer = req
                .headers()
                .get(hyper::header::REFERER)
                .and_then(|v| v.to_str().ok());
            let host = req
                .headers()
                .get(hyper::header::HOST)
                .and_then(|v| v.to_str().ok())
                .or_else(|| req.uri().authority().map(|a| a.as_str()));
            if let (Some(r), Some(h)) = (referer, host) {
                if let Some((id, addr)) = cfg.mounts.lookup_by_referer(r, h) {
                    let pq = req
                        .uri()
                        .path_and_query()
                        .map(|p| p.as_str())
                        .unwrap_or("/");
                    if let Ok(uri) = format!("/{id}{pq}").parse::<hyper::Uri>() {
                        *req.uri_mut() = uri;
                        return Ok(self
                            .handle_mount(cfg, mount::Hit::Under(addr), req, peer, true)
                            .await);
                    }
                }
            }
        }
        if let Some(cfg) = &self.mounts {
            // (b2) Referer yolunun ilk parçası bir rootrel mount'a ÖĞRENİLMİŞSE (HTML belge yanıtından, bkz. `handle_mount`) istek o
            // uygulamanındır, panel yolu olsa da (`/v1`, `/api`: sayfa uygulamanın). (b3) İstek yolunun ilk parçası öğrenilmişse
            // (Referer'sız F5/yeni sekme) de öyle. Panel kökleri hiç öğrenilmez (`mount::learnable`), çerezden ÖNCE gelir.
            let r_seg = req
                .headers()
                .get(hyper::header::REFERER)
                .and_then(|v| v.to_str().ok())
                .zip(
                    req.headers()
                        .get(hyper::header::HOST)
                        .and_then(|v| v.to_str().ok())
                        .or_else(|| req.uri().authority().map(|a| a.as_str())),
                )
                .and_then(|(r, h)| mount::same_origin_referer_path(r, h))
                .and_then(|p| first_segment(p).map(str::to_string));
            let hit = r_seg.and_then(|seg| cfg.mounts.learned(&seg)).or_else(|| {
                first_segment(req.uri().path()).and_then(|seg| cfg.mounts.learned(seg))
            });
            if let Some((id, addr)) = hit {
                let pq = req
                    .uri()
                    .path_and_query()
                    .map(|p| p.as_str())
                    .unwrap_or("/");
                if let Ok(uri) = format!("/{id}{pq}").parse::<hyper::Uri>() {
                    *req.uri_mut() = uri;
                    return Ok(self
                        .handle_mount(cfg, mount::Hit::Under(addr), req, peer, false)
                        .await);
                }
            }
        }
        if let Some(cfg) = &self.mounts {
            // (d) Referer'sız köke göre istek (F5, yeni sekme, pushState adresi): `cops_app` çerezi var olan bir rootrel mount'u
            // gösteriyorsa o uygulamanın isteğidir. Panelin kendi yolları hariç. Çerez yalnız yolu seçer, yetki `handle_mount`ta.
            // Çakışma (Rancher `/v1/`, `/api/`): çerez + aynı kökenli Referer VAR ve Referer'ın yolu panel SAYFASI DEĞİLSE (`/dashboard/..` gibi
            // panelde olmayan sayfa) panel yolu olsa da uygulamanındır; panel arayüzünün istekleri Referer olarak panel sayfasını taşır.
            // Referer'sız panel yolu isteği (curl, OpenAI istemcisi) panelde kalır.
            let from_app_page = {
                let r = req
                    .headers()
                    .get(hyper::header::REFERER)
                    .and_then(|v| v.to_str().ok());
                let h = req
                    .headers()
                    .get(hyper::header::HOST)
                    .and_then(|v| v.to_str().ok())
                    .or_else(|| req.uri().authority().map(|a| a.as_str()));
                match (r, h) {
                    (Some(r), Some(h)) => mount::same_origin_referer_path(r, h).is_some_and(|p| {
                        let p = p.split(['?', '#']).next().unwrap_or("/");
                        !is_panel_path(p)
                    }),
                    _ => false,
                }
            };
            if from_app_page || !is_panel_path(req.uri().path()) {
                if let Some(id) = app_cookie_id(req.headers()) {
                    if let Some(addr) = cfg.mounts.rootrel_upstream(&id) {
                        let pq = req
                            .uri()
                            .path_and_query()
                            .map(|p| p.as_str())
                            .unwrap_or("/");
                        if let Ok(uri) = format!("/{id}{pq}").parse::<hyper::Uri>() {
                            *req.uri_mut() = uri;
                            return Ok(self
                                .handle_mount(cfg, mount::Hit::Under(addr), req, peer, false)
                                .await);
                        }
                    }
                }
            }
        }
        if let Some(r) = self.try_static(&req) {
            return Ok(r);
        }
        let req = match self.try_metrics(req, peer).await {
            Ok(r) => return Ok(r),
            Err(r) => r,
        };
        let mut req = req;
        if let Some(r) = self.try_local(&req, peer).await {
            return Ok(r);
        }
        req.headers_mut().remove("x-cops-front");
        drop_untrusted_client_ip(req.headers_mut(), peer);
        if let Some(sec) = &self.secret {
            req.headers_mut()
                .insert(HeaderName::from_static("x-cops-front"), sec.clone());
        }
        if let Ok(v) = HeaderValue::from_str(&peer.ip().to_string()) {
            req.headers_mut()
                .insert(HeaderName::from_static("x-forwarded-for"), v);
        }
        let pq = req
            .uri()
            .path_and_query()
            .map(|p| p.as_str().to_string())
            .unwrap_or_else(|| "/".into());
        Ok(self.forward(req, self.upstream, &pq).await)
    }

    /// Ortak aktarım (Python iç portu ya da mount upstream'i): hop-by-hop süzme, WS yükseltme tüneli, gövde AKIŞLI (tamponlama yok).
    /// Kimlik/başlık kararlarını çağıran verir; `pq` upstream'e gidecek yol + sorgu.
    async fn forward(
        &self,
        mut req: Request<Incoming>,
        target: SocketAddr,
        pq: &str,
    ) -> Response<Body> {
        let upgrade = is_upgrade(req.headers());
        let uri: hyper::Uri = match format!("http://{target}{pq}").parse() {
            Ok(u) => u,
            Err(_) => return err(StatusCode::BAD_REQUEST, "bad uri"),
        };
        let client_up = if upgrade {
            Some(hyper::upgrade::on(&mut req))
        } else {
            None
        };
        *req.uri_mut() = uri;
        strip_hop(req.headers_mut(), upgrade);
        let mut resp = match self.client.request(req).await {
            Ok(r) => r,
            Err(e) => return err(StatusCode::BAD_GATEWAY, &format!("upstream: {e}")),
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
            let empty = http_body_util::Empty::<Bytes>::new()
                .map_err(|n| match n {})
                .boxed();
            return Response::from_parts(parts, empty);
        }
        let (mut parts, body) = resp.into_parts();
        strip_hop(&mut parts.headers, false);
        Response::from_parts(parts, body.boxed())
    }

    /// Mount isteği: panel kimliği (web.token `?token=`/Bearer ya da `cops_ext` çerezi) burada denetlenir; panel kimlik bilgisi upstream'e
    /// GİTMEZ. `?token=` ile gelen GET/HEAD 302 + çerez ile token'sız adrese yönlenir; `/<id>` 308 ile `/<id>/`a.
    async fn handle_mount(
        &self,
        cfg: &MountCfg,
        hit: mount::Hit,
        mut req: Request<Incoming>,
        peer: SocketAddr,
        learn_any_type: bool,
    ) -> Response<Body> {
        let (target, bare) = match hit {
            mount::Hit::Under(a) => (a, false),
            mount::Hit::Bare(a) => (a, true),
        };
        let query = req.uri().query().unwrap_or("").to_string();
        let by_query = cfg.token.authorized(&query, None);
        let bearer = req
            .headers()
            .get(AUTHORIZATION)
            .and_then(|v| v.to_str().ok());
        let by_bearer = !by_query && cfg.token.authorized("", bearer);
        let by_cookie = req
            .headers()
            .get_all(COOKIE)
            .iter()
            .filter_map(|v| v.to_str().ok())
            .any(|c| cfg.token.cookie_ok(c));
        if !by_query && !by_bearer && !by_cookie {
            let html = req
                .headers()
                .get(ACCEPT)
                .and_then(|v| v.to_str().ok())
                .is_some_and(|a| a.contains("text/html"));
            return unauthorized(html);
        }
        let https = client_https(req.headers(), peer);
        let set_cookie = if by_query && !by_cookie {
            cfg.token
                .cookie_value()
                .and_then(|v| HeaderValue::from_str(&ext_cookie(v, https)).ok())
        } else {
            None
        };
        // Kodlu ad (`tok%65n=`) dahil tüm `token` parametreleri silinir; silinen varsa (uzunluk değişti) token URL'de demektir.
        let q = if query.is_empty() {
            query
        } else {
            cops_auth::strip_query_param(&query, "token")
        };
        let has_qtoken = q.len() != req.uri().query().map_or(0, str::len);
        let path = req.uri().path().to_string();
        let get_like = (req.method() == hyper::Method::GET || req.method() == hyper::Method::HEAD)
            && !is_upgrade(req.headers());
        if bare || (has_qtoken && get_like) {
            let loc_path = if bare { format!("{path}/") } else { path };
            let loc = if q.is_empty() {
                loc_path
            } else {
                format!("{loc_path}?{q}")
            };
            let code = if has_qtoken && get_like {
                StatusCode::FOUND
            } else {
                StatusCode::PERMANENT_REDIRECT
            };
            return redirect(code, &loc, set_cookie);
        }
        // Uygulama çerezi: rootrel mount yanıtına `cops_app=<id>` (istek zaten aynı değeri taşımıyorsa).
        let app_id = path_id(req.uri().path());
        let app_cookie = match &app_id {
            Some(id)
                if cfg.mounts.rootrel_upstream(id).is_some()
                    && app_cookie_id(req.headers()).as_deref() != Some(id.as_str()) =>
            {
                HeaderValue::from_str(&format!(
                    "{APP_COOKIE}={id}; Path=/; HttpOnly; SameSite=Lax{}",
                    if https { "; Secure" } else { "" }
                ))
                .ok()
            }
            _ => None,
        };
        let h = req.headers_mut();
        h.remove(AUTHORIZATION);
        strip_panel_cookies(h);
        let names: Vec<HeaderName> = h
            .keys()
            .filter(|n| n.as_str().starts_with("x-cops-front"))
            .cloned()
            .collect();
        for n in names {
            h.remove(n);
        }
        for n in [
            "x-forwarded-for",
            "x-forwarded-proto",
            "x-forwarded-host",
            "forwarded",
            "x-real-ip",
        ] {
            h.remove(n);
        }
        if let Ok(v) = HeaderValue::from_str(&peer.ip().to_string()) {
            h.insert(HeaderName::from_static("x-forwarded-for"), v);
        }
        h.insert(
            HeaderName::from_static("x-forwarded-proto"),
            HeaderValue::from_static(if https { "https" } else { "http" }),
        );
        let pq = if q.is_empty() {
            path
        } else {
            format!("{path}?{q}")
        };
        // Yol kökü öğrenme: rootrel mount'tan GET ile gelen HTML belge yanıtı, mount önekinden sonraki ilk yol parçasını (`/gw/grafana/d/x`
        // -> `grafana`) bu mount'a bağlar. API/JS/resim yanıtı öğretmez. Karar yalnız kimlikli (yukarıdaki kapıdan geçmiş) istekten.
        let learn = if req.method() == hyper::Method::GET && !is_upgrade(req.headers()) {
            app_id
                .as_deref()
                .filter(|id| cfg.mounts.rootrel_upstream(id).is_some())
                .and_then(|id| {
                    let rest = pq.strip_prefix('/')?.strip_prefix(id)?;
                    first_segment(rest).map(|seg| (seg.to_string(), id.to_string()))
                })
        } else {
            None
        };
        let mut resp = self.forward(req, target, &pq).await;
        if let Some((seg, id)) = learn {
            // Referer mount YOLUNUN altındaki (b) alt kaynak: yanıt türüne bakılmaz, 2xx/3xx yeter (SPA pushState sonrası HTML isteği olmaz).
            // Diğer yönlenmeler (a, b2, b3, çerez) yalnız 2xx `text/html` belge ile öğretir: yanlış öğrenme zinciri olmasın.
            let st = resp.status();
            let ok_status = if learn_any_type {
                st.is_success() || st.is_redirection()
            } else {
                st.is_success()
            };
            let html = ok_status
                && (learn_any_type
                    || resp
                        .headers()
                        .get(CONTENT_TYPE)
                        .and_then(|v| v.to_str().ok())
                        .is_some_and(|v| {
                            v.trim_start().to_ascii_lowercase().starts_with("text/html")
                        }));
            if html {
                cfg.mounts.learn(&seg, &id);
            }
        }
        if let Some(c) = set_cookie {
            resp.headers_mut().append(SET_COOKIE, c);
        }
        if let Some(c) = app_cookie {
            resp.headers_mut().append(SET_COOKIE, c);
        }
        resp
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
            let _ = hyper::server::conn::http1::Builder::new()
                .serve_connection(TokioIo::new(sock), svc)
                .with_upgrades()
                .await;
        });
    }
}

#[cfg(test)]
mod client_ip_tests {
    use super::*;

    #[test]
    fn cf_connecting_ip_survives_only_from_loopback_peer() {
        for (peer, kept) in [
            ("127.0.0.1:5", true),
            ("[::1]:5", true),
            ("[::ffff:127.0.0.1]:5", true),
            ("10.0.0.5:5", false),
        ] {
            let mut h = hyper::HeaderMap::new();
            h.insert("cf-connecting-ip", HeaderValue::from_static("203.0.113.7"));
            drop_untrusted_client_ip(&mut h, peer.parse().unwrap());
            assert_eq!(h.contains_key("cf-connecting-ip"), kept, "{peer}");
        }
    }
}
