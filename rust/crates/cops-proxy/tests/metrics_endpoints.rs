//! Metrik uçları: POST points (web.token ya da loopback + X-Cops-Front), GET series/names (web.token); yetkisiz 401.
use cops_proxy::{MetricsCfg, Proxy};
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

async fn raw(addr: SocketAddr, req: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

fn post(extra: &str, body: &str) -> String {
    format!("POST /api/metrics/points HTTP/1.1\r\nHost: x\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len())
}

#[tokio::test]
async fn points_series_names_with_auth() {
    let d = tempfile::tempdir().unwrap();
    let store = Arc::new(cops_metrics::Store::open(&d.path().join("metrics.db")).unwrap());
    let up: SocketAddr = "127.0.0.1:9".parse().unwrap();
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    let px = Proxy::new(up).with_metrics(MetricsCfg {
        store,
        token: cops_auth::Token::new("tok"),
        front_secret: cops_auth::Token::new("fs"),
    });
    tokio::spawn(cops_proxy::serve_on(l, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;

    let body = r#"[{"name":"project.todo_open","key":"p1","ts":100,"value":4,"unit":"adet"},{"name":"project.todo_open","key":"p1","ts":200,"value":3}]"#;
    assert!(raw(addr, &post("", body)).await.starts_with("HTTP/1.1 401"));
    assert!(raw(addr, &post("X-Cops-Front: yanlis\r\n", body))
        .await
        .starts_with("HTTP/1.1 401"));
    let r = raw(addr, &post("X-Cops-Front: fs\r\n", body)).await;
    assert!(
        r.starts_with("HTTP/1.1 200") && r.contains("\"inserted\":2"),
        "{r}"
    );
    let r = raw(
        addr,
        &post("Authorization: Bearer tok\r\n", r#"{"name":"x","value":1}"#),
    )
    .await;
    assert!(r.contains("\"inserted\":1"), "{r}");
    let r = raw(
        addr,
        &post("Authorization: Bearer tok\r\n", r#"{"name":"","value":1}"#),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 400"), "{r}");
    // okuma yalnız web.token ile
    let r = raw(addr, "GET /api/metrics/series?name=project.todo_open&key=p1 HTTP/1.1\r\nHost: x\r\nX-Cops-Front: fs\r\nConnection: close\r\n\r\n").await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let r = raw(addr, "GET /api/metrics/series?name=project.todo_open&key=p1&token=tok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").await;
    assert!(
        r.starts_with("HTTP/1.1 200")
            && r.contains("\"value\":4.0")
            && r.contains("\"unit\":\"adet\""),
        "{r}"
    );
    let r = raw(
        addr,
        "GET /api/metrics/names?token=tok HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
    )
    .await;
    assert!(
        r.contains("project.todo_open") && r.contains("\"points\":2"),
        "{r}"
    );
}
