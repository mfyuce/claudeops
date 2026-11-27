//! B1 (`cops-ep-state`): copsd `register` iki salt okuma ucunu kaydeder; yetki eylemleri Python tablosuyla aynı
//! (`fleet.admin`, `admin.config`); `--instances` durum dizini dışındaysa `/api/instances` kaydedilmez; copsd'nin GERÇEK
//! kurulumuyla (`RouteCtx::new`, `db` kipi, yan dosyasız WAL DB) cevaplanan istekler durum ve ev dizinine HİÇBİR şey yazmaz.
//! Karşılaştırma: aynı durumda ham `StateDocs` okuması DB'ye içe aktarır (senaryo gerçekten yazım tetikleyen bir okuma).
use cops_proxy::routes::RouteTable;
use cops_proxy::Proxy;
use cops_state::instances::Instances;
use cops_state::{StateDocs, TestEnv};
use copsd::routes::RouteCtx;
use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::path::Path;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "b1-tok-NOT-REAL";

fn snapshot(root: &Path) -> BTreeMap<String, (Vec<u8>, u32)> {
    use std::os::unix::fs::PermissionsExt;
    let mut out = BTreeMap::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            let m = std::fs::symlink_metadata(&p).unwrap();
            let key = p.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            if m.is_dir() {
                out.insert(key, (b"<dizin>".to_vec(), m.permissions().mode()));
                stack.push(p);
            } else {
                out.insert(key, (std::fs::read(&p).unwrap(), m.permissions().mode()));
            }
        }
    }
    out
}

fn ctx(env: &TestEnv) -> RouteCtx {
    let mut ctx = RouteCtx::new(
        env.dir().root().to_path_buf(),
        env.dir().db(),
        env.dir().instances_json(),
    );
    let home = env.root().join("home");
    std::fs::create_dir_all(&home).unwrap();
    ctx.env.home = Some(home.to_string_lossy().into_owned());
    // B2a terminal uçları bu testte çağrılmaz; yine de canlı `cops` soketi değil, var olmayan özel soket
    ctx.tmux =
        cops_tmux::Tmux::with_socket(format!("cxb1-{}", std::process::id())).tmpdir(env.root());
    ctx
}

fn table(ctx: &RouteCtx) -> RouteTable {
    let mut t = RouteTable::new();
    copsd::routes::register(&mut t, ctx);
    t
}

#[test]
fn b1_routes_registered_with_python_actions() {
    let env = TestEnv::new().unwrap();
    let t = table(&ctx(&env));
    let routes: Vec<_> = t.routes().collect();
    assert!(routes.contains(&("GET", "/api/instances")), "{routes:?}");
    assert!(routes.contains(&("GET", "/api/diag/log")), "{routes:?}");
    assert_eq!(
        cops_auth::authz::action_for("GET", "/api/instances"),
        "fleet.admin"
    );
    assert_eq!(
        cops_auth::authz::action_for("GET", "/api/diag/log"),
        "admin.config"
    );
}

#[test]
fn foreign_instances_path_is_left_to_python() {
    let env = TestEnv::new().unwrap();
    let mut c = ctx(&env);
    c.instances = env.root().join("baska/instances.json");
    let routes: Vec<_> = table(&c).routes().collect();
    assert!(!routes.contains(&("GET", "/api/instances")), "{routes:?}");
    assert!(routes.contains(&("GET", "/api/diag/log")), "{routes:?}");
}

async fn get(addr: SocketAddr, path: &str) -> String {
    let mut s = TcpStream::connect(addr).await.unwrap();
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\nX-Cops-Parity: 1\r\nConnection: close\r\n\r\n"
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(30), s.read_to_end(&mut out)).await;
    String::from_utf8_lossy(&out).into_owned()
}

/// Python şemasının `docs` parçası, WAL kipinde ve KAPALI (yan dosya yok): salt okunur açılış yan dosya yaratsaydı görülürdü.
fn closed_wal_db(env: &TestEnv) {
    let c = rusqlite::Connection::open(env.dir().db()).unwrap();
    c.query_row("PRAGMA journal_mode=WAL", [], |_| Ok(()))
        .unwrap();
    c.execute_batch(
        "CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT, version INTEGER, updated REAL);
         CREATE TABLE tsv_rows(file TEXT, line INTEGER, active INTEGER, cols TEXT);",
    )
    .unwrap();
    c.execute(
        "INSERT INTO docs VALUES('steward/projects', '{\"ncs\": {}}', 1, 1.0)",
        [],
    )
    .unwrap();
    c.pragma_update(None, "user_version", cops_state::store::SCHEMA_VERSION)
        .unwrap();
}

#[tokio::test]
async fn served_requests_write_nothing() {
    let env = TestEnv::new().unwrap();
    let st = env.dir().root().to_path_buf();
    std::fs::write(st.join("settings.json"), r#"{"store_backend": "db"}"#).unwrap();
    closed_wal_db(&env);
    std::fs::write(
        st.join("instances.json"),
        r#"{"version": 1, "instances": {"ncs20261127": {"created_at": 3}, "bozuk": {"created_at": 1}}}"#,
    )
    .unwrap();
    std::fs::create_dir_all(st.join("steward")).unwrap();
    std::fs::write(st.join("steward/projects.json"), r#"{"ncs": {}}"#).unwrap();
    std::fs::write(st.join("diag.log"), "{\"event\": \"x\"}\n").unwrap();
    let c = ctx(&env);
    let before = snapshot(env.root());

    let up = TcpListener::bind("127.0.0.1:0").await.unwrap(); // Python yok: Rust'a düşmeyen istek 502 olurdu
    let px = Proxy::new(up.local_addr().unwrap())
        .with_route_table(table(&c), cops_auth::Token::new(TOKEN));
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    tokio::spawn(cops_proxy::serve_on(ln, px));
    for _ in 0..3 {
        let r = get(addr, "/api/instances").await;
        assert!(r.to_lowercase().contains("x-cops-served: local"), "{r}");
        assert!(r.contains(r#""name": "ncs20261127""#), "{r}");
        assert!(
            r.contains("ncs20261127 (de\\u011fnek\\u00e7i: default)"),
            "db'deki proje listesi: {r}"
        );
        let r = get(addr, "/api/diag/log").await;
        assert!(r.ends_with(r#"{"lines": ["{\"event\": \"x\"}"]}"#), "{r}");
    }
    assert_eq!(
        snapshot(env.root()),
        before,
        "cevaplanan istekler dizine yazdı"
    );

    // karşılaştırma: aynı durumda ham (yazabilen) okuma `instances`i DB'ye içe aktarır ve yan dosya yaratır
    let raw = StateDocs::new(env.dir().clone()).with_logger(|_| {});
    assert_eq!(Instances::new(&raw).load().len(), 2);
    drop(raw);
    assert_ne!(
        snapshot(env.root()),
        before,
        "ham yol yazmadı: karşılaştırma boş"
    );
}
