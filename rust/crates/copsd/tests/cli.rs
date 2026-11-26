//! İkili düzeyi: `--help`/`--version` yan etkisiz, varsayılan üst port Python `cops front` ile aynı, ön kapı gizlisinin açılış
//! (gevşek/bozuk dosyada çıkış 2) ve çalışma (değişince yeniden okuma, bozulunca kapalı yön) davranışı, `/api/front/stats`
//! sürümü. Her şey geçici `$HOME`, geçici durum dizini ve boş portlarda; canlı dizine ve portlara dokunulmaz.
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

struct Proc(Child);

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct TmpDir(PathBuf);

impl Drop for TmpDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn tmp(tag: &str) -> TmpDir {
    let p = std::env::temp_dir().join(format!("copsd-cli-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&p);
    std::fs::create_dir_all(&p).unwrap();
    TmpDir(p)
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

fn put(p: &Path, b: &[u8], mode: u32) {
    let _ = std::fs::remove_file(p);
    std::fs::write(p, b).unwrap();
    std::fs::set_permissions(p, std::fs::Permissions::from_mode(mode)).unwrap();
}

fn copsd(home: &Path) -> Command {
    let mut c = Command::new(env!("CARGO_BIN_EXE_copsd"));
    c.env("HOME", home)
        .env_remove("CLAUDEOPS_DIR")
        .env_remove("CLAUDEOPS_FRONT_SECRET")
        .env_remove("COPSD_LISTEN")
        .env_remove("COPSD_UPSTREAM");
    c
}

/// Süreç `limit` içinde biterse çıkış kodu.
fn wait_exit(c: &mut Child, limit: Duration) -> Option<i32> {
    let t = Instant::now();
    while t.elapsed() < limit {
        if let Some(st) = c.try_wait().unwrap() {
            return st.code();
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    None
}

/// Her bağlantıda aldığı başlıkları gövde olarak döner (Python iç portu yerine).
fn echo_upstream() -> u16 {
    let ln = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = ln.local_addr().unwrap().port();
    std::thread::spawn(move || {
        for c in ln.incoming() {
            let Ok(mut c) = c else { return };
            std::thread::spawn(move || {
                let _ = c.set_read_timeout(Some(Duration::from_secs(5)));
                let mut buf = Vec::new();
                let mut tmp = [0u8; 4096];
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                    match c.read(&mut tmp) {
                        Ok(0) | Err(_) => return,
                        Ok(n) => buf.extend_from_slice(&tmp[..n]),
                    }
                }
                let body = String::from_utf8_lossy(&buf).replace("\r\n", "|");
                let _ = write!(
                    c,
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
            });
        }
    });
    port
}

fn get(port: u16, path: &str, extra: &str) -> String {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    write!(
        s,
        "GET {path} HTTP/1.1\r\nHost: x\r\n{extra}Connection: close\r\n\r\n"
    )
    .unwrap();
    let mut buf = String::new();
    let _ = s.read_to_string(&mut buf);
    buf
}

fn spawn(home: &Path, state: &Path, secret: &Path, up: u16) -> (Proc, u16) {
    let port = free_port();
    let mut c = copsd(home);
    c.args([
        "--listen",
        &format!("127.0.0.1:{port}"),
        "--upstream",
        &format!("127.0.0.1:{up}"),
        "--state-dir",
        state.to_str().unwrap(),
        "--secret-file",
        secret.to_str().unwrap(),
    ])
    .stdout(Stdio::null())
    .stderr(Stdio::null());
    let mut p = Proc(c.spawn().unwrap());
    let t = Instant::now();
    while TcpStream::connect(("127.0.0.1", port)).is_err() {
        assert!(p.0.try_wait().unwrap().is_none(), "copsd erken çıktı");
        assert!(t.elapsed() < Duration::from_secs(10), "copsd açılmadı");
        std::thread::sleep(Duration::from_millis(20));
    }
    (p, port)
}

/// Ders 2.3 (`812942e`): `--help` ve `--version` hiçbir dosya yaratmaz/okumaz, port açmaz, hemen çıkar.
#[test]
fn help_and_version_have_no_side_effects() {
    let home = tmp("help");
    let port = free_port();
    for flag in ["--help", "-h", "--version", "-V"] {
        let out = copsd(&home.0)
            .args([flag, "--listen", &format!("127.0.0.1:{port}")])
            .output()
            .unwrap();
        assert!(out.status.success(), "{flag}");
        let s = String::from_utf8_lossy(&out.stdout);
        if flag.contains('h') {
            assert!(s.contains("--upstream ADRES (127.0.0.1:28765)"), "{s}");
            assert!(s.contains("--version"), "{s}");
        } else {
            assert_eq!(s.trim(), format!("copsd {}", copsd::GIT_SHA));
        }
        assert!(
            TcpStream::connect(("127.0.0.1", port)).is_err(),
            "{flag}: port açıldı"
        );
    }
    assert_eq!(
        std::fs::read_dir(&home.0).unwrap().count(),
        0,
        "$HOME'a yazıldı"
    );
    assert!(!copsd::GIT_SHA.is_empty());
}

/// İş 1: `--upstream` verilmezse Python `cops front` `DEFAULT_INTERNAL` (28765). Ağ kullanılmaz: kaynak karşılaştırılır.
#[test]
fn default_upstream_matches_python_front_cmd() {
    let py =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../py/claudeops/commands/front_cmd.py");
    let src = std::fs::read_to_string(py).unwrap();
    let line = src
        .lines()
        .find(|l| l.starts_with("DEFAULT_INTERNAL = "))
        .unwrap();
    assert_eq!(
        line,
        format!("DEFAULT_INTERNAL = \"{}\"", copsd::DEFAULT_UPSTREAM)
    );
    let src =
        std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("src/main.rs")).unwrap();
    assert!(src.contains(&format!("--upstream ADRES ({})", copsd::DEFAULT_UPSTREAM)));
}

/// İş 2 (açılış): gizli dosyası var ama kullanılamıyorsa copsd çıkış 2 ile durur (Python yok sayar; Rust daha sıkı). Ortam
/// değişkeni doluysa dosyaya bakılmaz (Python önceliği). Dosya yoksa açılır.
#[test]
fn startup_refuses_unusable_secret_file() {
    let home = tmp("start");
    let state = tmp("start-state");
    let sec = state.0.join("front.secret");
    for (bytes, mode, env, want_exit) in [
        (&b"gizli\n"[..], 0o644, None, Some(2)),
        (&b"\xff\xfe\n"[..], 0o600, None, Some(2)),
        (&b"gizli\n"[..], 0o644, Some("ortam"), None),
    ] {
        put(&sec, bytes, mode);
        let port = free_port();
        let mut c = copsd(&home.0);
        c.args([
            "--listen",
            &format!("127.0.0.1:{port}"),
            "--upstream",
            &format!("127.0.0.1:{}", free_port()),
            "--state-dir",
            state.0.to_str().unwrap(),
            "--secret-file",
            sec.to_str().unwrap(),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
        if let Some(e) = env {
            c.env("CLAUDEOPS_FRONT_SECRET", e);
        }
        let mut p = Proc(c.spawn().unwrap());
        assert_eq!(
            wait_exit(&mut p.0, Duration::from_secs(3)),
            want_exit,
            "{mode:o} {env:?}"
        );
    }
    std::fs::remove_file(&sec).unwrap();
    let (_p, port) = spawn(&home.0, &state.0, &sec, echo_upstream());
    assert!(get(port, "/api/x", "").starts_with("HTTP/1.1 200"));
    // `--secret-file` yoksa varsayılan yol durum dizinidir (Python `front.secret_path`): `--state-dir` ve `CLAUDEOPS_DIR` izlenir,
    // `$HOME/.claude/claudeops/front.secret` durum dizini başkayken okunmaz.
    let hd = home.0.join(".claude/claudeops");
    std::fs::create_dir_all(&hd).unwrap();
    put(&hd.join("front.secret"), b"gizli\n", 0o644);
    put(&sec, b"gizli\n", 0o644);
    for by_env in [false, true] {
        let mut c = copsd(&home.0);
        c.args([
            "--listen",
            &format!("127.0.0.1:{}", free_port()),
            "--upstream",
            &format!("127.0.0.1:{}", free_port()),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
        if by_env {
            c.env("CLAUDEOPS_DIR", &state.0);
        } else {
            c.arg("--state-dir").arg(&state.0);
        }
        let mut p = Proc(c.spawn().unwrap());
        assert_eq!(
            wait_exit(&mut p.0, Duration::from_secs(3)),
            Some(2),
            "durum dizinindeki gizli okunmadı (env={by_env})"
        );
    }
    std::fs::remove_file(&sec).unwrap();
    let mut c = copsd(&home.0);
    let port = free_port();
    c.args([
        "--listen",
        &format!("127.0.0.1:{port}"),
        "--upstream",
        &format!("127.0.0.1:{}", free_port()),
        "--state-dir",
        state.0.to_str().unwrap(),
    ])
    .stdout(Stdio::null())
    .stderr(Stdio::null());
    let mut p = Proc(c.spawn().unwrap());
    assert_eq!(
        wait_exit(&mut p.0, Duration::from_secs(1)),
        None,
        "$HOME altındaki gizli okunmamalı"
    );
}

/// İş 2 (çalışma): dosya değişince yeni değer aktarılır ve `X-Cops-Front` denetimi onu kullanır; gevşerse ya da silinirse
/// süreç ÇIKMAZ, gizli YOK sayılır (kapalı yön); sonradan oluşan dosya okunur. `/api/front/stats` sürümü = `--version`.
#[test]
fn runtime_secret_changes_apply_without_restart() {
    let home = tmp("run");
    let state = tmp("run-state");
    let sec = state.0.join("front.secret");
    put(&state.0.join("web.token"), b"tok-NOT-REAL\n", 0o600);
    let (mut p, port) = spawn(&home.0, &state.0, &sec, echo_upstream());
    let fwd = || get(port, "/api/x", "X-Cops-Front: sahte\r\n").to_ascii_lowercase();
    let stats = |v: &str| get(port, "/api/front/stats", &format!("X-Cops-Front: {v}\r\n"));
    assert!(
        !fwd().contains("x-cops-front"),
        "gizli yokken başlık eklenmez"
    );
    put(&sec, b"bir\n", 0o600);
    assert!(fwd().contains("x-cops-front: bir|"));
    assert!(stats("bir").starts_with("HTTP/1.1 200"));
    put(&sec, b"ikinci\n", 0o600);
    assert!(fwd().contains("x-cops-front: ikinci|"));
    assert!(stats("bir").starts_with("HTTP/1.1 401"));
    put(&sec, b"ikinci\n", 0o644);
    assert!(!fwd().contains("x-cops-front"));
    assert!(stats("ikinci").starts_with("HTTP/1.1 401"));
    std::fs::remove_file(&sec).unwrap();
    assert!(!fwd().contains("x-cops-front"));
    assert!(
        p.0.try_wait().unwrap().is_none(),
        "çalışırken bozulan gizli süreci durdurmaz"
    );
    let r = get(
        port,
        "/api/front/stats",
        "Authorization: Bearer tok-NOT-REAL\r\n",
    );
    let v: serde_json::Value = serde_json::from_str(r.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(v["version"], copsd::GIT_SHA);
}

/// Ders 2.3 (`733373f`, `fe1c5fd`): çekirdek rota tablosuna kayıtlı her uç, yetki eylem tablosunda (`cops_auth::authz`,
/// Python `_ACTION_TABLE` eşi) eşlenmiş olmalı (`admin.unmapped` değil). Tablo bugün boş; kayıt eklenince bu test denetler.
#[test]
fn registered_routes_have_authz_actions() {
    let mut t = cops_proxy::routes::RouteTable::new();
    copsd::routes::register(
        &mut t,
        &copsd::routes::RouteCtx {
            state_dir: "/nonexistent".into(),
            db: "/nonexistent/claudeops.db".into(),
            instances: "/nonexistent/instances.json".into(),
        },
    );
    for (method, pattern) in t.routes() {
        let path = pattern.replace('*', "x");
        assert_ne!(
            cops_auth::authz::action_for(method, &path),
            cops_auth::authz::UNMAPPED,
            "{method} {pattern}"
        );
    }
}
