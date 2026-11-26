//! `docs/rust-lessons-from-python.md` 2.6 / bölüm 3: saf çekirdeğin verdiği güvencelerin adlı (çoğu NEGATİF) testleri.
//! Davranış Python ile aynıdır (parite ayrıca `tick`, `questions`, `store`, `gates` vektörlerinde).
use cops_steward_core::gates::brain_may_answer;
use cops_steward_core::store::{answer_question, Answered, Minted, Reply};
use cops_steward_core::tick::{plan_tick, TickInput};
use cops_steward_core::types::{Action, Config, Project, Question, SessionView};
use indexmap::IndexMap;
use serde_json::Map;

const NOW: f64 = 1_800_000_000.0;

fn actions(views: &[SessionView], phase: &str, questions: &[Question]) -> Vec<Action> {
    let mut projects = IndexMap::new();
    projects.insert("p".to_string(), Project { name: "p".into(), phase: phase.into(), ..Project::default() });
    let cfg = Config { enabled: true, mode: "act".into(), ..Config::default() };
    let state = Map::new();
    let (acts, _) = plan_tick(TickInput {
        views,
        projects: &projects,
        state: &state,
        cfg: &cfg,
        now: NOW,
        questions,
        ideas: &[],
        world: None,
        open_work: None,
        open_tbd: None,
        claim_check: None,
        todo_sha: None,
        open_work_real: None,
    })
    .expect("plan");
    acts
}

fn answered(answer: &str) -> Question {
    Question {
        id: "q1".into(),
        project: "p".into(),
        text: "başlayayım mı?".into(),
        status: "answered".into(),
        answer: answer.into(),
        answered_at: NOW - 60.0,
        answered_by: "owner_panel".into(),
        ..Question::default()
    }
}

fn kinds(acts: &[Action]) -> Vec<&str> {
    acts.iter().map(|a| a.kind.as_str()).collect()
}

#[test]
fn negative_or_hold_answer_never_opens_a_halted_project() {
    for phase in ["paused", "done"] {
        for answer in ["hayır", "paused kalsın", "Başlamasın", "başlama", "devam etme", "gelene dek beklesin"] {
            let acts = actions(&[], phase, &[answered(answer)]);
            let k = kinds(&acts);
            assert!(!k.contains(&"start") && !k.contains(&"set_phase"), "{phase} {answer}: {k:?}");
            assert!(k.contains(&"close_negative_answer"), "{phase} {answer}: {k:?}");
        }
    }
}

#[test]
fn clearly_positive_answer_opens_a_paused_project() {
    let acts = actions(&[], "paused", &[answered("evet, devam et")]);
    assert_eq!(kinds(&acts), ["set_phase", "start"]);
}

fn big_session(subagent_active: bool) -> SessionView {
    SessionView {
        name: "p".into(),
        running: true,
        tmux: true,
        cwd: "/w".into(),
        cli: "claude".into(),
        busy: Some(false),
        subagent_active,
        context_tokens: Some(900_000),
        started_at: 1.0,
        last_activity: NOW - 60.0,
        ..SessionView::default()
    }
}

#[test]
fn active_subagent_defers_the_threshold_handover() {
    let mut v = big_session(true);
    v.context_tokens = Some(Config::default().context_warn_tokens);
    let k = actions(std::slice::from_ref(&v), "planned", &[]);
    assert!(kinds(&k).contains(&"handover_deferred") && !kinds(&k).contains(&"handover"), "{:?}", kinds(&k));
    v.subagent_active = false;
    assert!(kinds(&actions(&[v], "planned", &[])).contains(&"handover"));
}

#[test]
fn halted_project_gets_no_automatic_handover() {
    for phase in ["paused", "done"] {
        let k = actions(&[big_session(false)], phase, &[]);
        let k = kinds(&k);
        assert!(!k.contains(&"handover") && !k.contains(&"respawn"), "{phase}: {k:?}");
    }
}

#[test]
fn busy_or_subagent_session_gets_no_answer_delivery() {
    for (busy, sub) in [(Some(true), false), (Some(false), true)] {
        let mut v = big_session(sub);
        v.busy = busy;
        v.context_tokens = None;
        let k = actions(&[v], "planned", &[answered("evet")]);
        assert!(!kinds(&k).contains(&"deliver_answer"), "{busy:?} {sub}: {:?}", kinds(&k));
    }
}

#[test]
fn brain_cannot_answer_owner_questions_or_overwrite_an_answered_one() {
    let owner = Question { id: "q".into(), text: "hangisi?".into(), routine: false, ..Question::default() };
    assert!(!brain_may_answer(&owner).0);
    let risky = Question { routine: true, text: "dosyayı sileyim mi?".into(), ..owner };
    assert!(!brain_may_answer(&risky).0);

    let mut qs = vec![answered("sahibin cevabı")];
    let before = qs.clone();
    let mut mint = || -> Minted { panic!("yeni soru üretilmemeli") };
    let reply = Reply { question_id: "q1", answer: "beynin cevabı", by: "brain", only_open: true, prefix: "" };
    assert_eq!(answer_question(&mut qs, reply, NOW, &mut mint), Ok(Answered::Missing));
    assert_eq!(qs, before);
}
