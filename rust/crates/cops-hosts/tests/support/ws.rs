//! Sahte uzak panel: AYNI portta REST (betikli `Handler`) ve WS (`/ws`, `/ws/term`, hyper upgrade + tungstenite sunucu
//! rolü), isteğe bağlı TLS. Sunucu tarafı sayaçlar: TCP kabulü, TLS el sıkışma hatası, WS yükseltmesi, açık WS sayısı
//! (istemci soketi kapatınca düşer), istemcinin Pong/Close yanıtları.

use std::net::SocketAddr;
use std::sync::atomic::{AtomicU16, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use bytes::Bytes;
use futures_util::{SinkExt, StreamExt};
use http_body_util::{BodyExt, Empty};
use hyper::body::Incoming;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tokio::task::AbortHandle;
use tokio_rustls::TlsAcceptor;
use tokio_tungstenite::tungstenite::handshake::derive_accept_key;
use tokio_tungstenite::tungstenite::protocol::{Role, WebSocketConfig};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::WebSocketStream;

use super::{body_of, wait_until, Act, Handler, Rec, RespBody};

pub enum Cmd {
    Send(Message),
    /// Kapanış el sıkışması başlat (istemcinin Close yanıtı sayılır).
    Close,
    /// Soketi el sıkışmasız kapat (kopma).
    Drop,
}

/// Yeni WS bağlantısında hemen gönderilecek çerçeveler (el sıkışma isteğine ve bağlantı sırasına göre).
pub type Opener = Arc<dyn Fn(&Rec, usize) -> Vec<Message> + Send + Sync>;

pub trait Io: AsyncRead + AsyncWrite + Unpin + Send {}
impl<T: AsyncRead + AsyncWrite + Unpin + Send> Io for T {}

#[derive(Default)]
struct Shared {
    recs: Mutex<Vec<Rec>>,
    accepted: AtomicUsize,
    tls_failed: AtomicUsize,
    upgrades: AtomicUsize,
    ws_live: AtomicUsize,
    pongs: AtomicUsize,
    client_closes: AtomicUsize,
    /// 0 = yükselt; değilse bu durum koduyla reddet.
    refuse: AtomicU16,
    conns: Mutex<Vec<mpsc::UnboundedSender<Cmd>>>,
    tasks: Mutex<Vec<AbortHandle>>,
}

struct Dec<'a>(&'a AtomicUsize);
impl Drop for Dec<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

pub struct WsFake {
    pub addr: SocketAddr,
    sh: Arc<Shared>,
    accept: AbortHandle,
}

fn is_upgrade(req: &hyper::Request<Incoming>) -> bool {
    req.headers()
        .get(http::header::UPGRADE)
        .is_some_and(|v| v.as_bytes().eq_ignore_ascii_case(b"websocket"))
}

fn rec_of(parts: &http::request::Parts, conn: usize, idx: usize, body: Bytes) -> Rec {
    Rec {
        conn,
        idx,
        method: parts.method.to_string(),
        path: parts.uri.path().to_string(),
        query: parts.uri.query().unwrap_or("").to_string(),
        headers: parts.headers.clone(),
        body,
    }
}

async fn run_ws<S: Io + 'static>(
    sh: Arc<Shared>,
    rec: Rec,
    conn: usize,
    opener: Opener,
    mut ws: WebSocketStream<S>,
) {
    // Önce komut kanalı: `wait_ws_live` döndüğünde `send_last` bu bağlantıya ulaşır.
    let (tx, mut rx) = mpsc::unbounded_channel();
    sh.conns.lock().unwrap().push(tx);
    sh.ws_live.fetch_add(1, Ordering::SeqCst);
    let _live = Dec(&sh.ws_live);
    for m in opener(&rec, conn) {
        if ws.send(m).await.is_err() {
            return;
        }
    }
    loop {
        tokio::select! {
            cmd = rx.recv() => match cmd {
                Some(Cmd::Send(m)) => {
                    if ws.send(m).await.is_err() {
                        return;
                    }
                }
                Some(Cmd::Close) => {
                    let _ = ws.close(None).await;
                }
                Some(Cmd::Drop) | None => return,
            },
            msg = ws.next() => match msg {
                None | Some(Err(_)) => return,
                Some(Ok(Message::Pong(_))) => {
                    sh.pongs.fetch_add(1, Ordering::SeqCst);
                }
                Some(Ok(Message::Close(_))) => {
                    sh.client_closes.fetch_add(1, Ordering::SeqCst);
                }
                Some(Ok(_)) => {}
            },
        }
    }
}

