//! B2a (`cops-ep-term`): copsd `register` iki terminal OKUMA ucunu kaydeder (yetki eylemi Python tablosuyla aynı:
//! `term.read`); `/api/term/` altında başka (yazan) kayıt yok; canlı soket Python'unkiyle aynı (`cops`); `HOME` yoksa uçlar
//! Python'da. Uçtan uca (gerçek vekil + yalıtılmış tmux sunucusu + gerçek süreç): yerel pane Rust'ta, uzak `host` ve imzalı
//! iletim başlığı Python'da.
use cops_proxy::routes::RouteTable;
use cops_proxy::Proxy;
use cops_state::TestEnv;
use copsd::routes::RouteCtx;
use std::net::SocketAddr;
use std::process::Command;
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "b2a-tok-NOT-REAL";

/// Yalıtılmış tmux: geçici `TMUX_TMPDIR` + benzersiz soket; `Drop`ta yalnız kendi sunucusu kapanır.
struct Srv {
    sock: String,
    dir: std::path::PathBuf,
}

impl Srv {
    fn new() -> Srv {
        // unix soket yolu kısa kalsın (108 bayt): `TestEnv` kökü değil, `/tmp` altında kısa dizin
        let dir = std::env::temp_dir().join(format!("cxb2a{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        Srv {
            sock: format!("cxb2a{}", std::process::id()),
            dir,
        }
    }
    fn tmux(&self) -> cops_tmux::Tmux {
        cops_tmux::Tmux::with_socket(self.sock.clone()).tmpdir(&self.dir)
    }
    fn raw(&self, args: &[&str]) -> String {
        let o = Command::new("tmux")
            .args(["-L", &self.sock, "-f", "/dev/null"])
            .args(args)
            .env("TMUX_TMPDIR", &self.dir)
            .env_remove("TMUX")
            .output()
            .unwrap();
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        String::from_utf8(o.stdout).unwrap()
    }
}

impl Drop for Srv {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", &self.sock, "kill-server"])
            .env("TMUX_TMPDIR", &self.dir)
            .env_remove("TMUX")
            .output();
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn ctx(env: &TestEnv, tmux: cops_tmux::Tmux) -> RouteCtx {
    let mut ctx = RouteCtx::new(
        env.dir().root().to_path_buf(),
        env.dir().db(),
        env.dir().instances_json(),
    );
    let home = env.root().join("home");
    std::fs::create_dir_all(&home).unwrap();
    ctx.env.home = Some(home.to_string_lossy().into_owned());
    ctx.tmux = tmux;
    ctx
}

fn private(env: &TestEnv) -> cops_tmux::Tmux {
    cops_tmux::Tmux::with_socket(format!("cxb2ax{}", std::process::id())).tmpdir(env.root())
}

fn table(ctx: &RouteCtx) -> RouteTable {
    let mut t = RouteTable::new();
    copsd::routes::register(&mut t, ctx);
    t
}

#[test]
fn b2a_routes_registered_read_only_with_python_action() {
    let env = TestEnv::new().unwrap();
    let t = table(&ctx(&env, private(&env)));
    let term: Vec<_> = t
        .routes()
        .filter(|(_, p)| p.starts_with("/api/term/"))
        .collect();
    assert_eq!(
        term,
        vec![("GET", "/api/term/history"), ("GET", "/api/term/output")],
        "`/api/term/` altında yalnız iki okuma ucu (force_proxy öneki yazan uca dokunmaz: yazan uç tabloda yok)"
    );
    for (_, p) in term {
        assert_eq!(cops_auth::authz::action_for("GET", p), "term.read");
    }
    // yazan uçlar Python'un eylemleriyle; tabloda değiller
    for w in [
        "/api/term/input",
        "/api/term/key",
        "/api/term/raw",
        "/api/term/resize",
    ] {
        assert_eq!(cops_auth::authz::action_for("POST", w), "term.write");
        assert!(!t.routes().any(|(_, p)| p == w));
    }
}

#[test]
fn live_socket_is_pythons() {
    let env = TestEnv::new().unwrap();
    let c = RouteCtx::new(
        env.dir().root().to_path_buf(),
        env.dir().db(),
        env.dir().instances_json(),
    );
    let py = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../py/claudeops/tmux_backend.py"),
    )
    .unwrap();
    assert!(py.contains("\nTMUX_SOCKET = \"cops\"\n"));
    assert_eq!(c.tmux.socket(), "cops");
}

#[test]
fn without_home_term_stays_in_python() {
    let env = TestEnv::new().unwrap();
    let mut c = ctx(&env, private(&env));
    c.env.home = None;
    assert!(!table(&c).routes().any(|(_, p)| p.starts_with("/api/term/")));
}

/// Sahte Python: istek başını `UPSTREAM` ile cevaplar.
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
                let out =
                    b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nUPSTREAM";
                let _ = c.write_all(out).await;
            });
        }
    });
    addr
}

