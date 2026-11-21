//! Vekil davranışı: istek aktarımı, X-Forwarded-For ezme, WS yükseltme tüneli, upstream yokken 502.
use std::net::SocketAddr;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

async fn fake_upstream() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let mut buf = vec![0u8; 8192];
                let n = c.read(&mut buf).await.unwrap();
                let d = String::from_utf8_lossy(&buf[..n]).to_string();
                if d.to_ascii_lowercase().contains("upgrade: websocket") {
                    c.write_all(b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n").await.unwrap();
                    loop {
                        let n = c.read(&mut buf).await.unwrap_or(0);
                        if n == 0 {
                            break;
                        }
                        let mut o = b"echo:".to_vec();
                        o.extend_from_slice(&buf[..n]);
                        c.write_all(&o).await.unwrap();
                    }
                } else {
                    let xf: Vec<&str> = d
                        .split("\r\n")
                        .filter(|l| {
                            l.to_ascii_lowercase().starts_with("x-forwarded-for")
                                || l.to_ascii_lowercase().starts_with("x-cops-front")
                        })
                        .collect();
                    let body = xf.join("|");
                    let r = format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                        body.len(),
                        body
                    );
                    c.write_all(r.as_bytes()).await.unwrap();
                }
            });
        }
    });
    addr
}

async fn start_proxy(up: SocketAddr) -> SocketAddr {
    start_proxy_with(up, None).await
}

async fn start_proxy_with(up: SocketAddr, secret: Option<&str>) -> SocketAddr {
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    drop(l);
    let px = match secret {
        Some(x) => cops_proxy::Proxy::with_secret(up, x),
        None => cops_proxy::Proxy::new(up),
    };
    tokio::spawn(cops_proxy::serve(addr, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    addr
}

async fn raw(addr: SocketAddr, req: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

#[tokio::test]
async fn forwards_and_overwrites_x_forwarded_for() {
    let p = start_proxy(fake_upstream().await).await;
    let r = raw(
        p,
        "GET /api/x HTTP/1.1\r\nHost: a\r\nX-Forwarded-For: 6.6.6.6\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert!(r.contains("127.0.0.1") && !r.contains("6.6.6.6"), "{r}");
}

#[tokio::test]
async fn websocket_upgrade_is_tunnelled() {
    let p = start_proxy(fake_upstream().await).await;
    let mut s = TcpStream::connect(p).await.unwrap();
    s.write_all(b"GET /ws HTTP/1.1\r\nHost: a\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Key: abc\r\nSec-WebSocket-Version: 13\r\n\r\n").await.unwrap();
    let mut buf = vec![0u8; 1024];
    let n = tokio::time::timeout(std::time::Duration::from_secs(3), s.read(&mut buf))
        .await
        .unwrap()
        .unwrap();
    assert!(String::from_utf8_lossy(&buf[..n]).starts_with("HTTP/1.1 101"));
    s.write_all(b"hi").await.unwrap();
    let n = tokio::time::timeout(std::time::Duration::from_secs(3), s.read(&mut buf))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(&buf[..n], b"echo:hi");
}

#[tokio::test]
async fn upstream_down_gives_502() {
    let dead = {
        let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
        l.local_addr().unwrap()
    };
    let p = start_proxy(dead).await;
    let r = raw(p, "GET / HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n").await;
    assert!(r.starts_with("HTTP/1.1 502"), "{r}");
}

#[tokio::test]
async fn front_secret_is_injected_and_client_copy_dropped() {
    let p = start_proxy_with(fake_upstream().await, Some("gizli")).await;
    let r = raw(
        p,
        "GET / HTTP/1.1\r\nHost: a\r\nX-Cops-Front: sahte\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(r.contains("gizli") && !r.contains("sahte"), "{r}");
    let r = raw(
        start_proxy(fake_upstream().await).await,
        "GET / HTTP/1.1\r\nHost: a\r\nX-Cops-Front: sahte\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(
        !r.contains("sahte"),
        "gizli yokken de istemci kopyası düşer: {r}"
    );
}

#[tokio::test]
async fn internal_paths_are_never_forwarded() {
    let p = start_proxy_with(fake_upstream().await, Some("gizli")).await;
    for path in [
        "/api/_internal/authz",
        "//api/_internal/ws-ticket/consume",
        "/API/_internal/authz",
    ] {
        let r = raw(p, &format!("POST {path} HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}")).await;
        assert!(r.starts_with("HTTP/1.1 404"), "{path}: {r}");
    }
}

#[tokio::test]
async fn unread_post_body_does_not_poison_next_request() {
    // Upstream gövdeyi OKUMADAN yanıtlayıp bağlantıyı açık tutan bir sunucu gibi davranır: her bağlantıda ilk istek satırından sonrasını yok sayar.
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let up = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let mut acc = Vec::new();
                let mut buf = vec![0u8; 4096];
                loop {
                    let n = c.read(&mut buf).await.unwrap_or(0);
                    if n == 0 {
                        break;
                    }
                    acc.extend_from_slice(&buf[..n]);
                    let t = String::from_utf8_lossy(&acc).to_string();
                    // başlık bitince gövdeyi sayma: hemen yanıtla
                    if let Some(i) = t.find("\r\n\r\n") {
                        let first = t.lines().next().unwrap_or("").to_string();
                        let poisoned = !t.starts_with("GET") && !t.starts_with("POST");
                        let body = if poisoned {
                            "POISONED".to_string()
                        } else {
                            first
                        };
                        let r = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
                            body.len(),
                            body
                        );
                        c.write_all(r.as_bytes()).await.unwrap();
                        acc = acc.split_off((i + 4).min(acc.len())); // gövde baytları bağlantıda kalır (artık)
                    }
                }
            });
        }
    });
    let p = start_proxy(up).await;
    let _ = raw(p, "POST /api/ws-ticket HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}").await;
    let r = raw(p, "GET /x HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n").await;
    assert!(r.contains("GET /x") && !r.contains("POISONED"), "{r}");
}

#[tokio::test]
async fn static_assets_served_from_dist_with_headers_and_no_escape() {
    let d = std::env::temp_dir().join(format!("copsd_dist_{}", std::process::id()));
    std::fs::create_dir_all(d.join("assets")).unwrap();
    std::fs::write(d.join("assets/app-1.js"), "console.log(1)").unwrap();
    std::fs::write(d.join("favicon.svg"), "<svg/>").unwrap();
    std::fs::write(
        d.parent().unwrap().join("copsd_secret_outside.txt"),
        "SECRETFILE",
    )
    .unwrap();
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    drop(l);
    let px = cops_proxy::Proxy::new(fake_upstream().await).with_dist(d.clone());
    tokio::spawn(cops_proxy::serve(addr, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    let r = raw(
        addr,
        "GET /assets/app-1.js HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 200") && r.contains("console.log(1)"),
        "{r}"
    );
    let lr = r.to_ascii_lowercase();
    assert!(
        lr.contains("immutable")
            && lr.contains("application/javascript")
            && lr.contains("nosniff")
            && lr.contains("frame-ancestors"),
        "{r}"
    );
    let r = raw(
        addr,
        "GET /favicon.svg HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(
        r.to_ascii_lowercase().contains("no-cache") && r.contains("<svg/>"),
        "{r}"
    );
    // dist dışına kaçış: Python'a (sahte upstream) düşer, dosya içeriği ASLA dönmez
    let r = raw(addr, "GET /assets/../../copsd_secret_outside.txt HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n").await;
    assert!(!r.contains("SECRETFILE"), "{r}");
    assert!(cops_proxy::resolve_static(&d, "/assets/../../copsd_secret_outside.txt").is_none());
}
