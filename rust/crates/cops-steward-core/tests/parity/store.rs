//! Grup 1 (depo karar çekirdekleri) paritesi: vektör = Python argümanları + önceki belge + üretilen kimlikler; `after` =
//! sonraki belge.
use crate::harness::{parity, py_error, same, Case};
use cops_steward_core::cards::*;
use cops_steward_core::identity::OwnershipIndex;
use cops_steward_core::store::*;
use cops_steward_core::types::{Idea, Project, Question};
use indexmap::IndexMap;
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

/// Çağrı sonrası belge Python'unkiyle aynı olmalı.
fn check_after<T: Serialize>(c: &Case, key: &str, got: &T) {
    let got = serde_json::to_value(got).expect("belge");
    let want = c.after.get(key).cloned().unwrap_or(Value::Null);
    assert!(same(&got, &want), "{key} sonrası farklı\n args: {:?}\n python: {want}\n rust:   {got}", c.args);
}

fn json_of<T: Serialize>(v: &T) -> Value {
    serde_json::to_value(v).expect("serileştirme")
}

/// Python'un ürettiği kimlikleri sırayla verir.
fn minter(c: &Case) -> impl FnMut() -> Minted {
    let mut ids = c.or("_ids", Vec::<String>::new()).into_iter();
    let mut keys = c.or("_keys", Vec::<String>::new()).into_iter();
    move || Minted { id: ids.next().expect("kimlik"), key: keys.next().expect("anahtar") }
}

fn docs<T: DeserializeOwned>(c: &Case) -> T {
    c.arg("questions")
}

/// Soru belgesini değiştiren işlev: oynat, belgeyi karşılaştır.
fn on_questions(c: &Case, f: impl FnOnce(&mut Vec<Question>) -> Value) -> Value {
    let mut qs: Vec<Question> = docs(c);
    let ret = f(&mut qs);
    check_after(c, "questions", &qs);
    ret
}

fn text(c: &Case, name: &str) -> String {
    c.opt::<String>(name).unwrap_or_default()
}

fn add(c: &Case, qs: &mut Vec<Question>) -> Result<Added, EmptyText> {
    let (project, body, source, detail) = (text(c, "project"), text(c, "text"), text(c, "source"), text(c, "detail"));
    let options = c.args.get("options").cloned().unwrap_or(Value::Null);
    let ask = Ask {
        project: &project,
        text: &body,
        source: &source,
        options: &options,
        routine: c.or("routine", false),
        detail: &detail,
    };
    let before = qs.clone();
    let added = add_question_ex(qs, ask, c.now, &mut minter(c));
    if !added.as_ref().is_ok_and(|a| a.dirty) {
        assert_eq!(&before, qs, "kaydetme gerekmiyorsa belge değişmemeli");
    }
    added
}

