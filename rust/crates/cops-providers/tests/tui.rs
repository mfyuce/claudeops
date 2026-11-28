//! G4 sözleşme testleri (sahte pane + sahte saat). Python testlerinin karşılıkları ve Rust'ın döndürdüğü
//! [`SwitchOutcome`]; Python ile davranış eşliği `parity.rs::parity_tui`.

#[path = "parity/fake_pane.rs"]
mod fake_pane;

use cops_providers::{Cli, DismissOutcome, SwitchOutcome};
use fake_pane::{FakePane, Script};

const PERMISSION: &str = " Do you want to proceed?\n ❯ 1. Yes\n   2. No\n\n Esc to cancel";

fn rule() -> String {
    "─".repeat(40)
}

fn boxed(inner: &str, history: &str) -> String {
    let r = rule();
    format!("{history}\n\n{r}\n❯\u{a0}{inner}\n{r}\n  ⏵⏵ auto mode on")
}

fn idle() -> String {
    boxed("", "")
}

fn result(text: &str) -> String {
    boxed("", &format!("  ⎿  {text}"))
}

fn dialog(title: &str, label: &str, on_no: bool) -> String {
    let (yes, no) = if on_no { (" ", "❯") } else { ("❯", " ") };
    format!(
        "{}\n {title}\n\n {yes} 1. Yes, switch to {label}\n {no} 2. No, go back\n\n Enter to confirm · Esc to cancel\n",
        rule()
    )
}

fn model_dialog() -> String {
    dialog(MODEL, "Sonnet 5.5", false)
}

const MODEL: &str = "Switch model?";
const EFFORT: &str = "Change effort level?";

fn pane(screens: &[&str]) -> FakePane {
    FakePane::screens(screens)
}

fn model(pane: &FakePane) -> SwitchOutcome {
    Cli::Claude.apply_live_model_switch(pane, "s", "sonnet")
}

fn effort(pane: &FakePane) -> SwitchOutcome {
    Cli::Claude.apply_live_effort_switch(pane, "s", "high")
}

const UNCONFIRMED: SwitchOutcome = SwitchOutcome::Unconfirmed { confirmed: false };

// test_proc08_model_switch_no_blind_enter.py, test_tbd399_live_switch.py

#[test]
fn permission_dialog_is_never_confirmed_even_with_switch_text_above_it() {
    let screen = format!("  ⎿  {MODEL}\n  ⎿  {EFFORT}\n{PERMISSION}");
    for run in [model, effort] {
        let p = pane(&[&idle(), &screen]);
        assert_eq!(run(&p), UNCONFIRMED);
        assert!(p.keys().is_empty());
    }
    let p = pane(&[&screen]);
    assert_eq!(
        Cli::Claude.dismiss_stray_dialog(&p, "s"),
        DismissOutcome::NotSeen
    );
    assert!(p.keys().is_empty());
}

#[test]
fn switch_dialog_is_confirmed_once_and_waits_for_a_new_result() {
    let applied = result("Set model to Sonnet 5.5");
    let p = pane(&[&idle(), &model_dialog(), &applied]);
    assert_eq!(model(&p), SwitchOutcome::Done { confirmed: true });
    assert_eq!(p.keys(), ["Enter"]);
    assert_eq!(p.texts(), ["/model sonnet"]);
}

#[test]
fn an_old_result_line_does_not_count() {
    let old = result("Set effort level to high");
    let p = pane(&[&old]);
    assert_eq!(effort(&p), UNCONFIRMED);
    assert!(p.keys().is_empty());
    assert_eq!(p.diags.borrow()[0].event, "live_switch_not_done");
}

#[test]
fn applied_without_dialog_sends_no_key() {
    let p = pane(&[&idle(), &result("Set model to Sonnet 5.5")]);
    assert_eq!(model(&p), SwitchOutcome::Done { confirmed: false });
    assert!(p.keys().is_empty() && p.diags.borrow().is_empty());
}

#[test]
fn only_the_expected_dialog_with_the_cursor_on_yes_is_confirmed() {
    for screen in [
        dialog(EFFORT, "high", false),
        dialog(MODEL, "Opus 5.5", false),
        dialog(MODEL, "Sonnet 5.5", true),
        format!("{}  3. Other", model_dialog()),
        format!("{}\n{}", model_dialog(), idle()),
    ] {
        let p = pane(&[&idle(), &screen]);
        assert_eq!(model(&p), UNCONFIRMED, "{screen}");
        assert!(p.keys().is_empty(), "{screen}");
    }
    let p = pane(&[&idle(), &dialog(EFFORT, "xhigh", false)]);
    assert_eq!(effort(&p), UNCONFIRMED);
    assert!(p.keys().is_empty());
}

#[test]
fn draft_dialog_busy_and_unknown_screens_get_no_command() {
    let busy = format!("{} · esc to interrupt", idle());
    for (screen, want) in [
        (boxed("yarım", ""), SwitchOutcome::Draft),
        (model_dialog(), SwitchOutcome::DialogOpen),
        (PERMISSION.to_string(), SwitchOutcome::Unreadable),
        (
            format!("{}\n{PERMISSION}", idle()),
            SwitchOutcome::Unreadable,
        ),
        (String::new(), SwitchOutcome::Unreadable),
        (busy, SwitchOutcome::Busy),
    ] {
        for run in [model, effort] {
            let p = pane(&[&screen]);
            assert_eq!(run(&p), want, "{screen}");
            assert!(p.texts().is_empty() && p.keys().is_empty(), "{screen}");
            assert_eq!(want.safe_to_type(), want == SwitchOutcome::Busy);
        }
    }
}

