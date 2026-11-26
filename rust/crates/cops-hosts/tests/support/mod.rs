//! Sahte uzak panel (127.0.0.1, rastgele port). Testler sunucu tarafındaki sayaçlarla "istek gitti/GİTMEDİ" der.
//! `Fake` = hyper sunucusu (betikli işleyici), `Raw` = çıplak TCP (susan, damla damla yanıt veren, dev gövde).
#![allow(dead_code)]

pub mod grpc;
pub mod tls;
pub mod ws;

use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;

use bytes::Bytes;
use cops_hosts::consts::Timeouts;
use cops_hosts::http::BoxError;
use cops_hosts::net::{Connector, Resolver};
use cops_hosts::sign::{OutboundRefused, OutboundSigner, Principal, SignRequest};
use cops_hosts::{HostClient, HostRecord, Secret};
use futures_util::future::BoxFuture;
use http_body_util::combinators::UnsyncBoxBody;
use http_body_util::{BodyExt, Full};
use hyper::body::{Body, Frame, Incoming};
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use serde_json::Value;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;
use tokio::task::AbortHandle;

/// Kayıtlı token: hiçbir hata metninde, olayda ya da yanıtta görünmemeli.
pub const TOKEN: &str = "SEKRET-tok-7f3a9c";

/// Tüm testlerin mutlak tavanı (asılan test CI'yi kilitlemesin).
pub async fn deadline<F: Future>(f: F) -> F::Output {
    deadline_within(Duration::from_secs(30), f).await
}

/// `deadline`, büyük veri taşıyan testler için açık tavanla (yüklü makinede 30 sn yetmiyor).
pub async fn deadline_within<F: Future>(max: Duration, f: F) -> F::Output {
    match tokio::time::timeout(max, f).await {
        Ok(v) => v,
        Err(_) => panic!("test deadline ({} s) exceeded", max.as_secs()),
    }
}

