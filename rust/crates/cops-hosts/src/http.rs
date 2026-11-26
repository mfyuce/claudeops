//! HTTP/1.1 istemcisi: host başına küçük keep-alive havuzu, adım başı zaman aşımı, sınırlı gövde.

use std::collections::HashMap;
use std::error::Error as StdError;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use bytes::{Bytes, BytesMut};
use http::{HeaderMap, HeaderName, HeaderValue, Method, Request};
use http_body_util::combinators::UnsyncBoxBody;
use http_body_util::{BodyExt, Full};
use hyper::body::{Body, Frame};
use hyper::client::conn::http1::{self, SendRequest};
use hyper_util::rt::TokioIo;
use tokio::time::Instant;

use crate::endpoint::Endpoint;
use crate::net::Connector;

pub type BoxError = Box<dyn StdError + Send + Sync>;
pub type ReqBody = UnsyncBoxBody<Bytes, BoxError>;

pub const POOL_MAX_IDLE: usize = 4;

pub fn full(body: Option<Bytes>) -> ReqBody {
    Full::new(body.unwrap_or_default())
        .map_err(|never| match never {})
        .boxed_unsync()
}

#[derive(Debug)]
pub struct Response {
    pub status: u16,
    pub headers: HeaderMap,
    pub body: Bytes,
}

/// Başarısız deneme. `from_pool` + `!sent` = taze bağlantıyla güvenle yeniden denenebilir.
#[derive(Debug)]
pub struct Failure {
    pub message: String,
    pub from_pool: bool,
    /// İstek karşıya ulaşmış OLABİLİR.
    pub sent: bool,
}

pub struct Attempt<'a> {
    pub method: Method,
    pub endpoint: &'a Endpoint,
    /// `/yol?sorgu` (taban yolu dahil).
    pub target: &'a str,
    pub headers: Vec<(HeaderName, HeaderValue)>,
    pub body: Option<Bytes>,
    /// Her ağ adımının sınırı.
    pub timeout: Duration,
    /// Tüm adımların tavanı.
    pub total: Duration,
    pub max_body: usize,
}

#[derive(Clone)]
pub struct Pool {
    pub connector: Connector,
    idle: Arc<Mutex<HashMap<String, Vec<SendRequest<ReqBody>>>>>,
}

