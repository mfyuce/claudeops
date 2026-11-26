//! Uygulama mount'ları (`/<id>/` -> yerel derbent loopback portu): kimlik copsd'de, panel kimlik bilgisi upstream'e gitmez,
//! Host korunur, WS ve uzun akışlar tamponlanmadan geçer, mount yokken her şey Python'a gider.
use cops_proxy::{mount::Mounts, MountCfg, Proxy};
use std::net::SocketAddr;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "sekret";
// Python: hmac.new(b"sekret", b"claudeops-ext-session", hashlib.sha256).hexdigest()
const COOKIE: &str = "fd10ed735fac0d564927ae5896d62a45609190913ff450ca45453c6c12801d81";
const BIG: usize = 100 * 1024 * 1024;

async fn read_head(c: &mut TcpStream) -> String {
    let mut acc = Vec::new();
    let mut buf = [0u8; 4096];
    while !acc.windows(4).any(|w| w == b"\r\n\r\n") {
        let n = c.read(&mut buf).await.unwrap_or(0);
        if n == 0 {
            break;
        }
        acc.extend_from_slice(&buf[..n]);
    }
    String::from_utf8_lossy(&acc).to_string()
}

/// Sahte derbent uygulama dinleyicisi: istek başını gövdede geri yansıtır; `/grafana/big` 100 MB, `/grafana/sse` ilk olaydan sonra bekler,
/// WS'de önce `H:<1 ise panel kimliği sızdı>` sonra yankı.
async fn fake_app() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let head = read_head(&mut c).await;
                let low = head.to_ascii_lowercase();
                let leaked =
                    low.contains("cops_") || head.contains(TOKEN) || low.contains("authorization");
                let path = head.split(' ').nth(1).unwrap_or("").to_string();
                if low.contains("upgrade: websocket") {
                    c.write_all(b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n").await.unwrap();
                    c.write_all(if leaked { b"H:1" } else { b"H:0" })
                        .await
                        .unwrap();
                    let mut buf = vec![0u8; 4096];
                    loop {
                        let n = c.read(&mut buf).await.unwrap_or(0);
                        if n == 0 {
                            break;
                        }
                        let mut o = b"echo:".to_vec();
                        o.extend_from_slice(&buf[..n]);
                        if c.write_all(&o).await.is_err() {
                            break;
                        }
                    }
                } else if path.starts_with("/grafana/big") {
                    c.write_all(
                        format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {BIG}\r\nConnection: close\r\n\r\n"
                        )
                        .as_bytes(),
                    )
                    .await
                    .unwrap();
                    let chunk = vec![b'x'; 64 * 1024];
                    for _ in 0..BIG / chunk.len() {
                        if c.write_all(&chunk).await.is_err() {
                            return;
                        }
                    }
                } else if path.starts_with("/grafana/sse") {
                    c.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n9\r\ndata: 1\n\n\r\n").await.unwrap();
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                    let _ = c.write_all(b"0\r\n\r\n").await;
                } else {
                    let ct = low
                        .lines()
                        .find_map(|l| l.strip_prefix("x-fake-ct: "))
                        .map(|v| format!("Content-Type: {}\r\n", v.trim()))
                        .unwrap_or_default();
                    let st = low
                        .lines()
                        .find_map(|l| l.strip_prefix("x-fake-status: "))
                        .map(|v| v.trim().to_string())
                        .unwrap_or_else(|| "200 OK".into());
                    // `x-fake-base: /x/` -> HTML gövdesinde `<base href="/x/">`.
                    let base = low
                        .lines()
                        .find_map(|l| l.strip_prefix("x-fake-base: "))
                        .map(|v| format!("<head><base href=\"{}\"></head>", v.trim()))
                        .unwrap_or_default();
                    let r = format!("HTTP/1.1 {st}\r\nSet-Cookie: grafana_session=new; Path=/grafana/\r\n{ct}Content-Length: {}\r\nConnection: close\r\n\r\n{base}APP\n{}", base.len() + head.len() + 4, head);
                    c.write_all(r.as_bytes()).await.unwrap();
                }
            });
        }
    });
    addr
}

