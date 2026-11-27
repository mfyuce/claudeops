//! Gerçek X gönderimi (`send_startup_x11`) YALNIZ bu testin açtığı özel bir `Xvfb` sunucusunda: Rust ve Python aynı
//! iletiyi gönderir, ayrı bir dinleyici (kök pencerede yalnız `PropertyChangeMask`) ikisinin olaylarını karşılaştırır.
//! Çağıranın `DISPLAY`i hiç okunmaz. `Xvfb` yoksa test atlanır (stderr'e yazar). Pencere yöneticisinin (Mutter) iletiye
//! göre pencereyi taşıması burada SINANAMAZ.

use cops_providers::real::startup_desktop::X11Desktop;
use cops_providers::real::Env;
use cops_providers::startup_desktop::{build_message, chunks, DesktopIo};
use serde_json::Value;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, ChildStdout, Command, Stdio};
use std::time::Duration;

const XVFB: &str = "/usr/bin/Xvfb";

/// Bu testin kendi `Xvfb` çocuğu; düşünce `SIGTERM` (kilit ve soket dosyaları silinsin) ve toplama.
struct Server {
    child: Child,
    display: String,
    /// `-displayfd` borusu sunucu yaşadıkça açık kalır.
    _stdout: Option<BufReader<ChildStdout>>,
}

impl Drop for Server {
    fn drop(&mut self) {
        // SAFETY: yalnız bu testin başlattığı, henüz toplanmamış çocuğun kimliği.
        unsafe { libc::kill(self.child.id() as libc::pid_t, libc::SIGTERM) };
        let _ = self.child.wait();
    }
}

/// Boş, yüksek numaralı bir ekran (canlı oturumların `:0`/`:1` yoklamalarından uzak).
fn start_server() -> Server {
    let base = 600 + std::process::id() % 300;
    for n in base..base + 20 {
        let lock = format!("/tmp/.X{n}-lock");
        let socket = format!("/tmp/.X11-unix/X{n}");
        if Path::new(&lock).exists() || Path::new(&socket).exists() {
            continue;
        }
        let mut child = Command::new(XVFB)
            .args([&format!(":{n}"), "-nolisten", "tcp", "-noreset"])
            .args(["-screen", "0", "64x64x8", "-displayfd", "1"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        // `-displayfd`: hazır olunca KENDİ sunucumuz numarasını yazar; açılamazsa boru satırsız kapanır.
        let stdout = child.stdout.take().unwrap();
        let server = Server {
            child,
            display: format!(":{n}"),
            _stdout: None,
        };
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            let _ = reader.read_line(&mut line);
            let _ = tx.send((line, reader));
        });
        if let Ok((line, reader)) = rx.recv_timeout(Duration::from_secs(10)) {
            if line.trim() == n.to_string() {
                let mut server = server;
                server._stdout = Some(reader);
                return server;
            }
        }
    }
    panic!("Xvfb açılamadı");
}

fn probe(home: &str, args: &[&str]) -> Command {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let mut c = Command::new("/usr/bin/python3");
    c.arg(format!("{manifest}/tests/x11/probe.py"))
        .args(args)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", home)
        .env("CLAUDEOPS_DIR", home)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("COPS_PY", format!("{manifest}/../../../py"))
        .stdout(Stdio::piped());
    c
}

/// `send` sırasında dinleyicinin gördüğü olaylar. Dinleyici en çok 10 sn bekler.
fn received(home: &str, display: &str, want: usize, send: impl FnOnce()) -> Vec<Value> {
    let mut child = probe(home, &["listen", display, &want.to_string()])
        .spawn()
        .unwrap();
    let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
    assert_eq!(lines.next().unwrap().unwrap(), "ready");
    send();
    let out = lines.next().unwrap().unwrap();
    assert!(child.wait().unwrap().success());
    serde_json::from_str(&out).unwrap()
}

/// Gönderen pencere her bağlantıda farklıdır: bir iletinin tüm parçalarında aynı ve sıfır değil olduğu denetlenip atılır.
fn without_window(mut events: Vec<Value>) -> Vec<Value> {
    let windows: Vec<u64> = events
        .iter()
        .map(|e| e["window"].as_u64().unwrap())
        .collect();
    assert!(
        windows.iter().all(|w| *w != 0 && *w == windows[0]),
        "{windows:?}"
    );
    for e in &mut events {
        e.as_object_mut().unwrap().remove("window");
    }
    events
}

#[test]
fn startup_message_reaches_a_private_x_server_like_python() {
    if !Path::new(XVFB).exists() {
        eprintln!("ATLANDI: {XVFB} yok, gerçek X gönderimi sınanmadı");
        return;
    }
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().to_string_lossy().into_owned();
    let server = start_server();
    let msg = build_message("claudeops-1-2_TIME2", "proje \"ç\" \\ 1", 1);
    let parts = chunks(&msg);
    assert!(parts.len() > 2);
    let io = X11Desktop::new(Env::fixed([("PATH", "/usr/bin:/bin")]));

    let rust = received(&home, &server.display, parts.len(), || {
        assert_eq!(io.send(&server.display, &msg), Ok(true));
    });
    let hex: String = msg.iter().map(|b| format!("{b:02x}")).collect();
    let python = received(&home, &server.display, parts.len(), || {
        let out = probe(&home, &["send", &server.display, &hex])
            .output()
            .unwrap();
        assert_eq!(out.stdout, b"true\n");
    });

    let rust = without_window(rust);
    assert_eq!(rust, without_window(python));
    assert_eq!(rust.len(), parts.len());
    for (i, (event, part)) in rust.iter().zip(&parts).enumerate() {
        let atom = if i == 0 {
            "_NET_STARTUP_INFO_BEGIN"
        } else {
            "_NET_STARTUP_INFO"
        };
        assert_eq!(event["atom"], atom);
        assert_eq!(event["format"], 8);
        assert_eq!(event["send_event"], 1);
        let data: String = part.iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(event["data"], data.as_str());
    }
}