parity!("add_question_ex", add_question_ex_vectors, |c| on_questions(c, |qs| match add(c, qs) {
    Ok(a) => json!([qs[a.index], a.kind.as_str()]),
    Err(e) => py_error("ValueError", e),
}));
parity!("add_question", add_question_vectors, |c| on_questions(c, |qs| {
    let (project, body, source, detail) = (text(c, "project"), text(c, "text"), text(c, "source"), text(c, "detail"));
    let options = c.args.get("options").cloned().unwrap_or(Value::Null);
    let ask = Ask {
        project: &project,
        text: &body,
        source: &source,
        options: &options,
        routine: c.or("routine", false),
        detail: &detail,
    };
    match add_question(qs, ask, c.now, &mut minter(c)) {
        Ok(q) => json_of(&q),
        Err(e) => py_error("ValueError", e),
    }
}));
parity!("set_question_detail", set_question_detail_vectors, |c| {
    on_questions(c, |qs| Value::from(set_question_detail(qs, &c.str("question_id"), &text(c, "detail"))))
});
parity!("answer_question", answer_question_vectors, |c| on_questions(c, |qs| {
    let (id, answer, by, prefix) = (c.str("question_id"), c.str("answer"), text(c, "by"), text(c, "prefix"));
    let reply =
        Reply { question_id: &id, answer: &answer, by: &by, only_open: c.or("only_open", false), prefix: &prefix };
    match answer_question(qs, reply, c.now, &mut minter(c)) {
        Ok(Answered::Missing) => Value::Null,
        Ok(Answered::Deferred(i)) => json_of(&qs[i]),
        Ok(Answered::Done { index, review_where }) => {
            assert_eq!(review_where, qs[index].source == "reviewer-where");
            json_of(&qs[index])
        }
        Err(e @ AnswerError::Resolve(cops_steward_core::questions::ResolveError::MultiCharUpper(_))) => {
            py_error("TypeError", e)
        }
        Err(e) => py_error("ValueError", e),
    }
}));
parity!("set_answered_by", set_answered_by_vectors, |c| on_questions(c, |qs| {
    match set_answered_by(qs, &c.arg::<Vec<String>>("ids"), &c.str("by")) {
        Ok(done) => json_of(&done),
        Err(e) => py_error("ValueError", e),
    }
}));
parity!("mark_notified", mark_notified_vectors, |c| on_questions(c, |qs| {
    mark_notified(qs, &c.str("question_id"), c.now);
    Value::Null
}));
parity!("escalate_routine", escalate_routine_vectors, |c| {
    on_questions(c, |qs| {
        let hit = escalate_routine(qs, &c.str("question_id"));
        json_of(&hit.map(|i| &qs[i]))
    })
});
parity!("mark_delivered", mark_delivered_vectors, |c| on_questions(c, |qs| {
    mark_delivered(qs, &c.str("question_id"), c.now);
    Value::Null
}));
parity!("mark_undeliverable", mark_undeliverable_vectors, |c| {
    on_questions(c, |qs| Value::from(mark_undeliverable(qs, &c.str("question_id"), &text(c, "reason"), c.now)))
});

fn on_ideas(c: &Case, f: impl FnOnce(&mut Vec<Idea>) -> Value) -> Value {
    let mut ideas: Vec<Idea> = c.arg("ideas");
    let ret = f(&mut ideas);
    check_after(c, "ideas", &ideas);
    ret
}

parity!("add_idea", add_idea_vectors, |c| on_ideas(c, |ideas| {
    let mut ids = c.or("_ids", Vec::<String>::new()).into_iter();
    let mut mint = move || ids.next().expect("kimlik");
    match add_idea(ideas, &c.str("text"), &text(c, "source"), &text(c, "project"), c.now, &mut mint) {
        Ok(i) => json_of(&ideas[i]),
        Err(e) => py_error("ValueError", e),
    }
}));
parity!("update_idea", update_idea_vectors, |c| on_ideas(c, |ideas| {
    let (status, project, reason) = (c.opt::<String>("status"), c.opt::<String>("project"), c.opt::<String>("reason"));
    let update = IdeaUpdate { status: status.as_deref(), project: project.as_deref(), reason: reason.as_deref() };
    let hit = update_idea(ideas, &c.str("idea_id"), update);
    json_of(&hit.map(|i| &ideas[i]))
}));
parity!("record_idea_export", record_idea_export_vectors, |c| {
    on_ideas(c, |ideas| {
        let hit = record_idea_export(ideas, &c.str("idea_id"), &c.arg("record"));
        json_of(&hit.map(|i| &ideas[i]))
    })
});

parity!("_clear_project_state", p_clear_project_state, |c| {
    let mut state: Map<String, Value> = c.arg("state");
    let gone = clear_project_state(&c.str("name"), &c.arg("projects"), &mut state);
    check_after(c, "state", &state);
    gone
});