#[test]
fn a_dim_suggestion_is_not_a_draft() {
    let p = pane(&[
        &boxed("\x1b[2mcommit this\x1b[22m", ""),
        &result("Set model to Sonnet 5.5"),
    ]);
    assert_eq!(model(&p), SwitchOutcome::Done { confirmed: false });
}

#[test]
fn a_failed_or_ignored_confirm_enter_is_reported_and_never_repeated() {
    let p = FakePane::new(Script {
        screens: vec![Some(idle()), Some(model_dialog())],
        keys: vec![false],
        ..Script::default()
    });
    assert_eq!(model(&p), SwitchOutcome::Unconfirmed { confirmed: true });
    assert!(p.elapsed() < 1.0);
    assert_eq!(p.keys(), ["Enter"]);
    let p = pane(&[&idle(), &model_dialog()]);
    assert_eq!(model(&p), SwitchOutcome::Unconfirmed { confirmed: true });
    assert_eq!(p.keys(), ["Enter"]);
}

#[test]
fn every_wait_ends_on_its_budget_even_when_the_pane_stops_being_readable() {
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
        (6.0, 0.5, |p| {
            let _ = Cli::Claude.dismiss_stray_dialog(p, "s");
        }),
    ] {
        let screens = if budget == 6.0 {
            vec![None]
        } else {
            vec![Some(idle()), None]
        };
        let p = FakePane::new(Script {
            screens,
            ..Script::default()
        });
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
    for run in [model, effort] {
        let p = FakePane::new(Script {
            screens: vec![Some(idle())],
            send_ok: false,
            ..Script::default()
        });
        assert_eq!(run(&p), SwitchOutcome::SendFailed);
        assert_eq!((p.calls("sleep"), p.calls("key")), (0, 0));
    }
}

// test_rsprov_g4_dismiss.py, test_tbd399_live_switch.py

#[test]
fn late_model_and_effort_dialogs_are_refused_after_rereading_the_screen() {
    for (title, label) in [(MODEL, "Sonnet 5.5"), (EFFORT, "high")] {
        let p = pane(&[
            &dialog(title, label, false),
            &dialog(title, label, true),
            &idle(),
        ]);
        assert_eq!(
            Cli::Claude.dismiss_stray_dialog(&p, "s"),
            DismissOutcome::Closed
        );
        assert_eq!(p.keys(), ["Down", "Enter"]);
    }
}

#[test]
fn no_enter_unless_the_cursor_is_seen_on_no() {
    for after_down in [
        model_dialog(),
        PERMISSION.to_string(),
        dialog(EFFORT, "high", true),
        idle(),
    ] {
        let p = pane(&[&model_dialog(), &after_down]);
        assert_eq!(
            Cli::Claude.dismiss_stray_dialog(&p, "s"),
            DismissOutcome::LeftOpen
        );
        assert_eq!(p.keys(), ["Down"], "{after_down}");
        assert_eq!(p.diags.borrow()[0].event, "stray_dialog_left_open");
    }
    let p = FakePane::new(Script {
        screens: vec![Some(model_dialog())],
        keys: vec![false],
        ..Script::default()
    });
    assert_eq!(
        Cli::Claude.dismiss_stray_dialog(&p, "s"),
        DismissOutcome::LeftOpen
    );
    assert_eq!(p.keys(), ["Down"]);
    // reddetme Enter'ından sonra hâlâ açık
    let p = pane(&[&dialog(MODEL, "Sonnet 5.5", true)]);
    assert_eq!(
        Cli::Claude.dismiss_stray_dialog(&p, "s"),
        DismissOutcome::LeftOpen
    );
    assert_eq!(p.keys(), ["Enter"]);
}

#[test]
fn only_claude_touches_the_pane() {
    for cli in Cli::ALL.into_iter().filter(|c| *c != Cli::Claude) {
        let p = pane(&[&model_dialog()]);
        assert_eq!(
            cli.apply_live_model_switch(&p, "s", "sonnet"),
            SwitchOutcome::Unsupported
        );
        assert_eq!(
            cli.apply_live_effort_switch(&p, "s", "high"),
            SwitchOutcome::Unsupported
        );
        assert_eq!(cli.dismiss_stray_dialog(&p, "s"), DismissOutcome::NotSeen);
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

// test_rsprov_stuck_other_providers.py `_Disabled.test_provider_opts_out` (TBD#441)
#[test]
fn codex_and_agy_opt_out_of_stuck_recovery() {
    for c in [Cli::Codex, Cli::Agy] {
        assert!(c.has_conversation() && c.wants_handover_wrapup() && !c.wants_stuck_recovery());
    }
    assert!(Cli::Copilot.wants_stuck_recovery());
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
    assert_eq!(u.dismiss_stray_dialog(&p, "cops"), DismissOutcome::NotSeen);
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
