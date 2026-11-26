//! `GET` istemcisi ([`crate::ModelIo::http_get`] için): hyper (HTTP/1.1) + rustls (sistem kök sertifikaları, doğrulama
//! HEP açık). Proxy ortam değişkenleri [`proxy`] kurallarıyla.
//!
//! Python `urllib`den BİLİNÇLİ fark: YÖNLENDİRME İZLENMEZ (TOBEDECIDED #389 varsayılanı). Python izler ve API anahtarı
//! başlığını yeni adrese (başka alan adı, `http`) de taşır; burada 3xx diğer 2xx dışı durumlar gibi hatadır.
//!
//! Süre TOPLAM süredir (ad çözümleme, bağlantı, TLS, gövde). Her istek kendi iş parçacığında kendi çalışma zamanıyla
//! koşar: çağıran bir tokio bağlamında olsa da güvenlidir. [`HttpError`] adres, başlık ya da gövde TAŞIMAZ.

use crate::model_sources::HttpRequest;
use crate::real::proxy::{self, Route};
use crate::real::Env;
use bytes::Bytes;
use http_body_util::{BodyExt, Empty, Limited};
use hyper::header::{HeaderName, HeaderValue, ACCEPT_ENCODING, CONNECTION, HOST, PROXY_AUTHORIZATION, USER_AGENT};
use hyper::{Method, Request, Uri};
use hyper_util::rt::TokioIo;
use std::sync::{Arc, OnceLock};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio_rustls::rustls::pki_types::ServerName;
use tokio_rustls::rustls::{self, ClientConfig, RootCertStore};
use tokio_rustls::TlsConnector;

/// `CONNECT` yanıt başlığı sınırı.
const TUNNEL_HEAD_MAX: usize = 64 * 1024;
const AGENT: &str = "claudeops";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpError {
    /// Adres/başlık gönderilemez (şema, kullanıcı bilgisi, geçersiz karakter).
    Request,
    /// Proxy ayarı kullanılamıyor ya da tünel açılamadı.
    Proxy,
    Connect,
    Tls,
    /// 2xx dışı durum (yönlendirmeler dahil).
    Status(u16),
    TooBig,
    Timeout,
    /// Bozuk ya da yarım yanıt.
    Protocol,
}

pub struct HttpClient {
    env: Env,
    tls: OnceLock<Option<Arc<ClientConfig>>>,
}

fn config(roots: RootCertStore) -> Option<Arc<ClientConfig>> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let builder = ClientConfig::builder_with_provider(provider).with_safe_default_protocol_versions().ok()?;
    Some(Arc::new(builder.with_root_certificates(roots).with_no_client_auth()))
}

trait Stream: AsyncRead + AsyncWrite + Unpin + Send {}
impl<T: AsyncRead + AsyncWrite + Unpin + Send> Stream for T {}

/// `host[:port]` -> (köşeli parantezsiz ad, kapı).
fn host_port(hostport: &str, default: u16) -> Option<(String, u16)> {
    let uri: hyper::http::uri::Authority = hostport.parse().ok()?;
    let host = uri.host().trim_start_matches('[').trim_end_matches(']').to_string();
    let rest = &hostport[uri.host().len().min(hostport.len())..];
    let port = match rest.strip_prefix(':') {
        None if rest.is_empty() => default,
        Some("") => default,
        Some(p) => p.parse().ok()?,
        None => return None,
    };
    (!host.is_empty()).then_some((host, port))
}

impl HttpClient {
    /// Kök sertifikalar ilk TLS isteğinde sistemden okunur (`SSL_CERT_FILE`/`SSL_CERT_DIR` süreç ortamı geçerli).
    pub fn new(env: Env) -> HttpClient {
        HttpClient { env, tls: OnceLock::new() }
    }

    /// Yalnız verilen köklerle (özel kurum kökü ya da test).
    pub fn with_roots(env: Env, roots: RootCertStore) -> HttpClient {
        let tls = OnceLock::new();
        let _ = tls.set(config(roots));
        HttpClient { env, tls }
    }

    fn tls(&self) -> Result<Arc<ClientConfig>, HttpError> {
        self.tls
            .get_or_init(|| {
                let mut roots = RootCertStore::empty();
                roots.add_parsable_certificates(rustls_native_certs::load_native_certs().certs);
                config(roots)
            })
            .clone()
            .ok_or(HttpError::Tls)
    }

    async fn secure(&self, stream: Box<dyn Stream>, host: &str) -> Result<Box<dyn Stream>, HttpError> {
        let name = ServerName::try_from(host.to_string()).map_err(|_| HttpError::Tls)?;
        let secured = TlsConnector::from(self.tls()?).connect(name, stream).await.map_err(|_| HttpError::Tls)?;
        Ok(Box::new(secured))
    }

