//! Bekleyen onay kartları ve açılıştaki kurtarma (`ucli_approval.{pending, recover_resuming}`; yalnız geçici dizin).
//! Python `test_ucli_approval_resumed.py` ve `test_rsprov_approval_cards.py` karşılığı; davranış eşliği ayrıca
//! `parity.rs::parity_oneshot` (`kart-`).

#[path = "g8/support.rs"]
mod support;

use cops_providers::approval::NewRun;
use cops_providers::pyjson::Py;
use cops_providers::real::approval::{ApprovalStore, RECOVER_MAX_AGE};
use std::fs;
use std::time::{Duration, Instant};
use support::{mkfifo, Tmp};

fn store() -> (Tmp, ApprovalStore) {
    let t = Tmp::new();
    let approvals = ApprovalStore::new(&t.paths());
    let argv = vec!["/bin/ucli".to_string()];
    let run = NewRun {
        cwd: "/c",
        session: "",
        argv_resume: &argv,
        owner: "",
    };
    approvals.register("k1", run).unwrap();
    (t, approvals)
}

fn put(a: &ApprovalStore, id: &str, status: &str) {
    let path = format!("{}/pending/{id}.json", a.dir_for("k1", false).unwrap());
    let card = format!(
        r#"{{"id":"{id}","kind":"edit","tool":"write_file","summary":"s","expires_at":9e12,"status":"{status}"}}"#
    );
    fs::write(path, card).unwrap();
}

fn record(a: &ApprovalStore, field: &str) -> Option<Py> {
    let raw = fs::read_to_string(a.index_path()).unwrap();
    Py::parse(&raw).unwrap().get("k1")?.get(field).cloned()
}

fn state(a: &ApprovalStore) -> String {
    record(a, "state").unwrap().py_str()
}

fn ids(a: &ApprovalStore) -> Vec<String> {
    a.pending("k1", None)
        .iter()
        .map(|c| c.get("id").unwrap().py_str())
        .collect()
}

const LOST: &str = "{'error': 'resume ran but its result was not recorded'}";

/// Sürdürme başlamışken panel yeniden başlar.
fn interrupted(cards: &[(&str, &str)]) -> (Tmp, ApprovalStore) {
    let (t, a) = store();
    a.set_state("k1", "resuming").unwrap();
    for (id, status) in cards {
        put(&a, id, status);
    }
    a.recover_resuming(None, RECOVER_MAX_AGE).unwrap();
    (t, a)
}

#[test]
fn a_resumed_card_is_not_pending() {
    let (_t, a) = store();
    put(&a, "a1", "resumed");
    assert!(a.pending("k1", None).is_empty());
}

#[test]
fn a_run_with_only_a_resumed_card_is_closed() {
    let (_t, a) = interrupted(&[("a1", "resumed")]);
    assert_eq!(state(&a), "done");
    assert_eq!(record(&a, "result").unwrap().py_repr(), LOST);
    assert!(matches!(record(&a, "finished_at"), Some(Py::Float(_))));
}

#[test]
fn an_already_suspended_record_with_only_a_resumed_card_is_closed() {
    let (_t, a) = store();
    a.set_state("k1", "suspended").unwrap();
    put(&a, "a1", "resumed");
    assert_eq!(a.recover_resuming(None, RECOVER_MAX_AGE).unwrap(), 1);
    assert_eq!(state(&a), "done");
}

#[test]
fn a_chained_suspension_keeps_only_the_new_card() {
    let (_t, a) = interrupted(&[("a1", "resumed"), ("a2", "pending")]);
    assert_eq!(state(&a), "suspended");
    assert_eq!(ids(&a), ["a2"]);
}

#[test]
fn an_untouched_card_stays_resumable() {
    let (_t, a) = interrupted(&[("a1", "pending")]);
    assert_eq!(state(&a), "suspended");
    assert_eq!(ids(&a), ["a1"]);
}

#[test]
fn a_consumed_mark_closes_the_run_even_with_a_pending_card() {
    let (_t, a) = store();
    a.set_state("k1", "suspended").unwrap();
    put(&a, "a1", "pending");
    fs::write(format!("{}/consumed", a.dir_for("k1", false).unwrap()), "").unwrap();
    assert_eq!(a.recover_resuming(None, RECOVER_MAX_AGE).unwrap(), 1);
    assert_eq!(state(&a), "done");
}

#[test]
fn fifo_and_deeply_nested_cards_are_skipped_without_blocking() {
    let (_t, a) = store();
    a.set_state("k1", "suspended").unwrap();
    put(&a, "b", "pending");
    let pending = format!("{}/pending", a.dir_for("k1", false).unwrap());
    mkfifo(&format!("{pending}/a.json"));
    fs::write(format!("{pending}/c.json"), vec![b'['; 100_000]).unwrap();
    let start = Instant::now();
    assert_eq!(a.recover_resuming(None, RECOVER_MAX_AGE).unwrap(), 0);
    assert_eq!(ids(&a), ["b"]);
    assert!(start.elapsed() < Duration::from_secs(10));
}
