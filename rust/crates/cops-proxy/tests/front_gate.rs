//! rs/gate eşlik işleri (docs/rs-gate-eslik.md bölüm 5): gizli yaşam döngüsü, güvenlik başlıkları, iç uç engelinin derinliği,
//! başlık okuma süre sınırı, `Content-Length` doğrulama, erken ret sonrası aynı bağlantı, eksik gövde 408, `cops_ext` çerezinin
//! yerel API'yi açmaması, `force_proxy` boyut sınırları. Her şey geçici dizin ve boş portta.
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::force::ForceProxy;
use cops_proxy::front::FrontSecret;
use cops_proxy::gate::{RouteHook, RouteRequest, RouteResponse};
use cops_proxy::routes::RouteTable;
use cops_proxy::{LocalCfg, MetricsCfg, Proxy, StatsCfg};
use std::net::SocketAddr;
use std::os::unix::fs::PermissionsExt;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "panel-token-NOT-REAL";

/// İstek satırlarını ve başlıklarını kaydeden, her isteğe `UP` gövdeli 200 dönen (gövdeyi okuyan) üst sunucu.
async fn recording_upstream() -> (SocketAddr, Arc<Mutex<Vec<String>>>) {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let s2 = seen.clone();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            let seen = s2.clone();
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut tmp = [0u8; 8192];
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                    let n = c.read(&mut tmp).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    buf.extend_from_slice(&tmp[..n]);
                }
                let head = String::from_utf8_lossy(&buf).to_string();
                seen.lock().unwrap().push(head.clone());
                let body = format!("UP|{}", head.replace("\r\n", "|"));
                let r = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = c.write_all(r.as_bytes()).await;
            });
        }
    });
    (addr, seen)
}

async fn serve(px: Arc<Proxy>) -> SocketAddr {
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on(l, px));
    addr
}

/// Ham istek; yanıtın tamamı (bağlantı kapanana ya da 5 sn dolana dek).
async fn raw(addr: SocketAddr, req: &[u8]) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

fn header<'a>(r: &'a str, name: &str) -> Option<&'a str> {
    let head = r.split("\r\n\r\n").next()?;
    head.lines().skip(1).find_map(|l| {
        let (k, v) = l.split_once(':')?;
        k.trim().eq_ignore_ascii_case(name).then(|| v.trim())
    })
}

fn count_header(r: &str, name: &str) -> usize {
    let head = r.split("\r\n\r\n").next().unwrap_or("");
    head.lines()
        .skip(1)
        .filter(|l| {
            l.split_once(':')
                .is_some_and(|(k, _)| k.trim().eq_ignore_ascii_case(name))
        })
        .count()
}

/// Python `end_headers` kümesi tam ve tek mi.
fn assert_hardened(r: &str, what: &str) {
    assert_eq!(
        header(r, "x-content-type-options"),
        Some("nosniff"),
        "{what}: {r}"
    );
    assert_eq!(
        header(r, "referrer-policy"),
        Some("no-referrer"),
        "{what}: {r}"
    );
    assert_eq!(header(r, "x-frame-options"), Some("DENY"), "{what}: {r}");
    assert_eq!(
        header(r, "content-security-policy"),
        Some(cops_proxy::CSP),
        "{what}: {r}"
    );
    for h in [
        "x-content-type-options",
        "referrer-policy",
        "x-frame-options",
        "content-security-policy",
    ] {
        assert_eq!(count_header(r, h), 1, "{what}: {h} tek olmalı: {r}");
    }
}

fn get(path: &str, extra: &str) -> Vec<u8> {
    format!("GET {path} HTTP/1.1\r\nHost: x\r\n{extra}Connection: close\r\n\r\n").into_bytes()
}

/// GET `/api/own/*` (kendi kimliği) ve `/api/panel/*` (panel kimliği) kaydı; `/api/own/csp` kendi CSP'sini verir.
struct Named;

impl RouteHook for Named {
    fn route(&self, _view: &RequestView) -> Option<usize> {
        Some(1024)
    }
    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async move {
            let mut headers = vec![("Content-Type".into(), "application/json".into())];
            if req.view.path == "/api/own/csp" {
                headers.push((
                    "Content-Security-Policy".into(),
                    "default-src 'none'".into(),
                ));
            }
            RouteResponse {
                status: 200,
                headers,
                body: br#"{"ok": true}"#.to_vec(),
            }
        })
    }
}

