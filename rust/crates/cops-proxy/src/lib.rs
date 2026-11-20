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

pub struct Proxy {
    upstream: SocketAddr,
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

impl Proxy {
    pub fn new(upstream: SocketAddr) -> Arc<Self> {
        let client = Client::builder(TokioExecutor::new()).build_http();
        Arc::new(Proxy { upstream, client })
    }

    /// `peer`: bağlanan istemcinin adresi (X-Forwarded-For için). İstemcinin gönderdiği X-Forwarded-For'a GÜVENİLMEZ, üzerine yazılır.
    pub async fn handle(self: Arc<Self>, mut req: Request<Incoming>, peer: SocketAddr) -> Result<Response<Body>, hyper::Error> {
        let upgrade = is_upgrade(req.headers());
        let pq = req.uri().path_and_query().map(|p| p.as_str().to_string()).unwrap_or_else(|| "/".into());
        let uri: hyper::Uri = match format!("http://{}{}", self.upstream, pq).parse() {
            Ok(u) => u,
            Err(_) => return Ok(err(StatusCode::BAD_REQUEST, "bad uri")),
        };
        let client_up = if upgrade { Some(hyper::upgrade::on(&mut req)) } else { None };
        *req.uri_mut() = uri;
        strip_hop(req.headers_mut(), upgrade);
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