/// Koşul sağlanana dek bekle (en çok `max`); sağlanmazsa panik.
pub async fn wait_until(what: &str, max: Duration, mut cond: impl FnMut() -> bool) {
    let end = tokio::time::Instant::now() + max;
    while !cond() {
        if tokio::time::Instant::now() >= end {
            panic!("timed out waiting for: {what}");
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

#[derive(Debug, Clone)]
pub struct Rec {
    /// Sunucunun kabul ettiği bağlantının sırası (0'dan).
    pub conn: usize,
    /// Bağlantı içindeki istek sırası (0'dan).
    pub idx: usize,
    pub method: String,
    pub path: String,
    pub query: String,
    pub headers: http::HeaderMap,
    pub body: Bytes,
}

impl Rec {
    pub fn json(&self) -> Value {
        serde_json::from_slice(&self.body).expect("request body is JSON")
    }
    pub fn header(&self, name: &str) -> Option<String> {
        self.headers
            .get(name)
            .map(|v| v.to_str().unwrap().to_string())
    }
}

pub type RespBody = UnsyncBoxBody<Bytes, BoxError>;

pub enum Act {
    Reply(hyper::Response<RespBody>),
    /// Yanıt vermeden bağlantıyı kapat (istek sunucuya ULAŞMIŞ, kaydedildi).
    Drop,
}

pub fn body_of(b: impl Into<Bytes>) -> RespBody {
    Full::new(b.into())
        .map_err(|never| match never {})
        .boxed_unsync()
}

pub fn json(status: u16, v: Value) -> Act {
    Act::Reply(
        hyper::Response::builder()
            .status(status)
            .header("content-type", "application/json")
            .body(body_of(v.to_string()))
            .unwrap(),
    )
}

pub fn text(status: u16, s: &str) -> Act {
    Act::Reply(
        hyper::Response::builder()
            .status(status)
            .header("content-type", "text/html")
            .body(body_of(s.to_string()))
            .unwrap(),
    )
}

pub type Handler = Arc<dyn Fn(Rec) -> BoxFuture<'static, Act> + Send + Sync>;

pub fn handler<F, Fut>(f: F) -> Handler
where
    F: Fn(Rec) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = Act> + Send + 'static,
{
    Arc::new(move |r| Box::pin(f(r)))
}

/// Her isteğe `{"ok":true,"seq":<kaçıncı istek>}`.
pub fn ok_handler() -> Handler {
    let n = Arc::new(AtomicUsize::new(0));
    handler(move |_r| {
        let seq = n.fetch_add(1, Ordering::SeqCst) + 1;
        async move { json(200, serde_json::json!({"ok": true, "seq": seq})) }
    })
}

#[derive(Default)]
struct Shared {
    recs: Mutex<Vec<Rec>>,
    accepted: AtomicUsize,
    live: AtomicUsize,
    tasks: Mutex<Vec<AbortHandle>>,
}

/// hyper ile sahte uzak panel. Gövdenin TAMAMI alınmadan istek kaydedilmez (yarım yükleme sayılmaz).
pub struct Fake {
    pub addr: SocketAddr,
    sh: Arc<Shared>,
    accept: AbortHandle,
}

impl Fake {
    pub async fn start(h: Handler) -> Fake {
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
                sh2.live.fetch_add(1, Ordering::SeqCst);
                let sh3 = sh2.clone();
                let h = h.clone();
                let task = tokio::spawn(async move {
                    let _live = LiveGuardRef(sh3.clone());
                    let idx = Arc::new(AtomicUsize::new(0));
                    let sh4 = sh3.clone();
                    let svc = service_fn(move |req: hyper::Request<Incoming>| {
                        let h = h.clone();
                        let sh = sh4.clone();
                        let i = idx.fetch_add(1, Ordering::SeqCst);
                        async move {
                            let (parts, body) = req.into_parts();
                            let body = match body.collect().await {
                                Ok(b) => b.to_bytes(),
                                Err(e) => return Err(std::io::Error::other(e)),
                            };
                            let rec = Rec {
                                conn,
                                idx: i,
                                method: parts.method.to_string(),
                                path: parts.uri.path().to_string(),
                                query: parts.uri.query().unwrap_or("").to_string(),
                                headers: parts.headers,
                                body,
                            };
                            sh.recs.lock().unwrap().push(rec.clone());
                            match h(rec).await {
                                Act::Reply(r) => Ok::<_, std::io::Error>(r),
                                Act::Drop => Err(std::io::Error::other("fake: drop connection")),
                            }
                        }
                    });
                    let _ = hyper::server::conn::http1::Builder::new()
                        .serve_connection(TokioIo::new(stream), svc)
                        .await;
                });
                sh2.tasks.lock().unwrap().push(task.abort_handle());
            }
        })
        .abort_handle();
        Fake { addr, sh, accept }
    }

    pub fn url(&self) -> String {
        format!("http://{}", self.addr)
    }
    pub fn recs(&self) -> Vec<Rec> {
        self.sh.recs.lock().unwrap().clone()
    }
    pub fn count(&self) -> usize {
        self.sh.recs.lock().unwrap().len()
    }
    pub fn accepted(&self) -> usize {
        self.sh.accepted.load(Ordering::SeqCst)
    }
    pub fn live(&self) -> usize {
        self.sh.live.load(Ordering::SeqCst)
    }
    /// Sunucu tarafında tüm açık bağlantıları kapatır (boşta bekleyen keep-alive bağlantıları dahil).
    pub fn kill_connections(&self) {
        for t in self.sh.tasks.lock().unwrap().drain(..) {
            t.abort();
        }
    }
    pub async fn wait_count(&self, n: usize) {
        let sh = self.sh.clone();
        wait_until(
            &format!("{n} requests at fake server"),
            Duration::from_secs(5),
            || sh.recs.lock().unwrap().len() >= n,
        )
        .await
    }
    pub async fn wait_no_live(&self) {
        let sh = self.sh.clone();
        wait_until(
            "fake server connections closed",
            Duration::from_secs(5),
            || sh.live.load(Ordering::SeqCst) == 0,
        )
        .await
    }
}

