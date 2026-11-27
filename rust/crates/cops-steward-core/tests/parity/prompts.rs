//! Grup D (prompt üreticileri, tur hazırlığı) paritesi: kayıtlı vektörler + `fixtures/hand` (parity/hand_cases.py).
use crate::harness::{parity, same, Case};
use cops_steward_core::prompts::*;
use cops_steward_core::types::*;
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

type Items = Vec<Map<String, Value>>;

/// `build_directive`in soru deposu. Kayıtlı vektörlerde depo argüman değildir (Python dosyadan okur): "Önceki cevaplarım"
/// içeren birkaç kayıtta depo, beklenen metnin o bloğundan kurulur (süzme/sıralama `fixtures/hand`de gerçek depoyla sınanır).
fn store(c: &Case, project: &Project) -> Vec<Question> {
    if c.args.contains_key("questions") {
        return c.arg("questions");
    }
    let ret = c.ret.as_str().expect("metin");
    let Some((_, block)) = ["Önceki cevaplarım:\n", "My earlier answers:\n"].iter().find_map(|h| ret.split_once(h))
    else {
        return Vec::new();
    };
    block
        .split("\n\n")
        .next()
        .unwrap_or("")
        .lines()
        .enumerate()
        .map(|(i, line)| {
            let (text, answer) = line.strip_prefix("- ").and_then(|l| l.split_once(" → ")).expect("satır");
            Question {
                id: format!("prior{i}"),
                project: project.name.clone(),
                status: "answered".into(),
                text: text.into(),
                answer: answer.into(),
                answered_at: i as f64,
                ..Question::default()
            }
        })
        .collect()
}

parity!("build_directive", build_directive_vectors, |c| {
    let project: Project = c.arg("project");
    build_directive(
        &project,
        &c.or("lang", "tr".to_string()),
        &c.or("extra", String::new()),
        c.opt::<Question>("answer").as_ref(),
        &c.opt::<Vec<Question>>("more").unwrap_or_default(),
        c.or("compact", false),
        &store(c, &project),
    )
});
// Python negatif `n`de de boş döner; Rust `usize` alır, 0 aynı sonucu verir.
parity!("_clip", p_clip, |c| {
    clip(&c.opt::<String>("text").unwrap_or_default(), usize::try_from(c.arg::<i64>("n")).unwrap_or(0))
});
parity!("card_lines", card_lines_vectors, |c| card_lines(
    &c.arg("card"),
    c.or("tr", true),
    c.opt("now").unwrap_or(c.now)
)
.expect("kart"));
parity!("build_tour_prompt", build_tour_prompt_vectors, |c| {
    build_tour_prompt(
        &c.arg::<Items>("items"),
        &c.or("lang", "tr".to_string()),
        &c.opt::<Vec<Question>>("open_qs").unwrap_or_default(),
        c.opt("now"),
        c.now,
    )
    .expect("tur")
});
parity!("identity_section", identity_section_vectors, |c| {
    identity_section(&c.str("sid"), &c.or("label", String::new()), &c.or("lang", "tr".to_string()))
});
parity!("build_workspace_claude_md", build_workspace_claude_md_vectors, |c| build_workspace_claude_md(
    &c.str("persona"),
    &c.or("lang", "tr".to_string()),
    &c.or("sid", "default".to_string()),
    &c.or("label", String::new()),
    c.or("remote", false),
    &c.or("role", "steward".to_string())
));
parity!("_is_project_session", p_is_project_session, |c| { is_project_session(&c.arg("v"), &c.arg("projects")) });
parity!("phase_model_effort", phase_model_effort_vectors, |c| { phase_model_effort(&c.arg("project"), &c.arg("cfg")) });
parity!("main_session_model_effort", main_session_model_effort_vectors, |c| main_session_model_effort(
    &c.opt::<String>("model").unwrap_or_default(),
    &c.str("effort"),
    &c.str("cli"),
    &c.str("sonnet")
));
parity!("item_signature", item_signature_vectors, |c| item_signature(
    &c.arg("v"),
    &c.arg::<IndexMap<String, Project>>("projects"),
    &c.arg::<Vec<Question>>("questions")
));
parity!("stale_answers", stale_answers_vectors, |c| {
    let questions: Vec<Question> = c.arg("questions");
    let live = c.opt::<BTreeSet<String>>("live").unwrap_or_default();
    let got = stale_answers(&questions, &c.arg("projects"), &c.arg("cfg"), c.arg("now"), &live);
    got.into_iter().cloned().collect::<Vec<_>>()
});
parity!("note_claims", note_claims_vectors, |c| note_claims(&c.opt::<String>("notes").unwrap_or_default()));
parity!("check_note_claims", check_note_claims_vectors, |c| {
    let alive = c.callback("pid_alive").unwrap_or_default();
    let gate = c.callback("gate_ahead").unwrap_or_default();
    check_note_claims(
        &c.str("notes"),
        &|pid| alive.get(&json!([pid]).to_string()).expect("pid_alive kaydı").as_bool(),
        &|| gate.get("[]").expect("gate_ahead kaydı").as_i64(),
        c.or("tr", true),
    )
});
parity!("cut_tour_items", cut_tour_items_vectors, |c| cut_tour_items(
    &c.arg::<Items>("items"),
    &c.or("ask_gate", "off".to_string())
));
parity!("mark_ask_seen", mark_ask_seen_vectors, |c| {
    let before: Map<String, Value> = c.arg("state");
    let mut state = before.clone();
    mark_ask_seen(&mut state, &c.arg::<Items>("items"), c.arg("now")).expect("durum");
    let want = c.after.get("state").cloned().unwrap_or(Value::Object(before));
    assert!(same(&Value::Object(state), &want), "state farkı: {want}");
});