/// `/api/hook/*` POST'u üstlenir (gövde sınırı 64), varsayılan süre.
struct PostHook;

impl RouteHook for PostHook {
    fn route(&self, view: &RequestView) -> Option<usize> {
        view.path.starts_with("/api/hook/").then_some(64)
    }
    fn handle(&self, req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async move {
            RouteResponse {
                status: 200,
                headers: vec![],
                body: format!("{:?}", req.body.map(|b| b.len())).into_bytes(),
            }
        })
    }
}

struct Fixture {
    _dir: tempfile::TempDir,
    db: std::path::PathBuf,
}

fn questions_db() -> Fixture {
    let d = tempfile::tempdir().unwrap();
    let db = d.path().join("claudeops.db");
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute("CREATE TABLE docs (name TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL)", []).unwrap();
    c.execute(
        "INSERT INTO docs VALUES ('steward/questions', '[]', 1, 0)",
        [],
    )
    .unwrap();
    Fixture { _dir: d, db }
}

fn full_proxy(up: SocketAddr, fx: &Fixture, store_dir: &std::path::Path) -> Arc<Proxy> {
    let mut t = RouteTable::new();
    t.get("/api/panel/*", Arc::new(Named));
    t.own_auth("GET", "/api/own/*", Arc::new(Named));
    let store = Arc::new(cops_metrics::Store::open(&store_dir.join("metrics.db")).unwrap());
    Proxy::with_secret(up, "onkapi")
        .with_local(LocalCfg {
            token: cops_auth::Token::new(TOKEN),
            db: fx.db.clone(),
        })
        .with_metrics(MetricsCfg {
            store,
            token: cops_auth::Token::new(TOKEN),
            front_secret: cops_auth::Token::new("onkapi"),
        })
        .with_route_table(t, cops_auth::Token::new(TOKEN))
        .with_routes(Arc::new(PostHook))
        .with_stats(StatsCfg {
            token: cops_auth::Token::new(TOKEN),
            front_secret: cops_auth::Token::new("onkapi"),
        })
        .with_version("test-sha")
}

/// İş 4: Rust'ın cevapladığı her yanıt türünde (200/401/404/408/413, stats, metrik, soru, tablo, kanca) ve Python yolunda copsd'nin
/// ürettiği 502'de Python `end_headers` kümesi; kendi CSP'sini veren kanca yanıtına ikinci CSP/XFO EKLENMEZ (`_ext_own_csp`);
/// Python'dan gelen yanıta dokunulmaz.
#[tokio::test]
async fn security_headers_match_python_end_headers() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    let auth = format!("Authorization: Bearer {TOKEN}\r\n");
    for (what, req) in [
        ("stats 200", get("/api/front/stats", &auth)),
        ("stats 401", get("/api/front/stats", "")),
        ("metrik 200", get("/api/metrics/names", &auth)),
        ("metrik 401", get("/api/metrics/names", "")),
        ("metrik 400", get("/api/metrics/series", &auth)),
        ("soru 200", get("/api/steward/questions?all=1", &auth)),
        ("soru 401", get("/api/steward/questions?all=1", "")),
        ("tablo 200", get("/api/panel/x", &auth)),
        ("tablo 401", get("/api/panel/x", "")),
        ("kendi kimlikli 200", get("/api/own/x", "")),
        ("iç uç 404", get("/api/_internal/authz", "")),
        (
            "kanca 408 (eksik gövde)",
            b"POST /api/hook/a HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nabc".to_vec(),
        ),
        (
            "metrik 413",
            format!(
                "POST /api/metrics/points HTTP/1.1\r\nHost: x\r\n{auth}Content-Length: {}\r\nConnection: close\r\n\r\n",
                2 << 20
            )
            .into_bytes(),
        ),
    ] {
        let r = if what.contains("408") {
            let mut s = TcpStream::connect(addr).await.unwrap();
            s.write_all(&req).await.unwrap();
            s.shutdown().await.unwrap();
            let mut out = Vec::new();
            let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
            String::from_utf8_lossy(&out).to_string()
        } else {
            raw(addr, &req).await
        };
        assert!(r.starts_with("HTTP/1.1 "), "{what}: {r}");
        assert_hardened(&r, what);
    }
    let r = raw(addr, &get("/api/own/csp", "")).await;
    assert_eq!(
        header(&r, "content-security-policy"),
        Some("default-src 'none'"),
        "{r}"
    );
    assert_eq!(count_header(&r, "content-security-policy"), 1, "{r}");
    assert_eq!(header(&r, "x-frame-options"), None, "{r}");
    assert_eq!(header(&r, "x-content-type-options"), Some("nosniff"), "{r}");
    // Python'dan gelen yanıt bayt bayt (copsd başlık eklemez: Python kendisi ekler).
    let r = raw(addr, &get("/api/status", "")).await;
    assert!(r.contains("UP|GET /api/status"), "{r}");
    assert_eq!(header(&r, "content-security-policy"), None, "{r}");
    // Python'a ulaşılamadı: copsd'nin 502'si sertleştirilir.
    let holder = tokio::net::TcpSocket::new_v4().unwrap();
    holder.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let addr = serve(Proxy::new(holder.local_addr().unwrap())).await;
    let r = raw(addr, &get("/api/status", "")).await;
    assert!(r.starts_with("HTTP/1.1 502"), "{r}");
    assert_hardened(&r, "502");
}

