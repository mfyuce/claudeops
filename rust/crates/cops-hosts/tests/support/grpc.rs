//! Sahte `HostBridge` gRPC sunucusu (tonic, protoc'suz: crate'in kendi `pb` mesajlarıyla), isteğe bağlı TLS.
//! Sayaçlar: TCP kabulü, TLS hatası, açık TCP, çağrılar (yöntem + `authorization`), açık sunucu akışı (istemci
//! iptal edince düşer).

use std::convert::Infallible;
use std::io;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;

use cops_hosts::grpc::pb;
use futures_util::future::BoxFuture;
use futures_util::stream::BoxStream;
use futures_util::StreamExt;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tokio::task::AbortHandle;
use tokio_rustls::TlsAcceptor;
use tonic::server::{Grpc, NamedService, ServerStreamingService, UnaryService};
use tonic::{Request, Response, Status};
use tonic_prost::ProstCodec;

use super::ws::Io;
use super::{wait_until, TOKEN};

#[derive(Debug, Clone)]
pub struct Call {
    pub method: String,
    pub auth: Option<String>,
    /// `StreamTermOutput` isteği (ad, dil).
    pub term: Option<(String, String)>,
    /// HTTP/2 `:scheme` ve `:authority` (istemcinin `origin`i).
    pub scheme: Option<String>,
    pub authority: Option<String>,
}

#[derive(Default)]
struct Shared {
    accepted: AtomicUsize,
    tls_failed: AtomicUsize,
    live: AtomicUsize,
    streams: AtomicUsize,
    calls: Mutex<Vec<Call>>,
    /// Sunucu akışlarına sonradan ileti göndermek için.
    senders: Mutex<Vec<mpsc::Sender<Result<StreamItem, Status>>>>,
    /// true = durum akışı ilk iletiden sonra biter (ölü akış).
    end_streams: std::sync::atomic::AtomicBool,
    refuse_term: std::sync::atomic::AtomicBool,
}

#[derive(Clone)]
pub enum StreamItem {
    Status(pb::StatusUpdate),
    Term(pb::TermUpdate),
}

pub fn status_update(session: &str) -> pb::StatusUpdate {
    pb::StatusUpdate {
        ok: true,
        sessions: vec![pb::SessionRow {
            name: session.into(),
            host: "local".into(),
            cwd: "/w".into(),
            running: true,
            ..Default::default()
        }],
        cli_list: vec!["claude".into()],
        extras_json: r#"{"build":{"running":"0123456789abcdef"},"junk":1}"#.into(),
        ..Default::default()
    }
}

/// TCP/TLS soketi + açık bağlantı sayacı.
struct Conn {
    io: Box<dyn Io>,
    sh: Arc<Shared>,
}

impl Drop for Conn {
    fn drop(&mut self) {
        self.sh.live.fetch_sub(1, Ordering::SeqCst);
    }
}

impl AsyncRead for Conn {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().io).poll_read(cx, buf)
    }
}

impl AsyncWrite for Conn {
    fn poll_write(self: Pin<&mut Self>, cx: &mut Context<'_>, b: &[u8]) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.get_mut().io).poll_write(cx, b)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().io).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().io).poll_shutdown(cx)
    }
}

impl tonic::transport::server::Connected for Conn {
    type ConnectInfo = ();
    fn connect_info(&self) {}
}

#[derive(Clone)]
struct Bridge(Arc<Shared>);

impl NamedService for Bridge {
    const NAME: &'static str = "claudeops.hostbridge.v1.HostBridge";
}

struct PingSvc;
impl UnaryService<pb::PingRequest> for PingSvc {
    type Response = pb::PingResponse;
    type Future = BoxFuture<'static, Result<Response<pb::PingResponse>, Status>>;
    fn call(&mut self, _: Request<pb::PingRequest>) -> Self::Future {
        Box::pin(async {
            Ok(Response::new(pb::PingResponse {
                claudeops_version: "test".into(),
            }))
        })
    }
}

/// Akış: ilk iletiler + sonra (bitirilmedikçe) istemci iptal edene dek açık; `send_all` sonradan ileti ekler.
fn open_stream<T: Send + 'static>(
    sh: Arc<Shared>,
    first: StreamItem,
    pick: fn(StreamItem) -> Option<T>,
) -> BoxStream<'static, Result<T, Status>> {
    let (tx, mut rx) = mpsc::channel::<Result<StreamItem, Status>>(16);
    sh.streams.fetch_add(1, Ordering::SeqCst);
    let end = sh.end_streams.load(Ordering::SeqCst);
    let _ = tx.try_send(Ok(first));
    // Gönderenin TEK kopyası `senders`te: `end_all` ya da `end` kipi akışı sunucu tarafında bitirir.
    if !end {
        sh.senders.lock().unwrap().push(tx);
    }
    let guard = StreamGuard(sh.clone());
    async_stream(move |cx| rx.poll_recv(cx), guard)
        .filter_map(move |r| async move {
            match r {
                Ok(item) => pick(item).map(Ok),
                Err(s) => Some(Err(s)),
            }
        })
        .boxed()
}

