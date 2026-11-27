//! Kaynak sızıntısı: her tmux çağrısı (başarı, hata, zaman aşımı, boruyu tutan torun süreç, büyük girdi/çıktı)
//! sonrasında fd ve iş parçacığı sayısı aynı kalır, başlatılan her süreç toplanır (zombi yok).
//!
//! Bu dosyada BİLEREK tek test var: sayımlar süreç genelidir, paralel test onları bozardı.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cops_tmux::{MaskGuard, Tmux, TmuxError};

fn count(dir: &str) -> usize {
    fs::read_dir(dir).unwrap().count()
}

fn script(dir: &Path, name: &str, body: &str) -> PathBuf {
    let path = dir.join(name);
    let pids = dir.join("pids");
    fs::write(
        &path,
        format!("#!/bin/sh\necho $$ >>'{}'\n{body}\n", pids.display()),
    )
    .unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

/// Bu sürecin zombi çocuğu var mı (`pids` dosyasındaki süreçlerden).
fn zombies(dir: &Path) -> Vec<u32> {
    let me = std::process::id();
    fs::read_to_string(dir.join("pids"))
        .unwrap()
        .split_whitespace()
        .filter_map(|p| p.parse::<u32>().ok())
        .filter(|pid| {
            let Ok(raw) = fs::read_to_string(format!("/proc/{pid}/stat")) else {
                return false;
            };
            let rest: Vec<&str> = raw[raw.rfind(')').unwrap() + 1..]
                .split_whitespace()
                .collect();
            rest[0] == "Z" && rest[1].parse::<u32>().ok() == Some(me)
        })
        .collect()
}

fn tmux(program: &Path, timeout: Duration) -> Tmux {
    Tmux::with_socket("cxrs-leak")
        .program(program)
        .timeout(timeout)
}

struct Fakes {
    ok: Tmux,
    fail: Tmux,
    hang: Tmux,
    grandchild: Tmux,
    big: Tmux,
    deaf: Tmux,
}

fn cycle(f: &Fakes) {
    assert!(f.ok.capture("x", 1).unwrap().starts_with("out"));
    assert!(matches!(
        f.fail.capture("x", 1),
        Err(TmuxError::Failed { code: Some(3), .. })
    ));
    assert!(matches!(f.hang.capture("x", 1), Err(TmuxError::Timeout)));
    // tmux çıktı ama torun süreç stdout'u açık tutuyor: süre dolunca dönülür, torunun ölmesi BEKLENMEZ.
    let start = Instant::now();
    assert!(matches!(
        f.grandchild.capture("x", 1),
        Err(TmuxError::Timeout)
    ));
    assert!(start.elapsed() < Duration::from_millis(1500));
    assert_eq!(f.big.capture("x", 1).unwrap().len(), 3_000_000);
    // Girdi (büyük, çok satırlı): `ok` okur; `deaf` okumadan 0 ile çıkar -> yarım girdi başarı sayılmaz.
    let text = "satır\n".repeat(200_000);
    f.ok.send_text("x", &text, Duration::ZERO, MaskGuard::UserTyped)
        .unwrap();
    assert!(matches!(
        f.deaf
            .send_text("x", &text, Duration::ZERO, MaskGuard::UserTyped),
        Err(TmuxError::Io(_))
    ));
}

#[test]
fn no_fd_thread_or_zombie_survives_any_outcome() {
    let dir = tempfile::tempdir().unwrap();
    let d = dir.path();
    let short = Duration::from_millis(100);
    let long = Duration::from_secs(10);
    let f = Fakes {
        ok: tmux(
            &script(d, "ok", "cat >/dev/null; echo out; echo err >&2"),
            long,
        ),
        fail: tmux(&script(d, "fail", "echo err >&2; exit 3"), long),
        hang: tmux(&script(d, "hang", "exec sleep 30"), short),
        grandchild: tmux(&script(d, "grandchild", "sleep 2 &\nexit 0"), short),
        big: tmux(&script(d, "big", "head -c 3000000 /dev/zero"), long),
        deaf: tmux(&script(d, "deaf", "exit 0"), long),
    };
    // Isınma: tembel kurulan durum (regex, std iç önbellekleri) sayıma girmesin.
    cycle(&f);
    let (fds, threads) = (count("/proc/self/fd"), count("/proc/self/task"));
    for _ in 0..10 {
        cycle(&f);
    }
    assert_eq!(count("/proc/self/fd"), fds, "fd sızıntısı");
    assert_eq!(count("/proc/self/task"), threads, "iş parçacığı sızıntısı");
    assert_eq!(zombies(d), Vec::<u32>::new(), "toplanmamış çocuk");
}
