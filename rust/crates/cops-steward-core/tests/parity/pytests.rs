//! Python testlerinin kayıtla yakalanmayan iddiaları (sabit, varsayılan ayar, desen, kaynak denetimi): aynı iddia burada
//! Rust karşılığında sınanır. Sabitlerin Python'la eşitliği ayrıca `generated`de. `/// py:` satırı eşleme tablosunun
//! test kimliğidir (`parity/map.py`).
use cops_steward_core::consts_gen::*;
use cops_steward_core::pyc;
use cops_steward_core::tick::{plan_tick, TickInput};
use cops_steward_core::types::{Config, Project};
use indexmap::IndexMap;
use serde_json::Map;

/// py: test_brain_permission_ucli.BrainPermission.test_default_allow_edit_is_a_valid_ucli_mode
#[test]
fn default_brain_permission_is_allow_edit() {
    assert_eq!(Config::default().brain_permission, "allow-edit");
}

/// py: test_brain_rules_g_h.TestBrainRules.test_rules_present_in_both_languages
#[test]
fn writing_map_rule_in_both_languages() {
    assert!(MODEL_RULE_TR.contains("YAZIM HARİTASI = ONAY"));
    assert!(MODEL_RULE_TR.contains("anladığım:"));
    assert!(MODEL_RULE_EN.contains("WRITING MAP = APPROVAL"));
    assert!(MODEL_RULE_EN.contains("understood:"));
}

/// py: test_brain_rules_g_h.TestBrainRules.test_h_is_limited_to_reversible_questions
#[test]
fn owner_answer_reading_is_limited_to_reversible() {
    assert!(MODEL_RULE_TR.contains("GERİ ALINABİLİR"));
    assert!(MODEL_RULE_EN.contains("REVERSIBLE"));
}

/// py: test_steward_claude_idle_work.StewardNextMarkerTest.test_protocol_mentions_marker
#[test]
fn protocol_mentions_next_marker() {
    assert!(P_PROTOCOL_TR.contains("STEWARD-NEXT:"));
    assert!(P_PROTOCOL_EN.contains("STEWARD-NEXT:"));
}

/// py: test_todo_triage.Plan.test_observe_list_and_preamble_rule
#[test]
fn todo_triage_is_observe_skipped_and_protocol_has_rule() {
    assert!(OBSERVE_SKIPPED.contains(&"todo_triage"));
    assert!(P_PROTOCOL_TR.contains("TODO/TBD kuralı"));
    assert!(P_PROTOCOL_EN.contains("TODO/TBD rule"));
    assert!(!P_PROTOCOL_TR.contains("private ise yerelde kalır"));
}

/// py: test_steward_owner_todo.Move.test_observe_skips_kind
#[test]
fn owner_todo_move_is_observe_skipped() {
    assert!(OBSERVE_SKIPPED.contains(&"owner_todo_move"));
}

/// py: test_steward_owner_todo.Regex.test_tags
#[test]
fn owner_todo_line_tags() {
    for t in [
        "SAHİPTE",
        "SAHIPTE",
        "sahipte",
        "(sahip)",
        "DIŞ GİRDİ",
        "DIS GIRDI",
        "dış girdi bekliyor",
        "sahip kararı bekliyor",
        "sahip karari bekliyor",
        "Sahip Kararı Bekliyor",
    ] {
        assert!(OWNER_TODO_LINE_RE.is_match(&format!("- [ ] {t}")), "{t}");
    }
    for t in ["sahipsiz iş", "kalite girdisi"] {
        assert!(!OWNER_TODO_LINE_RE.is_match(&format!("- [ ] {t}")), "{t}");
    }
}

/// py: test_steward_owner_todo.Regex.test_wait_re_covers_new_and_old
#[test]
fn owner_wait_line_covers_new_and_old() {
    assert!(OWNER_WAIT_LINE_RE.is_match("- [ ] SAHİPTE x"));
    assert!(OWNER_WAIT_LINE_RE.is_match("- [ ] STEWARD-ASK x"));
}

/// py: test_steward_core_a.ReviewFindings20261029Test.test_owner_only_false_positives
#[test]
fn owner_only_pattern_false_positives() {
    let re = pyc::py_regex(OWNER_ONLY_RE.as_str()).expect("desen");
    let hit = |t: &str| re.is_match(&pyc::ci_input(t)).expect("arama");
    for t in [
        "Qdrant koleksiyonu kuruldu mu?",
        "bağlam token'ı 200K, alt ajan açayım mı?",
        "silsile tablosunu yeniden üretsem?",
        "workforce raporu",
    ] {
        assert!(!hit(t), "{t}");
    }
    for t in ["git push --force yapayım mı", "dosyayı sileyim mi", "API token ver", "apt install x", "parolayı gir"]
    {
        assert!(hit(t), "{t}");
    }
}

