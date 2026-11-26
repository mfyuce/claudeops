//! `gate::RouteHook` (enterprise A6b-2: `/api/auth/*` Rust'ta): kanca takılı değilse ya da `route` `None` dönerse istek Python'a
//! AYNEN gider; `Some(sınır)` dönerse gövde en çok `sınır` bayt okunur, yanıtı kanca verir (Python'a hiçbir şey gitmez). Sınırı aşan
//! gövde `BodyError::TooLarge`; panik 500, süre aşımı 503 (fail-closed); `/api/_internal/*` kancaya da gitmez; https bilgisi yalnız
//! loopback eşten.
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::gate::{BodyError, RouteHook, RouteRequest, RouteResponse};
use cops_proxy::Proxy;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

/// Aldığı isteğin baş kısmını gövde olarak geri döner (Python yerine).
async fn echo_upstream() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut tmp = [0u8; 4096];
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                    let n = c.read(&mut tmp).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    buf.extend_from_slice(&tmp[..n]);
                }
                let mut out = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    buf.len() + 9
                )
                .into_bytes();
                out.extend_from_slice(b"UPSTREAM:");
                out.extend_from_slice(&buf);
                let _ = c.write_all(&out).await;
            });
        }
    });
    addr
}

#[derive(Debug, Clone)]
struct Seen {
    view: RequestView,
    body: Result<Vec<u8>, BodyError>,
    https: bool,
}

/// `/api/auth/` altını üstlenir (`/api/auth/pass` hariç); `X-T: panic|slow` davranışı.
struct Hook(Mutex<Vec<Seen>>);

impl RouteHook for Hook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (view.path.starts_with("/api/auth/") && view.path != "/api/auth/pass").then_some(16)
    }

    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async move {
            self.0.lock().unwrap().push(Seen {
                view: req.view.clone(),
                body: req.body.clone().map(|b| b.to_vec()),
                https: req.https,
            });
            match req.view.header("x-t") {
                Some("panic") => panic!("kanca paniği"),
                Some("slow") => {
                    tokio::time::sleep(Duration::from_secs(10)).await;
                }
                _ => {}
            }
            RouteResponse {
                status: 201,
                headers: vec![
                    ("Content-Type".into(), "application/json".into()),
                    ("Set-Cookie".into(), "a=1".into()),
                    ("Set-Cookie".into(), "b=2".into()),
                ],
                body: br#"{"ok": true}"#.to_vec(),
            }
        })
    }

    fn timeout(&self) -> Duration {
        Duration::from_millis(500)
    }

    fn body_timeout(&self) -> Duration {
        Duration::from_millis(300)
    }
}

async fn start(h: Option<Arc<Hook>>) -> SocketAddr {
    let up = echo_upstream().await;
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    drop(l);
    let px = Proxy::with_secret(up, "onkapi");
    let px = match h {
        Some(h) => px.with_routes(h),
        None => px,
    };
    tokio::spawn(cops_proxy::serve(addr, px));
    tokio::time::sleep(Duration::from_millis(150)).await;
    addr
}

async fn raw(addr: SocketAddr, req: &[u8]) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(6), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

fn post(path: &str, extra: &str, body: &str) -> Vec<u8> {
    format!(
        "POST {path} HTTP/1.1\r\nHost: x\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
    .into_bytes()
}

#[tokio::test]
async fn without_hook_or_unclaimed_path_goes_to_python() {
    let addr = start(None).await;
    let r = raw(addr, &post("/api/auth/login", "", "{}")).await;
    assert!(r.contains("UPSTREAM:POST /api/auth/login"), "{r}");
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(hook.clone())).await;
    let r = raw(addr, &post("/api/auth/pass", "", "{}")).await;
    assert!(r.contains("UPSTREAM:POST /api/auth/pass"), "{r}");
    let r = raw(addr, &post("/api/status", "", "")).await;
    assert!(r.contains("UPSTREAM:"), "{r}");
    assert!(hook.0.lock().unwrap().is_empty(), "kanca çağrılmadı");
}

