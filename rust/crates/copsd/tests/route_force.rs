//! B0 test yardımcısı: copsd'de kayıtlı (`routes::register`) HER rota, `front_force_proxy` önek listesine yazılınca Python'a
//! (burada sahte upstream) gider; listede yokken Rust'ta cevaplanır. Tablo bugün boş: yardımcının kendisinin kırmızı
//! olabildiği sahte kancalarla gösterilir (önek yanlış yazılırsa / kanca üstlenmezse hata).
//!
//! Ek denetim: kayıtlı her rotanın `cops-parity/requests/endpoints.json`da en az bir `"expect": "local"` isteği var, listedeki
//! her istek de kayıtlı bir rotaya düşer (izler uç eklerken parite listesini de doldurur).
use cops_auth::authz::{BoxFut, RequestView};
use cops_proxy::force::ForceProxy;
use cops_proxy::gate::{RouteHook, RouteRequest, RouteResponse};
use cops_proxy::routes::RouteTable;
use cops_proxy::Proxy;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "b0-tok-NOT-REAL";
const PROBE: &str = "b0-probe";

/// Sahte Python: istek başını `UPSTREAM:` önekiyle geri yollar.
async fn upstream() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let Ok((mut c, _)) = ln.accept().await else {
                return;
            };
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
                let body = b"UPSTREAM";
                let mut out = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                )
                .into_bytes();
                out.extend_from_slice(body);
                let _ = c.write_all(&out).await;
            });
        }
    });
    addr
}

struct Tmp(PathBuf);

impl Drop for Tmp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn tmp(tag: &str) -> Tmp {
    let p = std::env::temp_dir().join(format!(
        "copsd-routeforce-{tag}-{}-{:?}",
        std::process::id(),
        std::thread::current().id()
    ));
    let _ = std::fs::remove_dir_all(&p);
    std::fs::create_dir_all(&p).unwrap();
    Tmp(p)
}

async fn call(addr: SocketAddr, method: &str, path: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Cops-Parity: 1\r\n\
         Content-Length: 0\r\nConnection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(10), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).to_lowercase()
}

/// Deseni somut yola çevirir (`/api/x/*` -> `/api/x/b0-probe`).
fn concrete(pattern: &str) -> String {
    match pattern.strip_suffix('*') {
        Some(p) => format!("{p}{PROBE}"),
        None => pattern.to_string(),
    }
}

/// Gerçek önek satırı: desenin `*`sız hali (`cops front`/elle yazılan biçim).
fn real_line(pattern: &str) -> String {
    pattern.trim_end_matches('*').to_string()
}

/// Tablodaki her rota için: (1) liste boşken istek Rust'ta cevaplanır (yoksa denetim boş olurdu), (2) `force_line(desen)`
/// listeye yazılınca istek Python'a gider. Dönüş: denetlenen rota sayısı ya da ilk hatanın metni.
async fn check_forced(table: &RouteTable, force_line: fn(&str) -> String) -> Result<usize, String> {
    let up = upstream().await;
    let dir = tmp("chk");
    let mut n = 0;
    for (method, pattern) in table.routes() {
        let path = concrete(pattern);
        for forced in [false, true] {
            let list = dir.0.join(format!("force-{n}-{forced}"));
            std::fs::write(
                &list,
                if forced {
                    force_line(pattern)
                } else {
                    String::new()
                },
            )
            .map_err(|e| e.to_string())?;
            let px = Proxy::new(up)
                .with_route_table(table.clone(), cops_auth::Token::new(TOKEN))
                .with_force_proxy(Arc::new(ForceProxy::load(&list)));
            let ln = TcpListener::bind("127.0.0.1:0")
                .await
                .map_err(|e| e.to_string())?;
            let addr = ln.local_addr().map_err(|e| e.to_string())?;
            let server = tokio::spawn(cops_proxy::serve_on(ln, px));
            let r = call(addr, method, &path).await;
            server.abort();
            let python = r.contains("x-cops-served: python") && r.ends_with("upstream");
            let local = r.contains("x-cops-served: local");
            match (forced, python, local) {
                (false, _, true) | (true, true, false) => {}
                (false, ..) => {
                    return Err(format!(
                        "{method} {pattern}: liste boşken Rust cevaplamadı (kanca üstlenmiyor, denetim boş olurdu): {r}"
                    ))
                }
                (true, ..) => {
                    return Err(format!(
                        "{method} {pattern}: force_proxy {:?} ile Python'a gitmedi: {r}",
                        force_line(pattern)
                    ))
                }
            }
        }
        n += 1;
    }
    Ok(n)
}

