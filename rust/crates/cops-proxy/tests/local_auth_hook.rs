//! Yerel uç kancası (`gate::LocalAuth`): takılmamışsa ya da `Default` dönerse bugünkü `web.token` yolu; `Allow`/401/403 kancanın
//! kararı; panik = 401; kanca yalnız GET yerel uçlarında sorulur (POST metrics ve vekillenen istekler kancaya hiç gitmez);
//! Python `urlparse`'ın başka yol göreceği hedefler (`//x/...`, `;params`) yerel uca eşleşmez, Python'a gider.
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::gate::{LocalAuth, LocalVerdict};
use cops_proxy::{LocalCfg, MetricsCfg, Proxy};
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
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
    let _ = tokio::time::timeout(std::time::Duration::from_secs(5), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

/// Sorgudaki `v=` değerine göre karar veren kanca; gördüğü görünümleri kaydeder.
struct Hook(Mutex<Vec<RequestView>>);

impl LocalAuth for Hook {
    fn decide<'a>(&'a self, view: &'a RequestView) -> BoxFut<'a, LocalVerdict> {
        Box::pin(async move {
            self.0.lock().unwrap().push(view.clone());
            let q = view.raw_query.as_str();
            if q.contains("v=panic") {
                panic!("kanca paniği");
            }
            if q.contains("v=slow") {
                tokio::time::sleep(std::time::Duration::from_secs(10)).await;
            }
            if q.contains("v=allow") {
                LocalVerdict::Allow
            } else if q.contains("v=401") {
                LocalVerdict::Unauthorized
            } else if q.contains("v=403") {
                LocalVerdict::Forbidden
            } else {
                LocalVerdict::Default
            }
        })
    }
}

async fn start(hook: Option<Arc<Hook>>) -> (SocketAddr, tempfile::TempDir) {
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
    let store = Arc::new(cops_metrics::Store::open(&d.path().join("metrics.db")).unwrap());
    let up = fake_upstream().await;
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    drop(l);
    let px = Proxy::with_secret(up, "onkapi")
        .with_local(LocalCfg {
            token: cops_auth::Token::new("sekret"),
            db,
        })
        .with_metrics(MetricsCfg {
            store,
            token: cops_auth::Token::new("sekret"),
            front_secret: cops_auth::Token::new("onkapi"),
        });
    let px = match hook {
        Some(h) => px.with_local_auth(h),
        None => px,
    };
    tokio::spawn(cops_proxy::serve(addr, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    (addr, d)
}

fn get(path: &str, extra: &str) -> String {
    format!("GET {path} HTTP/1.1\r\nHost: x\r\n{extra}Connection: close\r\n\r\n")
}

#[tokio::test]
async fn hook_verdicts_apply_and_default_keeps_the_token_path() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let (addr, _d) = start(Some(hook.clone())).await;
    for base in [
        "/api/steward/questions?all=1",
        "/api/metrics/names?x=1",
        "/api/metrics/series?name=m",
    ] {
        let r = raw(addr, &get(&format!("{base}&v=allow"), "")).await;
        assert!(r.starts_with("HTTP/1.1 200"), "{base}: {r}");
        let r = raw(addr, &get(&format!("{base}&v=401&token=sekret"), "")).await;
        assert!(
            r.starts_with("HTTP/1.1 401") && r.contains("unauthorized"),
            "kanca token'ı ezer: {base}: {r}"
        );
        let r = raw(addr, &get(&format!("{base}&v=403"), "")).await;
        assert!(
            r.starts_with("HTTP/1.1 403") && r.contains("\"error\":\"forbidden\""),
            "{base}: {r}"
        );
        // Default: bugünkü yol (token yoksa 401, varsa 200)
        let r = raw(addr, &get(&format!("{base}&v=def"), "")).await;
        assert!(r.starts_with("HTTP/1.1 401"), "{base}: {r}");
        let r = raw(
            addr,
            &get(&format!("{base}&v=def"), "Authorization: Bearer sekret\r\n"),
        )
        .await;
        assert!(r.starts_with("HTTP/1.1 200"), "{base}: {r}");
        assert!(!r.contains("PYTHON"));
    }
    // panik ve süre aşımı = 401 (token geçerli olsa da)
    let r = raw(
        addr,
        &get("/api/steward/questions?all=1&v=panic&token=sekret", ""),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let t0 = std::time::Instant::now();
    let r = raw(
        addr,
        &get("/api/steward/questions?all=1&v=slow&token=sekret", ""),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    assert!(
        t0.elapsed() < std::time::Duration::from_secs(4),
        "2 sn sınırı"
    );
}

#[tokio::test]
async fn hook_sees_lowercase_headers_and_is_not_asked_for_post_or_proxied_requests() {
    let hook = Arc::new(Hook(Mutex::new(Vec::new())));
    let (addr, _d) = start(Some(hook.clone())).await;
    let r = raw(
        addr,
        &get(
            "/api/steward/questions?all=1&v=allow",
            "Cookie: a=1; cops_t=x\r\nX-Test: é\r\n",
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    {
        let seen = hook.0.lock().unwrap();
        let v = seen.last().unwrap();
        assert_eq!(v.method, "GET");
        assert_eq!(v.path, "/api/steward/questions");
        assert_eq!(v.raw_query, "all=1&v=allow");
        assert_eq!(v.header("cookie"), Some("a=1; cops_t=x"));
        assert_eq!(v.cookie("cops_t"), Some("x"));
        assert!(v.peer_loopback);
    }
    let n = hook.0.lock().unwrap().len();
    // POST metrics: kancaya gitmez (makine kimliği), ön kapı gizlisiyle 200
    let body = r#"{"name":"m","value":1}"#;
    let r = raw(addr, &format!("POST /api/metrics/points?v=403 HTTP/1.1\r\nHost: x\r\nX-Cops-Front: onkapi\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len())).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    // vekillenen istekler ve Python'un başka yol gördüğü hedefler: kancaya gitmez, Python'a aktarılır
    for p in [
        "/api/status?v=403",
        "//x/api/steward/questions?all=1&v=403",
        "/api/steward/questions;p?all=1&v=403",
        "/api/metrics/names;p?v=403",
        "//api/metrics/names?v=403",
    ] {
        let r = raw(addr, &get(p, "")).await;
        assert!(r.contains("PYTHON"), "{p}: {r}");
    }
    assert_eq!(hook.0.lock().unwrap().len(), n, "kanca sorulmadı");
}

#[tokio::test]
async fn without_hook_behaviour_is_unchanged() {
    let (addr, _d) = start(None).await;
    let r = raw(addr, &get("/api/steward/questions?all=1&v=allow", "")).await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let r = raw(
        addr,
        &get("/api/steward/questions?all=1&v=403&token=sekret", ""),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let r = raw(addr, &get("/api/metrics/names?v=403&token=sekret", "")).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
}
