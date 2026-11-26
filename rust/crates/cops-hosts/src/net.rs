//! TCP + TLS bağlantı kurucu. REST, WS ve gRPC AYNI kapıdan geçer: DNS adı çözülen her adres bağlanmadan ÖNCE denetlenir
//! (kontrol edilen adres = bağlanılan adres, DNS rebinding penceresi yok).

use std::io;
use std::net::{IpAddr, SocketAddr};
use std::pin::Pin;
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll};

use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::TcpStream;
use tokio_rustls::rustls::pki_types::ServerName;
use tokio_rustls::rustls::{ClientConfig, RootCertStore};
use tokio_rustls::TlsConnector;

use crate::endpoint::Endpoint;
use crate::guard;

pub enum Stream {
    Plain(TcpStream),
    Tls(Box<tokio_rustls::client::TlsStream<TcpStream>>),
}

macro_rules! delegate {
    ($self:ident, $s:ident => $e:expr) => {
        match $self.get_mut() {
            Stream::Plain($s) => {
                let $s = Pin::new($s);
                $e
            }
            Stream::Tls($s) => {
                let $s = Pin::new($s.as_mut());
                $e
            }
        }
    };
}

impl AsyncRead for Stream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        delegate!(self, s => s.poll_read(cx, buf))
    }
}

impl AsyncWrite for Stream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        delegate!(self, s => s.poll_write(cx, buf))
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        delegate!(self, s => s.poll_flush(cx))
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        delegate!(self, s => s.poll_shutdown(cx))
    }
}

/// Ad çözümleyici (testler sahtesini verir).
pub type Resolver = Arc<dyn Fn(String, u16) -> ResolveFuture + Send + Sync>;
pub type ResolveFuture = futures_util::future::BoxFuture<'static, io::Result<Vec<SocketAddr>>>;

pub fn system_resolver() -> Resolver {
    Arc::new(|host, port| {
        Box::pin(async move { Ok(tokio::net::lookup_host((host, port)).await?.collect()) })
    })
}

#[derive(Clone)]
pub struct Connector {
    pub resolver: Resolver,
    /// Test ya da özel CA için; yoksa sistem kök deposu (ilk TLS bağlantısında bir kez yüklenir).
    pub tls: Option<Arc<ClientConfig>>,
}

impl Default for Connector {
    fn default() -> Self {
        Connector {
            resolver: system_resolver(),
            tls: None,
        }
    }
}

fn system_tls() -> io::Result<Arc<ClientConfig>> {
    static CFG: OnceLock<Result<Arc<ClientConfig>, String>> = OnceLock::new();
    CFG.get_or_init(|| {
        let mut roots = RootCertStore::empty();
        roots.add_parsable_certificates(rustls_native_certs::load_native_certs().certs);
        tls_config(roots)
    })
    .clone()
    .map_err(io::Error::other)
}

/// Verilen köklerle istemci yapılandırması (ring sağlayıcısı açıkça: süreç varsayılanına bağlı değil).
pub fn tls_config(roots: RootCertStore) -> Result<Arc<ClientConfig>, String> {
    let provider = Arc::new(tokio_rustls::rustls::crypto::ring::default_provider());
    ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map(|b| Arc::new(b.with_root_certificates(roots).with_no_client_auth()))
        .map_err(|e| e.to_string())
}

fn blocked_error(host: &str, ip: IpAddr) -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        format!("blocked: {host} resolved to a loopback/link-local/unspecified address ({ip})"),
    )
}

impl Connector {
    /// IP literalleri kayıt anında denetlendi (ve reach loopback istisnası taşır); DNS adları burada denetlenir.
    pub async fn tcp(&self, ep: &Endpoint) -> io::Result<TcpStream> {
        let addrs = match ep.host.split('%').next().unwrap_or("").parse::<IpAddr>() {
            Ok(ip) => vec![SocketAddr::new(ip, ep.port)],
            Err(_) => (self.resolver)(ep.host.clone(), ep.port).await?,
        };
        let mut last = io::Error::new(
            io::ErrorKind::NotFound,
            format!("no address for {}", ep.host),
        );
        for addr in addrs {
            if ep.is_dns_name() && guard::ip_is_blocked(addr.ip()) {
                return Err(blocked_error(&ep.host, addr.ip()));
            }
            match TcpStream::connect(addr).await {
                Ok(s) => {
                    let _ = s.set_nodelay(true);
                    return Ok(s);
                }
                Err(e) => last = e,
            }
        }
        Err(last)
    }

    pub async fn connect(&self, ep: &Endpoint, alpn: &[&[u8]]) -> io::Result<Stream> {
        let tcp = self.tcp(ep).await?;
        if !ep.https {
            return Ok(Stream::Plain(tcp));
        }
        let mut cfg = match &self.tls {
            Some(c) => c.clone(),
            None => system_tls()?,
        };
        if !alpn.is_empty() {
            let mut c = (*cfg).clone();
            c.alpn_protocols = alpn.iter().map(|p| p.to_vec()).collect();
            cfg = Arc::new(c);
        }
        let name = ServerName::try_from(ep.host.clone())
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "invalid TLS server name"))?;
        let tls = TlsConnector::from(cfg).connect(name, tcp).await?;
        Ok(Stream::Tls(Box::new(tls)))
    }
}
