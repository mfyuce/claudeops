//! Çoklu rota tablosu, `force_proxy`, `/api/front/stats` ve parite başlığı (vekil düzeyinde, sahte Python ile).
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::force::ForceProxy;
use cops_proxy::gate::{LocalAuth, LocalVerdict, RouteHook, RouteRequest, RouteResponse};
use cops_proxy::routes::RouteTable;
use cops_proxy::{Proxy, StatsCfg};
use serde_json::Value;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "tok-NOT-REAL";

/// Aldığı istek başını `UPSTREAM:` önekiyle döner; sahte `x-cops-served` başlığı da yollar.
async fn upstream() -> SocketAddr {
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
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nX-Cops-Served: local\r\nConnection: close\r\n\r\nUPSTREAM:",
                    buf.len() + 9
                )
                .into_bytes();
                out.extend_from_slice(&buf);
                let _ = c.write_all(&out).await;
            });
        }
    });
    addr
}

/// Adını döner; `decline` verilirse o yolu üstlenmez.
struct Named(&'static str, Option<&'static str>);

impl RouteHook for Named {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (Some(view.path.as_str()) != self.1).then_some(64)
    }
    fn handle(&self, _req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async move {
            RouteResponse {
                status: 200,
                headers: vec![],
                body: format!("HOOK:{}", self.0).into_bytes(),
            }
        })
    }
}

fn hook(name: &'static str) -> Arc<Named> {
    Arc::new(Named(name, None))
}

/// Eski tek kanca: yalnız `/api/auth/` ve `/api/files/x`.
struct Legacy;

impl RouteHook for Legacy {
    fn route(&self, view: &RequestView) -> Option<usize> {
        (view.path.starts_with("/api/auth/") || view.path == "/api/files/x").then_some(64)
    }
    fn handle(&self, _req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async {
            RouteResponse {
                status: 200,
                headers: vec![],
                body: b"LEGACY".to_vec(),
            }
        })
    }
}

fn table() -> RouteTable {
    let mut t = RouteTable::new();
    t.get("/api/files/*", hook("files"))
        .get("/api/files/deep/*", hook("deep"))
        .get(
            "/api/files/list",
            Arc::new(Named("list", Some("/api/none"))),
        )
        .get(
            "/api/files/deep/skip",
            Arc::new(Named("skip", Some("/api/files/deep/skip"))),
        )
        .own_auth("POST", "/api/open", hook("open"));
    t
}

async fn serve(px: Arc<Proxy>) -> SocketAddr {
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on(l, px));
    addr
}

fn proxy(up: SocketAddr) -> Arc<Proxy> {
    Proxy::with_secret(up, "onkapi")
        .with_route_table(table(), cops_auth::Token::new(TOKEN))
        .with_routes(Arc::new(Legacy))
        .with_stats(StatsCfg {
            token: cops_auth::Token::new(TOKEN),
            front_secret: cops_auth::Token::new("onkapi"),
        })
}