/// İş 5: dış istek hangi biçimde gelirse gelsin (yöntem, `//`, harf, mutlak biçim) Python'un iç uç sayacağı yola ULAŞMAZ;
/// yanıt Python'un dış istemciye verdiği `{"error": "not found"}`. Python'un iç uç saymadığı biçimler aktarılabilir.
#[tokio::test]
async fn internal_block_covers_every_form_python_would_route() {
    let (up, seen) = recording_upstream().await;
    let addr = serve(Proxy::with_secret(up, "onkapi")).await;
    let targets = [
        "/api/_internal/authz",
        "/api/_internal/ws-ticket/consume",
        "//api/_internal/authz",
        "///api/_internal/authz?x=1",
        "/API/_INTERNAL/authz",
        "/api/_internal",
        "/api/_internal/",
        "http://h/api/_internal/authz",
        "http://h//api/_internal/authz",
        "HTTP://h/api/_internal/authz?q=1",
        "/api/_internal/authz;p=1",
        // Python'un iç uç SAYMADIĞI biçimler (aktarılır; Python 404 ya da başka uca yönlendirir):
        "/x/api/_internal/authz",
        "//x/api/_internal/authz",
        "/api/%5Finternal/authz",
        "/./api/_internal/authz",
    ];
    for t in targets {
        for m in ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"] {
            let req = format!(
                "{m} {t} HTTP/1.1\r\nHost: h\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
            );
            let r = raw(addr, req.as_bytes()).await;
            assert!(r.starts_with("HTTP/1.1 "), "{m} {t}: {r}");
            let python = cops_proxy::python_path(t);
            if python.starts_with("/api/_internal")
                || python.to_ascii_lowercase().starts_with("/api/_internal")
            {
                assert!(r.starts_with("HTTP/1.1 404"), "{m} {t}: {r}");
                if m != "HEAD" {
                    assert!(r.ends_with(r#"{"error":"not found"}"#), "{m} {t}: {r}");
                }
            }
        }
    }
    for head in seen.lock().unwrap().iter() {
        let line = head.lines().next().unwrap_or("");
        let target = line.split(' ').nth(1).unwrap_or("");
        let p = cops_proxy::python_path(target);
        assert!(
            !p.to_ascii_lowercase().starts_with("/api/_internal"),
            "Python iç uca ulaştı: {line}"
        );
        assert!(
            !head.contains("_internal")
                || line.contains("/x/")
                || line.contains("%5F")
                || line.contains("/./"),
            "{line}"
        );
    }
    // Python'un yol indirgemesi (3.10 `parse_request` + `urlparse`).
    for (t, p) in [
        ("//api/_internal/x", "/api/_internal/x"),
        ("///a//b?c", "/a//b"),
        ("/a?b#c", "/a"),
        ("http://h/api/x?y", "/api/x"),
        ("http://h", ""),
        ("//x/api/_internal", "/x/api/_internal"),
        ("/a://b", "/a://b"),
        ("*", "*"),
    ] {
        assert_eq!(cops_proxy::python_path(t), p, "{t}");
    }
}

/// İş 2: gizli dosyası çalışırken değişir/silinir/gevşer: aktarılan isteğe o anki değer eklenir ya da hiç eklenmez,
/// `X-Cops-Front` denetimi (stats, metrik POST) aynı değeri kullanır; yokken istemci kopyası yine silinir.
#[tokio::test]
async fn front_secret_file_is_reread_and_fails_closed() {
    let d = tempfile::tempdir().unwrap();
    let f = d.path().join("front.secret");
    let put = |v: &str, mode: u32| {
        let _ = std::fs::remove_file(&f);
        std::fs::write(&f, v).unwrap();
        std::fs::set_permissions(&f, std::fs::Permissions::from_mode(mode)).unwrap();
    };
    put("bir\n", 0o600);
    let (up, _) = recording_upstream().await;
    let md = tempfile::tempdir().unwrap();
    let store = Arc::new(cops_metrics::Store::open(&md.path().join("m.db")).unwrap());
    let px = Proxy::new(up)
        .with_front_secret(Arc::new(FrontSecret::file(&f)))
        .with_metrics(MetricsCfg {
            store,
            token: cops_auth::Token::new(TOKEN),
            // takılı FrontSecret varken yok sayılır
            front_secret: cops_auth::Token::new("bir"),
        })
        .with_stats(StatsCfg {
            token: cops_auth::Token::new(TOKEN),
            front_secret: cops_auth::Token::new("bir"),
        });
    let addr = serve(px).await;
    let fwd = |extra: &'static str| async move { raw(addr, &get("/api/x", extra)).await };
    let stats = |v: &str| {
        let req = get("/api/front/stats", &format!("X-Cops-Front: {v}\r\n"));
        async move { raw(addr, &req).await }
    };
    let r = fwd("X-Cops-Front: sahte\r\n").await;
    assert!(
        r.contains("x-cops-front: bir|") && !r.contains("sahte"),
        "{r}"
    );
    assert!(stats("bir").await.starts_with("HTTP/1.1 200"));
    put("iki-uzun\n", 0o600);
    let r = fwd("").await;
    assert!(
        r.contains("x-cops-front: iki-uzun|"),
        "döndürülen gizli: {r}"
    );
    assert!(
        stats("bir").await.starts_with("HTTP/1.1 401"),
        "eski gizli geçersiz"
    );
    assert!(stats("iki-uzun").await.starts_with("HTTP/1.1 200"));
    put("iki-uzun\n", 0o640);
    let r = fwd("X-Cops-Front: iki-uzun\r\n").await;
    assert!(
        !r.to_ascii_lowercase().contains("x-cops-front"),
        "gevşek izin = gizli yok: {r}"
    );
    assert!(stats("iki-uzun").await.starts_with("HTTP/1.1 401"));
    put("\u{fffd}\n", 0o600);
    std::fs::write(&f, b"\xff\xfe").unwrap();
    assert!(
        !fwd("").await.to_ascii_lowercase().contains("x-cops-front"),
        "bozuk = gizli yok"
    );
    std::fs::remove_file(&f).unwrap();
    let r = fwd("X-Cops-Front: iki-uzun\r\n").await;
    assert!(
        !r.to_ascii_lowercase().contains("x-cops-front"),
        "silinen = gizli yok: {r}"
    );
    // Gizli yokken bile uzak eşin adresi Cf-Connecting-IP ile iletilir (birim testi: front::tests); loopback eşin tünel başlığı kalır.
    let r = fwd("Cf-Connecting-IP: 203.0.113.7\r\n").await;
    assert!(r.contains("cf-connecting-ip: 203.0.113.7|"), "{r}");
    put("uc\n", 0o600);
    assert!(
        fwd("").await.contains("x-cops-front: uc|"),
        "geri gelen gizli"
    );
}

/// İş 3: başlık okuma süre sınırı (Python `HEADER_READ_TIMEOUT`): yarım başlıkla bekleyen bağlantı kapanır; zamanında gelen
/// istek etkilenmez.
#[tokio::test]
async fn slow_headers_are_cut_off() {
    let (up, _) = recording_upstream().await;
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on_with(
        l,
        Proxy::new(up),
        Duration::from_millis(300),
    ));
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(b"GET /api/x HTTP/1.1\r\nHost: x\r\n")
        .await
        .unwrap();
    let t = std::time::Instant::now();
    let mut out = Vec::new();
    let r = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
    assert!(r.is_ok(), "bağlantı kapanmadı");
    assert!(t.elapsed() < Duration::from_secs(3), "{:?}", t.elapsed());
    assert!(
        !String::from_utf8_lossy(&out).contains("UP|"),
        "yarım istek aktarılmamalı"
    );
    let r = raw(addr, &get("/api/x", "")).await;
    assert!(r.contains("UP|GET /api/x"), "{r}");
    assert_eq!(cops_proxy::HEADER_READ_TIMEOUT, Duration::from_secs(15));
}

