//! G4 sözleşme testleri (sahte pane + sahte saat). Python testlerinin karşılıkları ve Rust'ın döndürdüğü
//! [`SwitchOutcome`]; Python ile davranış eşliği `parity.rs::parity_tui`.

#[path = "parity/fake_pane.rs"]
mod fake_pane;

use cops_providers::{Cli, SwitchOutcome};
use fake_pane::{FakePane, Script};

const PERMISSION: &str = "Do you want to proceed?\n❯ 1. Yes\n  2. No";

fn model(pane: &FakePane) -> SwitchOutcome {
    Cli::Claude.apply_live_model_switch(pane, "s", "claude-sonnet-5-5")
}

fn effort(pane: &FakePane) -> SwitchOutcome {
    Cli::Claude.apply_live_effort_switch(pane, "s", "high")
}

// test_proc08_model_switch_no_blind_enter.py

#[test]
fn permission_dialog_is_not_confirmed() {
    let p = FakePane::screens(&[PERMISSION]);
    assert_eq!(model(&p), SwitchOutcome::TimedOut { confirmed: false });
    assert!(p.keys().is_empty());
    assert_eq!(p.texts(), ["/model claude-sonnet-5-5"]);
}

#[test]
fn switch_dialog_is_confirmed_once() {
    let p = FakePane::screens(&["Switch model?\n❯ Yes", "Set model to sonnet"]);
    assert_eq!(model(&p), SwitchOutcome::MarkerSeen { confirmed: true });
    assert_eq!(p.keys(), ["Enter"]);
}

#[test]
fn applied_without_dialog_sends_no_key() {
    let p = FakePane::screens(&["Set model to sonnet"]);
    assert_eq!(model(&p), SwitchOutcome::MarkerSeen { confirmed: false });
    assert!(p.keys().is_empty());
    assert_eq!(p.calls("capture"), 1);
}

// test_live_model_effort.py::EffortSwitchNoBlindEnter

#[test]
fn effort_without_dialog_sends_no_enter() {
    let p = FakePane::screens(&["kullanıcı yazıyor..."]);
    assert_eq!(effort(&p), SwitchOutcome::TimedOut { confirmed: false });
    assert!(p.keys().is_empty());
    assert_eq!(p.texts(), ["/effort high"]);
}

#[test]
fn effort_dialog_is_confirmed_once_and_waits_for_a_done_marker() {
    let p = FakePane::screens(&[
        "Change effort level?",
        "Change effort level?",
        "Set effort level to high",
    ]);
    assert_eq!(effort(&p), SwitchOutcome::MarkerSeen { confirmed: true });
    assert_eq!(p.keys(), ["Enter"]);
}

#[test]
fn each_switch_ignores_the_other_dialog() {
    let p = FakePane::screens(&["Change effort level?"]);
    assert_eq!(model(&p), SwitchOutcome::TimedOut { confirmed: false });
    assert!(p.keys().is_empty());
    let p = FakePane::screens(&["Switch model?"]);
    assert_eq!(effort(&p), SwitchOutcome::TimedOut { confirmed: false });
    assert!(p.keys().is_empty());
}

#[test]
fn every_wait_ends_on_its_budget_even_when_the_pane_cannot_be_read() {
    for (budget, step, run) in [
        (
            20.0,
            0.3,
            (|p| {
                let _ = model(p);
            }) as fn(&FakePane),
        ),
        (8.0, 0.3, |p| {
            let _ = effort(p);
        }),
        (6.0, 0.5, |p| Cli::Claude.dismiss_stray_dialog(p, "s")),
    ] {
        let p = FakePane::new(Script::default());
        run(&p);
        assert!(
            p.elapsed() >= budget && p.elapsed() < budget + 2.0 * step,
            "{budget}: {}",
            p.elapsed()
        );
        assert!(p.keys().is_empty());
    }
}

#[test]
fn a_failed_send_returns_without_waiting() {
    let p = FakePane::new(Script {
        send_ok: false,
        ..Script::default()
    });
    assert_eq!(model(&p), SwitchOutcome::SendFailed);
    assert_eq!(effort(&p), SwitchOutcome::SendFailed);
    assert_eq!(
        (p.calls("capture"), p.calls("sleep"), p.calls("key")),
        (0, 0, 0)
    );
}

#[test]
fn stray_dialog_is_refused_and_a_failed_down_sends_no_enter() {
    let p = FakePane::screens(&["Switch model?"]);
    Cli::Claude.dismiss_stray_dialog(&p, "s");
    assert_eq!(p.keys(), ["Down", "Enter"]);
    let p = FakePane::new(Script {
        screens: vec![Some("Switch model?".into())],
        keys: vec![false],
        ..Script::default()
    });
    Cli::Claude.dismiss_stray_dialog(&p, "s");
    assert_eq!(p.keys(), ["Down"]);
}

