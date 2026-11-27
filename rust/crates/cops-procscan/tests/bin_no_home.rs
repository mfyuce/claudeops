//! `HOME` yalnız süreç taraması (`list`, `scan`) için gerekir.

use std::process::{Command, Output};

fn run_without_home(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_cops-procscan"))
        .args(args)
        .env_remove("HOME")
        .output()
        .expect("ikili çalışır")
}

#[test]
fn usage_and_needs_ho_work_without_home() {
    let dir = std::env::temp_dir().join(format!("cops-procscan-nohome-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let (state, jsonl) = (dir.join("state"), dir.join("t.jsonl"));
    std::fs::write(&jsonl, "").unwrap();
    let (dir_s, state_s, jsonl_s) = (dir.to_str().unwrap(), state.to_str().unwrap(), jsonl.to_str().unwrap());

    let usage = run_without_home(&["usage", jsonl_s]);
    let needs = run_without_home(&["needs-ho", state_s, dir_s, jsonl_s]);
    std::fs::remove_dir_all(&dir).ok();

    assert!(usage.status.success(), "usage: {usage:?}");
    assert!(needs.status.success(), "needs-ho: {needs:?}");
    assert!(String::from_utf8_lossy(&needs.stdout).contains("\"needs_ho\""));
}

#[test]
fn scanning_commands_still_require_home() {
    for cmd in ["list", "scan"] {
        let out = run_without_home(&[cmd, "--no-cpu"]);
        assert_eq!(out.status.code(), Some(2), "{cmd}: {out:?}");
    }
}