async fn fake_python() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            tokio::spawn(async move {
                let _ = read_head(&mut c).await;
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

fn write_mounts(dir: &std::path::Path, body: &str, mode: u32) -> std::path::PathBuf {
    let f = dir.join("mounts.json");
    std::fs::write(&f, body).unwrap();
    std::fs::set_permissions(&f, std::fs::Permissions::from_mode(mode)).unwrap();
    f
}

/// Vekil: Python sahte upstream'i + ön kapı gizlisi + `mounts.json` (verilen içerik/kip; None = dosya yok).
async fn start(app: SocketAddr, mounts: Option<(&str, u32)>) -> (SocketAddr, tempfile::TempDir) {
    let d = tempfile::tempdir().unwrap();
    let f = match mounts {
        Some((body, mode)) => write_mounts(d.path(), &body.replace("APP", &app.to_string()), mode),
        None => d.path().join("mounts.json"),
    };
    let m = Mounts::new(f);
    m.refresh();
    let px = Proxy::with_secret(fake_python().await, "gizli").with_mounts(MountCfg {
        mounts: m,
        token: cops_auth::Token::new(TOKEN),
    });
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on(l, px));
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    (addr, d)
}

const GRAFANA: &str = r#"[{"path":"/grafana/","upstream":"APP"}]"#;

async fn raw(addr: SocketAddr, req: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(std::time::Duration::from_secs(3), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_string()
}

fn get(path: &str, extra: &str) -> String {
    format!("GET {path} HTTP/1.1\r\nHost: panel.example:8765\r\n{extra}Connection: close\r\n\r\n")
}

fn header<'a>(resp: &'a str, name: &str) -> Option<&'a str> {
    let head = resp.split("\r\n\r\n").next()?;
    head.split("\r\n").find_map(|l| {
        l.split_once(':')
            .filter(|(k, _)| k.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.trim())
    })
}

#[tokio::test]
async fn no_credentials_is_401_plain_or_html_and_never_reaches_app() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    let r = raw(p, &get("/grafana/", "")).await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    assert!(
        !r.contains("APP\n")
            && header(&r, "content-type")
                .unwrap()
                .starts_with("text/plain"),
        "{r}"
    );
    let r = raw(
        p,
        &get(
            "/grafana/d/x",
            "Accept: text/html,application/xhtml+xml\r\n",
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 401")
            && header(&r, "content-type").unwrap().starts_with("text/html")
            && header(&r, "location").is_none(),
        "{r}"
    );
    for bad in ["?token=yanlis", ""] {
        let r = raw(
            p,
            &get(
                &format!("/grafana/{bad}"),
                "Cookie: cops_ext=deadbeef; grafana_session=x\r\nAuthorization: Bearer yanlis\r\n",
            ),
        )
        .await;
        assert!(r.starts_with("HTTP/1.1 401"), "{bad}: {r}");
    }
    let r = raw(p, &get("/grafana", "")).await;
    assert!(
        r.starts_with("HTTP/1.1 401"),
        "kimliksiz bare yol da 401 (mount varlığı sızmaz): {r}"
    );
}