async fn call(addr: SocketAddr, method: &str, path: &str, extra: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: x\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

fn auth() -> String {
    format!("Authorization: Bearer {TOKEN}\r\n")
}

fn body(r: &str) -> &str {
    r.split_once("\r\n\r\n").map_or("", |x| x.1)
}

#[tokio::test]
async fn most_specific_entry_wins_and_unclaimed_falls_through() {
    let addr = serve(proxy(upstream().await)).await;
    for (path, want) in [
        ("/api/files/list", "HOOK:list"),
        ("/api/files/list2", "HOOK:files"),
        ("/api/files/deep/a", "HOOK:deep"),
        // tam kayıt üstlenmedi -> uzun önek
        ("/api/files/deep/skip", "HOOK:deep"),
        // tablo eski tek kancadan önce
        ("/api/files/x", "HOOK:files"),
        ("/api/auth/me", "LEGACY"),
    ] {
        let r = call(addr, "GET", path, &auth()).await;
        assert_eq!(body(&r), want, "{path}: {r}");
    }
    for (method, path) in [
        ("GET", "/api/files"),
        ("POST", "/api/files/list"),
        ("HEAD", "/api/other"),
        ("GET", "/api/open"),
    ] {
        let r = call(addr, method, path, &auth()).await;
        assert!(
            !r.contains("HOOK:") && r.starts_with("HTTP/1.1 200"),
            "{method} {path}: {r}"
        );
    }
}

#[tokio::test]
async fn panel_entries_need_token_own_auth_entries_do_not() {
    let addr = serve(proxy(upstream().await)).await;
    for extra in ["", "Authorization: Bearer yanlis\r\n"] {
        let r = call(addr, "GET", "/api/files/list", extra).await;
        assert!(r.starts_with("HTTP/1.1 401"), "{r}");
        assert!(!r.contains("HOOK:") && !r.contains("UPSTREAM"), "{r}");
    }
    let r = call(addr, "GET", &format!("/api/files/list?token={TOKEN}"), "").await;
    assert_eq!(body(&r), "HOOK:list");
    let r = call(addr, "POST", "/api/open", "").await;
    assert_eq!(body(&r), "HOOK:open");
}

struct Verdict(LocalVerdict);

impl LocalAuth for Verdict {
    fn decide<'a>(&'a self, _view: &'a RequestView) -> BoxFut<'a, LocalVerdict> {
        let v = self.0;
        Box::pin(async move { v })
    }
}

#[tokio::test]
async fn local_auth_hook_decides_panel_entries() {
    let up = upstream().await;
    for (verdict, extra, status) in [
        (LocalVerdict::Allow, String::new(), "200"),
        (LocalVerdict::Unauthorized, auth(), "401"),
        (LocalVerdict::Forbidden, auth(), "403"),
        (LocalVerdict::Default, auth(), "200"),
        (LocalVerdict::Default, String::new(), "401"),
    ] {
        let px = proxy(up).with_local_auth(Arc::new(Verdict(verdict)));
        let r = call(serve(px).await, "GET", "/api/files/list", &extra).await;
        assert!(
            r.starts_with(&format!("HTTP/1.1 {status}")),
            "{verdict:?}: {r}"
        );
    }
}

#[tokio::test]
async fn force_proxy_sends_local_routes_upstream_until_reloaded() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("front_force_proxy");
    std::fs::write(&file, "/api/files/\n").unwrap();
    let force = Arc::new(ForceProxy::load(&file));
    let px = proxy(upstream().await).with_force_proxy(force.clone());
    let addr = serve(px).await;

    // Kimlik de Python'a kalır (token'sız istek aktarılır).
    let r = call(addr, "GET", "/api/files/list", "").await;
    assert!(body(&r).starts_with("UPSTREAM:GET /api/files/list"), "{r}");
    assert!(
        r.to_ascii_lowercase().contains("x-cops-front: onkapi"),
        "{r}"
    );
    // Listede olmayan yerel uç Rust'ta; eski kanca da listeye tabi.
    assert_eq!(body(&call(addr, "GET", "/api/auth/me", "").await), "LEGACY");
    std::fs::write(&file, "*\n").unwrap();
    force.reload().unwrap();
    let r = call(addr, "GET", "/api/auth/me", "").await;
    assert!(body(&r).starts_with("UPSTREAM:"), "{r}");
    // Sayaç ucu Python'da yok: `*` onu aktarmaz.
    let r = call(addr, "GET", "/api/front/stats", &auth()).await;
    assert!(body(&r).contains("\"totals\""), "{r}");

    std::fs::remove_file(&file).unwrap();
    assert_eq!(force.reload().unwrap(), 0);
    let r = call(addr, "GET", "/api/files/list", &auth()).await;
    assert_eq!(body(&r), "HOOK:list");
}

#[test]
fn force_file_parsing_and_failure_modes() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("f");
    assert!(ForceProxy::load(&file).list().is_empty(), "dosya yok");
    std::fs::write(&file, "\u{feff}# x\n\n  api/status \r\n/ws\n").unwrap();
    let f = ForceProxy::load(&file);
    assert_eq!(f.list(), ["/api/status", "/ws"]);
    assert!(f.matches("/ws/term") && !f.matches("/api/stat"));
    // okunamaz hale geldi: yeniden okuma da ilk yükleme de her şeyi Python'a verir (kapalı yön)
    std::fs::remove_file(&file).unwrap();
    std::fs::create_dir(&file).unwrap();
    assert!(f.reload().is_err());
    assert_eq!(f.list(), ["*"]);
    assert_eq!(ForceProxy::load(&file).list(), ["*"]);
    // bozuk (UTF-8 olmayan) içerik de aynı; düzelince liste geri gelir, silinince boşalır
    std::fs::remove_dir(&file).unwrap();
    std::fs::write(&file, "/ws\n").unwrap();
    f.reload().unwrap();
    assert_eq!(f.list(), ["/ws"]);
    std::fs::write(&file, b"/api/a\n\xff\n").unwrap();
    assert!(f.reload().is_err());
    assert_eq!(f.list(), ["*"]);
    std::fs::remove_file(&file).unwrap();
    f.reload().unwrap();
    assert!(f.list().is_empty());
}