#[tokio::test]
async fn claimed_path_is_answered_by_hook_with_body() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(hook.clone())).await;
    let r = raw(
        addr,
        &post(
            "/api/auth/login?x=1",
            "Content-Type: application/json\r\nCookie: cops_t=a\r\n",
            r#"{"u":1}"#,
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 201"), "{r}");
    assert!(!r.contains("UPSTREAM"), "{r}");
    assert!(r.contains(r#"{"ok": true}"#), "{r}");
    let lower = r.to_ascii_lowercase();
    assert!(
        lower.contains("set-cookie: a=1\r\n") && lower.contains("set-cookie: b=2\r\n"),
        "{r}"
    );
    let s = hook.0.lock().unwrap().last().cloned().unwrap();
    assert_eq!(s.view.method, "POST");
    assert_eq!(s.view.path, "/api/auth/login");
    assert_eq!(s.view.raw_query, "x=1");
    assert_eq!(s.view.header("cookie"), Some("cops_t=a"));
    assert_eq!(s.body, Ok(br#"{"u":1}"#.to_vec()));
    assert!(!s.https);
}

#[tokio::test]
async fn oversized_body_is_reported_not_read_whole() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(hook.clone())).await;
    let r = raw(addr, &post("/api/auth/login", "", &"x".repeat(17))).await;
    assert!(r.starts_with("HTTP/1.1 201"), "{r}");
    assert_eq!(
        hook.0.lock().unwrap().last().unwrap().body,
        Err(BodyError::TooLarge)
    );
    let r = raw(addr, &post("/api/auth/login", "", &"x".repeat(16))).await;
    assert!(r.starts_with("HTTP/1.1 201"), "{r}");
    assert_eq!(
        hook.0.lock().unwrap().last().unwrap().body,
        Ok(b"x".repeat(16))
    );
}

#[tokio::test]
async fn hook_panic_and_timeout_fail_closed() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(hook.clone())).await;
    let r = raw(addr, &post("/api/auth/login", "X-T: panic\r\n", "")).await;
    assert!(r.starts_with("HTTP/1.1 500"), "{r}");
    assert!(!r.contains("UPSTREAM"), "{r}");
    let t0 = std::time::Instant::now();
    let r = raw(addr, &post("/api/auth/login", "X-T: slow\r\n", "")).await;
    assert!(r.starts_with("HTTP/1.1 503"), "{r}");
    assert!(t0.elapsed() < Duration::from_secs(3));
    assert!(!r.contains("UPSTREAM"), "{r}");
}

#[tokio::test]
async fn https_only_from_loopback_forwarded_proto_and_internal_never_routed() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(hook.clone())).await;
    let _ = raw(
        addr,
        &post("/api/auth/me", "X-Forwarded-Proto: https\r\n", ""),
    )
    .await;
    assert!(hook.0.lock().unwrap().last().unwrap().https, "loopback eş");
    let n = hook.0.lock().unwrap().len();
    let r = raw(addr, &post("/api/_internal/authz", "", "")).await;
    assert!(r.starts_with("HTTP/1.1 404"), "{r}");
    assert_eq!(hook.0.lock().unwrap().len(), n);
}

/// Eksik kalan (yavaş) gövde: kanca çağrılmaz, süre dolunca 408.
#[tokio::test]
async fn slow_body_times_out_with_408() {
    let h = Arc::new(Hook(Mutex::new(Vec::new())));
    let addr = start(Some(h.clone())).await;
    let t = std::time::Instant::now();
    let r = raw(
        addr,
        b"POST /api/auth/login HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nabc",
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 408"), "{r}");
    assert!(r.to_ascii_lowercase().contains("connection: close"), "{r}");
    assert!(t.elapsed() < Duration::from_secs(4), "{:?}", t.elapsed());
    assert!(h.0.lock().unwrap().is_empty(), "kanca çağrılmamalı");
}