impl WsFake {
    pub async fn start(rest: Handler, opener: Opener, tls: Option<TlsAcceptor>) -> WsFake {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let sh = Arc::new(Shared::default());
        let sh2 = sh.clone();
        let accept = tokio::spawn(async move {
            loop {
                let Ok((stream, _)) = listener.accept().await else {
                    return;
                };
                let conn = sh2.accepted.fetch_add(1, Ordering::SeqCst);
                let sh3 = sh2.clone();
                let rest = rest.clone();
                let opener = opener.clone();
                let tls = tls.clone();
                let task = tokio::spawn(async move {
                    let io: Box<dyn Io> = match tls {
                        None => Box::new(stream),
                        Some(acc) => match acc.accept(stream).await {
                            Ok(s) => Box::new(s),
                            Err(_) => {
                                sh3.tls_failed.fetch_add(1, Ordering::SeqCst);
                                return;
                            }
                        },
                    };
                    let idx = Arc::new(AtomicUsize::new(0));
                    let sh4 = sh3.clone();
                    let svc = service_fn(move |mut req: hyper::Request<Incoming>| {
                        let sh = sh4.clone();
                        let rest = rest.clone();
                        let opener = opener.clone();
                        let i = idx.fetch_add(1, Ordering::SeqCst);
                        async move {
                            if is_upgrade(&req) {
                                let key = req.headers().get("sec-websocket-key").cloned();
                                let on = hyper::upgrade::on(&mut req);
                                let (parts, _) = req.into_parts();
                                let rec = rec_of(&parts, conn, i, Bytes::new());
                                sh.recs.lock().unwrap().push(rec.clone());
                                let refuse = sh.refuse.load(Ordering::SeqCst);
                                let Some(key) = key.filter(|_| refuse == 0) else {
                                    let code = if refuse == 0 { 400 } else { refuse };
                                    return Ok::<_, std::io::Error>(
                                        hyper::Response::builder()
                                            .status(code)
                                            .body(body_of("refused"))
                                            .unwrap(),
                                    );
                                };
                                sh.upgrades.fetch_add(1, Ordering::SeqCst);
                                let sh5 = sh.clone();
                                let t = tokio::spawn(async move {
                                    let Ok(up) = on.await else { return };
                                    let cfg = WebSocketConfig::default()
                                        .max_message_size(None)
                                        .max_frame_size(None);
                                    let ws = WebSocketStream::from_raw_socket(
                                        TokioIo::new(up),
                                        Role::Server,
                                        Some(cfg),
                                    )
                                    .await;
                                    run_ws(sh5, rec, conn, opener, ws).await;
                                });
                                sh.tasks.lock().unwrap().push(t.abort_handle());
                                let resp: hyper::Response<RespBody> = hyper::Response::builder()
                                    .status(101)
                                    .header(http::header::CONNECTION, "Upgrade")
                                    .header(http::header::UPGRADE, "websocket")
                                    .header(
                                        "sec-websocket-accept",
                                        derive_accept_key(key.as_bytes()),
                                    )
                                    .body(
                                        Empty::<Bytes>::new()
                                            .map_err(|never| match never {})
                                            .boxed_unsync(),
                                    )
                                    .unwrap();
                                return Ok(resp);
                            }
                            let (parts, body) = req.into_parts();
                            let body = match body.collect().await {
                                Ok(b) => b.to_bytes(),
                                Err(e) => return Err(std::io::Error::other(e)),
                            };
                            let rec = rec_of(&parts, conn, i, body);
                            sh.recs.lock().unwrap().push(rec.clone());
                            match rest(rec).await {
                                Act::Reply(r) => Ok(r),
                                Act::Drop => Err(std::io::Error::other("fake: drop")),
                            }
                        }
                    });
                    let _ = hyper::server::conn::http1::Builder::new()
                        .serve_connection(TokioIo::new(io), svc)
                        .with_upgrades()
                        .await;
                });
                sh2.tasks.lock().unwrap().push(task.abort_handle());
            }
        })
        .abort_handle();
        WsFake { addr, sh, accept }
    }

