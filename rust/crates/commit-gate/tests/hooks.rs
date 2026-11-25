//! Uçtan uca: gerçek git repolarında kurulum, `commit-msg`, `pre-push` ve `check`.
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_commit-gate");

struct Tmp(PathBuf);
impl Drop for Tmp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn git(dir: &Path, args: &[&str]) -> Output {
    let mut c = Command::new("git");
    c.arg("-C").arg(dir).args(args).env("GIT_CONFIG_GLOBAL", "/dev/null").env("GIT_CONFIG_NOSYSTEM", "1");
    for (k, v) in [("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                   ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid")] {
        c.env(k, v);
    }
    c.output().unwrap()
}

fn ok(o: Output) {
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
}

fn write(dir: &Path, rel: &str, body: &str) {
    let p = dir.join(rel);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    std::fs::write(p, body).unwrap();
}

/// (geçici kök, çalışma reposu "claudeops", TBD yolu)
fn setup(name: &str) -> (Tmp, PathBuf, PathBuf) {
    let root = std::env::temp_dir().join(format!("commit-gate-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    let repo = root.join("it's claudeops"); // boşluk ve kesme işareti: kanca alıntılaması
    std::fs::create_dir_all(&repo).unwrap();
    ok(git(&root, &["init", "-q", "--bare", "remote.git"]));
    ok(git(&repo, &["init", "-q"]));
    ok(git(&repo, &["remote", "add", "origin", "../remote.git"]));
    let tbd = root.join("TOBEDECIDED.md");
    std::fs::write(&tbd, "## #7 x\n- Python-istisnası: ONAYLI (sahip, 2026-11-25)\n").unwrap();
    (Tmp(root), repo, tbd)
}

fn gate(args: &[&str]) -> Output {
    Command::new(BIN).args(args).output().unwrap()
}

fn s(p: &Path) -> &str {
    p.to_str().unwrap()
}

#[test]
fn commit_msg_hook_blocks_and_allows() {
    let (_t, repo, tbd) = setup("msg");
    ok(gate(&["install", "--tbd", s(&tbd), "--repo", s(&repo)]));
    ok(gate(&["install", "--tbd", s(&tbd), "--repo", s(&repo)])); // yeniden kurulum serbest
    write(&repo, "py/a.py", "def a():\n    pass\n");
    ok(git(&repo, &["add", "."]));
    let out = git(&repo, &["commit", "-qm", "feat: x"]);
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("py/a.py"));
    ok(git(&repo, &["commit", "-qm", "feat: x\n\nPython-exception: TBD#7"]));
    write(&repo, "py/a.py", "def a():\n    pass\n\ndef b():\n    pass\n");
    let out = git(&repo, &["commit", "-qam", "fix: y"]);
    assert!(out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("işlev b"));
}

#[test]
fn pre_push_and_check_catch_bypassed_commit_only_while_unpushed() {
    let (_t, repo, tbd) = setup("push");
    write(&repo, "py/a.py", "x = 1\n");
    ok(git(&repo, &["add", "."]));
    ok(git(&repo, &["commit", "-qm", "feat: kancasız"])); // kök commit
    let out = gate(&["check", "--core", s(&repo)]);
    assert_eq!(out.status.code(), Some(1));
    let err = String::from_utf8_lossy(&out.stderr).into_owned();
    assert!(err.contains("kancası kurulu değil") && err.contains("py/a.py"), "{err}");
    ok(gate(&["install", "--tbd", s(&tbd), "--repo", s(&repo)]));
    let out = git(&repo, &["push", "-q", "origin", "HEAD:main"]);
    assert!(!out.status.success());
    // zaten uzakta olan commit geriye dönük reddedilmez
    ok(git(&repo, &["push", "-q", "--no-verify", "origin", "HEAD:main"]));
    write(&repo, "rust/a.rs", "fn a() {}\n");
    ok(git(&repo, &["add", "."]));
    ok(git(&repo, &["commit", "-qm", "feat: rust"]));
    ok(git(&repo, &["push", "-q", "origin", "HEAD:main"]));
    ok(gate(&["check", "--core", s(&repo)]));
}

#[test]
fn install_keeps_foreign_hook() {
    let (_t, repo, tbd) = setup("foreign");
    write(&repo, ".git/hooks/pre-push", "#!/bin/sh\nexit 0\n");
    let out = gate(&["install", "--tbd", s(&tbd), "--repo", s(&repo)]);
    assert_eq!(out.status.code(), Some(2));
    assert!(!repo.join(".git/hooks/commit-msg").exists());
}
