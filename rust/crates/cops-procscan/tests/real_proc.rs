//! GERÇEK `/proc` ile: yalnız bu testin açtığı geçici süreçler (stdin borusu kapanınca kendiliğinden çıkar;
//! çıkmazsa `Child::kill` + `wait`, yalnız kendi çocuğumuz). Canlı durum dizinine dokunmaz (claude/agy yolları geçici).

use cops_procscan::mirrors::running_mirrors;
use cops_procscan::procfs::ProcFs;
use cops_procscan::{find_sessions, Config, CpuMode, Liveness};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use tempfile::TempDir;

/// Testin kendi çocuğu: düşerken stdin'i kapatır (çocuk ve torunları EOF ile çıkar), gerekirse öldürüp biçer.
struct Own(Option<Child>);

impl Own {
    fn spawn(cmd: &mut Command) -> Self {
        Own(Some(
            cmd.stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap(),
        ))
    }

    fn pid(&self) -> u32 {
        self.0.as_ref().unwrap().id()
    }

    fn finish(&mut self) {
        let Some(mut c) = self.0.take() else { return };
        drop(c.stdin.take());
        let t = Instant::now();
        while t.elapsed() < Duration::from_secs(5) {
            if let Ok(Some(_)) = c.try_wait() {
                return;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        #[allow(clippy::disallowed_methods)] // yalnız bu testin kendi çocuğu
        let _ = c.kill();
        let _ = c.wait();
    }
}

impl Drop for Own {
    fn drop(&mut self) {
        self.finish();
    }
}

fn cfg(tmp: &TempDir) -> Config {
    let live = Config::from_env().expect("HOME");
    let t = tmp.path();
    Config {
        proc_root: PathBuf::from("/proc"),
        claude_dir: t.join("claude"),
        agy_cache: t.join("agy_cache.json"),
        agy_sids: t.join("agy_sids.json"),
        uid: live.uid,
        clk_tck: live.clk_tck,
    }
}

fn wait_until(what: &str, mut f: impl FnMut() -> bool) {
    let t = Instant::now();
    while !f() {
        assert!(t.elapsed() < Duration::from_secs(10), "beklenen olmadı: {what}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Python `RealSubshellTests`: arka plan alt kabuğu (aynı argv + `COPS_NAME`) ikinci satır üretmez.
#[test]
fn real_background_subshell_is_one_session() {
    if !std::path::Path::new("/bin/bash").exists() {
        return;
    }
    let tmp = TempDir::new().unwrap();
    let cfg = cfg(&tmp);
    let name = format!("zz_rsproc_subshell_{}", std::process::id());
    let script = "exec 3<&0; ( cat <&3 >/dev/null; true ) & cat >/dev/null; wait";
    let mut child = Own::spawn(
        Command::new("/bin/bash")
            .args(["-c", &format!("exec -a claudeops-shell /bin/bash -c '{script}'")])
            .env("COPS_NAME", &name),
    );
    let pid = child.pid();
    let proc = ProcFs::new(&cfg.proc_root, cfg.uid);
    // alt kabuk doğana dek bekle (yoksa test boşa geçer)
    wait_until("alt kabuk", || {
        proc.own_processes()
            .iter()
            .any(|p| p.stat().is_some_and(|s| s.ppid == pid) && p.cmdline().first().is_some_and(|c| c == "claudeops-shell"))
    });
    let found: Vec<u32> = find_sessions(&cfg, CpuMode::Skip)
        .sessions
        .iter()
        .filter(|s| s.name == name)
        .map(|s| s.pid)
        .collect();
    assert_eq!(found, [pid]);
    let id = proc.own(pid).and_then(|p| p.id()).unwrap();
    assert_eq!(proc.verify(&id), Liveness::Same);
    child.finish();
    assert!(matches!(proc.verify(&id), Liveness::Gone | Liveness::Replaced));
}

/// Python `test_a_real_viewer_process_is_seen_by_the_real_scan`: gerçek görüntüleyici süreci tarama turunda ve
/// ayrı `running_mirrors` taramasında aynı görünür.
#[test]
fn real_viewer_process_is_seen() {
    let tmp = TempDir::new().unwrap();
    let cfg = cfg(&tmp);
    let spec = format!("zzmarkerhost:zzmarker{}", std::process::id());
    let child = Own::spawn(Command::new("sh").args(["-c", "cat >/dev/null; true", "claudeops", "watch", &spec]));
    let pid = child.pid();
    wait_until("cmdline", || running_mirrors(&cfg).contains_key(&spec));
    let scan = find_sessions(&cfg, CpuMode::Skip);
    assert_eq!(scan.mirrors.get(&spec), Some(&vec![pid]));
    assert_eq!(running_mirrors(&cfg).get(&spec), Some(&vec![pid]));
    assert!(!scan.sessions.iter().any(|s| s.pid == pid), "görüntüleyici oturum değil");
    drop(child);
    wait_until("pencere kapandı", || !running_mirrors(&cfg).contains_key(&spec));
}