fn upsert(c: &Case) -> Value {
    let mut projects: IndexMap<String, Project> = c.arg("projects");
    let sid = c.str("sid");
    let reviewers: BTreeSet<String> = c.arg::<bool>("reviewer").then(|| sid.clone()).into_iter().collect();
    let known: bool = c.arg("host_known");
    let owner: Option<String> = c.opt("owner_elsewhere");
    let index: OwnershipIndex = c.opt("index").unwrap_or_default();
    let busy: Option<bool> = c.opt("running");
    let host_known = |_: &str| known;
    let owner_elsewhere = |_: &str| owner.clone();
    let index_of = || index.clone();
    let running = || busy;
    let expanduser = |p: &str| match p.strip_prefix('~') {
        Some(rest) => format!("/home/x{rest}"),
        None => p.to_string(),
    };
    let ctx = UpsertContext {
        sid: &sid,
        reviewers: &reviewers,
        host_known: &host_known,
        owner_elsewhere: &owner_elsewhere,
        index: &index_of,
        running: if c.arg("running_given") { Some(&running) } else { None },
        expanduser: &expanduser,
        force: c.or("force", false),
        now: c.now,
    };
    let result = upsert_project(&mut projects, &c.str("name"), &c.arg("fields"), &ctx);
    check_after(c, "projects", &projects);
    match result {
        Ok(done) => {
            assert_eq!(done.host_changed, c.after["cleared"] == Value::Bool(true), "{:?}", c.args);
            assert_eq!(json_of(&done.auto_label_via), c.after["auto_label_via"], "{:?}", c.args);
            json_of(&done.project)
        }
        Err(e) => {
            let class = match e {
                UpsertError::InvalidName(_) => "ValueError",
                UpsertError::Reviewer(_) => "ReviewerRefused",
                UpsertError::Host(_) => "HostChangeRefused",
                UpsertError::Owned(_) => "OwnedElsewhere",
                UpsertError::Reserved(_) => "ReservedName",
                UpsertError::BadType(_) => "BadType",
            };
            py_error(class, e)
        }
    }
}

parity!("upsert_project", upsert_project_vectors, |c| upsert(c));

parity!("make_card", make_card_vectors, |c| make_card(
    &c.arg("raw"),
    c.opt::<Map<String, Value>>("parsed").as_ref(),
    c.opt::<Project>("project").as_ref(),
    c.opt("now").unwrap_or(c.now),
    c.opt::<Map<String, Value>>("meta").as_ref()
));
parity!("mark_card_stale", mark_card_stale_vectors, |c| {
    let mut card: Option<Map<String, Value>> = c.opt("card");
    let changed = mark_card_stale(card.as_mut());
    check_after(c, "card", &card);
    changed
});
parity!("note_card_failure", note_card_failure_vectors, |c| {
    let mut card: Option<Map<String, Value>> = c.opt("card");
    note_card_failure(card.as_mut(), &c.str("source_hash"), &text(c, "error"), c.opt("now").unwrap_or(c.now));
    check_after(c, "card", &card);
    Value::Null
});

/// py: HostChangeRefused
#[test]
fn error_messages() {
    assert_eq!(HostChangeRefused("m".into()).to_string(), "m");
    assert_eq!(EmptyText("idea").to_string(), "empty idea");
    assert_eq!(BadAnsweredBy.to_string(), "bad answered_by");
    assert_eq!(UpsertError::InvalidName("A'".into()).to_string(), "invalid project name: \"A'\"");
}

/// Python yanlış tipli alanı olduğu gibi saklar; tipli yapı reddeder ve hiçbir şey değişmez.
///
/// py: upsert_project
#[test]
fn wrong_field_type_is_rejected_without_changes() {
    let mut projects: IndexMap<String, Project> = IndexMap::new();
    let (reviewers, known, owner) = (BTreeSet::new(), |_: &str| true, |_: &str| None);
    let (index, expand) = (OwnershipIndex::default, |p: &str| p.to_string());
    let ctx = UpsertContext {
        sid: "default",
        reviewers: &reviewers,
        host_known: &known,
        owner_elsewhere: &owner,
        index: &index,
        running: None,
        expanduser: &expand,
        force: false,
        now: 1.0,
    };
    let fields = json!({"priority": 1, "goal": 5}).as_object().cloned().expect("nesne");
    assert_eq!(upsert_project(&mut projects, "pr", &fields, &ctx), Err(UpsertError::BadType("goal".into())));
    assert!(projects.is_empty());
}