/// Bağlantı görevinin canlılık sayacı (iptalde de düşer).
struct LiveGuardRef(Arc<Shared>);
impl Drop for LiveGuardRef {
    fn drop(&mut self) {
        self.0.live.fetch_sub(1, Ordering::SeqCst);
    }
}

impl Drop for Fake {
    fn drop(&mut self) {
        self.accept.abort();
        self.kill_connections();
    }
}

/// Çıplak TCP sunucusu: her bağlantı verilen betikle işlenir.
pub struct Raw {
    pub addr: SocketAddr,
    sh: Arc<Shared>,
    accept: AbortHandle,
}

impl Raw {
    pub async fn start<F, Fut>(f: F) -> Raw
    where
        F: Fn(TcpStream) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = ()> + Send + 'static,
    {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let sh = Arc::new(Shared::default());
        let sh2 = sh.clone();
        let f = Arc::new(f);
        let accept = tokio::spawn(async move {
            loop {
                let Ok((stream, _)) = listener.accept().await else {
                    return;
                };
                sh2.accepted.fetch_add(1, Ordering::SeqCst);
                sh2.live.fetch_add(1, Ordering::SeqCst);
                let sh3 = sh2.clone();
                let f = f.clone();
                let task = tokio::spawn(async move {
                    let _live = LiveGuardRef(sh3);
                    f(stream).await;
                });
                sh2.tasks.lock().unwrap().push(task.abort_handle());
            }
        })
        .abort_handle();
        Raw { addr, sh, accept }
    }
    pub fn url(&self) -> String {
        format!("http://{}", self.addr)
    }
    pub fn accepted(&self) -> usize {
        self.sh.accepted.load(Ordering::SeqCst)
    }
    pub fn live(&self) -> usize {
        self.sh.live.load(Ordering::SeqCst)
    }
    /// İstemci tüm soketlerini kapatana dek bekle (sunucu tarafı EOF okur).
    pub async fn wait_no_live(&self) {
        let sh = self.sh.clone();
        wait_until(
            "client closed every socket to raw server",
            Duration::from_secs(5),
            || sh.live.load(Ordering::SeqCst) == 0,
        )
        .await
    }
}

impl Drop for Raw {
    fn drop(&mut self) {
        self.accept.abort();
        for t in self.sh.tasks.lock().unwrap().drain(..) {
            t.abort();
        }
    }
}

/// İstek başlığını (boş satıra dek, en çok 64 KiB) okur.
pub async fn read_head(s: &mut TcpStream) -> bool {
    let mut buf = Vec::new();
    let mut b = [0u8; 1024];
    while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
        match s.read(&mut b).await {
            Ok(0) | Err(_) => return false,
            Ok(n) => buf.extend_from_slice(&b[..n]),
        }
        if buf.len() > 65536 {
            return false;
        }
    }
    true
}

