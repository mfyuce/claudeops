//! Testlerin tmux sunucusu: geçici `TMUX_TMPDIR` + rastgele soket + `-f /dev/null`. Kullanıcının sunucusuna ve
//! `-L cops` soketine DOKUNMAZ.

// Her test ikilisi yardımcıların yalnız bir kısmını kullanır.
#![allow(dead_code)]

use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use cops_tmux::Tmux;
use tempfile::TempDir;

pub struct Server {
    pub tmux: Tmux,
    pub dir: TempDir,
}

impl Server {
    pub fn new() -> Self {
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .subsec_nanos();
        let socket = format!(
            "cxrs{nanos}-{}-{}",
            SEQ.fetch_add(1, Ordering::Relaxed),
            std::process::id()
        );
        let dir = tempfile::tempdir().unwrap();
        let tmux = Tmux::with_socket(socket).tmpdir(dir.path());
        Self { tmux, dir }
    }

    pub fn path(&self) -> &Path {
        self.dir.path()
    }

    /// Crate'ten bağımsız ham tmux çağrısı (kurulum ve doğrulama için).
    pub fn raw(&self, args: &[&str]) -> String {
        let out = Command::new("tmux")
            .args(["-u", "-L", self.tmux.socket(), "-f", "/dev/null"])
            .args(args)
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "tmux {args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        String::from_utf8(out.stdout).unwrap()
    }

    pub fn spawn(&self, name: &str, command: &str) {
        let cwd = self.path().to_str().unwrap();
        self.raw(&[
            "new-session",
            "-d",
            "-s",
            name,
            "-x",
            "80",
            "-y",
            "24",
            "-c",
            cwd,
            command,
        ]);
    }

    /// `setup` çalıştıktan SONRA `READY` basan pane.
    pub fn spawn_ready(&self, name: &str, setup: &str, then: &str) {
        self.spawn(name, &format!("{setup}; echo READY; {then}"));
        self.wait_screen(name, "READY");
    }

    pub fn screen(&self, name: &str) -> String {
        self.raw(&["capture-pane", "-p", "-t", &format!("={name}:")])
    }

    pub fn wait_screen(&self, name: &str, needle: &str) {
        wait_until(|| self.screen(name).contains(needle), needle);
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", self.tmux.socket(), "kill-server"])
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output();
    }
}

pub fn wait_until(mut done: impl FnMut() -> bool, what: &str) {
    let deadline = Instant::now() + Duration::from_secs(10);
    while !done() {
        assert!(Instant::now() < deadline, "beklenen durum oluşmadı: {what}");
        thread::sleep(Duration::from_millis(20));
    }
}

/// Dosya en az `len` bayt olana dek bekler, sonra kısa bir süre daha (fazlalık da görülsün).
pub fn read_at_least(path: &Path, len: usize) -> Vec<u8> {
    wait_until(
        || std::fs::metadata(path).is_ok_and(|m| m.len() >= len as u64),
        "dosya boyutu",
    );
    thread::sleep(Duration::from_millis(100));
    std::fs::read(path).unwrap()
}