    async fn fetch(&self, req: &HttpRequest) -> Result<Vec<u8>, HttpError> {
        let uri: Uri = req.url.parse().map_err(|_| HttpError::Request)?;
        let https = match uri.scheme_str() {
            Some("http") => false,
            Some("https") => true,
            _ => return Err(HttpError::Request),
        };
        let netloc = uri.authority().map(|a| a.as_str().to_string()).ok_or(HttpError::Request)?;
        // `kullanıcı:parola@` taşıyan adres gönderilmez (Python da `nonnumeric port` ile düşer)
        if netloc.contains('@') {
            return Err(HttpError::Request);
        }
        let default = if https { 443 } else { 80 };
        let (host, port) = host_port(&netloc, default).ok_or(HttpError::Request)?;
        let route = proxy::route(&self.env.vars(), if https { "https" } else { "http" }, &netloc);
        let mut forward_auth = None;
        let mut absolute = false;
        let stream: Box<dyn Stream> = match &route {
            Route::Unusable => return Err(HttpError::Proxy),
            Route::Direct => {
                let tcp = TcpStream::connect((host.as_str(), port)).await.map_err(|_| HttpError::Connect)?;
                if https {
                    self.secure(Box::new(tcp), &host).await?
                } else {
                    Box::new(tcp)
                }
            }
            Route::Proxy { hostport, tls_to_proxy, auth } => {
                let proxy_default = if https || *tls_to_proxy { 443 } else { 80 };
                let (phost, pport) = host_port(hostport, proxy_default).ok_or(HttpError::Proxy)?;
                let mut tcp = TcpStream::connect((phost.as_str(), pport)).await.map_err(|_| HttpError::Proxy)?;
                if https {
                    tunnel(&mut tcp, &host, port, auth.as_ref().map(|a| a.expose())).await?;
                    self.secure(Box::new(tcp), &host).await?
                } else {
                    forward_auth = auth.clone();
                    absolute = true;
                    if *tls_to_proxy {
                        self.secure(Box::new(tcp), &phost).await?
                    } else {
                        Box::new(tcp)
                    }
                }
            }
        };
        let target = if absolute {
            req.url.split('#').next().unwrap_or_default().to_string()
        } else {
            uri.path_and_query().map_or("/", |p| p.as_str()).to_string()
        };
        let mut request = Request::builder().method(Method::GET).uri(target);
        let headers = request.headers_mut().ok_or(HttpError::Request)?;
        headers.insert(HOST, HeaderValue::from_str(&netloc).map_err(|_| HttpError::Request)?);
        headers.insert(USER_AGENT, HeaderValue::from_static(AGENT));
        headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("identity"));
        headers.insert(CONNECTION, HeaderValue::from_static("close"));
        for (name, value) in &req.headers {
            let name = HeaderName::from_bytes(name.as_bytes()).map_err(|_| HttpError::Request)?;
            headers.insert(name, secret_header(value.expose())?);
        }
        if let Some(auth) = &forward_auth {
            headers.insert(PROXY_AUTHORIZATION, secret_header(auth.expose())?);
        }
        let request = request.body(Empty::<Bytes>::new()).map_err(|_| HttpError::Request)?;
        let (mut sender, connection) =
            hyper::client::conn::http1::handshake(TokioIo::new(stream)).await.map_err(|_| HttpError::Protocol)?;
        // bağlantı görevi: çalışma zamanı kapanınca düşer
        tokio::spawn(async move {
            let _ = connection.await;
        });
        let response = sender.send_request(request).await.map_err(|_| HttpError::Protocol)?;
        let status = response.status();
        if !status.is_success() {
            return Err(HttpError::Status(status.as_u16()));
        }
        let limit = usize::try_from(req.max_body).unwrap_or(usize::MAX);
        let body = Limited::new(response.into_body(), limit).collect().await.map_err(|e| {
            if e.downcast_ref::<http_body_util::LengthLimitError>().is_some() {
                HttpError::TooBig
            } else {
                HttpError::Protocol
            }
        })?;
        Ok(body.to_bytes().to_vec())
    }

    /// `GET`; yalnız 2xx yanıtın gövdesi.
    pub fn get(&self, req: &HttpRequest) -> Result<Vec<u8>, HttpError> {
        std::thread::scope(|scope| {
            let job = std::thread::Builder::new().name("model-http".into()).spawn_scoped(scope, || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_io()
                    .enable_time()
                    .build()
                    .map_err(|_| HttpError::Connect)?;
                let result = runtime.block_on(async {
                    tokio::time::timeout(req.timeout, self.fetch(req)).await.map_err(|_| HttpError::Timeout)?
                });
                // süren ad çözümleme iş parçacığı beklenmez (süre sınırı aşılmasın)
                runtime.shutdown_background();
                result
            });
            job.map_err(|_| HttpError::Connect)?.join().map_err(|_| HttpError::Protocol)?
        })
    }
}

fn secret_header(value: &[u8]) -> Result<HeaderValue, HttpError> {
    let mut header = HeaderValue::from_bytes(value).map_err(|_| HttpError::Request)?;
    header.set_sensitive(true);
    Ok(header)
}

/// `http.client` tüneli: `CONNECT host:port HTTP/1.0`, yalnız 200.
async fn tunnel(tcp: &mut TcpStream, host: &str, port: u16, auth: Option<&[u8]>) -> Result<(), HttpError> {
    let host = if host.contains(':') { format!("[{host}]") } else { host.to_string() };
    let mut head = format!("CONNECT {host}:{port} HTTP/1.0\r\n").into_bytes();
    if let Some(auth) = auth {
        head.extend_from_slice(b"Proxy-Authorization: ");
        head.extend_from_slice(auth);
        head.extend_from_slice(b"\r\n");
    }
    head.extend_from_slice(b"\r\n");
    tcp.write_all(&head).await.map_err(|_| HttpError::Proxy)?;
    // bayt bayt: başlıktan sonrası TLS'e ait
    let mut reply = Vec::new();
    while !reply.ends_with(b"\r\n\r\n") {
        let byte = tcp.read_u8().await.map_err(|_| HttpError::Proxy)?;
        reply.push(byte);
        if reply.len() > TUNNEL_HEAD_MAX {
            return Err(HttpError::Proxy);
        }
    }
    let status = reply.split(|b| *b == b' ').nth(1);
    if reply.starts_with(b"HTTP/") && status.is_some_and(|s| s.starts_with(b"200")) {
        Ok(())
    } else {
        Err(HttpError::Proxy)
    }
}