#[tokio::test]
async fn query_token_redirects_with_cookie_and_strips_token() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    let r = raw(
        p,
        &get(
            &format!("/grafana/d/abc?orgId=1&token={TOKEN}&from=now-1h"),
            "",
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 302"), "{r}");
    assert_eq!(
        header(&r, "location"),
        Some("/grafana/d/abc?orgId=1&from=now-1h")
    );
    assert_eq!(
        header(&r, "set-cookie"),
        Some(format!("cops_ext={COOKIE}; Path=/; HttpOnly; SameSite=Strict").as_str())
    );
    assert!(!r.contains("APP\n"), "yönlendirme upstream'e gitmez: {r}");
    // bare + token: tek adımda /grafana/ (token'sız)
    let r = raw(p, &get(&format!("/grafana?token={TOKEN}"), "")).await;
    assert!(
        r.starts_with("HTTP/1.1 302")
            && header(&r, "location") == Some("/grafana/")
            && header(&r, "set-cookie").is_some(),
        "{r}"
    );
    // tünel (loopback eş + X-Forwarded-Proto: https) -> Secure
    let r = raw(
        p,
        &get(
            &format!("/grafana/?token={TOKEN}"),
            "X-Forwarded-Proto: https\r\n",
        ),
    )
    .await;
    assert!(
        header(&r, "set-cookie").unwrap().ends_with("; Secure"),
        "{r}"
    );
    // kodlu ad da silinir (Python parse_qs anahtarı çözer); token'sız boş parça içeren sorgu yönlenmez
    let r = raw(
        p,
        &get(
            &format!("/grafana/x?a=1&tok%65n={TOKEN}"),
            &format!("Cookie: cops_ext={COOKIE}\r\n"),
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 302") && header(&r, "location") == Some("/grafana/x?a=1"),
        "{r}"
    );
    let r = raw(
        p,
        &get(
            "/grafana/x?a=1&&b",
            &format!("Cookie: cops_ext={COOKIE}\r\n"),
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 200") && r.contains("GET /grafana/x?a=1&&b HTTP/1.1"),
        "{r}"
    );
    // geçerli çerez zaten varsa yine token'sız adrese yönlenir ama çerez yeniden basılmaz
    let r = raw(
        p,
        &get(
            &format!("/grafana/?token={TOKEN}"),
            &format!("Cookie: cops_ext={COOKIE}\r\n"),
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 302") && header(&r, "set-cookie").is_none(),
        "{r}"
    );
}

#[tokio::test]
async fn token_cookie_and_authorization_never_reach_app_host_and_other_cookies_kept() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    let r = raw(p, &get("/grafana/api/x?a=1", &format!("Cookie: grafana_session=abc; cops_ext={COOKIE}; cops_t=jwt; theme=dark\r\nX-Forwarded-For: 6.6.6.6\r\nX-Forwarded-Proto: https\r\nX-Cops-Front: sahte\r\nX-Forwarded-Host: evil\r\n"))).await;
    assert!(r.starts_with("HTTP/1.1 200") && r.contains("APP\n"), "{r}");
    let body = r.split("APP\n").nth(1).unwrap().to_ascii_lowercase();
    assert!(
        body.starts_with("get /grafana/api/x?a=1 http/1.1"),
        "yol DEĞİŞMEZ: {body}"
    );
    assert!(
        body.contains("host: panel.example:8765"),
        "Host korunur: {body}"
    );
    assert!(
        body.contains("cookie: grafana_session=abc; theme=dark\r\n"),
        "diğer çerezler aynen: {body}"
    );
    assert!(!body.contains("cops_") && !body.contains(COOKIE), "{body}");
    assert!(
        body.contains("x-forwarded-for: 127.0.0.1") && !body.contains("6.6.6.6"),
        "{body}"
    );
    assert!(
        body.contains("x-forwarded-proto: https"),
        "loopback ön uçtan https korunur: {body}"
    );
    assert!(
        !body.contains("x-cops-front") && !body.contains("gizli") && !body.contains("sahte"),
        "ön kapı gizlisi uygulamaya gitmez: {body}"
    );
    assert!(!body.contains("x-forwarded-host"), "{body}");
    assert_eq!(
        header(&r, "set-cookie"),
        Some("grafana_session=new; Path=/grafana/"),
        "uygulamanın Set-Cookie'si aynen döner"
    );

    // Bearer ile: Authorization silinir
    let r = raw(
        p,
        &get(
            "/grafana/api/y",
            &format!("Authorization: Bearer {TOKEN}\r\n"),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let body = r.split("APP\n").nth(1).unwrap().to_ascii_lowercase();
    assert!(
        !body.contains("authorization")
            && !body.contains(TOKEN)
            && body.contains("x-forwarded-proto: http\r\n"),
        "{body}"
    );

    // GET dışı + ?token=: yönlenmez (yöntem korunur), token sorgudan silinip aktarılır, yanıta çerez eklenir
    let r = raw(p, &format!("POST /grafana/api/ds?token={TOKEN}&x=1 HTTP/1.1\r\nHost: h\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}")).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let body = r.split("APP\n").nth(1).unwrap();
    assert!(
        body.starts_with("POST /grafana/api/ds?x=1 HTTP/1.1") && !body.contains(TOKEN),
        "{body}"
    );
    assert!(r.contains(&format!("cops_ext={COOKIE}; Path=/")), "{r}");
}

#[tokio::test]
async fn bare_mount_path_is_308_with_query() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    let r = raw(
        p,
        &get(
            "/grafana?orgId=1",
            &format!("Cookie: cops_ext={COOKIE}\r\n"),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 308"), "{r}");
    assert_eq!(header(&r, "location"), Some("/grafana/?orgId=1"));
    let r = raw(
        p,
        &get("/grafana", &format!("Cookie: cops_ext={COOKIE}\r\n")),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 308") && header(&r, "location") == Some("/grafana/"),
        "{r}"
    );
}

#[tokio::test]
async fn websocket_through_mount_is_bidirectional_and_clean() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    let mut s = TcpStream::connect(p).await.unwrap();
    s.write_all(format!("GET /grafana/api/live/ws HTTP/1.1\r\nHost: h\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nCookie: cops_ext={COOKIE}; grafana_session=a\r\nSec-WebSocket-Key: abc\r\nSec-WebSocket-Version: 13\r\n\r\n").as_bytes()).await.unwrap();
    let mut acc = Vec::new();
    let mut buf = vec![0u8; 1024];
    while !String::from_utf8_lossy(&acc).contains("H:") {
        let n = tokio::time::timeout(std::time::Duration::from_secs(3), s.read(&mut buf))
            .await
            .unwrap()
            .unwrap();
        assert!(n > 0);
        acc.extend_from_slice(&buf[..n]);
    }
    let t = String::from_utf8_lossy(&acc).to_string();
    assert!(
        t.starts_with("HTTP/1.1 101") && t.ends_with("H:0"),
        "panel kimliği WS isteğinde de sızmaz: {t}"
    );
    for msg in ["hi", "ikinci"] {
        s.write_all(msg.as_bytes()).await.unwrap();
        let n = tokio::time::timeout(std::time::Duration::from_secs(3), s.read(&mut buf))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(&buf[..n], format!("echo:{msg}").as_bytes());
    }
    // kimliksiz WS: 401, yükseltme yok
    let r = raw(p, "GET /grafana/api/live/ws HTTP/1.1\r\nHost: h\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Key: abc\r\nSec-WebSocket-Version: 13\r\n\r\n").await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
}

fn rss_kb() -> usize {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines()
                .find(|l| l.starts_with("VmRSS:"))
                .and_then(|l| l.split_whitespace().nth(1))
                .and_then(|v| v.parse().ok())
        })
        .unwrap_or(0)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn large_stream_constant_memory_and_sse_not_buffered() {
    let (p, _d) = start(fake_app().await, Some((GRAFANA, 0o600))).await;
    // SSE: ilk olay upstream yanıtı bitmeden istemciye ulaşır
    let mut s = TcpStream::connect(p).await.unwrap();
    s.write_all(get("/grafana/sse", &format!("Cookie: cops_ext={COOKIE}\r\n")).as_bytes())
        .await
        .unwrap();
    let mut acc = Vec::new();
    let mut buf = vec![0u8; 4096];
    let t0 = std::time::Instant::now();
    while !String::from_utf8_lossy(&acc).contains("data: 1") {
        let n = tokio::time::timeout(std::time::Duration::from_secs(2), s.read(&mut buf))
            .await
            .expect("SSE tamponlandı")
            .unwrap();
        assert!(n > 0);
        acc.extend_from_slice(&buf[..n]);
    }
    assert!(t0.elapsed() < std::time::Duration::from_secs(2));
    drop(s);

    // 100 MB: bellek sabit
    let before = rss_kb();
    let mut s = TcpStream::connect(p).await.unwrap();
    s.write_all(get("/grafana/big", &format!("Cookie: cops_ext={COOKIE}\r\n")).as_bytes())
        .await
        .unwrap();
    let mut buf = vec![0u8; 64 * 1024];
    let (mut total, mut peak) = (0usize, before);
    loop {
        let n = tokio::time::timeout(std::time::Duration::from_secs(30), s.read(&mut buf))
            .await
            .unwrap()
            .unwrap();
        if n == 0 {
            break;
        }
        total += n;
        if total % (8 << 20) < n {
            peak = peak.max(rss_kb());
        }
    }
    assert!(total > BIG, "eksik gövde: {total}");
    let grew = peak.saturating_sub(before);
    assert!(
        grew < 32 * 1024,
        "100 MB akışta RSS {grew} KB büyüdü (tamponlama?)"
    );
}

#[tokio::test]
async fn without_mount_file_everything_goes_to_python() {
    let app = fake_app().await;
    for mounts in [
        None,
        Some((GRAFANA, 0o644)),
        Some(("[]", 0o600)),
        Some(("{bozuk", 0o600)),
    ] {
        let (p, _d) = start(app, mounts).await;
        for path in ["/grafana/", "/grafana", "/api/status", "/"] {
            let r = raw(p, &get(path, &format!("Cookie: cops_ext={COOKIE}\r\n"))).await;
            assert!(
                r.contains("PYTHON") && !r.contains("APP\n"),
                "{mounts:?} {path}: {r}"
            );
        }
    }
    // mount varken panel yolları yine Python'da
    let (p, _d) = start(app, Some((GRAFANA, 0o600))).await;
    for path in ["/api/status", "/", "/grafanax/", "/q/abc"] {
        let r = raw(p, &get(path, "")).await;
        assert!(r.contains("PYTHON"), "{path}: {r}");
    }
}

#[tokio::test]
async fn dead_app_upstream_is_502() {
    let dead = {
        let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
        l.local_addr().unwrap()
    };
    let (p, _d) = start(dead, Some((GRAFANA, 0o600))).await;
    let r = raw(
        p,
        &get("/grafana/", &format!("Cookie: cops_ext={COOKIE}\r\n")),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 502"), "{r}");
}

#[tokio::test]
async fn mount_table_hot_reload_through_proxy() {
    let app = fake_app().await;
    let d = tempfile::tempdir().unwrap();
    let f = d.path().join("mounts.json");
    let m: Arc<Mounts> = Mounts::new(f.clone());
    let h = m.spawn_watch(std::time::Duration::from_millis(20));
    let px = Proxy::new(fake_python().await).with_mounts(MountCfg {
        mounts: m,
        token: cops_auth::Token::new(TOKEN),
    });
    let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let p = l.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on(l, px));
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    let req = get("/grafana/", &format!("Cookie: cops_ext={COOKIE}\r\n"));
    assert!(raw(p, &req).await.contains("PYTHON"));
    write_mounts(d.path(), &GRAFANA.replace("APP", &app.to_string()), 0o600);
    let mut ok = false;
    for _ in 0..100 {
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        if raw(p, &req).await.contains("APP\n") {
            ok = true;
            break;
        }
    }
    h.abort();
    assert!(ok, "yeni mount canlıya alınmadı");
}

const GW: &str =
    r#"[{"path":"/gw/","upstream":"APP","rootrel":true},{"path":"/grafana/","upstream":"APP"}]"#;

#[tokio::test]
async fn rootrel_requests_follow_the_referer_into_the_mount() {
    let (p, _d) = start(fake_app().await, Some((GW, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    // Referer /gw/ altinda: panel yolu (/api/...) da uygulamaya gider, /gw oneki eklenir.
    let r = raw(
        p,
        &get(
            "/api/export?a=1",
            &format!("{auth}Referer: http://panel.example:8765/gw/maya-ui/x\r\n"),
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 200") && r.contains("GET /gw/api/export?a=1 "),
        "{r}"
    );
    assert!(
        !r.contains(COOKIE),
        "panel kimligi uygulamaya sizmamali: {r}"
    );
    // Kimliksiz: 401 (Referer kimlik vermez).
    let r = raw(
        p,
        &get("/api/export", "Referer: http://panel.example:8765/gw/\r\n"),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    // Baska kokenin Referer'i, rootrel olmayan mount ve Referer'siz istek panele (Python) gider.
    for extra in [
        "Referer: http://evil.example/gw/\r\n",
        "Referer: http://panel.example:8765/grafana/d/1\r\n",
        "",
    ] {
        let r = raw(p, &get("/api/export", &format!("{auth}{extra}"))).await;
        assert!(r.contains("PYTHON"), "{extra}: {r}");
    }
}

const TWO: &str = r#"[{"path":"/gw/","upstream":"APP","rootrel":true},{"path":"/rancher/","upstream":"APP","rootrel":true},{"path":"/grafana/","upstream":"APP"}]"#;

fn set_cookies(r: &str) -> Vec<String> {
    r.split("\r\n\r\n")
        .next()
        .unwrap_or("")
        .split("\r\n")
        .filter(|l| l.to_ascii_lowercase().starts_with("set-cookie:"))
        .map(|l| l.to_string())
        .collect()
}

#[tokio::test]
async fn rootrel_mount_response_sets_the_app_cookie_once() {
    let (p, _d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("cops_ext={COOKIE}");
    let r = raw(p, &get("/gw/x", &format!("Cookie: {auth}\r\n"))).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert!(
        set_cookies(&r).iter().any(|c| c.contains("cops_app=gw")
            && c.contains("Path=/")
            && c.contains("HttpOnly")
            && c.contains("SameSite=Lax")),
        "{r}"
    );
    // Istek ayni degeri zaten tasiyorsa tekrar konmaz.
    let r = raw(
        p,
        &get("/gw/x", &format!("Cookie: {auth}; cops_app=gw\r\n")),
    )
    .await;
    assert!(
        !set_cookies(&r).iter().any(|c| c.contains("cops_app=")),
        "{r}"
    );
    // Cerez uygulamaya sizmaz.
    assert!(!r.contains("cops_app"), "{r}");
    // rootrel olmayan mount cerez koymaz.
    let r = raw(p, &get("/grafana/x", &format!("Cookie: {auth}\r\n"))).await;
    assert!(
        !set_cookies(&r).iter().any(|c| c.contains("cops_app=")),
        "{r}"
    );
}

#[tokio::test]
async fn cookie_routes_refererless_root_requests_to_the_app() {
    let (p, _d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("cops_ext={COOKIE}");
    let r = raw(
        p,
        &get(
            "/maya-ui/a?b=1",
            &format!("Cookie: {auth}; cops_app=gw\r\n"),
        ),
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 200") && r.contains("GET /gw/maya-ui/a?b=1 "),
        "{r}"
    );
    // Yonlenen yanit da cerezi yeniler (istek zaten tasiyor: eklenmez).
    assert!(
        !set_cookies(&r).iter().any(|c| c.contains("cops_app=")),
        "{r}"
    );
    // Yetki degismez: kimliksiz cerez 401.
    let r = raw(p, &get("/maya-ui/a", "Cookie: cops_app=gw\r\n")).await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
}

#[tokio::test]
async fn panel_paths_and_unknown_cookies_stay_on_the_panel() {
    let (p, _d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("cops_ext={COOKIE}");
    for path in [
        "/",
        "/api/status",
        "/ws",
        "/q/abc",
        "/v1/models",
        "/desktop/viewer.js",
        "/readlist/x",
        "/assets/a.js",
    ] {
        let r = raw(p, &get(path, &format!("Cookie: {auth}; cops_app=gw\r\n"))).await;
        assert!(r.contains("PYTHON"), "{path}: {r}");
    }
    for ck in [
        "cops_app=nope",
        "cops_app=grafana",
        "cops_app=",
        "cops_app=../gw",
    ] {
        let r = raw(p, &get("/maya-ui/a", &format!("Cookie: {auth}; {ck}\r\n"))).await;
        assert!(r.contains("PYTHON"), "{ck}: {r}");
    }
    // Cerezsiz ve Referer'siz.
    let r = raw(p, &get("/maya-ui/a", &format!("Cookie: {auth}\r\n"))).await;
    assert!(r.contains("PYTHON"), "{r}");
}

#[tokio::test]
async fn referer_beats_the_cookie() {
    let (p, _d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("cops_ext={COOKIE}");
    let r = raw(
        p,
        &get(
            "/dashboard/x",
            &format!("Cookie: {auth}; cops_app=gw\r\nReferer: http://panel.example:8765/rancher/dashboard/\r\n"),
        ),
    )
    .await;
    assert!(r.contains("GET /rancher/dashboard/x "), "{r}");
    // /api: Referer'li uygulamaya, Referer'siz panele.
    let r = raw(
        p,
        &get("/api/x", &format!("Cookie: {auth}; cops_app=gw\r\n")),
    )
    .await;
    assert!(r.contains("PYTHON"), "{r}");
}

#[tokio::test]
async fn panel_path_from_an_app_page_with_cookie_goes_to_the_app() {
    let (p, _d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("cops_ext={COOKIE}");
    let ck = format!("Cookie: {auth}; cops_app=rancher\r\n");
    // Referer panelde olmayan bir sayfa (pushState): /v1 ve /api uygulamanin.
    for path in ["/v1/x", "/api/y"] {
        let r = raw(
            p,
            &get(
                path,
                &format!("{ck}Referer: http://panel.example:8765/dashboard/auth/login?a=1\r\n"),
            ),
        )
        .await;
        assert!(r.contains(&format!("GET /rancher{path} ")), "{path}: {r}");
    }
    // Referer panel sayfasi: panel.
    for refp in ["/", "/?x=1", "/index.html", "/q/abc", "/desktop/v"] {
        let r = raw(
            p,
            &get(
                "/api/status",
                &format!("{ck}Referer: http://panel.example:8765{refp}\r\n"),
            ),
        )
        .await;
        assert!(r.contains("PYTHON"), "{refp}: {r}");
    }
    // Referer'siz panel yolu: panel. Baska kokenli Referer: panel. Cerezsiz: panel.
    let r = raw(p, &get("/v1/models", &ck)).await;
    assert!(r.contains("PYTHON"), "{r}");
    let r = raw(
        p,
        &get(
            "/v1/x",
            &format!("{ck}Referer: http://evil.example/dashboard/\r\n"),
        ),
    )
    .await;
    assert!(r.contains("PYTHON"), "{r}");
    let r = raw(
        p,
        &get(
            "/v1/x",
            &format!("Cookie: {auth}\r\nReferer: http://panel.example:8765/dashboard/\r\n"),
        ),
    )
    .await;
    assert!(r.contains("PYTHON"), "{r}");
}

const HTML: &str = "X-Fake-Ct: text/html; charset=utf-8\r\n";

fn ckh(app: &str) -> String {
    format!("Cookie: cops_ext={COOKIE}; cops_app={app}\r\n")
}

#[tokio::test]
async fn html_pages_through_a_rootrel_mount_teach_their_first_segment() {
    let (p, d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    // Grafana sayfasi /gw/graf/ uzerinden sunulunca `graf` -> gw ogrenilir.
    let r = raw(p, &get("/gw/graf/d/x", &format!("{auth}{HTML}"))).await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    // Cerez rancher iken Referer'li alt kaynak gw'ye gider.
    let r = raw(
        p,
        &get(
            "/offline-map/1.png",
            &format!(
                "{}Referer: http://panel.example:8765/graf/d/x\r\n",
                ckh("rancher")
            ),
        ),
    )
    .await;
    assert!(r.contains("GET /gw/offline-map/1.png "), "{r}");
    // Referer'siz F5 / yeni sekme.
    let r = raw(p, &get("/graf/d/x", &ckh("rancher"))).await;
    assert!(r.contains("GET /gw/graf/d/x "), "{r}");
    // Rancher /dashboard/ ogrenilince Referer /dashboard/auth/login + /v1/x rancher'a gider (cerez gw olsa da).
    raw(p, &get("/rancher/dashboard/", &format!("{auth}{HTML}"))).await;
    let r = raw(
        p,
        &get(
            "/v1/x",
            &format!(
                "{}Referer: http://panel.example:8765/dashboard/auth/login\r\n",
                ckh("gw")
            ),
        ),
    )
    .await;
    assert!(r.contains("GET /rancher/v1/x "), "{r}");
    // Tablo dosyada, 0600.
    let f = d.path().join("rootrel_learned.json");
    let mode = std::fs::metadata(&f).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode, 0o600);
    let t = std::fs::read_to_string(&f).unwrap();
    assert!(t.contains("graf") && t.contains("dashboard"), "{t}");
    // Yeniden baslatma: ayni dizinde yeni Mounts tabloyu yukler.
    let m = Mounts::new(d.path().join("mounts.json"));
    m.refresh();
    assert_eq!(m.learned("graf").map(|x| x.0), Some("gw".to_string()));
    assert_eq!(
        m.learned("dashboard").map(|x| x.0),
        Some("rancher".to_string())
    );
}

#[tokio::test]
async fn only_html_non_panel_segments_are_learned() {
    let (p, d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    // JSON/duz yanit ogretmez.
    raw(p, &get("/gw/zzz/a", &auth)).await;
    raw(
        p,
        &get(
            "/gw/jsn/a",
            &format!("{auth}X-Fake-Ct: application/json\r\n"),
        ),
    )
    .await;
    // Panel kokleri, mount koku ve bos parca ogretilmez.
    for path in [
        "/gw/",
        "/gw/api/x",
        "/gw/v1/x",
        "/gw/q/x",
        "/gw/assets/a",
        "/gw/index.html",
        "/gw/desktop/v",
        "/gw/gw/x",
    ] {
        raw(p, &get(path, &format!("{auth}{HTML}"))).await;
    }
    let f = d.path().join("rootrel_learned.json");
    let t = std::fs::read_to_string(&f).unwrap_or_default();
    for bad in [
        "zzz", "jsn", "api", "v1", "\"q\"", "assets", "index", "desktop", "\"gw\":",
    ] {
        assert!(!t.contains(bad), "{bad}: {t}");
    }
    let r = raw(p, &get("/zzz/a", &auth)).await;
    assert!(r.contains("PYTHON"), "{r}");
    // Rootrel olmayan mount ogretmez.
    raw(p, &get("/graf/page/x", &format!("{auth}{HTML}"))).await;
    let t = std::fs::read_to_string(&f).unwrap_or_default();
    assert!(!t.contains("\"page\""), "{t}");
}

#[tokio::test]
async fn last_taught_wins_and_removed_mounts_are_ignored() {
    let app = fake_app().await;
    let (p, d) = start(app, Some((TWO, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    raw(p, &get("/gw/shared/x", &format!("{auth}{HTML}"))).await;
    raw(p, &get("/rancher/shared/x", &format!("{auth}{HTML}"))).await;
    let r = raw(p, &get("/shared/y", &auth)).await;
    assert!(r.contains("GET /rancher/shared/y "), "{r}");
    // rancher mount'u silinince (yeni Mounts, yalniz gw) o mount'un satiri yok sayilir.
    let m = Mounts::new(write_mounts(
        d.path(),
        &GW.replace("APP", &app.to_string()),
        0o600,
    ));
    m.refresh();
    assert_eq!(m.learned("shared"), None);
}

#[tokio::test]
async fn subresources_with_a_mount_path_referer_teach_their_root_automatically() {
    let (p, d) = start(fake_app().await, Some((TWO, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    let f = d.path().join("rootrel_learned.json");
    // Referer /gw/ + HTML olmayan alt kaynak 200 -> `maya-ui` ogrenilir.
    let r = raw(
        p,
        &get(
            "/maya-ui/chunk.js",
            &format!("{auth}Referer: http://panel.example:8765/gw/\r\n"),
        ),
    )
    .await;
    assert!(r.contains("GET /gw/maya-ui/chunk.js "), "{r}");
    // Sonra cerez rancher iken Referer'siz F5 -> gw.
    let r = raw(p, &get("/maya-ui/", &ckh("rancher"))).await;
    assert!(r.contains("GET /gw/maya-ui/ "), "{r}");
    // Mount yolunun derinindeki Referer de olur.
    raw(
        p,
        &get(
            "/deep-app/a.js",
            &format!("{auth}Referer: http://panel.example:8765/gw/graf/x\r\n"),
        ),
    )
    .await;
    let t = std::fs::read_to_string(&f).unwrap();
    assert!(t.contains("deep-app"), "{t}");
    // Panel kokleri ogrenilmez.
    for path in ["/api/x", "/v1/x", "/q/x", "/assets/a.js"] {
        raw(
            p,
            &get(
                path,
                &format!("{auth}Referer: http://panel.example:8765/gw/\r\n"),
            ),
        )
        .await;
    }
    // 404 / 5xx ogretmez.
    for st in ["404 Not Found", "500 Internal Server Error"] {
        raw(
            p,
            &get(
                "/bad-seg/a",
                &format!("{auth}Referer: http://panel.example:8765/gw/\r\nX-Fake-Status: {st}\r\n"),
            ),
        )
        .await;
    }
    // Cerezle yonlenmis (Referer'siz) HTML olmayan istek ogretmez.
    raw(p, &get("/cookie-seg/a.js", &ckh("gw"))).await;
    // Referer yok ya da baska koken: ogretmez (panel'e gider).
    raw(p, &get("/nor-seg/a.js", &auth)).await;
    raw(
        p,
        &get(
            "/evil-seg/a.js",
            &format!("{auth}Referer: http://evil.example/gw/\r\n"),
        ),
    )
    .await;
    let t = std::fs::read_to_string(&f).unwrap();
    for bad in [
        "api",
        "v1",
        "\"q\"",
        "assets",
        "bad-seg",
        "cookie-seg",
        "nor-seg",
        "evil-seg",
    ] {
        assert!(!t.contains(bad), "{bad}: {t}");
    }
}

#[test]
fn learned_sqlite_migrates_json_and_persists() {
    let d = tempfile::tempdir().unwrap();
    let db = d.path().join("c.db");
    let mf = d.path().join("mounts.json");
    let json = d.path().join("rootrel_learned.json");
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::write(&json, r#"{"dash":"gw"}"#).unwrap();
        std::fs::set_permissions(&json, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let m = Mounts::with_db(mf.clone(), Some(db.clone()));
    assert!(!json.exists() && d.path().join("rootrel_learned.json.migrated").exists());
    assert_eq!(cops_local::learned::load(&db).unwrap()["dash"], "gw");
    m.learn("site", "rancher");
    drop(m);
    let m2 = Mounts::with_db(mf, Some(db.clone()));
    let _ = m2;
    let t = cops_local::learned::load(&db).unwrap();
    assert_eq!(t["site"], "rancher");
    assert_eq!(t.len(), 2);
}

const ONE_ROOTREL: &str = r#"[{"path":"/gw/","upstream":"APP","rootrel":true}]"#;

#[tokio::test]
async fn rootrel_mount_root_with_foreign_base_href_redirects_there_and_routes_it() {
    let (p, _d) = start(fake_app().await, Some((ONE_ROOTREL, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    let r = raw(
        p,
        &get(
            "/gw/",
            &format!("{auth}x-fake-ct: text/html\r\nx-fake-base: /maya-ui/\r\n"),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 302"), "{r}");
    assert_eq!(header(&r, "location"), Some("/maya-ui/"), "{r}");
    assert!(
        set_cookies(&r).iter().any(|c| c.contains(": cops_app=gw")),
        "{r}"
    );
    // Yönlendirilen kök artık öğrenilmiş: Referer ve uygulama çerezi olmadan da uygulamaya gider, ikinci kez yönlenmez.
    let r = raw(
        p,
        &get(
            "/maya-ui/",
            &format!("{auth}x-fake-ct: text/html\r\nx-fake-base: /maya-ui/\r\n"),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200") && r.contains("APP\n"), "{r}");
}

#[tokio::test]
async fn mount_root_is_served_unchanged_when_base_href_is_not_a_safe_foreign_root() {
    let (p, _d) = start(fake_app().await, Some((ONE_ROOTREL, 0o600))).await;
    let auth = format!("Cookie: cops_ext={COOKIE}\r\n");
    for base in [
        "/gw/",
        "/gw/app/",
        "/",
        "./",
        "app/",
        "//evil.example/x/",
        "https://evil.example/",
        "/api/",
        "/\\evil.example/",
    ] {
        let r = raw(
            p,
            &get(
                "/gw/",
                &format!("{auth}x-fake-ct: text/html\r\nx-fake-base: {base}\r\n"),
            ),
        )
        .await;
        assert!(
            r.starts_with("HTTP/1.1 200") && r.contains("<base href=") && r.contains("APP\n"),
            "{base}: {r}"
        );
    }
    // HTML olmayan yanıt ve kök dışı yol yönlendirilmez.
    for (path, ct) in [("/gw/", "application/json"), ("/gw/d/x", "text/html")] {
        let r = raw(
            p,
            &get(
                path,
                &format!("{auth}x-fake-ct: {ct}\r\nx-fake-base: /maya-ui/\r\n"),
            ),
        )
        .await;
        assert!(r.starts_with("HTTP/1.1 200"), "{path} {ct}: {r}");
    }
}

#[tokio::test]
async fn query_token_on_a_learned_root_keeps_the_public_path() {
    let (p, _d) = start(fake_app().await, Some((ONE_ROOTREL, 0o600))).await;
    let r = raw(
        p,
        &get(
            "/gw/",
            &format!(
                "Cookie: cops_ext={COOKIE}\r\nx-fake-ct: text/html\r\nx-fake-base: /maya-ui/\r\n"
            ),
        ),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 302"), "{r}");
    let r = raw(p, &get(&format!("/maya-ui/?a=1&token={TOKEN}"), "")).await;
    assert!(r.starts_with("HTTP/1.1 302"), "{r}");
    assert_eq!(header(&r, "location"), Some("/maya-ui/?a=1"), "{r}");
    assert!(
        set_cookies(&r).iter().any(|c| c.contains(": cops_ext=")),
        "{r}"
    );
}