struct StreamGuard(Arc<Shared>);
impl Drop for StreamGuard {
    fn drop(&mut self) {
        self.0.streams.fetch_sub(1, Ordering::SeqCst);
    }
}

/// `poll_recv` tabanlı akış; düşünce `guard` sayaç azaltır (istemci iptal etti ya da akış bitti).
fn async_stream<T, F>(f: F, guard: StreamGuard) -> impl futures_util::Stream<Item = T> + Send
where
    F: FnMut(&mut Context<'_>) -> Poll<Option<T>> + Send + Unpin,
    T: Send,
{
    struct S<F> {
        f: F,
        _g: StreamGuard,
    }
    impl<T, F: FnMut(&mut Context<'_>) -> Poll<Option<T>> + Unpin> futures_util::Stream for S<F> {
        type Item = T;
        fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<T>> {
            (self.get_mut().f)(cx)
        }
    }
    S { f, _g: guard }
}

struct StatusSvc(Arc<Shared>);
impl ServerStreamingService<pb::StreamStatusRequest> for StatusSvc {
    type Response = pb::StatusUpdate;
    type ResponseStream = BoxStream<'static, Result<pb::StatusUpdate, Status>>;
    type Future = BoxFuture<'static, Result<Response<Self::ResponseStream>, Status>>;
    fn call(&mut self, _: Request<pb::StreamStatusRequest>) -> Self::Future {
        let sh = self.0.clone();
        Box::pin(async move {
            let s = open_stream(sh, StreamItem::Status(status_update("g1")), |i| match i {
                StreamItem::Status(s) => Some(s),
                _ => None,
            });
            Ok(Response::new(s))
        })
    }
}

struct TermSvc(Arc<Shared>);
impl ServerStreamingService<pb::StreamTermOutputRequest> for TermSvc {
    type Response = pb::TermUpdate;
    type ResponseStream = BoxStream<'static, Result<pb::TermUpdate, Status>>;
    type Future = BoxFuture<'static, Result<Response<Self::ResponseStream>, Status>>;
    fn call(&mut self, req: Request<pb::StreamTermOutputRequest>) -> Self::Future {
        let sh = self.0.clone();
        let r = req.into_inner();
        if let Some(c) = sh.calls.lock().unwrap().last_mut() {
            c.term = Some((r.name.clone(), r.lang.clone()));
        }
        Box::pin(async move {
            if sh.refuse_term.load(Ordering::SeqCst) {
                return Err(Status::permission_denied("signature_required"));
            }
            let first = pb::TermUpdate {
                ok: true,
                text: format!("{}/{}#grpc", r.name, r.lang),
                cols: Some(80),
                ..Default::default()
            };
            let s = open_stream(sh, StreamItem::Term(first), |i| match i {
                StreamItem::Term(t) => Some(t),
                _ => None,
            });
            Ok(Response::new(s))
        })
    }
}

impl tower_service::Service<http::Request<tonic::body::Body>> for Bridge {
    type Response = http::Response<tonic::body::Body>;
    type Error = Infallible;
    type Future = BoxFuture<'static, Result<Self::Response, Infallible>>;

    fn poll_ready(&mut self, _: &mut Context<'_>) -> Poll<Result<(), Infallible>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, req: http::Request<tonic::body::Body>) -> Self::Future {
        let sh = self.0.clone();
        Box::pin(async move {
            let method = req
                .uri()
                .path()
                .rsplit('/')
                .next()
                .unwrap_or("")
                .to_string();
            let auth = req
                .headers()
                .get("authorization")
                .and_then(|v| v.to_str().ok())
                .map(str::to_string);
            sh.calls.lock().unwrap().push(Call {
                method: method.clone(),
                auth: auth.clone(),
                term: None,
                scheme: req.uri().scheme_str().map(str::to_string),
                authority: req.uri().authority().map(|a| a.to_string()),
            });
            if auth.as_deref() != Some(&format!("Bearer {TOKEN}")) {
                return Ok(Status::unauthenticated("bad token").into_http());
            }
            Ok(match method.as_str() {
                "Ping" => {
                    Grpc::new(ProstCodec::<pb::PingResponse, pb::PingRequest>::default())
                        .unary(PingSvc, req)
                        .await
                }
                "StreamStatus" => {
                    Grpc::new(ProstCodec::<pb::StatusUpdate, pb::StreamStatusRequest>::default())
                        .server_streaming(StatusSvc(sh), req)
                        .await
                }
                "StreamTermOutput" => {
                    Grpc::new(ProstCodec::<pb::TermUpdate, pb::StreamTermOutputRequest>::default())
                        .server_streaming(TermSvc(sh), req)
                        .await
                }
                _ => Status::unimplemented("no such method").into_http(),
            })
        })
    }
}

pub struct GrpcFake {
    pub addr: SocketAddr,
    sh: Arc<Shared>,
    task: AbortHandle,
}

impl GrpcFake {
    pub async fn start(tls: Option<TlsAcceptor>) -> GrpcFake {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let sh = Arc::new(Shared::default());
        let sh2 = sh.clone();
        let incoming = futures_util::stream::unfold(listener, move |l| {
            let sh = sh2.clone();
            let tls = tls.clone();
            async move {
                loop {
                    let Ok((s, _)) = l.accept().await else {
                        return None;
                    };
                    sh.accepted.fetch_add(1, Ordering::SeqCst);
                    let io: Box<dyn Io> = match &tls {
                        None => Box::new(s),
                        Some(acc) => match acc.accept(s).await {
                            Ok(t) => Box::new(t),
                            Err(_) => {
                                sh.tls_failed.fetch_add(1, Ordering::SeqCst);
                                continue;
                            }
                        },
                    };
                    sh.live.fetch_add(1, Ordering::SeqCst);
                    return Some((Ok::<_, io::Error>(Conn { io, sh: sh.clone() }), l));
                }
            }
        });
        let svc = Bridge(sh.clone());
        let task = tokio::spawn(async move {
            let _ = tonic::transport::Server::builder()
                .add_service(svc)
                .serve_with_incoming(incoming)
                .await;
        })
        .abort_handle();
        GrpcFake { addr, sh, task }
    }

    pub fn url(&self) -> String {
        format!("http://{}", self.addr)
    }
    pub fn https_url(&self) -> String {
        format!("https://{}", self.addr)
    }
    pub fn accepted(&self) -> usize {
        self.sh.accepted.load(Ordering::SeqCst)
    }
    pub fn tls_failed(&self) -> usize {
        self.sh.tls_failed.load(Ordering::SeqCst)
    }
    pub fn live(&self) -> usize {
        self.sh.live.load(Ordering::SeqCst)
    }
    pub fn streams(&self) -> usize {
        self.sh.streams.load(Ordering::SeqCst)
    }
    pub fn calls(&self) -> Vec<Call> {
        self.sh.calls.lock().unwrap().clone()
    }
    pub fn count(&self, method: &str) -> usize {
        self.calls().iter().filter(|c| c.method == method).count()
    }
    /// `StreamTermOutput` `PERMISSION_DENIED` döner (Python `authz` gRPC terminal kapısı).
    pub fn refuse_term(&self, on: bool) {
        self.sh.refuse_term.store(on, Ordering::SeqCst);
    }
    /// Açık tüm akışları sunucu tarafında verilen durumla bitir.
    pub fn fail_streams(&self, status: Status) {
        for tx in self.sh.senders.lock().unwrap().drain(..) {
            let _ = tx.try_send(Err(status.clone()));
        }
    }
    pub fn end_streams(&self, on: bool) {
        self.sh.end_streams.store(on, Ordering::SeqCst);
    }
    /// Açık tüm akışlara ileti (alıcısı düşmüş olanlar atlanır).
    pub fn send_all(&self, item: StreamItem) {
        for tx in self.sh.senders.lock().unwrap().iter() {
            let _ = tx.try_send(Ok(item.clone()));
        }
    }
    /// Açık tüm akışları sunucu tarafında bitir.
    pub fn end_all(&self) {
        self.sh.senders.lock().unwrap().clear();
    }
    pub async fn wait_streams(&self, n: usize) {
        let sh = self.sh.clone();
        wait_until(
            &format!("{n} open gRPC stream(s)"),
            Duration::from_secs(5),
            || sh.streams.load(Ordering::SeqCst) == n,
        )
        .await
    }
    pub async fn wait_live(&self, n: usize) {
        let sh = self.sh.clone();
        wait_until(
            &format!("{n} live gRPC connection(s)"),
            Duration::from_secs(10),
            || sh.live.load(Ordering::SeqCst) == n,
        )
        .await
    }
}

impl Drop for GrpcFake {
    fn drop(&mut self) {
        self.task.abort();
    }
}