/// py: test_steward_core_a.ReviewFindings20261029Test.test_owner_only_bare_number_after_token_stays_owner
#[test]
fn owner_only_bare_number_after_token_stays_owner() {
    let re = pyc::py_regex(OWNER_ONLY_RE.as_str()).expect("desen");
    let hit = |t: &str| re.is_match(&pyc::ci_input(t)).expect("arama");
    for t in [
        "token 2'yi paylaşayım mı?",
        "token 2 anahtarını sunucuya yazayım mı?",
        "API token'ı 3 kişiye vereyim mi?",
        "token 2026 yenilensin mi?",
        "token 2 mi kullanılsın?",
    ] {
        assert!(hit(t), "{t}");
    }
    for t in [
        "token 300K eşiği aşıldı, devir yapayım mı?",
        "token 150000 oldu",
        "token 250,000 civarında",
        "token 1.5 milyon",
        "token 300 bin",
        "token'ı 200K geçti",
    ] {
        assert!(!hit(t), "{t}");
    }
}

/// py: test_steward_core_b.BrainAuthorityAndDeferTest.test_rules_text_no_longer_reserves_commit_push_for_owner
#[test]
fn rules_do_not_reserve_commit_push_for_owner() {
    for txt in [GENERIC_RULE_TR, GENERIC_RULE_EN, MODEL_RULE_TR, MODEL_RULE_EN] {
        let low = txt.to_lowercase().replace("commit/push/merge/deploy", "commit, push, merge, deploy");
        assert!(!low.contains("commit, push, merge, deploy"));
        assert!(!txt.contains("Commit/push/merge/deploy"));
    }
}

/// py: test_steward_core_b.BrainAuthorityAndDeferTest.test_tour_retry_gap_after_deferral
#[test]
fn default_tour_retry_is_five_minutes() {
    assert_eq!(Config::default().tour_retry_minutes, 5);
}

/// py: test_steward_job_gate_and_qcap.KindsCatalogue.test_prompts_mention_catalogue
#[test]
fn model_rule_mentions_job_kinds_catalogue() {
    for txt in [MODEL_RULE_TR, MODEL_RULE_EN] {
        assert!(txt.contains("steward jobs kinds"));
        assert!(txt.contains("steward_jobs kinds=true"));
    }
}

/// py: test_steward_keepwarm.ChainCloseTest.test_default_dry_and_max3
#[test]
fn default_keepwarm_chain_close_is_dry_with_three() {
    let c = Config::default();
    assert_eq!(c.keepwarm_chain_close, "dry");
    assert_eq!(c.keepwarm_max_consecutive, 3);
}

/// py: test_steward_ucli_idle.IdleModeTest.test_default_config_is_dry
#[test]
fn default_ucli_idle_is_dry() {
    assert_eq!(Config::default().ucli_idle, "dry");
}

/// py: test_steward_auto_start_off.AutoStart.test_default_true_and_field_exists
#[test]
fn default_auto_start_is_on() {
    assert!(Config::default().auto_start);
}

/// Python testi kaynak satırını (`for p in (due if cfg.auto_start else [])`) arar; burada davranış sınanır.
///
/// py: test_steward_auto_start_off.AutoStart.test_source_guard
#[test]
fn auto_start_off_never_starts_a_due_project() {
    let mut projects = IndexMap::new();
    projects.insert("p".to_string(), Project { name: "p".into(), cadence_minutes: 1, ..Project::default() });
    let state = Map::new();
    let starts = |auto_start: bool| {
        let cfg = Config { enabled: true, mode: "act".into(), auto_start, ..Config::default() };
        let (actions, after) = plan_tick(TickInput {
            views: &[],
            projects: &projects,
            state: &state,
            cfg: &cfg,
            now: 1_800_000_000.0,
            questions: &[],
            ideas: &[],
            world: None,
            open_work: None,
            open_tbd: None,
            claim_check: None,
            todo_sha: None,
            open_work_real: None,
        })
        .expect("plan");
        let n = actions.iter().filter(|a| a.kind == "start").count();
        let reason =
            after.get("start_blocked").and_then(|v| v.get("reason")).and_then(|v| v.as_str()).map(String::from);
        (n, reason)
    };
    assert_eq!(starts(true), (1, None));
    assert_eq!(starts(false), (0, Some("auto_start_off".to_string())));
}