#[test]
fn only_claude_touches_the_pane() {
    for cli in Cli::ALL.into_iter().filter(|c| *c != Cli::Claude) {
        let p = FakePane::screens(&["Switch model?\nChange effort level?"]);
        assert_eq!(
            cli.apply_live_model_switch(&p, "s", "sonnet"),
            SwitchOutcome::Unsupported
        );
        assert_eq!(
            cli.apply_live_effort_switch(&p, "s", "high"),
            SwitchOutcome::Unsupported
        );
        cli.dismiss_stray_dialog(&p, "s");
        assert!(p.log.borrow().is_empty(), "{}", cli.name());
    }
}

// test_provider_wants_split.py

#[test]
fn ucli_has_a_conversation_and_stuck_recovery_but_no_wrapup() {
    let c = Cli::Ucli;
    assert!(c.has_conversation() && c.wants_stuck_recovery() && !c.wants_handover_wrapup());
}

#[test]
fn claude_wants_follow_has_conversation() {
    assert!(Cli::Claude.wants_handover_wrapup() && Cli::Claude.wants_stuck_recovery());
}

#[test]
fn shell_wants_nothing() {
    let c = Cli::Shell;
    assert!(!c.has_conversation() && !c.wants_handover_wrapup() && !c.wants_stuck_recovery());
}

// test_ucli_multiline_flatten.py, test_steward_ucli_send.py (sağlayıcı kısmı)

#[test]
fn ucli_input_is_folded_to_one_line_without_truncation() {
    let u = Cli::Ucli;
    assert_eq!(u.prepare_input("a\nb\n\n  c  \r\nd\re"), "a b c d e");
    assert_eq!(u.prepare_input("  tek satır  "), "  tek satır  ");
    assert_eq!(u.prepare_input("x\n"), "x");
    // yalnız satır sonu boş metne inmez (yalın Enter olurdu): aynen döner, pane katmanı reddeder
    assert_eq!(u.prepare_input("\r\n \t\n"), "\r\n \t\n");
    assert_eq!(u.prepare_input("a\tb\t\tc  d"), "a b c d");
    let long = format!("satır1\n{}\nson", "uzun ".repeat(400));
    let out = u.prepare_input(&long);
    assert!(
        !out.contains('\n')
            && out.starts_with("satır1 uzun")
            && out.ends_with("son")
            && out.len() > 2000
    );
}

#[test]
fn other_providers_keep_the_input() {
    for cli in Cli::ALL.into_iter().filter(|c| *c != Cli::Ucli) {
        assert_eq!(cli.prepare_input("a\nb\tc"), "a\nb\tc", "{}", cli.name());
    }
}

/// test_ucli_fresh_handover.py::HandoverGateTest (sağlayıcı kısmı; web kapısı T4): mesaj tek satır gider, diyalog
/// taraması pane'e dokunmaz.
#[test]
fn ucli_handover_message_is_one_line_and_the_dialog_scan_is_a_noop() {
    let u = Cli::Ucli;
    assert!(u.has_conversation());
    assert!(!u.prepare_input("ÖNCE: notu yaz\n- madde").contains('\n'));
    let p = FakePane::screens(&["Switch model?"]);
    u.dismiss_stray_dialog(&p, "cops");
    assert!(p.log.borrow().is_empty());
}

#[test]
fn only_codex_needs_a_settle_delay_and_only_claude_compacts() {
    for cli in Cli::ALL {
        assert_eq!(
            cli.input_settle_delay(),
            if cli == Cli::Codex { 0.15 } else { 0.0 }
        );
        assert_eq!(
            cli.compact_command(),
            (cli == Cli::Claude).then_some("/compact")
        );
        assert_eq!(cli.cyclable_modes().is_empty(), cli != Cli::Claude);
        assert_eq!(
            cli.mode_status_patterns().is_empty(),
            !matches!(cli, Cli::Claude | Cli::Copilot)
        );
    }
}

#[test]
fn downgrades_only_go_down() {
    assert_eq!(
        Cli::Claude.handover_model_downgrade("claude-opus-5-5"),
        Some("sonnet")
    );
    assert_eq!(
        Cli::Claude.handover_model_downgrade("claude-haiku-5-5"),
        None
    );
    assert_eq!(Cli::Claude.handover_model_downgrade(""), None);
    assert_eq!(
        Cli::Claude.handover_effort_downgrade("max", "high"),
        Some("high")
    );
    assert_eq!(Cli::Claude.handover_effort_downgrade("high", "high"), None);
    assert_eq!(Cli::Claude.handover_effort_downgrade("low", "high"), None);
    assert_eq!(Cli::Claude.handover_effort_downgrade("?", "high"), None);
    assert_eq!(Cli::Codex.handover_effort_downgrade("max", "high"), None);
}