/// Hiç yanıt vermez; istemci soketi kapatınca (EOF) çıkar.
pub async fn hold_until_eof(mut s: TcpStream) {
    let mut b = [0u8; 1024];
    loop {
        match s.read(&mut b).await {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
    }
}

/// Yazma hata verene dek (istemci kapatana dek) yazar; çıkışta bağlantı kapanır.
pub async fn write_until_error(s: &mut TcpStream, chunk: &[u8], gap: Duration) {
    loop {
        if s.write_all(chunk).await.is_err() {
            return;
        }
        if !gap.is_zero() {
            tokio::time::sleep(gap).await;
        }
    }
}

pub fn host(name: &str, base_url: &str) -> HostRecord {
    HostRecord {
        name: name.into(),
        base_url: base_url.into(),
        token: Secret::new(TOKEN),
        ..Default::default()
    }
}

/// Kısa zaman aşımlı istemci (testler saniyeler içinde biter).
pub fn timeouts() -> Timeouts {
    let s = Duration::from_secs;
    Timeouts {
        status: s(3),
        term_read: s(3),
        action: s(3),
        fallback: s(1),
        long_read: s(3),
        term_attempt: s(2),
        ws_probe: s(1),
        grpc_probe: s(1),
        ws_open: s(2),
        total_cap: s(10),
    }
}

pub fn client() -> HostClient {
    let mut c = HostClient::new(Connector::default());
    c.timeouts = timeouts();
    c
}

/// Çağrı sayan, her adı verilen adrese çözen sahte çözümleyici.
pub fn counting_resolver(to: SocketAddr, calls: Arc<AtomicUsize>) -> Resolver {
    Arc::new(move |_host, _port| {
        calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move { Ok(vec![to]) })
    })
}

pub fn principal(uid: &str) -> Principal {
    let mut p = Principal::legacy();
    p.uid = uid.into();
    p
}

#[derive(Debug, Clone)]
pub struct Seen {
    pub uid: String,
    pub host_name: String,
    pub method: String,
    pub path: String,
    pub body: Option<Vec<u8>>,
}

pub enum SignMode {
    /// `x-test-sig: sig-<n>` (her çağrıda yeni değer, nonce gibi).
    Sign,
    Refuse,
    Panic,
    Header(&'static str, &'static str),
}

pub struct TestSigner {
    pub calls: AtomicUsize,
    pub seen: Mutex<Vec<Seen>>,
    pub mode: SignMode,
}

impl TestSigner {
    pub fn new(mode: SignMode) -> Arc<TestSigner> {
        Arc::new(TestSigner {
            calls: AtomicUsize::new(0),
            seen: Mutex::new(Vec::new()),
            mode,
        })
    }
    pub fn calls(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }
    pub fn seen(&self) -> Vec<Seen> {
        self.seen.lock().unwrap().clone()
    }
}

impl OutboundSigner for TestSigner {
    fn sign(&self, req: SignRequest<'_>) -> Result<Vec<(String, String)>, OutboundRefused> {
        let n = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        self.seen.lock().unwrap().push(Seen {
            uid: req.principal.uid.clone(),
            host_name: req.host_name.into(),
            method: req.method.into(),
            path: req.path.into(),
            body: req.body.map(<[u8]>::to_vec),
        });
        match self.mode {
            SignMode::Sign => Ok(vec![
                ("x-test-sig".into(), format!("sig-{n}")),
                ("x-test-uid".into(), req.principal.uid.clone()),
            ]),
            SignMode::Refuse => Err(OutboundRefused {
                reason: "no_key".into(),
            }),
            SignMode::Panic => panic!("test signer panic"),
            SignMode::Header(k, v) => Ok(vec![(k.into(), v.into())]),
        }
    }
}

/// Kanal beslemeli yükleme gövdesi: test parçaları istediği hızda yollar; gönderici düşünce gövde biter.
pub struct ChanBody(pub mpsc::Receiver<Bytes>);

impl Body for ChanBody {
    type Data = Bytes;
    type Error = std::io::Error;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Self::Error>>> {
        self.0.poll_recv(cx).map(|o| o.map(|b| Ok(Frame::data(b))))
    }
}

pub fn chan_body() -> (mpsc::Sender<Bytes>, ChanBody) {
    let (tx, rx) = mpsc::channel(16);
    (tx, ChanBody(rx))
}

/// Hata metni/yanıt URL, port ya da sır taşımamalı.
pub fn assert_clean(text: &str, port: u16) {
    assert!(!text.contains(TOKEN), "token leaked: {text}");
    assert!(!text.contains("token="), "query leaked: {text}");
    assert!(!text.contains("://"), "URL leaked: {text}");
    assert!(
        !text.contains(&format!(":{port}")),
        "address leaked: {text}"
    );
}

