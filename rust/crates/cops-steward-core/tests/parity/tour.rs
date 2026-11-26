//! Grup 2 paritesi: tur maddeleri ve işaretlerin kayıt eylemleri.
use crate::harness::{parity, same, Case};
use cops_steward_core::markers::{clip_words, is_conditional_note, marker_next_work, Markers};
use cops_steward_core::tour::*;
use cops_steward_core::types::{Action, Config, Idea, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

type Doc = Map<String, Value>;
type Projects = IndexMap<String, Project>;

fn text(c: &Case, name: &str) -> String {
    c.opt::<String>(name).unwrap_or_default()
}

parity!("clip_words", clip_words_vectors, |c| clip_words(&text(c, "text"), c.arg("limit")));
parity!("is_conditional_note", is_conditional_note_vectors, |c| is_conditional_note(&text(c, "text")));
parity!("marker_next_work", marker_next_work_vectors, |c| marker_next_work(&text(c, "text")));

parity!("review_items", review_items_vectors, |c| {
    let views: Vec<SessionView> = c.arg("views");
    let projects: Projects = c.arg("projects");
    let cfg: Config = c.arg("cfg");
    let questions: Vec<Question> = c.arg("questions");
    let ideas: Vec<Idea> = c.arg("ideas");
    let skip: BTreeSet<String> = c.opt("skip").unwrap_or_default();
    let lda: IndexMap<String, f64> = c.opt("last_directive_at").unwrap_or_default();
    let reviewed: IndexMap<String, f64> = c.opt("reviewed_at").unwrap_or_default();
    let world: Option<World> = c.opt("world");
    let skip_seen: Doc = c.opt("skip_seen").unwrap_or_default();
    let state: Doc = c.opt("state").unwrap_or_default();
    let mut sigs: Option<IndexMap<String, String>> = c.opt("sigs_out");
    // geri çağrı tablosu: `[[proje], sonuç]`
    let lookup = |table: &Option<std::collections::HashMap<String, Value>>, project: &str| {
        let key = json!([project]).to_string();
        table.as_ref().and_then(|t| t.get(&key)).unwrap_or_else(|| panic!("kayıtsız çağrı: {project}")).clone()
    };
    let (work, claims) = (c.callback("open_work"), c.callback("claim_check"));
    let open_work = |p: &str| lookup(&work, p).as_i64();
    let claim_check = |p: &str| serde_json::from_value::<Vec<String>>(lookup(&claims, p)).expect("liste");
    let got = review_items(TourInput {
        views: &views,
        projects: &projects,
        cfg: &cfg,
        now: c.arg("now"),
        questions: &questions,
        ideas: &ideas,
        skip: &skip,
        last_directive_at: &lda,
        reviewed_at: &reviewed,
        world: world.as_ref(),
        skip_seen: &skip_seen,
        sigs_out: sigs.as_mut(),
        open_work: if work.is_some() { Some(&open_work) } else { None },
        claim_check: if claims.is_some() { Some(&claim_check) } else { None },
        state: &state,
    })
    .expect("maddeler");
    let want = c.after.get("sigs_out").or_else(|| c.args.get("sigs_out")).cloned().unwrap_or(Value::Null);
    assert!(same(&json!(sigs), &want), "sigs_out: {sigs:?} != {want}");
    got
});

parity!("_ask_base", p_ask_base, |c| ask_base(&text(c, "name")).to_string());

parity!("start_decision_event", start_decision_event_vectors, |c| start_decision_event(
    &c.arg::<Vec<Action>>("actions"),
    &c.arg::<Doc>("state")
)
.expect("olay"));

parity!("marker_record_actions", marker_record_actions_vectors, |c| marker_record_actions(
    &c.str("name"),
    &text(c, "proj"),
    &c.arg::<Markers>("m")
));

parity!("note_project_next", note_project_next_vectors, |c| {
    let mut st: Doc = c.arg("st");
    note_project_next(&mut st, &text(c, "proj"), &c.str("session"), &c.arg::<Markers>("m"), c.arg("now")).expect("not");
    let want = c.after.get("st").cloned().unwrap_or_else(|| c.args["st"].clone());
    assert!(same(&Value::Object(st.clone()), &want), "st: {st:?} != {want}");
    json!(null)
});

/// Python `plan_markers` `project_next.at`i `time.time()`tan alır (kaydın `now`undan mikrosaniyeler sonra): saat,
/// Python'un yazdığı yeni `at` değerinden okunur.
fn written_at(c: &Case) -> f64 {
    let old = c.args.get("state").and_then(|s| s.get("project_next"));
    c.ret[1]["project_next"]
        .as_object()
        .into_iter()
        .flatten()
        .find(|(k, v)| old.and_then(|o| o.get(k.as_str())) != Some(*v))
        .and_then(|(_, v)| v["at"].as_f64())
        .unwrap_or(c.now)
}

parity!("plan_markers", plan_markers_vectors, |c| plan_markers(
    &c.arg::<Vec<SessionView>>("views"),
    &c.arg::<Projects>("projects"),
    &c.opt::<Doc>("state").unwrap_or_default(),
    &c.arg::<Config>("cfg"),
    c.opt::<World>("world").as_ref(),
    written_at(c)
)
.expect("tarama"));

/// py: note_project_next, start_decision_event, plan_markers
#[test]
fn bad_state_types_are_errors() {
    let obj = |v: Value| v.as_object().cloned().expect("nesne");
    let m = Markers { next: Some("iş".into()), ..Markers::default() };
    let mut st = obj(json!({"project_next": 7}));
    assert!(note_project_next(&mut st, "p", "s", &m, 1.0).is_err());
    assert!(start_decision_event(&[], &obj(json!({"start_blocked": 7}))).is_err());
    let state = obj(json!({"seen_assistant": 7}));
    assert!(plan_markers(&[], &Projects::new(), &state, &Config::default(), None, 1.0).is_err());
}