/// Ders 2.3 (`f99d422`): negatif, sayı olmayan, dev ve çelişkili `Content-Length`, `Transfer-Encoding` + `Content-Length` 400
/// alır ve Python'a HİÇ gitmez.
#[tokio::test]
async fn bad_content_length_is_rejected_before_python() {
    let (up, seen) = recording_upstream().await;
    let addr = serve(Proxy::with_secret(up, "onkapi")).await;
    for cl in [
        "Content-Length: -1\r\n",
        "Content-Length: abc\r\n",
        "Content-Length: 99999999999999999999999\r\n",
        "Content-Length: 2\r\nContent-Length: 3\r\n",
        "Content-Length: 2, 3\r\n",
        "Content-Length: +2\r\n",
    ] {
        let req = format!("POST /api/x HTTP/1.1\r\nHost: x\r\n{cl}Connection: close\r\n\r\n{{}}");
        let r = raw(addr, req.as_bytes()).await;
        assert!(r.starts_with("HTTP/1.1 400"), "{cl:?}: {r}");
    }
    assert!(
        seen.lock().unwrap().is_empty(),
        "{:?}",
        seen.lock().unwrap()
    );
    // `Transfer-Encoding` + `Content-Length`: hyper RFC 9112 6.1 gereği yalnız `Transfer-Encoding`e göre okur ve
    // `Content-Length`i SİLER (istek kaçakçılığı yok): Python'a giden istekte uzunluk başlığı çelişmez.
    for order in [
        "Transfer-Encoding: chunked\r\nContent-Length: 99\r\n",
        "Content-Length: 99\r\nTransfer-Encoding: chunked\r\n",
    ] {
        seen.lock().unwrap().clear();
        let req = format!(
            "POST /api/x HTTP/1.1\r\nHost: x\r\n{order}Connection: close\r\n\r\n2\r\n{{}}\r\n0\r\n\r\n"
        );
        let r = raw(addr, req.as_bytes()).await;
        assert!(r.starts_with("HTTP/1.1 200"), "{order:?}: {r}");
        let heads = seen.lock().unwrap().clone();
        assert_eq!(heads.len(), 1, "{heads:?}");
        let h = heads[0].to_ascii_lowercase();
        assert!(!h.contains("content-length"), "{order:?}: {h}");
        assert!(h.contains("transfer-encoding: chunked"), "{order:?}: {h}");
    }
}

