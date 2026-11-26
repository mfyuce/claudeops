//! Vekillenen istek ön süzgeci (`gate::ForwardFilter` + `strip_credentials`): takılmamışsa aktarılan başlıklar aynı; karar
//! silinecek `Authorization`/çerez adlarıdır, silme atlatılamaz (birden çok satır, harf büyüklüğü, iki `cops_t`, Python boşluğu,
//! ASCII dışı bayt); panik ve süre aşımı `on_failure`; yerel uçlar süzgece gitmez.
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::gate::{CredStrip, ForwardFilter};
use cops_proxy::{strip_credentials, LocalCfg, Proxy};
use hyper::header::{HeaderValue, AUTHORIZATION, COOKIE};
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

fn cookies(h: &hyper::HeaderMap) -> Vec<Vec<u8>> {
    h.get_all(COOKIE)
        .iter()
        .map(|v| v.as_bytes().to_vec())
        .collect()
}

fn strip_t() -> CredStrip {
    CredStrip {
        authorization: false,
        cookies: vec!["cops_t".into()],
    }
}

#[test]
fn strip_removes_every_variant_across_all_lines() {
    let mut h = hyper::HeaderMap::new();
    h.append(
        COOKIE,
        HeaderValue::from_static("a=1; cops_t=x; b=2; cops_t=y"),
    );
    h.append(COOKIE, HeaderValue::from_static("COPS_T=z;c=3"));
    h.append(COOKIE, HeaderValue::from_static(" Cops_T =w"));
    h.append(
        COOKIE,
        HeaderValue::from_bytes(b"\xa0cops_t\t=v; d=\xe9").unwrap(),
    );
    h.append(
        COOKIE,
        HeaderValue::from_static("e=5; cops_tx=keep; xcops_t=keep"),
    );
    h.append(AUTHORIZATION, HeaderValue::from_static("Bearer cpu_a"));
    h.append(AUTHORIZATION, HeaderValue::from_static("bearer cpu_b"));
    strip_credentials(&mut h, &strip_t());
    assert_eq!(
        cookies(&h),
        vec![
            b"a=1; b=2".to_vec(),
            b"c=3".to_vec(),
            b"d=\xe9".to_vec(),
            b"e=5; cops_tx=keep; xcops_t=keep".to_vec(),
        ],
        "sıra korunur; boşalan satır kalkar; benzer adlar kalır"
    );
    assert_eq!(h.get_all(AUTHORIZATION).iter().count(), 2, "istenmedi");
    strip_credentials(
        &mut h,
        &CredStrip {
            authorization: true,
            cookies: vec![],
        },
    );
    assert!(!h.contains_key(AUTHORIZATION), "tüm satırlar");
}

#[test]
fn strip_noop_and_untouched_lines_are_byte_identical() {
    let mut h = hyper::HeaderMap::new();
    h.append(COOKIE, HeaderValue::from_static("a=1;b=2"));
    h.append(COOKIE, HeaderValue::from_static("  c=3 ;  cops_t=x"));
    h.append(AUTHORIZATION, HeaderValue::from_static("Bearer w"));
    let before = h.clone();
    strip_credentials(&mut h, &CredStrip::default());
    assert_eq!(h, before);
    strip_credentials(
        &mut h,
        &CredStrip {
            authorization: false,
            cookies: vec!["nope".into()],
        },
    );
    assert_eq!(h, before, "eşleşme yoksa dokunulmaz");
    strip_credentials(&mut h, &strip_t());
    assert_eq!(cookies(&h), vec![b"a=1;b=2".to_vec(), b"c=3".to_vec()]);
    let mut only = hyper::HeaderMap::new();
    only.append(COOKIE, HeaderValue::from_static("cops_t=a; ; cops_t"));
    strip_credentials(&mut only, &strip_t());
    assert!(
        !only.contains_key(COOKIE),
        "yalnız boş parça kalan satır kalkar"
    );
}

/// Aldığı istek başlığını gövde olarak geri döner.
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
                let head = buf;
                let mut out = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    head.len()
                )
                .into_bytes();
                out.extend_from_slice(&head);
                let _ = c.write_all(&out).await;
            });
        }
    });
    addr
}

async fn raw(addr: SocketAddr, req: &[u8]) -> Vec<u8> {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(std::time::Duration::from_secs(6), s.read_to_end(&mut out)).await;
    out
}

/// `X-T: strip|panic|slow` başlığına göre karar veren süzgeç; çağrıları sayar.
struct Filter(Mutex<Vec<RequestView>>);