async fn get(addr: SocketAddr, path: &str, extra: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Cops-Parity: 1\r\n{extra}Connection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(30), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).into_owned()
}

fn served(r: &str) -> &str {
    let l = r.to_ascii_lowercase();
    if l.contains("x-cops-served: local") {
        "local"
    } else if l.contains("x-cops-served: python") {
        "python"
    } else {
        "?"
    }
}

#[tokio::test]
async fn local_pane_in_rust_remote_and_signed_in_python() {
    let env = TestEnv::new().unwrap();
    std::fs::write(env.dir().root().join("web.token"), TOKEN).unwrap();
    let srv = Srv::new();
    let name = format!(
        "qqcopsd{}",
        "abcdefghij"
            .chars()
            .nth(std::process::id() as usize % 10)
            .unwrap()
    );
    let cmd = format!(
        "exec -a claude python3 -I -c 'import time; print(\"b2a-icerik\", flush=True); time.sleep(600)' --remote-control {name}"
    );
    srv.raw(&[
        "new-session",
        "-d",
        "-s",
        &name,
        "-x",
        "90",
        "-y",
        "20",
        &cmd,
    ]);
    let deadline = Instant::now() + Duration::from_secs(15);
    while !srv
        .raw(&["capture-pane", "-p", "-t", &format!("={name}:")])
        .contains("b2a-icerik")
    {
        assert!(Instant::now() < deadline, "pane hazır değil");
        std::thread::sleep(Duration::from_millis(30));
    }
    let t = table(&ctx(&env, srv.tmux()));
    let px = Proxy::new(upstream().await).with_route_table(t, cops_auth::Token::new(TOKEN));
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    let server = tokio::spawn(cops_proxy::serve_on(ln, px));

    let r = get(
        addr,
        &format!("/api/term/output?name={name}&lite=1&lang=en"),
        "",
    )
    .await;
    assert_eq!(served(&r), "local", "{r}");
    assert!(
        r.contains("\"ok\": true") && r.contains("b2a-icerik") && r.contains("\"lite\": true"),
        "{r}"
    );
    let r = get(
        addr,
        &format!("/api/term/history?name={name}&start=0&end=1"),
        "",
    )
    .await;
    assert_eq!(served(&r), "local", "{r}");
    assert!(
        r.contains("\"ok\": true") && r.contains("\"start\": 0"),
        "{r}"
    );
    let r = get(addr, "/api/term/output?lang=en", "").await;
    assert!(
        r.starts_with("HTTP/1.1 400") && served(&r) == "local",
        "{r}"
    );
    let r = get(
        addr,
        &format!("/api/term/history?name={name}&start=x&end=1"),
        "",
    )
    .await;
    assert!(
        r.starts_with("HTTP/1.1 400") && r.contains("invalid_range"),
        "{r}"
    );
    for (path, extra) in [
        (format!("/api/term/output?name={name}&host=yuhem"), ""),
        (
            format!("/api/term/history?name={name}&start=0&end=1&host=uzak"),
            "",
        ),
        (
            format!("/api/term/output?name={name}"),
            "X-Cops-Fwd-Sig: v1.x\r\n",
        ),
        (format!("/api/term/output?name={name}"), "x-cops-fwd: 1\r\n"),
    ] {
        let r = get(addr, &path, extra).await;
        assert_eq!(served(&r), "python", "{path} {extra}: {r}");
        assert!(r.ends_with("UPSTREAM"), "{r}");
    }
    server.abort();
}