/// Ders 2.3 (`5b9f910`) ve Python `UnreadBodyTests.test_401_then_valid_request_on_same_socket`: yerel uç gövdeyi okumadan
/// (401, 413) yanıtlarsa aynı bağlantıdaki sonraki istek bozulmaz: ya doğru yanıtlanır ya bağlantı kapanır (kalan bayt yeni
/// isteğin başı SAYILMAZ). Gövdeli, chunked ve büyük gövde.
#[tokio::test]
async fn early_reject_then_second_request_on_same_connection() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    let big = "x".repeat(200 * 1024);
    let auth = format!("Authorization: Bearer {TOKEN}\r\n");
    let firsts: Vec<(String, Vec<u8>)> = vec![
        (
            "401 gövdeli".into(),
            b"POST /api/metrics/points HTTP/1.1\r\nHost: x\r\nContent-Length: 12\r\n\r\nGET /evil x\n".to_vec(),
        ),
        (
            "401 chunked".into(),
            b"POST /api/metrics/points HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\nc\r\nGET /evil x\n\r\n0\r\n\r\n"
                .to_vec(),
        ),
        (
            "401 büyük".into(),
            format!(
                "POST /api/metrics/points HTTP/1.1\r\nHost: x\r\nContent-Length: {}\r\n\r\n{big}",
                big.len()
            )
            .into_bytes(),
        ),
        (
            "413 büyük".into(),
            format!(
                "POST /api/metrics/points HTTP/1.1\r\nHost: x\r\n{auth}Content-Length: {}\r\n\r\n{}",
                (1 << 20) + 10,
                "y".repeat((1 << 20) + 10)
            )
            .into_bytes(),
        ),
        (
            "401 tablo GET gövdeli".into(),
            b"GET /api/panel/x HTTP/1.1\r\nHost: x\r\nContent-Length: 12\r\n\r\nGET /evil x\n".to_vec(),
        ),
    ];
    for (what, first) in firsts {
        let mut s = TcpStream::connect(addr).await.unwrap();
        let mut both = first.clone();
        both.extend_from_slice(b"GET /api/second HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n");
        // Sunucu erken yanıtlayıp kapatırsa yazım EPIPE alabilir: kabul.
        let _ = s.write_all(&both).await;
        let mut out = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
        let r = String::from_utf8_lossy(&out).to_string();
        assert!(
            r.starts_with("HTTP/1.1 401") || r.starts_with("HTTP/1.1 413"),
            "{what}: {r}"
        );
        assert!(!r.contains("/evil"), "{what}: gövde istek sayıldı: {r}");
        let responses = r.matches("HTTP/1.1 ").count();
        if responses > 1 {
            assert!(
                r.contains("UP|GET /api/second"),
                "{what}: ikinci yanıt bozuk: {r}"
            );
        }
        assert!(!r.contains("HTTP/1.1 400"), "{what}: {r}");
    }
}