fn ctx() -> (cops_state::TestEnv, copsd::routes::RouteCtx) {
    let env = cops_state::TestEnv::new().unwrap();
    let root = env.dir().root().to_path_buf();
    let mut ctx = copsd::routes::RouteCtx::new(root, env.dir().db(), env.dir().instances_json());
    // B1 `/api/instances` süreç taraması `$HOME/.claude/sessions` okur: gerçek ev dizini test girdisi olmasın
    let home = env.root().join("home");
    std::fs::create_dir_all(&home).unwrap();
    ctx.env.home = Some(home.to_string_lossy().into_owned());
    // B2a terminal uçları: canlı `cops` soketi değil, var olmayan özel soket (istek adsız: tmux'a hiç gidilmez)
    ctx.tmux =
        cops_tmux::Tmux::with_socket(format!("cxrf-{}", std::process::id())).tmpdir(env.root());
    (env, ctx)
}

fn registered() -> RouteTable {
    let (_env, ctx) = ctx();
    let mut t = RouteTable::new();
    copsd::routes::register(&mut t, &ctx);
    t
}

#[tokio::test]
async fn every_registered_route_goes_to_python_when_forced() {
    let t = registered();
    let n = check_forced(&t, real_line).await.unwrap();
    assert_eq!(n, t.routes().count());
    println!("copsd kayıtlı rota: {n}");
}

/// Kendi adını döner; `claim` yanlışsa hiçbir isteği üstlenmez.
struct Fake(bool);

impl RouteHook for Fake {
    fn route(&self, _view: &RequestView) -> Option<usize> {
        self.0.then_some(64)
    }
    fn handle(&self, _req: RouteRequest) -> BoxFut<'_, RouteResponse> {
        Box::pin(async {
            RouteResponse {
                status: 200,
                headers: vec![],
                body: b"RUST".to_vec(),
            }
        })
    }
}

fn sample(claim: bool) -> RouteTable {
    let h = Arc::new(Fake(claim));
    let mut t = RouteTable::new();
    t.get("/api/b0/*", h.clone())
        .get("/api/b0/tam", h.clone())
        .own_auth("POST", "/api/b0yaz", h);
    t
}

#[tokio::test]
async fn helper_passes_on_a_sample_table() {
    assert_eq!(check_forced(&sample(true), real_line).await, Ok(3));
}

#[tokio::test]
async fn helper_is_red_when_the_force_line_misses() {
    let e = check_forced(&sample(true), |_| "/baska/\n".into())
        .await
        .unwrap_err();
    assert!(e.contains("Python'a gitmedi"), "{e}");
}

#[tokio::test]
async fn helper_is_red_when_the_hook_never_claims() {
    let e = check_forced(&sample(false), real_line).await.unwrap_err();
    assert!(e.contains("denetim boş olurdu"), "{e}");
}

// ---- parite listesi ----------------------------------------------------------------------------------------------

fn covers(method: &str, pattern: &str, case: &cops_parity::config::Case) -> bool {
    let path = case.path.split('?').next().unwrap_or("");
    case.method == method
        && match pattern.strip_suffix('*') {
            Some(p) => path.starts_with(p),
            None => path == pattern,
        }
}

/// Rotası parite listesinde olmayan ya da hiçbir rotaya düşmeyen / `expect: local` olmayan istekler.
fn parity_gaps(table: &RouteTable, cases: &[cops_parity::config::Case]) -> Vec<String> {
    let mut gaps = Vec::new();
    for (m, p) in table.routes() {
        if !cases.iter().any(|c| c.expect_local && covers(m, p, c)) {
            gaps.push(format!("rota parite listesinde yok: {m} {p}"));
        }
    }
    for c in cases {
        if !c.expect_local {
            gaps.push(format!("istek `expect: local` değil: {}", c.name));
        }
        if !table.routes().any(|(m, p)| covers(m, p, c)) {
            gaps.push(format!("istek kayıtlı rotaya düşmüyor: {}", c.name));
        }
    }
    gaps
}

const ENDPOINTS: &str = include_str!("../../cops-parity/requests/endpoints.json");

#[test]
fn parity_list_matches_registered_routes() {
    let cases = cops_parity::config::parse(ENDPOINTS).unwrap();
    assert_eq!(parity_gaps(&registered(), &cases), Vec::<String>::new());
}

#[test]
fn parity_gap_check_is_red_on_mismatch() {
    let none = cops_parity::config::parse(r#"{"requests": []}"#).unwrap();
    assert_eq!(parity_gaps(&sample(true), &none).len(), 3);
    let stray = cops_parity::config::parse(
        r#"{"requests": [{"path": "/api/b0/x", "expect": "local"}, {"path": "/api/yok"}]}"#,
    )
    .unwrap();
    let gaps = parity_gaps(&sample(true), &stray);
    assert!(gaps.iter().any(|g| g.contains("/api/b0yaz")), "{gaps:?}");
    assert!(gaps.iter().any(|g| g.contains("expect: local")), "{gaps:?}");
    assert!(
        gaps.iter().any(|g| g.contains("rotaya düşmüyor")),
        "{gaps:?}"
    );
    assert!(!gaps.iter().any(|g| g.contains("/api/b0/*")), "{gaps:?}");
}