impl ForwardFilter for Filter {
    fn check<'a>(&'a self, view: &'a RequestView) -> BoxFut<'a, CredStrip> {
        Box::pin(async move {
            self.0.lock().unwrap().push(view.clone());
            match view.header("x-t") {
                Some("panic") => panic!("süzgeç paniği"),
                Some("slow") => {
                    tokio::time::sleep(std::time::Duration::from_secs(10)).await;
                    CredStrip::default()
                }
                Some("strip") => CredStrip {
                    authorization: true,
                    cookies: vec!["cops_t".into()],
                },
                _ => CredStrip::default(),
            }
        })
    }

    fn on_failure(&self, _view: &RequestView) -> CredStrip {
        CredStrip {
            authorization: true,
            cookies: vec!["cops_t".into()],
        }
    }
}

async fn start(f: Option<Arc<Filter>>) -> (SocketAddr, tempfile::TempDir) {
    let d = tempfile::tempdir().unwrap();
    let db = d.path().join("claudeops.db");
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute("CREATE TABLE docs (name TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL)", []).unwrap();
    drop(c);
    let up = echo_upstream().await;
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    let px = Proxy::with_secret(up, "onkapi").with_local(LocalCfg {
        token: cops_auth::Token::new("sekret"),
        db,
    });
    let px = match f {
        Some(f) => px.with_forward_filter(f),
        None => px,
    };
    tokio::spawn(cops_proxy::serve_on(l, px));
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    (addr, d)
}

const CREDS: &[u8] = b"Cookie: a=1; cops_t=x\r\ncookie: COPS_T=y; b=2\r\nAuthorization: Bearer cpu_q\r\nAUTHORIZATION: Bearer w\r\nX-E: \xe9\r\n";

fn req(path: &str, xt: &str) -> Vec<u8> {
    let mut r = format!("GET {path} HTTP/1.1\r\nHost: x\r\nX-T: {xt}\r\n").into_bytes();
    r.extend_from_slice(CREDS);
    r.extend_from_slice(b"Connection: close\r\n\r\n");
    r
}

fn has(hay: &[u8], needle: &[u8]) -> bool {
    hay.windows(needle.len()).any(|w| w == needle)
}

fn lower(b: &[u8]) -> Vec<u8> {
    b.to_ascii_lowercase()
}

#[tokio::test]
async fn without_filter_forwarded_credentials_are_unchanged() {
    let (addr, _d) = start(None).await;
    let r = lower(&raw(addr, &req("/api/status", "strip")).await);
    for want in [
        &b"cookie: a=1; cops_t=x\r\ncookie: cops_t=y; b=2\r\n"[..],
        b"authorization: bearer cpu_q\r\nauthorization: bearer w\r\n",
        b"x-e: \xe9\r\n",
    ] {
        assert!(has(&r, want), "{}", String::from_utf8_lossy(&r));
    }
}

#[tokio::test]
async fn filter_verdicts_strip_and_failures_fall_back_to_on_failure() {
    let f = Arc::new(Filter(Mutex::new(Vec::new())));
    let (addr, _d) = start(Some(f.clone())).await;
    // karar yok: başlıklar aynı
    let r = lower(&raw(addr, &req("/api/status", "keep")).await);
    assert!(has(
        &r,
        b"cookie: a=1; cops_t=x\r\ncookie: cops_t=y; b=2\r\n"
    ));
    assert!(has(
        &r,
        b"authorization: bearer cpu_q\r\nauthorization: bearer w\r\n"
    ));
    {
        let seen = f.0.lock().unwrap();
        let v = seen.last().unwrap();
        assert_eq!(v.header("cookie"), Some("a=1; cops_t=x"), "ilk satır");
        assert_eq!(v.header("x-e"), Some("é"), "Latin-1");
    }
    // sil + panik + süre aşımı (2 sn): hepsinde iki satır da gider
    for xt in ["strip", "panic", "slow"] {
        let t0 = std::time::Instant::now();
        let r = lower(&raw(addr, &req("/api/status", xt)).await);
        assert!(r.starts_with(b"http/1.1 200"), "{xt}");
        assert!(t0.elapsed() < std::time::Duration::from_secs(4), "{xt}");
        assert!(!has(&r, b"authorization:"), "{xt}");
        assert!(!has(&r, b"cops_t"), "{xt}: {}", String::from_utf8_lossy(&r));
        assert!(has(&r, b"cookie: a=1\r\ncookie: b=2\r\n"), "{xt}");
    }
    // yerel uç süzgece gitmez (yanıt Rust'tan: yankı yok)
    let n = f.0.lock().unwrap().len();
    let r = raw(
        addr,
        &req("/api/steward/questions?all=1&token=sekret", "strip"),
    )
    .await;
    assert!(
        r.starts_with(b"HTTP/1.1 200"),
        "{}",
        String::from_utf8_lossy(&r)
    );
    assert!(!has(&r, b"X-T"), "{}", String::from_utf8_lossy(&r));
    assert_eq!(f.0.lock().unwrap().len(), n, "yerel uç süzgece sorulmaz");
}