/// İş 7 + Python `_read_body_raw` "short body": gövde bildirilenden kısa kalıp bağlantı yarı kapanırsa kanca da metrik ucu da
/// 408 `{"ok": false, "error": "request body timeout"}` + `Connection: close` verir (kanca çağrılmaz).
#[tokio::test]
async fn short_body_is_408_and_closes() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    for req in [
        "POST /api/hook/a HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nabc".to_string(),
        format!("POST /api/metrics/points HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nContent-Length: 10\r\n\r\nabc"),
    ] {
        let mut s = TcpStream::connect(addr).await.unwrap();
        s.write_all(req.as_bytes()).await.unwrap();
        s.shutdown().await.unwrap();
        let mut out = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
        let r = String::from_utf8_lossy(&out).to_string();
        assert!(r.starts_with("HTTP/1.1 408"), "{req}: {r}");
        assert_eq!(header(&r, "connection"), Some("close"), "{r}");
        let body: serde_json::Value = serde_json::from_str(r.split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(body, serde_json::json!({"ok": false, "error": "request body timeout"}));
    }
    // Zamanında gelen gövde kancaya ulaşır.
    let r = raw(
        addr,
        b"POST /api/hook/a HTTP/1.1\r\nHost: x\r\nContent-Length: 3\r\nConnection: close\r\n\r\nabc",
    )
    .await;
    assert!(r.ends_with("Ok(3)"), "{r}");
}

