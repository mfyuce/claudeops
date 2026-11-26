//! D0 saf vekil: dış porttaki HTTP istek ve WebSocket yükseltmelerini Python'un iç portuna aktarır.
//! Python'a aktarılan isteklerde kimlik, yetki ve yönlendirme KARARI vermez; yalnız başlık temizler ve `X-Forwarded-For` ekler.
//! İstisnalar: Rust yerel uçları ve uygulama mount'ları (`mount.rs`, `/<id>/` -> derbent): bunlarda kimliği copsd kendisi denetler.
//! Takılabilir ön süzgeç ([`gate::ForwardFilter`], enterprise) aktarılan istekteki GEÇERSİZ kimlik bilgisini siler (karar yine Python'da).

mod base_href;
pub mod gate;
pub mod mount;
pub mod resources;

use bytes::Bytes;
use http_body_util::{combinators::BoxBody, BodyExt};
use hyper::body::Incoming;
use hyper::header::{
    HeaderName, HeaderValue, ACCEPT, ACCEPT_ENCODING, AUTHORIZATION, CACHE_CONTROL, CONNECTION,
    CONTENT_LENGTH, CONTENT_TYPE, COOKIE, LOCATION, SET_COOKIE, UPGRADE,
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
    routes: Option<Arc<dyn gate::RouteHook>>,
    forward_filter: Option<Arc<dyn gate::ForwardFilter>>,
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

/// Python `str.strip()` boşluğu, başlık baytı Latin-1 okunduğunda (Python `http.server` gibi): `\t\n\v\f\r`, U+001C..U+001F,
/// boşluk, U+0085, U+00A0.
fn py_ws(b: u8) -> bool {
    matches!(b, 0x09..=0x0d | 0x1c..=0x20 | 0x85 | 0xa0)
}

fn py_trim(mut s: &[u8]) -> &[u8] {
    while let [f, rest @ ..] = s {
        if !py_ws(*f) {
            break;
        }
        s = rest;
    }
    while let [rest @ .., l] = s {
        if !py_ws(*l) {
            break;
        }
        s = rest;
    }
    s
}

/// Ön süzgeç kararını uygular ([`gate::CredStrip`]). Atlatılamazlık: TÜM `Authorization` satırları; TÜM `Cookie` satırlarında
/// adı (Python boşluk kümesiyle kırpılmış, ASCII harf duyarsız) listedeki her parça. Değerler BAYT olarak işlenir (görünmez
/// ASCII dışı bayt içeren satır atlanmaz). Değişmeyen satır bayt bayt aynı (değişenin baş/son SP/HTAB'ı kırpılır), satır sırası korunur; boşalan satır kalkar.
pub fn strip_credentials(h: &mut hyper::HeaderMap, s: &gate::CredStrip) {
    if s.authorization {
        h.remove(AUTHORIZATION);
    }
    if s.cookies.is_empty() || !h.contains_key(COOKIE) {
        return;
    }
    let hit = |part: &[u8]| {
        let name = part.split(|b| *b == b'=').next().unwrap_or(part);
        let name = py_trim(name);
        s.cookies
            .iter()
            .any(|c| c.as_bytes().eq_ignore_ascii_case(name))
    };
    let mut changed = false;
    let mut out: Vec<HeaderValue> = Vec::new();
    for v in h.get_all(COOKIE).iter() {
        let parts: Vec<&[u8]> = v.as_bytes().split(|b| *b == b';').collect();
        if !parts.iter().any(|p| hit(p)) {
            out.push(v.clone());
            continue;
        }
        changed = true;
        let kept: Vec<&[u8]> = parts.into_iter().filter(|p| !hit(p)).collect();
        if kept.iter().all(|p| py_trim(p).is_empty()) {
            continue;
        }
        let joined = kept.join(&b';');
        let mut v: &[u8] = &joined;
        while let [b' ' | b'\t', rest @ ..] = v {
            v = rest;
        }
        while let [rest @ .., b' ' | b'\t'] = v {
            v = rest;
        }
        if let Ok(nv) = HeaderValue::from_bytes(v) {
            out.push(nv);
        }
    }
    if changed {
        h.remove(COOKIE);
        for v in out {
            h.append(COOKIE, v);
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
            routes: None,
            forward_filter: None,
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

    /// Vekillenen istekler için kimlik bilgisi ön süzgecini tak (enterprise, plan §7.3). Takılmazsa aktarılan istek bugünkü gibi.
    /// Yalnız Python iç portuna aktarılan isteklere uygulanır (WS yükseltmesi dahil); yerel uçlar, statikler ve mount'lar hariç.
    /// Proxy paylaşılmışsa değişmeden döner ve günlüğe yazar.
    pub fn with_forward_filter(self: Arc<Self>, f: Arc<dyn gate::ForwardFilter>) -> Arc<Self> {
        match Arc::try_unwrap(self) {
            Ok(me) => Arc::new(Proxy {
                forward_filter: Some(f),
                ..me
            }),
            Err(me) => {
                eprintln!("copsd: with_forward_filter: vekil paylaşılmış, süzgeç takılmadı");
                me
            }
        }
    }

    /// Rust'ın kendisinin cevapladığı uç kancasını tak (enterprise `/api/auth/*`, A6b-2; [`gate::RouteHook`]). Takılmazsa ya da
    /// kanca isteği üstlenmezse istek bugünkü gibi. Statik ve metrik uçlarından SONRA, yerel uçlardan ve Python'a aktarımdan ÖNCE
    /// sorulur; `/api/_internal/*` hiç gelmez. Proxy paylaşılmışsa değişmeden döner ve günlüğe yazar.
    pub fn with_routes(self: Arc<Self>, hook: Arc<dyn gate::RouteHook>) -> Arc<Self> {
        match Arc::try_unwrap(self) {
            Ok(me) => Arc::new(Proxy {
                routes: Some(hook),
                ..me
            }),
            Err(me) => {
                eprintln!("copsd: with_routes: vekil paylaşılmış, kanca takılmadı");
                me
            }
        }
    }

    /// Kanca isteği üstlenirse gövdeyi sınırla okur ve yanıtı kancadan alır; üstlenmezse isteği geri verir.
    // Err = isteğin kendisi (`try_metrics` ile aynı gerekçe: kutulamak her istekte ayırma).
    #[allow(clippy::result_large_err)]
    async fn try_routes(
        &self,
        req: Request<Incoming>,
        peer: SocketAddr,
    ) -> Result<Response<Body>, Request<Incoming>> {
        let Some(hook) = &self.routes else {
            return Err(req);
        };
        let view = request_view(&req, peer);
        let Some(limit) = hook.route(&view) else {
            return Err(req);
        };
        let https = client_https(req.headers(), peer);
        let read = http_body_util::Limited::new(req.into_body(), limit).collect();
        let body = match tokio::time::timeout(hook.body_timeout(), read).await {
            Ok(Ok(c)) => Ok(c.to_bytes()),
            Ok(Err(e)) if e.is::<http_body_util::LengthLimitError>() => {
                Err(gate::BodyError::TooLarge)
            }
            Ok(Err(_)) => Err(gate::BodyError::Read),
            // Gövde tamamlanmadı: kalan baytlar sonraki isteğin başı sanılmasın, bağlantı kapanır.
            Err(_) => {
                let mut r = err(StatusCode::REQUEST_TIMEOUT, "request body timeout");
                r.headers_mut()
                    .insert(hyper::header::CONNECTION, HeaderValue::from_static("close"));
                return Ok(r);
            }
        };
        let r = gate::route_call(hook.clone(), gate::RouteRequest { view, body, https }).await;
        let mut b = Response::builder()
            .status(StatusCode::from_u16(r.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR));
        for (k, v) in &r.headers {
            if let (Ok(k), Ok(v)) = (
                HeaderName::from_bytes(k.as_bytes()),
                HeaderValue::from_str(v),
            ) {
                b = b.header(k, v);
            }
        }
        let body = http_body_util::Full::new(Bytes::from(r.body))
            .map_err(|never| match never {})
            .boxed();
        Ok(b.body(body)
            .unwrap_or_else(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "internal error")))
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
            routes: None,
            forward_filter: None,
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
                return Ok(self.handle_mount(cfg, hit, req, peer, false, false).await);
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
                            .handle_mount(cfg, mount::Hit::Under(addr), req, peer, true, true)
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
                        .handle_mount(cfg, mount::Hit::Under(addr), req, peer, false, true)
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
                                .handle_mount(cfg, mount::Hit::Under(addr), req, peer, false, true)
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
        let req = match self.try_routes(req, peer).await {
            Ok(r) => return Ok(r),
            Err(r) => r,
        };
        let mut req = req;
        if let Some(r) = self.try_local(&req, peer).await {
            return Ok(r);
        }
        if let Some(f) = &self.forward_filter {
            let strip = gate::forward_check(f.clone(), request_view(&req, peer)).await;
            strip_credentials(req.headers_mut(), &strip);
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
            Err(e) => {
                let mut r = err(StatusCode::BAD_GATEWAY, &format!("upstream: {e}"));
                r.extensions_mut().insert(UpstreamError(root_cause(&e)));
                return r;
            }
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
        req: Request<Incoming>,
        peer: SocketAddr,
        learn_any_type: bool,
        prefixed: bool,
    ) -> Response<Body> {
        let method = req.method().clone();
        let path = req.uri().path().to_string();
        let resp = self
            .mount_response(cfg, hit, req, peer, learn_any_type, prefixed)
            .await;
        let reason = resp
            .extensions()
            .get::<UpstreamError>()
            .map(|e| e.0.as_str());
        if let Some(line) = mount_error_line(method.as_str(), &path, resp.status(), reason) {
            log_limited(resp.status(), &line);
        }
        resp
    }

    async fn mount_response(
        &self,
        cfg: &MountCfg,
        hit: mount::Hit,
        mut req: Request<Incoming>,
        peer: SocketAddr,
        learn_any_type: bool,
        prefixed: bool,
    ) -> Response<Body> {
        let (target, bare) = match hit {
            mount::Hit::Under(a) => (a, false),
            mount::Hit::Bare(a) => (a, true),
        };
        let query = req.uri().query().unwrap_or("").to_string();
        // Tek istek tek token değeri görür (döndürme anında eski token'la yeni çerez basılmasın).
        let token = cfg.token.snapshot();
        let by_query = token.authorized(&query, None);
        let bearer = req
            .headers()
            .get(AUTHORIZATION)
            .and_then(|v| v.to_str().ok());
        let by_bearer = !by_query && token.authorized("", bearer);
        let by_cookie = req
            .headers()
            .get_all(COOKIE)
            .iter()
            .filter_map(|v| v.to_str().ok())
            .any(|c| token.cookie_ok(c));
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
            token
                .cookie_value()
                .and_then(|v| HeaderValue::from_str(&ext_cookie(&v, https)).ok())
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
            // `prefixed`: `/<id>` önekini vekil ekledi; tarayıcı kendi (öneksiz) adresinde kalmalı, yoksa SPA'nın `base href`i tutmaz.
            let public = match path_id(&path) {
                Some(id) if prefixed => path[id.len() + 1..].to_string(),
                _ => path.clone(),
            };
            let loc_path = if bare { format!("{path}/") } else { public };
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
        // Rootrel mount belgesi: upstream `<base href>`i mount DIŞINDA bir köke bakıyorsa (Maya `/maya-ui/`, Grafana `/grafana/`)
        // SPA `/<id>/...` adresinde açılmaz. Mount kökü (`/<id>/`) o köke, o kökün altındaki sayfa (`/<id>/grafana/d/x`, yalnız belge
        // gezintisi) öneksiz adresine yönlendirilir. Gövdeyi okuyabilmek için sıkıştırma istenmez.
        let doc_id = app_id
            .as_deref()
            .filter(|id| {
                let path = req.uri().path();
                !prefixed
                    && req.method() == hyper::Method::GET
                    && !is_upgrade(req.headers())
                    && cfg.mounts.rootrel_upstream(id).is_some()
                    && (path == format!("/{id}/") || accepts_html(req.headers()))
            })
            .map(str::to_string);
        if doc_id.is_some() {
            req.headers_mut().remove(ACCEPT_ENCODING);
        }
        let public = req.uri().path().to_string();
        let mut resp = self.forward(req, target, &pq).await;
        if let Some(id) = doc_id {
            let (r, href) = base_href::inspect(resp).await;
            resp = r;
            if let Some((href, seg)) = href.and_then(|h| base_href::foreign_root(h, &id)) {
                if let Some(to_path) = base_href::target(&public, &id, &href) {
                    // Hedef başka bir mount'un yoluysa oraya düşer: derin sayfa yönlendirilmez.
                    let root = public == format!("/{id}/");
                    if root || cfg.mounts.lookup(&to_path).is_none() {
                        cfg.mounts.learn(&seg, &id);
                        let loc = if q.is_empty() {
                            to_path
                        } else {
                            format!("{to_path}?{q}")
                        };
                        let mut to = redirect(StatusCode::FOUND, &loc, None);
                        for c in resp.headers().get_all(SET_COOKIE) {
                            to.headers_mut().append(SET_COOKIE, c.clone());
                        }
                        resp = to;
                    }
                }
            }
        }
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

/// Tarayıcının belge gezintisi (`Accept` içinde `text/html`).
fn accepts_html(h: &hyper::HeaderMap) -> bool {
    h.get_all(hyper::header::ACCEPT)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .any(|v| v.to_ascii_lowercase().contains("text/html"))
}

/// 502'nin kök nedeni (yalnız günlük için yanıt uzantısında taşınır).
#[derive(Clone)]
struct UpstreamError(String);

fn root_cause(e: &dyn std::error::Error) -> String {
    let mut cur = e;
    while let Some(next) = cur.source() {
        cur = next;
    }
    cur.to_string()
}

/// Dakikada en çok `LOG_PER_WINDOW` satır; atlananların sayısı pencere bitince (ya da daha önce gelen sonraki pencerenin ilk
/// satırıyla) bildirilir.
const LOG_PER_WINDOW: u32 = 30;
const LOG_WINDOW: std::time::Duration = std::time::Duration::from_secs(60);

#[derive(Debug, PartialEq)]
enum Admit {
    /// Yaz; önceden bu kadar satır atlandı.
    Write(u64),
    /// Yazma. `Some` yalnız penceredeki ilk atlamada: sayının bildirileceği ana kalan süre.
    Skip(Option<std::time::Duration>),
}

struct LogLimiter {
    start: Option<std::time::Instant>,
    written: u32,
    skipped: u64,
}

impl LogLimiter {
    const fn new() -> Self {
        Self {
            start: None,
            written: 0,
            skipped: 0,
        }
    }

    fn expired(&self, now: std::time::Instant) -> bool {
        self.start
            .is_none_or(|s| now.duration_since(s) >= LOG_WINDOW)
    }

    fn admit(&mut self, now: std::time::Instant) -> Admit {
        if self.expired(now) {
            self.start = Some(now);
            self.written = 0;
        }
        if self.written >= LOG_PER_WINDOW {
            self.skipped += 1;
            let left = self
                .start
                .map(|s| LOG_WINDOW.saturating_sub(now.duration_since(s)));
            return Admit::Skip(left.filter(|_| self.skipped == 1));
        }
        self.written += 1;
        Admit::Write(std::mem::take(&mut self.skipped))
    }

    /// Pencere bittiyse henüz bildirilmemiş atlanan sayısı (bir kez); yoksa 0.
    fn flush(&mut self, now: std::time::Instant) -> u64 {
        if self.expired(now) {
            std::mem::take(&mut self.skipped)
        } else {
            0
        }
    }
}

/// 401 (kimliksiz istekler) ayrı kovada: sel halinde gelseler de diğer hata satırlarını bastırmaz.
fn log_limited(status: StatusCode, line: &str) {
    static AUTH: std::sync::Mutex<LogLimiter> = std::sync::Mutex::new(LogLimiter::new());
    static OTHER: std::sync::Mutex<LogLimiter> = std::sync::Mutex::new(LogLimiter::new());
    let (bucket, name) = if status == StatusCode::UNAUTHORIZED {
        (&AUTH, "401")
    } else {
        (&OTHER, "diğer")
    };
    let admitted = bucket
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .admit(std::time::Instant::now());
    match admitted {
        Admit::Write(0) => eprintln!("{line}"),
        Admit::Write(n) => eprintln!("{line} (önceki {n} satır atlandı)"),
        Admit::Skip(Some(left)) => {
            // Sel bitip yeni hata gelmese de sayı kaybolmasın. Yalnız istek işlerken (tokio içinde) çağrılır.
            tokio::spawn(async move {
                tokio::time::sleep(left).await;
                let n = bucket
                    .lock()
                    .unwrap_or_else(|p| p.into_inner())
                    .flush(std::time::Instant::now());
                if n > 0 {
                    eprintln!("copsd: mount hata: {name} kovasında {n} satır atlandı");
                }
            });
        }
        Admit::Skip(None) => {}
    }
}

/// Mount yanıtı >=400 ise günlük satırı: yöntem, mount kimliği, mount altındaki İLK yol parçası, durum. Yolun gerisi, sorgu, başlık
/// ve çerez YAZILMAZ (token/oturum sızmasın); parçalar istemci denetiminde olduğu için kırpılır.
fn mount_error_line(
    method: &str,
    path: &str,
    status: StatusCode,
    reason: Option<&str>,
) -> Option<String> {
    if status.as_u16() < 400 {
        return None;
    }
    let clip = |s: &str| -> String {
        s.split([';', '?', '#'])
            .next()
            .unwrap_or("")
            .chars()
            .filter(char::is_ascii_graphic)
            .take(40)
            .collect()
    };
    let mut parts = path.trim_start_matches('/').splitn(3, '/');
    let id = clip(parts.next().unwrap_or(""));
    let seg = clip(parts.next().unwrap_or(""));
    let reason = reason.map_or_else(String::new, |r| {
        let r: String = r.chars().filter(|c| !c.is_control()).take(80).collect();
        format!(" ({r})")
    });
    Some(format!(
        "copsd: mount hata: {} /{id}/{seg} -> {}{reason}",
        clip(method),
        status.as_u16()
    ))
}

#[cfg(test)]
mod mount_log_tests {
    use super::*;

    #[test]
    fn only_errors_are_logged() {
        for ok in [101, 200, 302, 308, 399] {
            let st = StatusCode::from_u16(ok).unwrap();
            assert_eq!(mount_error_line("GET", "/gw/x", st, None), None, "{ok}");
        }
    }

    #[test]
    fn line_carries_method_mount_first_segment_and_status_only() {
        let l = mount_error_line(
            "POST",
            "/gw/grafana/api/sekret-yol?token=sekret",
            StatusCode::BAD_GATEWAY,
            None,
        )
        .unwrap();
        assert_eq!(l, "copsd: mount hata: POST /gw/grafana -> 502");
        let l = mount_error_line("GET", "/gw", StatusCode::UNAUTHORIZED, None).unwrap();
        assert_eq!(l, "copsd: mount hata: GET /gw/ -> 401");
    }

    #[test]
    fn upstream_reason_is_appended_clipped_and_single_line() {
        let why = format!("Connection refused\n{}", "x".repeat(200));
        let l = mount_error_line("GET", "/gw/x", StatusCode::BAD_GATEWAY, Some(&why)).unwrap();
        assert!(l.contains("-> 502 (Connection refused"), "{l}");
        assert!(!l.contains('\n') && l.len() < 140, "{l}");
    }

    #[test]
    fn limiter_caps_a_window_and_reports_skipped_lines_in_the_next() {
        let mut lim = LogLimiter::new();
        let t0 = std::time::Instant::now();
        for _ in 0..LOG_PER_WINDOW {
            assert_eq!(lim.admit(t0), Admit::Write(0));
        }
        let later = t0 + LOG_WINDOW / 4;
        assert_eq!(
            lim.admit(later),
            Admit::Skip(Some(LOG_WINDOW - LOG_WINDOW / 4))
        );
        for _ in 0..2 {
            assert_eq!(lim.admit(later), Admit::Skip(None));
        }
        assert_eq!(lim.admit(t0 + LOG_WINDOW), Admit::Write(3));
        assert_eq!(lim.admit(t0 + LOG_WINDOW), Admit::Write(0));
    }

    #[test]
    fn skipped_count_is_flushed_once_after_the_window_without_a_new_line() {
        let mut lim = LogLimiter::new();
        let t0 = std::time::Instant::now();
        for _ in 0..LOG_PER_WINDOW + 5 {
            lim.admit(t0);
        }
        assert_eq!(lim.flush(t0 + LOG_WINDOW / 2), 0);
        assert_eq!(lim.flush(t0 + LOG_WINDOW), 5);
        assert_eq!(lim.flush(t0 + LOG_WINDOW), 0);
        assert_eq!(lim.admit(t0 + LOG_WINDOW), Admit::Write(0));
    }

    #[test]
    fn matrix_params_are_cut_and_long_segments_clipped() {
        let long = format!("/gw/{};jsessionid=sekret/x", "a".repeat(100));
        let l = mount_error_line("GET", &long, StatusCode::NOT_FOUND, None).unwrap();
        assert!(!l.contains("sekret"), "{l}");
        assert!(l.contains(&format!("/gw/{} ->", "a".repeat(40))), "{l}");
    }
}

/// Dinleyici döngüsü: her bağlantıyı `Proxy::handle`a verir (HTTP/1, yükseltme açık).
pub async fn serve(listen: SocketAddr, proxy: Arc<Proxy>) -> std::io::Result<()> {
    serve_on(tokio::net::TcpListener::bind(listen).await?, proxy).await
}

/// `serve`, hazır bağlanmış dinleyiciyle (port seçimiyle dinleme arasında başkası portu alamaz).
pub async fn serve_on(ln: tokio::net::TcpListener, proxy: Arc<Proxy>) -> std::io::Result<()> {
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
