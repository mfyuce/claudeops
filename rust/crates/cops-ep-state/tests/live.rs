//! "Çalışıyor mu" sütunu: sahte `/proc` ağacıyla (`cops_procscan::Config` kökleri geçici dizinde) süreç taraması ve kanca
//! uçtan uca (vekil + rota tablosu, sahte Python). Gerçek süreçlere ve durum dizinine dokunulmaz.
mod common;
use common::Env;
use cops_ep_state::{instances, DiagLogHook, InstancesHook, DIAG_LOG_PATH, INSTANCES_PATH};
use cops_procscan::Config;
use cops_proxy::routes::RouteTable;
use cops_proxy::Proxy;
use cops_state::{Backend, StateDocs};
use std::fs;
use std::net::SocketAddr;
use std::os::unix::fs::symlink;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const UID: u32 = 4242;
const TOKEN: &str = "b1-tok-NOT-REAL";

fn fake_proc(root: &Path) -> Config {
    for d in ["proc", "claude/sessions", "claude/projects"] {
        fs::create_dir_all(root.join(d)).unwrap();
    }
    fs::write(root.join("proc/stat"), "cpu 0\nbtime 1000000\n").unwrap();
    Config {
        proc_root: root.join("proc"),
        claude_dir: root.join("claude"),
        agy_cache: root.join("agy_cache.json"),
        agy_sids: root.join("agy_sids.json"),
        uid: UID,
        clk_tck: 100,
    }
}

fn add_proc(root: &Path, pid: u32, uid: u32, cmd: &[&str]) {
    let d = root.join("proc").join(pid.to_string());
    fs::create_dir_all(d.join("fd")).unwrap();
    fs::write(
        d.join("status"),
        format!("Name:\tx\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"),
    )
    .unwrap();
    fs::write(
        d.join("stat"),
        format!(
            "{pid} (x) S 1 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {} 0 0\n",
            pid * 10
        ),
    )
    .unwrap();
    fs::write(
        d.join("cmdline"),
        cmd.iter().map(|s| format!("{s}\0")).collect::<String>(),
    )
    .unwrap();
    fs::write(d.join("environ"), "").unwrap();
    symlink("/work/proj", d.join("cwd")).unwrap();
    symlink("/dev/pts/3", d.join("fd/0")).unwrap();
}

#[test]
fn running_comes_from_process_scan() {
    let e = Env::new();
    let cfg = fake_proc(&e.root.join("fake"));
    add_proc(
        &e.root.join("fake"),
        100,
        UID,
        &["claude", "--remote-control", "canli"],
    );
    add_proc(
        &e.root.join("fake"),
        101,
        UID + 1,
        &["claude", "--remote-control", "baskasinin"],
    );
    let live = instances::live_names(&cfg).unwrap();
    assert!(
        live.contains("canli") && !live.contains("baskasinin"),
        "{live:?}"
    );
    e.write(
        "instances.json",
        r#"{"version": 1, "instances": {"canli": {}, "baskasinin": {}}}"#,
    );
    let out =
        cops_ep_state::pyjson::dumps(&instances::payload(&e.ro(Backend::Files), &live).unwrap());
    assert!(out.contains(r#""name": "canli", "running": true"#), "{out}");
    assert!(
        out.contains(r#""name": "baskasinin", "running": false"#),
        "{out}"
    );
    // `/proc` listelenemiyor: Python'da istisna, burada hata (uç 500)
    let mut bad = cfg.clone();
    bad.proc_root = e.root.join("yok");
    assert!(matches!(
        instances::live_names(&bad),
        Err(instances::ListError::Scan(_))
    ));
}

/// Sahte Python: gövdesi `UPSTREAM`.
async fn upstream() -> SocketAddr {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(async move {
        while let Ok((mut c, _)) = ln.accept().await {
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
                let _ = c
                    .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nUPSTREAM")
                    .await;
            });
        }
    });
    addr
}

async fn get(addr: SocketAddr, path: &str, auth: bool) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    let a = if auth {
        format!("Authorization: Bearer {TOKEN}\r\n")
    } else {
        String::new()
    };
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: x\r\n{a}X-Cops-Parity: 1\r\nConnection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(20), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).into_owned()
}