/// İş 7 (Python `Routes.test_cookie_does_not_open_core_api`): geçerli `cops_ext` çerezi çekirdek yerel API'yi AÇMAZ (soru, metrik,
/// tablo, stats); yalnız mount'larda kimliktir.
#[tokio::test]
async fn cops_ext_cookie_does_not_open_local_api() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    let cookie = format!(
        "Cookie: {}={}\r\n",
        cops_auth::COOKIE_NAME,
        cops_auth::Token::new(TOKEN).cookie_value().unwrap()
    );
    for p in [
        "/api/steward/questions?all=1",
        "/api/metrics/names",
        "/api/panel/x",
        "/api/front/stats",
    ] {
        let r = raw(addr, &get(p, &cookie)).await;
        assert!(r.starts_with("HTTP/1.1 401"), "{p}: {r}");
        let r = raw(addr, &get(p, &format!("Authorization: Bearer {TOKEN}\r\n"))).await;
        assert!(r.starts_with("HTTP/1.1 200"), "{p}: {r}");
    }
}

/// `GET /api/front/stats` ikili sürümünü (`GIT_SHA`) taşır (ders 2.3, `812942e`).
#[tokio::test]
async fn stats_carry_binary_version() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    let r = raw(
        addr,
        &get(
            "/api/front/stats",
            &format!("Authorization: Bearer {TOKEN}\r\n"),
        ),
    )
    .await;
    let v: serde_json::Value = serde_json::from_str(r.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(v["version"], "test-sha");
    let addr = serve(Proxy::new(up).with_stats(StatsCfg {
        token: cops_auth::Token::new(TOKEN),
        front_secret: cops_auth::Token::new(""),
    }))
    .await;
    let r = raw(
        addr,
        &get(
            "/api/front/stats",
            &format!("Authorization: Bearer {TOKEN}\r\n"),
        ),
    )
    .await;
    let v: serde_json::Value = serde_json::from_str(r.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(v["version"], "unknown");
}

/// İş 7: `force_proxy` boyut sınırları. 512 satır geçerli, 513 = `*`; 64 KiB üstü dosya ilk ve yeniden okumada `*`; düzenli
/// dosya olmayan yol okuma hatası.
#[test]
fn force_proxy_size_limits() {
    let d = tempfile::tempdir().unwrap();
    let f = d.path().join("front_force_proxy");
    let lines = |n: usize| (0..n).map(|i| format!("/api/p{i}\n")).collect::<String>();
    std::fs::write(&f, lines(512)).unwrap();
    let fp = ForceProxy::load(&f);
    assert_eq!(fp.list().len(), 512);
    assert!(!fp.matches("/api/other"));
    std::fs::write(&f, lines(513)).unwrap();
    assert_eq!(fp.reload().unwrap(), 1);
    assert_eq!(fp.list(), vec!["*"]);
    std::fs::write(&f, "/api/a\n").unwrap();
    fp.reload().unwrap();
    assert_eq!(fp.list(), vec!["/api/a"]);
    std::fs::write(&f, format!("/api/b\n{}", "#".repeat(64 * 1024))).unwrap();
    assert!(fp.reload().is_err(), "64 KiB üstü okuma hatası");
    assert_eq!(fp.list(), vec!["*"], "yeniden okumada da `*`");
    let fresh = ForceProxy::load(&f);
    assert_eq!(fresh.list(), vec!["*"], "ilk okumada `*`");
    let dir_as_file = ForceProxy::load(d.path());
    assert_eq!(dir_as_file.list(), vec!["*"], "dizin: okuma hatası = `*`");
    std::fs::write(&f, format!("/api/c\n{}", "#".repeat(64 * 1024 - 8))).unwrap();
    assert!(std::fs::metadata(&f).unwrap().len() <= 64 * 1024);
    assert_eq!(
        ForceProxy::load(&f).list(),
        vec!["/api/c"],
        "sınırdaki dosya okunur"
    );
}

/// Mount upstream adres tablosu (ders 2.3 `030b4ab`, H17): yalnız loopback ve port != 0; IPv4 eşlemeli loopback, belirsiz, özel ve
/// bağlantı-yerel adresler REDDEDİLİR (Python mount sunmaz; Rust kuralı daha sıkı yönde).
#[test]
fn mount_upstream_address_table() {
    for (up, ok) in [
        ("127.0.0.1:80", true),
        ("[::1]:80", true),
        ("127.0.0.2:80", true),
        ("[::ffff:127.0.0.1]:80", false),
        ("0.0.0.0:80", false),
        ("[::]:80", false),
        ("10.0.0.1:80", false),
        ("192.168.1.1:80", false),
        ("169.254.1.1:80", false),
        ("[fe80::1]:80", false),
        ("127.0.0.1:0", false),
    ] {
        let doc = format!(r#"[{{"path":"/g/","upstream":"{up}"}}]"#);
        assert_eq!(cops_proxy::mount::parse(doc.as_bytes()).is_ok(), ok, "{up}");
    }
}

/// Ders 2.3 (`5b11899`, H15): Python'a aktarılan istekte başlık tablosu. Hop-by-hop başlıklar düşer, `X-Cops-Front` istemci
/// kopyası yerine copsd'nin gizlisi, `X-Forwarded-For` eşin adresi, `X-Cops-Parity` aktarılmaz, loopback eşin
/// `Cf-Connecting-IP`si (tünel) kalır; kimlik bilgisi ve diğer başlıklar AYNEN gider (karar Python'da).
#[tokio::test]
async fn forward_header_table() {
    let (up, seen) = recording_upstream().await;
    let addr = serve(Proxy::with_secret(up, "onkapi")).await;
    let req = "GET /api/x?token=t HTTP/1.1\r\nHost: panel.example\r\nKeep-Alive: timeout=5\r\nProxy-Authorization: Basic eA==\r\n\
TE: trailers\r\nTrailer: X-T\r\nProxy-Connection: keep-alive\r\nUpgrade: h2c\r\nX-Cops-Front: sahte\r\n\
X-Forwarded-For: 6.6.6.6\r\nCf-Connecting-IP: 203.0.113.7\r\nX-Cops-Parity: 1\r\nAuthorization: Bearer abc\r\n\
Cookie: cops_ext=c; a=b\r\nX-Custom: kalir\r\nX-Forwarded-Proto: https\r\nConnection: close\r\n\r\n";
    let r = raw(addr, req.as_bytes()).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert_eq!(header(&r, "x-cops-served"), Some("python"));
    let head = seen.lock().unwrap()[0].to_ascii_lowercase();
    let has = |line: &str| head.lines().any(|l| l == line);
    let absent = |name: &str| !head.lines().any(|l| l.starts_with(&format!("{name}:")));
    for h in [
        "keep-alive",
        "proxy-authorization",
        "te",
        "trailer",
        "proxy-connection",
        "upgrade",
        "x-cops-parity",
    ] {
        assert!(absent(h), "{h} düşmeliydi: {head}");
    }
    for l in [
        "get /api/x?token=t http/1.1",
        "x-cops-front: onkapi",
        "x-forwarded-for: 127.0.0.1",
        "cf-connecting-ip: 203.0.113.7",
        "authorization: bearer abc",
        "cookie: cops_ext=c; a=b",
        "x-custom: kalir",
        "x-forwarded-proto: https",
        "host: panel.example",
    ] {
        assert!(has(l), "{l} yok: {head}");
    }
    assert_eq!(head.matches("x-cops-front:").count(), 1, "{head}");
    assert_eq!(head.matches("x-forwarded-for:").count(), 1, "{head}");
}

/// Eşlik bölüm 3 (Rust daha sıkı): `Bearer <token>` sonunda Latin-1 `0x85`/`0xA0` baytı Python'da `str.strip()` ile kırpılıp
/// geçer; Rust ASCII dışı baytlı `Authorization`ı yok sayar (401). Düz token geçer.
#[tokio::test]
async fn bearer_with_trailing_latin1_space_is_rejected() {
    let (up, _) = recording_upstream().await;
    let fx = questions_db();
    let md = tempfile::tempdir().unwrap();
    let addr = serve(full_proxy(up, &fx, md.path())).await;
    for tail in [&b"\xa0"[..], &b"\x85"[..]] {
        let mut req =
            format!("GET /api/metrics/names HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}")
                .into_bytes();
        req.extend_from_slice(tail);
        req.extend_from_slice(b"\r\nConnection: close\r\n\r\n");
        let r = raw(addr, &req).await;
        assert!(r.starts_with("HTTP/1.1 401"), "{tail:?}: {r}");
    }
    let r = raw(
        addr,
        &get(
            "/api/metrics/names",
            &format!("Authorization: Bearer {TOKEN} \r\n"),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
}