/// py: check_note_claims
#[test]
fn check_note_claims_branches() {
    // Beklenen değerler Python'dan (parity/env.py ile yalıtılmış).
    let notes = "PID 12, PID 34, PID 56; kapıda bekliyor";
    let alive = |pid| match pid {
        12 => Some(false),
        34 => None,
        _ => Some(true),
    };
    let tr = check_note_claims(notes, &alive, &|| Some(0), true);
    assert_eq!(
        tr,
        vec![
            "notta PID 12 \"sürüyor\" deniyor ama bu süreç YOK (ölü); koşu bitmiş olabilir, notu güncelle / işi ilerlet",
            "notta \"kapıda bekliyor\" deniyor ama dal ana dalın İLERİSİNDE değil (0 commit: zaten birleşmiş ya da iş yok); notu düzelt",
        ]
    );
    let en = check_note_claims(notes, &alive, &|| Some(0), false);
    assert_eq!(
        en,
        vec![
            "the note says PID 12 is running but that process is GONE; the run may have finished, update the note / move on",
            "the note says \"waiting at the gate\" but the branch is not ahead of the main branch (0 commits: already merged or nothing to land); fix the note",
        ]
    );
    assert!(check_note_claims("kapıda bekliyor", &alive, &|| None, true).is_empty());
    // kapı iddiası yoksa `gate_ahead` çağrılmaz
    assert!(check_note_claims("x", &alive, &|| panic!("çağrılmamalı"), true).is_empty());
}

/// Python'un istisna fırlattığı bozuk girdiler `Err` döner; `state` değişmez.
#[test]
fn broken_inputs_are_errors() {
    let obj = |v: Value| v.as_object().cloned().expect("nesne");
    for item in [
        json!({"kind": null}),
        json!({"idle_minutes": "1.5"}),
        json!({"goal": 5}),
        json!({"last_exchange": "x"}),
        json!({"contradictions": 3}),
        json!({"similar": ["x"]}),
        json!({"card": [1]}),
        json!({"docs": "x"}),
    ] {
        assert!(build_tour_prompt(&[obj(item.clone())], "tr", &[], None, 0.0).is_err(), "{item}");
    }
    for card in [json!({"updated_at": "x"}), json!({"goal": 1}), json!({"open_tbds": 5}), json!({"blockers": {"a": 1}})]
    {
        assert!(card_lines(&obj(card.clone()), true, 0.0).is_err(), "{card}");
    }
    let ask = vec![obj(json!({"kind": "ask", "id": "a"}))];
    for state in [json!({"ask_seen": [1]}), json!({"ask_seen": {"a": 1}}), json!({"ask_seen": {"a": {"n": "x"}}})] {
        let mut got = obj(state.clone());
        assert!(mark_ask_seen(&mut got, &ask, 1.0).is_err(), "{state}");
        assert_eq!(Value::Object(got), state);
    }
}
