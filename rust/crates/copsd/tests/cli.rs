//! İkili düzeyi: `--help`/`--version` yan etkisiz, varsayılan üst port Python `cops front` ile aynı, ön kapı gizlisinin açılış
//! (gevşek/bozuk dosyada uyarı, süreç sürer) ve çalışma (değişince yeniden okuma, bozulunca kapalı yön) davranışı, `/api/front/stats`
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

fn wait_listen(c: &mut Child, port: u16) {
    let t = Instant::now();
    while TcpStream::connect(("127.0.0.1", port)).is_err() {
        assert!(c.try_wait().unwrap().is_none(), "copsd erken çıktı");
        assert!(t.elapsed() < Duration::from_secs(10), "copsd açılmadı");
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Varsayılan gizli yoluyla (durum dizini), stderr dosyaya.
fn spawn_logged(home: &Path, state: &Path, up: u16, log: &Path) -> (Proc, u16) {
    let port = free_port();
    let mut c = copsd(home);
    c.args([
        "--listen",
        &format!("127.0.0.1:{port}"),
        "--upstream",
        &format!("127.0.0.1:{up}"),
    ])
    .arg("--state-dir")
    .arg(state)
    .stdout(Stdio::null())
    .stderr(std::fs::File::create(log).unwrap());
    let mut p = Proc(c.spawn().unwrap());
    wait_listen(&mut p.0, port);
    (p, port)
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
    wait_listen(&mut p.0, port);
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

/// Açılış: gizli dosyası var ama kullanılamıyorsa (0644, bozuk) copsd ÇIKMAZ; uyarı yazar, gizli YOK sayar, dosya düzelince
/// yeniden başlatmadan kullanır. Uyarı ve günlük gizli değerini taşımaz.
#[test]
fn startup_ignores_unusable_secret_file_and_warns() {
    let home = tmp("start");
    let state = tmp("start-state");
    let sec = state.0.join("front.secret");
    let up = echo_upstream();
    for (bytes, mode) in [(&b"sizmis-deger\n"[..], 0o644), (&b"\xff\xfe\n"[..], 0o600)] {
        put(&sec, bytes, mode);
        let log = state.0.join("err.log");
        let (mut p, port) = spawn_logged(&home.0, &state.0, up, &log);
        let r = get(port, "/api/x", "").to_ascii_lowercase();
        assert!(r.starts_with("http/1.1 200"), "{r}");
        assert!(!r.contains("x-cops-front"), "{r}");
        assert!(p.0.try_wait().unwrap().is_none(), "{mode:o}: copsd çıktı");
        let err = std::fs::read_to_string(&log).unwrap();
        assert!(
            err.contains("UYARI") && err.contains("front.secret"),
            "{err}"
        );
        assert!(!err.contains("sizmis-deger"), "{err}");
        put(&sec, b"duzeldi\n", 0o600);
        assert!(get(port, "/api/x", "")
            .to_ascii_lowercase()
            .contains("x-cops-front: duzeldi|"));
    }
}

/// `--secret-file` yoksa varsayılan yol durum dizinidir (Python `front.secret_path`): `--state-dir` ve `CLAUDEOPS_DIR` izlenir,
/// `$HOME/.claude/claudeops/front.secret` durum dizini başkayken okunmaz.
#[test]
fn default_secret_path_follows_state_dir() {
    let home = tmp("path");
    let state = tmp("path-state");
    let hd = home.0.join(".claude/claudeops");
    std::fs::create_dir_all(&hd).unwrap();
    put(&hd.join("front.secret"), b"ev\n", 0o600);
    let up = echo_upstream();
    for by_env in [false, true] {
        let port = free_port();
        let mut c = copsd(&home.0);
        c.args([
            "--listen",
            &format!("127.0.0.1:{port}"),
            "--upstream",
            &format!("127.0.0.1:{up}"),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
        if by_env {
            c.env("CLAUDEOPS_DIR", &state.0);
        } else {
            c.arg("--state-dir").arg(&state.0);
        }
        let _ = std::fs::remove_file(state.0.join("front.secret"));
        let mut p = Proc(c.spawn().unwrap());
        wait_listen(&mut p.0, port);
        let fwd = || get(port, "/api/x", "").to_ascii_lowercase();
        assert!(!fwd().contains("x-cops-front"), "$HOME gizlisi okunmamalı");
        put(&state.0.join("front.secret"), b"durum\n", 0o600);
        assert!(fwd().contains("x-cops-front: durum|"), "env={by_env}");
    }
}

/// Dosya tanıtıcısı tükenince (`EMFILE`) copsd çıkmaz; bağlantılar bırakılınca yeniden cevap verir.
#[test]
fn accept_errors_do_not_stop_the_server() {
    let home = tmp("emfile");
    let state = tmp("emfile-state");
    let up = echo_upstream();
    let port = free_port();
    let log = state.0.join("err.log");
    let base = copsd(&home.0);
    let mut c = Command::new("sh");
    c.args(["-c", "ulimit -n 40 && exec \"$0\" \"$@\""])
        .arg(base.get_program())
        .args([
            "--listen",
            &format!("127.0.0.1:{port}"),
            "--upstream",
            &format!("127.0.0.1:{up}"),
        ])
        .arg("--state-dir")
        .arg(&state.0)
        .env("HOME", &home.0)
        .env_remove("CLAUDEOPS_DIR")
        .env_remove("CLAUDEOPS_FRONT_SECRET")
        .stdout(Stdio::null())
        .stderr(std::fs::File::create(&log).unwrap());
    let mut p = Proc(c.spawn().unwrap());
    wait_listen(&mut p.0, port);
    let held: Vec<TcpStream> = (0..80)
        .filter_map(|_| TcpStream::connect(("127.0.0.1", port)).ok())
        .collect();
    let t = Instant::now();
    while !std::fs::read_to_string(&log)
        .unwrap()
        .contains("kabul edilemedi")
    {
        assert!(
            p.0.try_wait().unwrap().is_none(),
            "copsd kabul hatasında çıktı"
        );
        assert!(t.elapsed() < Duration::from_secs(10), "EMFILE oluşmadı");
        std::thread::sleep(Duration::from_millis(20));
    }
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        p.0.try_wait().unwrap().is_none(),
        "copsd kabul hatasında çıktı"
    );
    drop(held);
    let t = Instant::now();
    while !get(port, "/api/x", "").starts_with("HTTP/1.1 200") {
        assert!(t.elapsed() < Duration::from_secs(10), "copsd toparlanmadı");
        std::thread::sleep(Duration::from_millis(50));
    }
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
        &copsd::routes::RouteCtx::new(
            "/nonexistent".into(),
            "/nonexistent/claudeops.db".into(),
            "/nonexistent/instances.json".into(),
        ),
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
