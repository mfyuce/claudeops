//! İkili düzeyinde `front_force_proxy` + SIGHUP + `/api/front/stats`: yerel uç (statik dosya) Python'a geri verilir ve geri
//! alınır; süreç SIGHUP'ta ölmez. Her şey geçici dizinde, boş portlarda; canlı durum dizinine dokunulmaz.
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
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

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
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

/// Koşul sağlanana dek (en çok 10 sn) tekrarlar.
fn until(what: &str, f: impl Fn() -> bool) {
    let t = Instant::now();
    while !f() {
        assert!(t.elapsed() < Duration::from_secs(10), "{what}");
        std::thread::sleep(Duration::from_millis(30));
    }
}

#[test]
fn sighup_reloads_force_proxy_and_stats_count_it() {
    let dir = TmpDir(std::env::temp_dir().join(format!("copsd-force-{}", std::process::id())));
    let _ = std::fs::remove_dir_all(&dir.0);
    std::fs::create_dir_all(dir.0.join("dist/assets")).unwrap();
    std::fs::write(dir.0.join("dist/assets/a.js"), "YEREL").unwrap();
    let tok = dir.0.join("web.token");
    std::fs::write(&tok, "tok-NOT-REAL\n").unwrap();
    std::fs::set_permissions(&tok, std::fs::Permissions::from_mode(0o600)).unwrap();

    let port = free_port();
    let up = free_port(); // kapalı: aktarılan istek 502
    let child = Command::new(env!("CARGO_BIN_EXE_copsd"))
        .args([
            "--listen",
            &format!("127.0.0.1:{port}"),
            "--upstream",
            &format!("127.0.0.1:{up}"),
        ])
        .arg("--state-dir")
        .arg(&dir.0)
        .arg("--dist")
        .arg(dir.0.join("dist"))
        .env("HOME", &dir.0)
        .env_remove("CLAUDEOPS_DIR")
        .env_remove("CLAUDEOPS_FRONT_SECRET")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut p = Proc(child);
    until("copsd açılmadı", || {
        TcpStream::connect(("127.0.0.1", port)).is_ok()
    });
    let asset = || get(port, "/assets/a.js", "X-Cops-Parity: 1\r\n");
    let hup = |pid: u32| {
        assert!(Command::new("kill")
            .args(["-HUP", &pid.to_string()])
            .status()
            .unwrap()
            .success());
    };

    let r = asset();
    assert!(
        r.contains("YEREL") && r.contains("x-cops-served: local"),
        "{r}"
    );

    // Dosya yazıldı ama sinyal yok: liste değişmez.
    let list = dir.0.join("front_force_proxy");
    std::fs::write(&list, "# geri al\nassets/\n").unwrap();
    assert!(asset().contains("YEREL"));
    hup(p.0.id());
    until("force_proxy uygulanmadı", || {
        asset().starts_with("HTTP/1.1 502")
    });
    assert!(asset().contains("x-cops-served: python"));

    // Dosya silinip tekrar sinyal: yerel uç geri gelir.
    std::fs::remove_file(&list).unwrap();
    hup(p.0.id());
    until("force_proxy geri alınmadı", || asset().contains("YEREL"));
    assert!(
        p.0.try_wait().unwrap().is_none(),
        "SIGHUP süreci öldürmemeli"
    );

    assert!(get(port, "/api/front/stats", "").starts_with("HTTP/1.1 401"));
    let r = get(
        port,
        "/api/front/stats",
        "Authorization: Bearer tok-NOT-REAL\r\n",
    );
    let body: serde_json::Value =
        serde_json::from_str(r.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let row = body["endpoints"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["path"] == "/assets/*")
        .unwrap();
    assert!(row["local"].as_u64().unwrap() >= 2, "{row}");
    assert!(row["forced"].as_u64().unwrap() >= 2, "{row}");
    assert_eq!(row["forced"], row["upstream_error"], "{row}");
}