fn body(resp: &str) -> &str {
    resp.split_once("\r\n\r\n").map_or("", |(_, b)| b)
}

/// Uçtan uca: yerel `host` Rust'ta (`x-cops-served: local`, Python gövdesi biçiminde), uzak `host` ve yöntem/yol dışı
/// istekler Python'a; kimliksiz istek 401; `HOME` yokken (`scan: None`) her istek Python'a.
#[tokio::test]
async fn hooks_through_the_proxy() {
    let e = Env::new();
    let cfg = fake_proc(&e.root.join("fake"));
    add_proc(
        &e.root.join("fake"),
        100,
        UID,
        &["claude", "--remote-control", "canli"],
    );
    e.write(
        "instances.json",
        r#"{"version": 1, "instances": {"canli": {"created_at": 1}}}"#,
    );
    e.write("diag.log", "{\"event\": \"ç\"}\n");
    let docs = Arc::new(e.ro(Backend::Files));
    let up = upstream().await;
    let serve = |scan: Option<Config>| {
        let mut t = RouteTable::new();
        t.get(
            INSTANCES_PATH,
            Arc::new(InstancesHook::new(docs.clone(), scan)),
        )
        .get(
            DIAG_LOG_PATH,
            Arc::new(DiagLogHook::new(e.state.join("diag.log"))),
        );
        let px = Proxy::new(up).with_route_table(t, cops_auth::Token::new(TOKEN));
        async move {
            let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let addr = ln.local_addr().unwrap();
            tokio::spawn(cops_proxy::serve_on(ln, px));
            addr
        }
    };
    let addr = serve(Some(cfg)).await;

    let r = get(addr, "/api/instances", true).await;
    assert!(r.to_lowercase().contains("x-cops-served: local"), "{r}");
    assert!(
        r.to_lowercase()
            .contains("content-type: application/json; charset=utf-8"),
        "{r}"
    );
    assert_eq!(
        body(&r),
        r#"{"ok": true, "instances": [{"created_at": 1, "name": "canli", "running": true, "host": "local"}]}"#
    );
    for local in [
        "/api/instances?host=local",
        "/api/instances?host=&lang=en",
        "/api/instances?host=%20",
    ] {
        assert!(
            get(addr, local, true).await.contains("\"running\": true"),
            "{local}"
        );
    }
    for remote in [
        "/api/instances?host=yuhem",
        "/api/instances?host=&host=ulak31",
        "/api/instances/forget",
    ] {
        let r = get(addr, remote, true).await;
        assert!(
            r.to_lowercase().contains("x-cops-served: python") && r.ends_with("UPSTREAM"),
            "{remote}: {r}"
        );
    }
    let r = get(addr, "/api/instances", false).await;
    assert!(r.starts_with("HTTP/1.1 401"), "{r}");
    let r = get(addr, "/api/diag/log?x=1", true).await;
    assert!(r.to_lowercase().contains("x-cops-served: local"), "{r}");
    assert_eq!(body(&r), r#"{"lines": ["{\"event\": \"\u00e7\"}"]}"#);

    let addr = serve(None).await;
    let r = get(addr, "/api/instances", true).await;
    assert!(
        r.to_lowercase().contains("x-cops-served: python"),
        "HOME yokken Python'a gitmeli: {r}"
    );
}

#[test]
#[should_panic(expected = "salt okuma")]
fn hook_refuses_a_writable_statedocs() {
    let e = Env::new();
    let _ = InstancesHook::new(
        Arc::new(StateDocs::isolated(e.dir(), Some(Backend::Files), "")),
        None,
    );
}
