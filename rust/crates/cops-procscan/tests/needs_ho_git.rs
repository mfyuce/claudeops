//! Geçici git deposu ve geçici durum dizini.

use cops_procscan::needs_ho::{repo_dirty, repo_untracked_count, NeedsHo};
use std::path::Path;
use std::process::Command;

fn git(dir: &Path, args: &[&str]) {
    let ok = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args([
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
        ])
        .args(args)
        .output()
        .unwrap()
        .status
        .success();
    assert!(ok, "git {args:?}");
}

#[test]
fn git_signals_and_baseline() {
    let tmp = tempfile::tempdir().unwrap();
    let (repo, remote, state) = (
        tmp.path().join("repo"),
        tmp.path().join("remote.git"),
        tmp.path().join("state"),
    );
    std::fs::create_dir_all(&repo).unwrap();
    let cwd = repo.to_str().unwrap();
    let ho = NeedsHo::new(&state);

    // depo değil
    assert!(!repo_dirty(cwd) && repo_untracked_count(cwd) == 0 && !ho.repo_committed_since(cwd));
    ho.repo_baseline_set(cwd).unwrap();
    assert!(!state.exists());
    assert!(!ho.needs_ho(cwd, None).value);

    git(&repo, &["init", "-q", "-b", "main"]);
    std::fs::write(repo.join("a"), "1").unwrap();
    assert_eq!((repo_dirty(cwd), repo_untracked_count(cwd)), (false, 1));
    assert!(ho.needs_ho(cwd, None).value);
    git(&repo, &["add", "a"]);
    assert!(repo_dirty(cwd));
    git(&repo, &["commit", "-qm", "1"]);
    assert!(!repo_dirty(cwd));
    // baseline ve zaman damgası yok
    assert!(!ho.repo_committed_since(cwd));

    std::fs::create_dir_all(&state).unwrap();
    std::fs::write(state.join("last-handover.ts"), "2000-01-01T00:00:00+00:00\n").unwrap();
    assert!(ho.repo_committed_since(cwd));
    std::fs::write(state.join("last-handover.ts"), "2999-01-01T00:00:00+00:00\n").unwrap();
    assert!(!ho.repo_committed_since(cwd));

    ho.repo_baseline_set(cwd).unwrap();
    assert_eq!(std::fs::read_dir(state.join("baselines")).unwrap().count(), 1);
    assert!(!ho.repo_committed_since(cwd));
    git(&repo, &["commit", "-qm", "2", "--allow-empty"]);
    assert!(ho.repo_committed_since(cwd));
    ho.repo_baseline_set(cwd).unwrap();

    // push edilmemiş ve geride kalma
    git(tmp.path(), &["init", "-q", "--bare", remote.to_str().unwrap()]);
    git(&repo, &["remote", "add", "origin", remote.to_str().unwrap()]);
    assert!(!repo_dirty(cwd), "remote dalı yokken temiz");
    git(&repo, &["push", "-q", "origin", "main"]);
    assert!(!repo_dirty(cwd));
    git(&repo, &["commit", "-qm", "3", "--allow-empty"]);
    assert!(repo_dirty(cwd));
    git(&repo, &["push", "-q", "origin", "main"]);
    git(&repo, &["reset", "-q", "--hard", "HEAD~1"]);
    assert!(repo_dirty(cwd));
    git(&repo, &["checkout", "-q", "--detach"]);
    assert!(!repo_dirty(cwd));

    // transkript: gerçek tur yoksa git durumuna bakılmaz
    std::fs::write(repo.join("b"), "").unwrap();
    let t = tmp.path().join("t.jsonl");
    std::fs::write(&t, "{\"type\":\"system\"}\n").unwrap();
    assert!(!ho.needs_ho(cwd, Some(&t)).value);
    std::fs::write(&t, "{\"type\":\"user\",\"message\":{\"content\":\"x\"}}\n").unwrap();
    assert!(ho.needs_ho(cwd, Some(&t)).value);
    std::fs::remove_file(repo.join("b")).unwrap();
    ho.repo_baseline_set(cwd).unwrap();
    assert!(ho.needs_ho(cwd, Some(&t)).value, "temiz depo, RFH yok");
    std::fs::write(&t, "{\"type\":\"user\",\"message\":{\"content\":\"x\"}}\n{\"type\":\"assistant\",\"message\":{\"content\":\"READY FOR HANDOVER\"}}\n").unwrap();
    assert!(!ho.needs_ho(cwd, Some(&t)).value);
}