/// Bu süreçteki açık fd sayısı.
pub fn fd_count() -> usize {
    std::fs::read_dir("/proc/self/fd").unwrap().count()
}

// ---------------------------------------------------------------- iş 2: federasyon/sağlık

/// Olayları toplayan `Events` (alanlarda token olmamalı).
#[derive(Default)]
pub struct RecEvents(pub Mutex<Vec<(String, Value)>>);

impl RecEvents {
    pub fn names(&self) -> Vec<String> {
        self.0
            .lock()
            .unwrap()
            .iter()
            .map(|(n, _)| n.clone())
            .collect()
    }
    pub fn all(&self) -> Vec<(String, Value)> {
        self.0.lock().unwrap().clone()
    }
}

impl cops_hosts::events::Events for RecEvents {
    fn log(&self, event: &str, fields: Value) {
        self.0.lock().unwrap().push((event.into(), fields));
    }
}

/// Bellek içi `HostSource`: `promote` kaydı `record::promote_base_url` ile GERÇEKTEN günceller (Python
/// `hosts_mod.promote_base_url` gibi), çağrılar sayılır.
#[derive(Default)]
pub struct MemSource {
    pub hosts: Mutex<Vec<HostRecord>>,
    pub promotes: Mutex<Vec<(String, String)>>,
    pub switches: Mutex<Vec<String>>,
    pub loads: AtomicUsize,
    /// `None` = varsayılan reach portları.
    pub ports: Mutex<Option<std::collections::BTreeSet<u16>>>,
    pub choice: Mutex<Option<String>>,
    /// true = `load` panikler (poller/prober panik kurtarma testi).
    pub panic_load: std::sync::atomic::AtomicBool,
}

impl MemSource {
    pub fn new(hosts: Vec<HostRecord>) -> Arc<MemSource> {
        let s = MemSource::default();
        *s.hosts.lock().unwrap() = hosts;
        Arc::new(s)
    }
    pub fn promotes(&self) -> Vec<(String, String)> {
        self.promotes.lock().unwrap().clone()
    }
    pub fn base_url(&self, name: &str) -> String {
        self.hosts
            .lock()
            .unwrap()
            .iter()
            .find(|h| h.name == name)
            .map(|h| h.base_url.clone())
            .unwrap_or_default()
    }
}

impl cops_hosts::HostSource for MemSource {
    fn load(&self) -> Vec<HostRecord> {
        self.loads.fetch_add(1, Ordering::SeqCst);
        if self.panic_load.load(Ordering::SeqCst) {
            panic!("test: host source panicked");
        }
        self.hosts.lock().unwrap().clone()
    }
    fn promote(&self, name: &str, new_base_url: &str) {
        self.promotes
            .lock()
            .unwrap()
            .push((name.into(), new_base_url.into()));
        let mut h = self.hosts.lock().unwrap();
        let cur = cops_hosts::record::Parsed {
            hosts: h.clone(),
            ..Default::default()
        };
        if let Some(next) = cops_hosts::record::promote_base_url(&cur, name, new_base_url) {
            *h = next;
        }
    }
    fn reach_ports(&self) -> std::collections::BTreeSet<u16> {
        self.ports
            .lock()
            .unwrap()
            .clone()
            .unwrap_or_else(|| cops_hosts::guard::reach_loopback_ports(None))
    }
    fn probe_choice(&self, _host: &HostRecord) -> Option<String> {
        self.choice.lock().unwrap().clone()
    }
    fn note_switch(&self, name: &str) {
        self.switches.lock().unwrap().push(name.into());
    }
}

/// Dinleyicisi olmayan loopback portu (bağlanma hemen reddedilir).
pub async fn closed_port() -> u16 {
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    l.local_addr().unwrap().port()
}

/// Belirli yoldaki istek sayısı.
pub fn count_path(f: &Fake, path: &str) -> usize {
    f.recs().iter().filter(|r| r.path == path).count()
}
