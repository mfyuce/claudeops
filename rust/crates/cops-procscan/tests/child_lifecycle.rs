//! Alt süreç sahipliği (ders H1, liste 9): zaman aşımı/başarı/torun durumlarında zombi ve fd sızıntısı yok.
//! Bu ikilide TEK test var: fd ve çocuk sayımı başka testlerin eşzamanlı süreçlerinden etkilenmesin.

use cops_procscan::proc_cmd::run_observed;
use cops_procscan::procfs::parse_stat;
use std::process::Command;
use std::time::{Duration, Instant};

fn fds() -> usize {
    std::fs::read_dir("/proc/self/fd").unwrap().count()
}

fn threads() -> usize {
    let st = std::fs::read_to_string("/proc/self/status").unwrap();
    st.lines()
        .find_map(|l| l.strip_prefix("Threads:"))
        .unwrap()
        .trim()
        .parse()
        .unwrap()
}

/// Süreç yaşıyor mu (zombi yaşamıyor sayılır).
fn alive(pid: u32) -> bool {
    std::fs::read_to_string(format!("/proc/{pid}/stat"))
        .ok()
        .and_then(|raw| raw.rfind(')').map(|i| raw[i + 1..].split_whitespace().next() != Some("Z")))
        .unwrap_or(false)
}

fn wait_until(mut f: impl FnMut() -> bool) -> bool {
    let t = Instant::now();
    while t.elapsed() < Duration::from_secs(5) {
        if f() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    f()
}

fn start_time(pid: u32) -> Option<u64> {
    parse_stat(&std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?).map(|s| s.starttime)
}

/// Bu sürecin zombi çocukları.
fn zombie_children() -> Vec<u32> {
    let me = std::process::id();
    std::fs::read_dir("/proc")
        .unwrap()
        .filter_map(|e| e.ok()?.file_name().to_str()?.parse::<u32>().ok())
        .filter(|pid| {
            let Ok(raw) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else {
                return false;
            };
            let Some(rest) = raw.rfind(')').map(|i| &raw[i + 1..]) else {
                return false;
            };
            let f: Vec<&str> = rest.split_whitespace().collect();
            f.first() == Some(&"Z") && f.get(1).and_then(|p| p.parse::<u32>().ok()) == Some(me)
        })
        .collect()
}

fn sh(s: &str) -> Command {
    let mut c = Command::new("sh");
    c.args(["-c", s]);
    c
}

#[test]
fn no_zombies_no_fd_leak_after_many_runs() {
    let before = fds();
    let mut spawned = Vec::new();
    for i in 0..100 {
        let (cmd, timeout, ok) = match i % 4 {
            0 => (sh("echo hi"), Duration::from_secs(5), true),
            1 => (sh("exec sleep 5"), Duration::from_millis(20), false),
            2 => (sh("exec >&-; exec sleep 5"), Duration::from_millis(20), false),
            _ => (sh("echo x; exit 7"), Duration::from_secs(5), true),
        };
        let out = run_observed(cmd, timeout, |pid| spawned.push((pid, start_time(pid))));
        assert_eq!(out.is_some(), ok, "koşu {i}");
    }
    // torun boruyu tutar: çağrı zaman aşımında döner, torun kısa süre sonra kendiliğinden çıkar
    let t = Instant::now();
    assert!(run_observed(sh("sleep 1 & echo x"), Duration::from_millis(50), |_| {}).is_none());
    assert!(t.elapsed() < Duration::from_millis(900));

    // Birleştirme kapısı: torun stdout'u UZUN süre tutar. Okuyucu süre sınırlı (iş parçacığı yok/sızmaz), zaman aşımında
    // çocuğun KENDİ süreç grubu öldürülür (torun dahil); fd ve iş parçacığı sayısı geri döner.
    let tmp = tempfile::tempdir().unwrap();
    let pidf = tmp.path().join("torun");
    let threads_before = threads();
    let t = Instant::now();
    let script = format!("sleep 8 & echo $! > {}; echo x", pidf.display());
    assert!(run_observed(sh(&script), Duration::from_millis(100), |_| {}).is_none());
    assert!(t.elapsed() < Duration::from_secs(2));
    let g: u32 = std::fs::read_to_string(&pidf).unwrap().trim().parse().unwrap();
    assert!(wait_until(|| !alive(g)), "torun {g} grupla öldürülmedi");
    assert!(wait_until(|| threads() == threads_before), "okuyucu iş parçacığı sızdı");
    // gruptan kaçan torun (setsid) öldürülmez ama okuyucu yine sürede döner, iş parçacığı kalmaz
    if std::path::Path::new("/usr/bin/setsid").exists() {
        let t = Instant::now();
        let script = format!("setsid sleep 2 & echo $! > {}; echo x", pidf.display());
        assert!(run_observed(sh(&script), Duration::from_millis(100), |_| {}).is_none());
        assert!(t.elapsed() < Duration::from_secs(1));
        assert!(
            wait_until(|| threads() == threads_before),
            "okuyucu iş parçacığı sızdı (setsid)"
        );
    }

    assert_eq!(spawned.len(), 100);
    for (pid, start) in &spawned {
        // biçilmiş: /proc girdisi yok ya da pid başka sürece geçmiş
        assert!(start.is_none() || start_time(*pid) != *start, "çocuk {pid} biçilmedi");
    }
    assert_eq!(zombie_children(), Vec::<u32>::new());
    let t = Instant::now();
    while fds() > before && t.elapsed() < Duration::from_secs(5) {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(fds(), before, "fd sızıntısı");
}
