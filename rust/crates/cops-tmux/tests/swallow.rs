//! Yutulan hatalar sessiz değil: sayaç artar, günlükçüye (kanca) sebep koduyla gider, asıl hata çağırana döner.

use std::os::unix::fs::symlink;
use std::sync::Mutex;
use std::time::Duration;

use cops_tmux::{set_swallow_hook, swallowed_count, MaskGuard, Swallowed, Tmux, TmuxError};
use tempfile::TempDir;

static SEEN: Mutex<Vec<(Swallowed, String)>> = Mutex::new(Vec::new());

fn record(kind: Swallowed, text: &str) {
    SEEN.lock()
        .unwrap_or_else(|e| e.into_inner())
        .push((kind, text.to_string()));
}

fn seen(kind: Swallowed) -> Vec<String> {
    SEEN.lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .filter(|(k, _)| *k == kind)
        .map(|(_, t)| t.clone())
        .collect()
}

fn fake() -> (TempDir, Tmux) {
    let dir = tempfile::tempdir().unwrap();
    let program = dir.path().join("tmux");
    symlink(
        concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fake_tmux.sh"),
        &program,
    )
    .unwrap();
    let tmux = Tmux::with_socket("cxrs-fake").program(program);
    (dir, tmux)
}

const SECRET: &str = "gizli-metin-42";

#[test]
fn failed_buffer_cleanup_is_counted_logged_and_the_paste_error_returned() {
    set_swallow_hook(record);
    let (dir, t) = fake();
    std::fs::write(dir.path().join("paste-buffer.rc"), "1\n").unwrap();
    std::fs::write(dir.path().join("delete-buffer.rc"), "1\n").unwrap();
    let before = swallowed_count(Swallowed::DeleteBuffer);
    let text = format!("{SECRET}\nikinci satır");
    let err = t
        .send_text("x", &text, Duration::ZERO, MaskGuard::UserTyped)
        .unwrap_err();
    assert!(matches!(err, TmuxError::Failed { code: Some(1), .. }));
    assert!(swallowed_count(Swallowed::DeleteBuffer) > before);
    let logged = seen(Swallowed::DeleteBuffer);
    assert!(!logged.is_empty());
    assert!(logged.iter().all(|l| !l.contains(SECRET)), "{logged:?}");
    assert_eq!(Swallowed::DeleteBuffer.code(), "delete_buffer_failed");
}

#[test]
fn input_cut_short_by_a_failing_tmux_is_counted_and_failure_returned() {
    set_swallow_hook(record);
    let before = swallowed_count(Swallowed::StdinWrite);
    // `/bin/false` girdiyi okumadan 1 ile çıkar; 1 MB boruya sığmaz -> yazım EPIPE.
    let t = Tmux::with_socket("x").program("/bin/false");
    let text = format!("{SECRET}\n").repeat(100_000);
    let err = t
        .send_text("x", &text, Duration::ZERO, MaskGuard::UserTyped)
        .unwrap_err();
    assert!(
        matches!(err, TmuxError::Failed { code: Some(1), .. }),
        "{err:?}"
    );
    assert!(swallowed_count(Swallowed::StdinWrite) > before);
    assert!(seen(Swallowed::StdinWrite)
        .iter()
        .all(|l| !l.contains(SECRET)));
    // `/bin/true` aynı durumda 0 ile çıkar: yarım girdi başarı SAYILMAZ, hata yutulmaz, döner.
    let t = Tmux::with_socket("x").program("/bin/true");
    assert!(matches!(
        t.send_text("x", &text, Duration::ZERO, MaskGuard::UserTyped),
        Err(TmuxError::Io(_))
    ));
}

#[test]
fn every_kind_has_a_distinct_code() {
    let mut codes: Vec<&str> = Swallowed::ALL.iter().map(|k| k.code()).collect();
    codes.sort_unstable();
    codes.dedup();
    assert_eq!(codes.len(), Swallowed::ALL.len());
}