#[tokio::test]
async fn stats_count_local_and_fallback_per_endpoint() {
    let addr = serve(proxy(upstream().await)).await;
    call(addr, "GET", "/api/files/list", &auth()).await;
    call(addr, "GET", "/api/files/list", "").await;
    // Kimliksiz 200 aktarım anahtar AÇMAZ (`other`); kimlikli açar.
    call(addr, "GET", "/api/anonymous", "").await;
    call(addr, "GET", "/api/status", &auth()).await;
    call(addr, "GET", "/readfile/SECRETTICKET/a.md", &auth()).await;
    call(addr, "POST", "/api/files/list", &auth()).await;

    let r = call(addr, "GET", "/api/front/stats", "").await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let r = call(addr, "GET", "/api/front/stats", "X-Cops-Front: onkapi\r\n").await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert!(!r.contains("SECRETTICKET"), "{r}");
    let v: Value = serde_json::from_str(body(&r)).unwrap();
    let row = |m: &str, p: &str| {
        v["endpoints"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["method"] == m && e["path"] == p)
            .unwrap_or_else(|| panic!("{m} {p}: {v}"))
            .clone()
    };
    assert_eq!(row("GET", "/api/files/list")["local"], 2);
    assert_eq!(row("POST", "/api/files/list")["fallback"], 1);
    assert_eq!(row("GET", "/api/status")["fallback"], 1);
    assert_eq!(row("GET", "/readfile/*")["fallback"], 1);
    // kayıtlı ama hiç istenmemiş uç da listede
    assert_eq!(row("GET", "/api/files/deep/*")["local"], 0);
    assert_eq!(v["totals"]["local"], 2);
    assert_eq!(v["totals"]["fallback"], 4);
    assert_eq!(v["other"]["fallback"], 1);
    assert!(!r.contains("/api/anonymous"), "{r}");
    assert_eq!(v["routes"].as_array().unwrap().len(), 5);
}

#[tokio::test]
async fn stats_endpoint_absent_unless_enabled() {
    let addr = serve(Proxy::new(upstream().await)).await;
    let r = call(addr, "GET", "/api/front/stats", &auth()).await;
    assert!(body(&r).starts_with("UPSTREAM:"), "{r}");
}

#[tokio::test]
async fn served_header_only_on_request_and_never_trusted_from_upstream() {
    let addr = serve(proxy(upstream().await)).await;
    let r = call(addr, "GET", "/api/status", "")
        .await
        .to_ascii_lowercase();
    assert!(
        !r.split_once("\r\n\r\n")
            .unwrap()
            .0
            .contains("x-cops-served"),
        "{r}"
    );
    let r = call(addr, "GET", "/api/status", "X-Cops-Parity: 1\r\n").await;
    let lower = r.to_ascii_lowercase();
    assert!(lower.contains("x-cops-served: python"), "{r}");
    assert!(!body(&lower).contains("x-cops-parity"), "aktarılmaz: {r}");
    let r = call(addr, "GET", "/api/auth/me", "X-Cops-Parity: 1\r\n").await;
    assert!(
        r.to_ascii_lowercase().contains("x-cops-served: local"),
        "{r}"
    );
}

#[test]
fn bad_registrations_panic() {
    for (method, pattern) in [
        ("GET", "api/x"),
        ("GET", "/*"),
        ("GET", "/api/x*"),
        ("GET", "/api/*/x"),
        ("GET", "/api/x?y"),
        ("GET", "/api/_internal/x"),
        ("GET", "/api/front/stats"),
        ("FETCH", "/api/x"),
    ] {
        let r = std::panic::catch_unwind(|| {
            RouteTable::new().own_auth(method, pattern, hook("x"));
        });
        assert!(r.is_err(), "{method} {pattern}");
    }
    let dup = std::panic::catch_unwind(|| {
        RouteTable::new()
            .get("/api/x", hook("a"))
            .own_auth("GET", "/api/x", hook("b"));
    });
    assert!(dup.is_err());
}