fn describe(e: &(dyn StdError + 'static)) -> String {
    let mut s = e.to_string();
    let mut cur = e.source();
    while let Some(c) = cur {
        s.push_str(": ");
        s.push_str(&c.to_string());
        cur = c.source();
    }
    s
}

const TIMED_OUT: &str = "timed out";

impl Pool {
    pub fn new(connector: Connector) -> Pool {
        Pool {
            connector,
            idle: Arc::default(),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, Vec<SendRequest<ReqBody>>>> {
        self.idle.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Havuzdaki ölü bağlantılar (karşı taraf kapatmış) elenir.
    fn checkout(&self, key: &str) -> Option<SendRequest<ReqBody>> {
        let mut idle = self.lock();
        let bucket = idle.get_mut(key)?;
        while let Some(s) = bucket.pop() {
            if s.is_ready() && !s.is_closed() {
                return Some(s);
            }
        }
        None
    }

    fn checkin(&self, key: String, sender: SendRequest<ReqBody>) {
        let mut idle = self.lock();
        let bucket = idle.entry(key).or_default();
        if bucket.len() < POOL_MAX_IDLE {
            bucket.push(sender);
        }
    }

    pub fn idle_count(&self, key: &str) -> usize {
        self.lock().get(key).map_or(0, Vec::len)
    }

    async fn open(&self, ep: &Endpoint) -> Result<SendRequest<ReqBody>, String> {
        let stream = self
            .connector
            .connect(ep, &[])
            .await
            .map_err(|e| describe(&e))?;
        let (sender, conn) = http1::handshake(TokioIo::new(stream))
            .await
            .map_err(|e| describe(&e))?;
        tokio::spawn(async move {
            let _ = conn.await;
        });
        Ok(sender)
    }

    fn request(
        ep: &Endpoint,
        method: Method,
        target: &str,
        headers: Vec<(HeaderName, HeaderValue)>,
        body: ReqBody,
    ) -> Result<Request<ReqBody>, String> {
        let mut req = Request::builder()
            .method(method)
            .uri(target)
            .header(http::header::HOST, ep.authority())
            .header(http::header::ACCEPT_ENCODING, "identity")
            .body(body)
            // Hata metni URI'yi (token) taşımasın.
            .map_err(|_| "invalid request".to_string())?;
        for (k, v) in headers {
            req.headers_mut().insert(k, v);
        }
        Ok(req)
    }

    /// Tek deneme. İptal edilirse (görev düşürülür) bağlantı havuza dönmez.
    pub async fn attempt(&self, a: Attempt<'_>) -> Result<Response, Failure> {
        let deadline = Instant::now() + a.total.max(a.timeout);
        let step = |d: Duration| deadline.min(Instant::now() + d);
        let key = a.endpoint.pool_key();
        let pooled = self.checkout(&key);
        let from_pool = pooled.is_some();
        let fail = |message: String, sent: bool| Failure {
            message,
            from_pool,
            sent,
        };
        let mut sender = match pooled {
            Some(s) => s,
            None => tokio::time::timeout_at(step(a.timeout), self.open(a.endpoint))
                .await
                .map_err(|_| fail(TIMED_OUT.into(), false))?
                .map_err(|m| fail(m, false))?,
        };
        let mut headers = a.headers;
        // Python `http.client`: gövdesiz POST da `Content-Length: 0` taşır.
        if a.body.is_none() && a.method == Method::POST {
            headers.push((http::header::CONTENT_LENGTH, HeaderValue::from_static("0")));
        }
        let req = Self::request(a.endpoint, a.method, a.target, headers, full(a.body))
            .map_err(|m| fail(m, false))?;
        let resp =
            match tokio::time::timeout_at(step(a.timeout), sender.try_send_request(req)).await {
                Err(_) => return Err(fail(TIMED_OUT.into(), true)),
                Ok(Err(mut e)) => {
                    let sent = e.take_message().is_none();
                    return Err(fail(describe(e.error()), sent));
                }
                Ok(Ok(r)) => r,
            };
        let (parts, mut incoming) = resp.into_parts();
        let mut body = BytesMut::new();
        loop {
            let frame = tokio::time::timeout_at(step(a.timeout), incoming.frame())
                .await
                .map_err(|_| fail(TIMED_OUT.into(), true))?;
            let Some(frame) = frame else { break };
            if let Ok(data) = frame.map_err(|e| fail(describe(&e), true))?.into_data() {
                if body.len() + data.len() > a.max_body {
                    return Err(fail("response too large".into(), true));
                }
                body.extend_from_slice(&data);
            }
        }
        if sender.is_ready()
            || tokio::time::timeout(Duration::from_millis(100), sender.ready())
                .await
                .is_ok_and(|r| r.is_ok())
        {
            self.checkin(key, sender);
        }
        Ok(Response {
            status: parts.status.as_u16(),
            headers: parts.headers,
            body: body.freeze(),
        })
    }

    /// Akışlı yükleme: BİLEREK havuzsuz (gövde geri sarılamaz, yeniden deneme yok). `idle` = gövde ilerlemeden ve
    /// yanıt gelmeden geçebilecek en uzun süre (büyük ama ilerleyen yükleme kesilmez).
    #[allow(clippy::too_many_arguments)]
    pub async fn upload<B>(
        &self,
        ep: &Endpoint,
        target: &str,
        mut headers: Vec<(HeaderName, HeaderValue)>,
        body: B,
        content_length: u64,
        idle: Duration,
        max_body: usize,
    ) -> Result<Response, String>
    where
        B: Body<Data = Bytes> + Send + Unpin + 'static,
        B::Error: Into<BoxError>,
    {
        let progress = Arc::new(Mutex::new(Instant::now()));
        let mut sender = tokio::time::timeout(idle, self.open(ep))
            .await
            .map_err(|_| TIMED_OUT.to_string())??;
        headers.push((
            http::header::CONTENT_LENGTH,
            HeaderValue::from(content_length),
        ));
        let body = Counted {
            inner: body,
            remaining: content_length,
            progress: progress.clone(),
        }
        .boxed_unsync();
        let req = Self::request(ep, Method::POST, target, headers, body)?;
        let send = sender.send_request(req);
        tokio::pin!(send);
        let resp = loop {
            let until = *progress.lock().unwrap_or_else(|e| e.into_inner()) + idle;
            tokio::select! {
                r = &mut send => break r.map_err(|e| describe(&e))?,
                _ = tokio::time::sleep_until(until) => {
                    if progress.lock().unwrap_or_else(|e| e.into_inner()).elapsed() >= idle {
                        return Err(TIMED_OUT.into());
                    }
                }
            }
        };
        let (parts, incoming) = resp.into_parts();
        let limited = http_body_util::Limited::new(incoming, max_body);
        let body = tokio::time::timeout(idle, limited.collect())
            .await
            .map_err(|_| TIMED_OUT.to_string())?
            .map_err(|e| describe(e.as_ref()))?
            .to_bytes();
        Ok(Response {
            status: parts.status.as_u16(),
            headers: parts.headers,
            body,
        })
    }
}

/// Bildirilen uzunluğu denetler (erken biten ya da taşan gövde = hata) ve ilerlemeyi işaretler.
struct Counted<B> {
    inner: B,
    remaining: u64,
    progress: Arc<Mutex<Instant>>,
}

impl<B> Body for Counted<B>
where
    B: Body<Data = Bytes> + Unpin,
    B::Error: Into<BoxError>,
{
    type Data = Bytes;
    type Error = BoxError;

    fn poll_frame(
        mut self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Option<Result<Frame<Bytes>, BoxError>>> {
        use std::task::{ready, Poll};
        let next = ready!(std::pin::Pin::new(&mut self.inner).poll_frame(cx));
        Poll::Ready(match next {
            Some(Ok(f)) => {
                let len = f.data_ref().map_or(0, |d| d.len() as u64);
                if len > self.remaining {
                    Some(Err("upload body longer than declared".into()))
                } else {
                    self.remaining -= len;
                    *self.progress.lock().unwrap_or_else(|e| e.into_inner()) = Instant::now();
                    Some(Ok(f))
                }
            }
            Some(Err(e)) => Some(Err(e.into())),
            None if self.remaining > 0 => Some(Err(format!(
                "upload body ended early, {} bytes missing",
                self.remaining
            )
            .into())),
            None => None,
        })
    }
}
