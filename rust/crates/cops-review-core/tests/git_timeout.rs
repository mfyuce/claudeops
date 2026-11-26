//! Ders H1/2.7 (`git` çağrısı): takılan `git` 10 sn sonra öldürülüp biçilir, karar "değişmedi" (Python `TimeoutExpired`
//! -> False), tanıtıcı sızmaz. `PATH` süreç genelinde değiştiği için bu ikilide TEK test olmalı.
use cops_review_core::export;
use cops_state::{Json, Map};
use std::os::unix::fs::PermissionsExt;
use std::time::{Duration, Instant};

fn open_fds() -> usize {
    std::fs::read_dir("/proc/self/fd").map_or(0, |d| d.count())
}

#[test]
fn hung_git_is_killed_and_reaped() {
    let t = tempfile::tempdir().unwrap();
    let d = std::fs::canonicalize(t.path()).unwrap();
    let bin = d.join("bin");
    let repo = d.join("repo");
    std::fs::create_dir_all(&bin).unwrap();
    std::fs::create_dir_all(repo.join(".git")).unwrap();
    let pidfile = d.join("git.pid");
    let fake = bin.join("git");
    std::fs::write(&fake, format!("#!/bin/sh\necho $$ > '{}'\nexec /bin/sleep 60\n", pidfile.display())).unwrap();
    std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::fs::write(repo.join("a.py"), "x").unwrap();
    let report = d.join("r.md");
    std::fs::write(&report, "r").unwrap();
    // dosya rapordan YENİ: git zaman aşımına uğramasa mtime ile `true` olurdu
    let old = std::time::SystemTime::UNIX_EPOCH + Duration::from_secs(1000);
    std::fs::File::options().write(true).open(&report).unwrap().set_modified(old).unwrap();
    std::env::set_var("PATH", &bin);

    let mut row = Map::new();
    row.insert("where".into(), Json::Str("a.py:1".into()));
    row.insert("review_file".into(), Json::Str(report.to_string_lossy().into_owned()));
    let before = open_fds();
    let start = Instant::now();
    assert!(!export::changed_after_review(&row, &repo.to_string_lossy()));
    let took = start.elapsed();
    assert!(took >= Duration::from_secs(9) && took < Duration::from_secs(30), "süre {took:?}");
    assert_eq!(open_fds(), before, "boru tanıtıcısı sızdı");
    let pid = std::fs::read_to_string(&pidfile).unwrap();
    let alive = std::path::Path::new(&format!("/proc/{}", pid.trim())).exists();
    assert!(!alive, "takılan git biçilmedi (zombi/yetim)");
}