    pub fn url(&self) -> String {
        format!("http://{}", self.addr)
    }
    pub fn https_url(&self) -> String {
        format!("https://{}", self.addr)
    }
    pub fn recs(&self) -> Vec<Rec> {
        self.sh.recs.lock().unwrap().clone()
    }
    /// Belirli yoldaki HTTP isteği (el sıkışmalar dahil) sayısı.
    pub fn count_path(&self, path: &str) -> usize {
        self.recs().iter().filter(|r| r.path == path).count()
    }
    pub fn accepted(&self) -> usize {
        self.sh.accepted.load(Ordering::SeqCst)
    }
    pub fn tls_failed(&self) -> usize {
        self.sh.tls_failed.load(Ordering::SeqCst)
    }
    pub fn upgrades(&self) -> usize {
        self.sh.upgrades.load(Ordering::SeqCst)
    }
    pub fn ws_live(&self) -> usize {
        self.sh.ws_live.load(Ordering::SeqCst)
    }
    pub fn pongs(&self) -> usize {
        self.sh.pongs.load(Ordering::SeqCst)
    }
    pub fn client_closes(&self) -> usize {
        self.sh.client_closes.load(Ordering::SeqCst)
    }
    pub fn refuse_upgrades(&self, code: u16) {
        self.sh.refuse.store(code, Ordering::SeqCst);
    }
    /// Tüm açık WS bağlantılarına komut.
    pub fn broadcast(&self, make: impl Fn() -> Cmd) {
        for tx in self.sh.conns.lock().unwrap().iter() {
            let _ = tx.send(make());
        }
    }
    /// Yalnız son açılan WS bağlantısına.
    pub fn send_last(&self, cmd: Cmd) {
        if let Some(tx) = self.sh.conns.lock().unwrap().last() {
            let _ = tx.send(cmd);
        }
    }
    pub async fn wait_ws_live(&self, n: usize) {
        let sh = self.sh.clone();
        wait_until(
            &format!("{n} live websocket(s) at fake server"),
            Duration::from_secs(5),
            || sh.ws_live.load(Ordering::SeqCst) == n,
        )
        .await
    }
    pub async fn wait_upgrades(&self, n: usize) {
        let sh = self.sh.clone();
        wait_until(
            &format!("{n} websocket upgrade(s)"),
            Duration::from_secs(5),
            || sh.upgrades.load(Ordering::SeqCst) >= n,
        )
        .await
    }
}

impl Drop for WsFake {
    fn drop(&mut self) {
        self.accept.abort();
        for t in self.sh.tasks.lock().unwrap().drain(..) {
            t.abort();
        }
    }
}

// ---------------------------------------------------------------- çerçeveler

pub fn status_frame(session: &str) -> Message {
    Message::text(
        serde_json::json!({"type": "status", "data": {
            "sessions": [{"name": session, "cwd": "/w", "running": true, "host": "local"}],
            "closed": [], "retired": [], "cli_list": ["claude"], "cli_options": {}, "dups": [],
            "build": {"running": "feedfacecafe0000"},
        }})
        .to_string(),
    )
}

pub fn term_frame(text: &str) -> Message {
    Message::text(
        serde_json::json!({"type": "term", "data": {"ok": true, "text": text}}).to_string(),
    )
}

/// `/ws` -> durum karesi (`s<bağlantı>`), `/ws/term` -> terim karesi (`<ad>#<bağlantı>`), başka yol -> hiçbir şey.
pub fn default_opener() -> Opener {
    Arc::new(|rec: &Rec, conn: usize| {
        if rec.path.ends_with("/ws/term") {
            let name = query_value(&rec.query, "name").unwrap_or_default();
            vec![term_frame(&format!("{name}#{conn}"))]
        } else if rec.path.ends_with("/ws") {
            vec![status_frame(&format!("s{conn}"))]
        } else {
            Vec::new()
        }
    })
}

/// Hiçbir şey göndermeyen (sessiz) açıcı.
pub fn silent_opener() -> Opener {
    Arc::new(|_: &Rec, _| Vec::new())
}

pub fn query_value(q: &str, key: &str) -> Option<String> {
    q.split('&').find_map(|kv| {
        let (k, v) = kv.split_once('=')?;
        (k == key).then(|| v.replace('+', " "))
    })
}
