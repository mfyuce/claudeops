//! R1-10: `--token-file` verilmezse `web.token` durum dizininden okunur (`--state-dir`, yoksa `CLAUDEOPS_DIR`, yoksa
//! `$HOME/.claude/claudeops`; Python `paths.CLAUDEOPS_DIR` ile aynı). Önceden yalnız `$HOME` kullanılıyordu: durum dizini farklıyken
//! Python bir token'ı, copsd başkasını kabul ediyordu. İkili kendi geçici dizini ve boş portuyla koşar, sonra öldürülür.
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
    let p = std::env::temp_dir().join(format!("copsd-statedir-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&p);
    std::fs::create_dir_all(&p).unwrap();
    TmpDir(p)
}

fn token(dir: &Path, v: &str) {
    let p = dir.join("web.token");
    std::fs::write(&p, v).unwrap();
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600)).unwrap();
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

/// `GET path` durum kodu; bağlanamazsa `None`.
fn status(port: u16, path: &str) -> Option<u16> {
    let mut s = TcpStream::connect(("127.0.0.1", port)).ok()?;
    s.set_read_timeout(Some(Duration::from_secs(5))).ok()?;
    write!(
        s,
        "GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
    )
    .ok()?;
    let mut buf = String::new();
    let _ = s.read_to_string(&mut buf);
    buf.split_whitespace().nth(1)?.parse().ok()
}

/// copsd'yi başlatır ve dinlemeye başlayana dek bekler. Seçilen port arada kapılıp süreç çıkarsa yeni portla dener.
fn spawn(home: &Path, env_dir: Option<&Path>, extra: &[&str]) -> (Proc, u16) {
    let mut last = String::new();
    for _ in 0..3 {
        match try_spawn(home, env_dir, extra, free_port()) {
            Ok(v) => return v,
            Err(e) => last = e,
        }
    }
    panic!("copsd açılmadı: {last}");
}

/// Süreç dinlemeden çıkarsa `Err` (çıkış durumu + stderr); yaşadığı hâlde açılmazsa panik.
fn try_spawn(
    home: &Path,
    env_dir: Option<&Path>,
    extra: &[&str],
    port: u16,
) -> Result<(Proc, u16), String> {
    let up = free_port(); // kapalı: vekillenen istek 502
    let mut c = Command::new(env!("CARGO_BIN_EXE_copsd"));
    c.args([
        "--listen",
        &format!("127.0.0.1:{port}"),
        "--upstream",
        &format!("127.0.0.1:{up}"),
    ])
    .args(extra)
    .env("HOME", home)
    .env_remove("CLAUDEOPS_DIR")
    .env_remove("CLAUDEOPS_FRONT_SECRET")
    .stdout(Stdio::null())
    .stderr(Stdio::piped());
    if let Some(d) = env_dir {
        c.env("CLAUDEOPS_DIR", d);
    }
    let mut p = Proc(c.spawn().unwrap());
    // stderr boru dolup süreci kilitlemesin: ayrı iş parçacığında okunur
    let mut pipe = p.0.stderr.take().unwrap();
    let err = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = pipe.read_to_string(&mut s);
        s
    });
    let t = Instant::now();
    loop {
        // bağlantıdan SONRA da canlılık: portu başkası kaptıysa bağlantı tutar ama copsd çıkar
        let up_now = TcpStream::connect(("127.0.0.1", port)).is_ok();
        if up_now {
            std::thread::sleep(Duration::from_millis(100));
        }
        if let Some(st) = p.0.try_wait().unwrap() {
            return Err(format!("{st}: {}", err.join().unwrap_or_default()));
        }
        if up_now {
            return Ok((p, port));
        }
        assert!(
            t.elapsed() < Duration::from_secs(60),
            "copsd 60 sn içinde dinlemedi"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
}

#[test]
fn token_file_defaults_to_state_dir() {
    let home = tmp("home");
    let state = tmp("state");
    let hd = home.0.join(".claude/claudeops");
    std::fs::create_dir_all(&hd).unwrap();
    token(&hd, "home-token-NOT-REAL\n");
    token(&state.0, "state-token-NOT-REAL\n");
    let names = |t: &str| format!("/api/metrics/names?token={t}");

    // CLAUDEOPS_DIR: yalnız oradaki token geçer ($HOME'daki değil)
    let (_p, port) = spawn(&home.0, Some(&state.0), &[]);
    assert_eq!(status(port, &names("state-token-NOT-REAL")), Some(200));
    assert_eq!(status(port, &names("home-token-NOT-REAL")), Some(401));
    drop(_p);

    // --state-dir CLAUDEOPS_DIR'den önce gelir
    let other = tmp("other");
    let (_p, port) = spawn(
        &home.0,
        Some(&other.0),
        &["--state-dir", state.0.to_str().unwrap()],
    );
    assert_eq!(status(port, &names("state-token-NOT-REAL")), Some(200));
    drop(_p);

    // ikisi de yoksa $HOME/.claude/claudeops (bugünkü davranış)
    let (_p, port) = spawn(&home.0, None, &[]);
    assert_eq!(status(port, &names("home-token-NOT-REAL")), Some(200));
    assert_eq!(status(port, &names("state-token-NOT-REAL")), Some(401));
    drop(_p);

    // açık --token-file her zaman kazanır
    let tf = hd.join("web.token");
    let (_p, port) = spawn(
        &home.0,
        Some(&state.0),
        &["--token-file", tf.to_str().unwrap()],
    );
    assert_eq!(status(port, &names("home-token-NOT-REAL")), Some(200));
}

/// Diğer varsayılan yollar da (DB, metrik deposu, mount tablosu) durum dizininden okunur; `$HOME` altında dosya yaratılmaz.
#[test]
fn other_default_paths_follow_the_state_dir() {
    let home = tmp("home2");
    let state = tmp("state2");
    token(&state.0, "state-token-NOT-REAL\n");
    std::fs::File::create(state.0.join("claudeops.db")).unwrap();
    std::fs::create_dir_all(state.0.join("derbent")).unwrap();
    let mounts = state.0.join("derbent/mounts.json");
    std::fs::write(&mounts, r#"[{"path":"/uyg/","upstream":"127.0.0.1:1"}]"#).unwrap();
    std::fs::set_permissions(&mounts, std::fs::Permissions::from_mode(0o600)).unwrap();

    let (_p, port) = spawn(&home.0, Some(&state.0), &[]);
    // mount yüklendi: kimliksiz istek copsd'de 401 (yüklenmese kapalı upstream'e gider, 502)
    assert_eq!(status(port, "/uyg/"), Some(401));
    // DB durum dizininde bulundu: yerel uç açık (kapalı olsa 502)
    assert_eq!(status(port, "/api/steward/questions?all=1"), Some(401));
    assert!(state.0.join("metrics.db").exists());
    assert!(!home.0.join(".claude").exists());
}

/// Dolu port: süreç çıkışı sebebiyle birlikte döner (`spawn` bu yolda yeni port dener).
#[test]
fn taken_port_is_reported_with_the_reason() {
    let home = tmp("home3");
    let hold = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = hold.local_addr().unwrap().port();
    let Err(e) = try_spawn(&home.0, None, &[], port) else {
        panic!("dolu portta açıldı sayıldı");
    };
    assert!(!e.is_empty());
    println!("{e}");
}
