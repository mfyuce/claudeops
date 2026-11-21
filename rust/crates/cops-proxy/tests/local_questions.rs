//! Yerel uç: GET /api/steward/questions Rust'ta cevaplanır (kimlikli), diğer her şey vekillenir.
use cops_proxy::{LocalCfg, Proxy};
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
                let mut buf = vec![0u8; 4096];
                let _ = c.read(&mut buf).await;
                let _ = c
                    .write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nPYTHON",
                    )
                    .await;
            });
        }
    });
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
async fn questions_endpoint_is_local_authenticated_and_everything_else_proxies() {
    let d = tempfile::tempdir().unwrap();
    let db = d.path().join("claudeops.db");
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute("CREATE TABLE docs (name TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL)", []).unwrap();
    c.execute(
        "INSERT INTO docs VALUES ('steward/questions', ?1, 1, 0)",
        [r#"[{"id":"q1","project":"p","text":"a?","status":"open","created_at":5.0}]"#],
    )
    .unwrap();
    drop(c);
    let up = fake_upstream().await;
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    drop(l);
    let px = Proxy::new(up).with_local(LocalCfg {
        token: cops_auth::Token::new("sekret"),
        db,
    });
    tokio::spawn(cops_proxy::serve(addr, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    let r = raw(
        addr,
        "GET /api/steward/questions HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    assert!(!r.contains("PYTHON"));
    let r = raw(
        addr,
        "GET /api/steward/questions?token=yanlis HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let r = raw(
        addr,
        "GET /api/steward/questions?token=sekret HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 200")
            && r.contains("\"id\":\"q1\"")
            && r.contains("\"sid\":\"default\""),
        "{r}"
    );
    let r = raw(addr, "GET /api/steward/questions?sid=BAD HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer sekret\r\nConnection: close\r\n\r\n").await;
    assert!(r.starts_with("HTTP/1.1 400"), "{r}");
    // yöntem/yol farkı Python'a gider (POST aynı yol, başka yol)
    let r = raw(addr, "POST /api/steward/questions HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;
    assert!(r.contains("PYTHON"), "{r}");
    let r = raw(
        addr,
        "GET /api/steward/answer HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(r.contains("PYTHON"), "{r}");
}
