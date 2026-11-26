//! Grup 2 paritesi: iş/cevap kapıları, generic rolü, ASK kapısının belirlenimci kısmı.
use crate::harness::{parity, Case};
use cops_steward_core::ask::*;
use cops_steward_core::gates::*;
use cops_steward_core::generic::*;
use cops_steward_core::identity::StewardPaths;
use cops_steward_core::types::{Config, Project, Question, SessionView, World};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use std::collections::BTreeSet;

type Doc = Map<String, Value>;
type Projects = IndexMap<String, Project>;

fn text(c: &Case, name: &str) -> String {
    c.opt::<String>(name).unwrap_or_default()
}

parity!("job_request_gate", job_request_gate_vectors, |c| job_request_gate(
    &c.arg::<Question>("q"),
    &text(c, "answer"),
    &c.arg::<Vec<Doc>>("jobs")
)
.expect("kapı"));

parity!("is_readonly_job_request", is_readonly_job_request_vectors, |c| is_readonly_job_request(&text(c, "text")));

parity!("brain_may_answer", brain_may_answer_vectors, |c| brain_may_answer(&c.arg::<Question>("q")));

parity!("owner_pending_block", owner_pending_block_vectors, |c| owner_pending_block(
    &c.arg::<BTreeSet<String>>("keys"),
    &c.arg::<Vec<Question>>("questions"),
    &c.arg::<Doc>("denied")
));

parity!("directive_defer_reason", directive_defer_reason_vectors, |c| directive_defer_reason(
    c.opt("busy"),
    c.arg("last_directive_at"),
    c.arg("now"),
    c.or("gap", 90.0)
));

parity!("job_marker_verdict", job_marker_verdict_vectors, |c| job_marker_verdict(
    &text(c, "body"),
    c.opt::<Vec<Value>>("known_kinds").as_deref(),
    c.arg("services_registered")
));

parity!("_ask_is_status_line", p_ask_is_status_line, |c| ask_is_status_line(&text(c, "q")));

parity!("brain_mcp_path", brain_mcp_path_vectors, |c| brain_mcp_path(&c.arg::<StewardPaths>("paths")));

parity!("brain_tools_missing_text", brain_tools_missing_text_vectors, |c| brain_tools_missing_text(&text(c, "text")));

parity!("brain_notools_verdict", brain_notools_verdict_vectors, |c| brain_notools_verdict(
    c.arg("prev_tour"),
    &c.arg::<IndexMap<String, f64>>("mcp"),
    &text(c, "last_text"),
    c.arg("nocall"),
    &c.arg::<Config>("cfg"),
    c.arg("now")
));

/// py: panic_path
#[test]
fn panic_path_is_under_default_root() {
    // beklenen: `os.path.join(paths_for("default").root, "PANIC")`
    assert_eq!(panic_path("/d/steward").as_deref(), Ok("/d/steward/PANIC"));
    assert_eq!(panic_path("/d/steward/").as_deref(), Ok("/d/steward/PANIC"));
}

parity!("is_generic", is_generic_vectors, |c| is_generic(&c.arg::<Config>("cfg")));

parity!("is_upper_tier", is_upper_tier_vectors, |c| is_upper_tier(&text(c, "model"), &text(c, "effort")));

parity!("is_claude_model", is_claude_model_vectors, |c| is_claude_model(&text(c, "model")));

parity!("upper_main_views", upper_main_views_vectors, |c| upper_main_views(
    &c.arg::<Vec<SessionView>>("views"),
    &c.arg::<Projects>("projects"),
    &c.arg::<Config>("cfg"),
    c.opt::<World>("world").as_ref()
));

parity!("upper_main_text", upper_main_text_vectors, |c| upper_main_text(
    &c.str("project"),
    &text(c, "model"),
    &text(c, "effort"),
    &c.or("lang", "tr".to_string())
));

parity!("upper_tier_tag", upper_tier_tag_vectors, |c| upper_tier_tag(
    &c.str("project"),
    &text(c, "model"),
    &text(c, "effort")
));

parity!("upper_tier_question_text", upper_tier_question_text_vectors, |c| upper_tier_question_text(
    &c.str("project"),
    &text(c, "model"),
    &text(c, "effort"),
    &c.or("lang", "tr".to_string())
));

parity!("upper_tier_approved", upper_tier_approved_vectors, |c| upper_tier_approved(
    &c.arg::<Vec<Question>>("questions"),
    &c.str("project"),
    &text(c, "model"),
    &text(c, "effort")
));

parity!("generic_backlog", generic_backlog_vectors, |c| generic_backlog(
    &text(c, "todo_text"),
    &text(c, "tbd_text"),
    c.opt::<Doc>("card").as_ref()
)
.expect("liste"));

fn eligible(c: &Case) -> bool {
    tour_eligible(
        &c.arg::<Question>("q"),
        &c.arg::<Projects>("projects"),
        &c.arg::<Config>("cfg"),
        &c.opt::<Doc>("state").unwrap_or_default(),
        c.arg("now"),
    )
    .expect("uygunluk")
}

parity!("steward_ask.tour_eligible", steward_ask_tour_eligible, |c| eligible(c));
parity!("tour_eligible", tour_eligible_hand, |c| eligible(c));

parity!("owner_class", owner_class_vectors, |c| owner_class(
    &c.arg::<Question>("q"),
    &text(c, "owner_projects"),
    &text(c, "note"),
    c.arg("now")
));

parity!("blocked_reason", blocked_reason_vectors, |c| blocked_reason(
    &c.arg::<Question>("q"),
    &c.arg::<Projects>("projects"),
    &c.arg::<Config>("cfg"),
    c.arg("now")
));

/// py: brain_may_answer, is_context_question
#[test]
fn long_texts_stay_within_regex_limits() {
    // Python `re`de geri izleme sınırı yok: uzun metinde de aynı sonuç (kapalı yöne düşme DEĞİL, gerçek eşleşme).
    let long = "sıradan bir cümle, token bütçe 5 ve bağlam token ölçümü. ".repeat(600);
    let mut q = Question { routine: true, text: long.clone(), ..Question::default() };
    assert_eq!(brain_may_answer(&q), (true, ""));
    q.text.push_str(" dosyayı sil");
    assert!(!brain_may_answer(&q).0);
    let ctx = format!("{long} bu oturumda mı sürdüreyim, devir mi?");
    assert!(cops_steward_core::closing::is_context_question(&ctx));
    assert!(brain_tools_missing_text(&format!("{long} karar veremedim")));
    assert!(!brain_tools_missing_text(&long));
}

/// py: job_request_gate, tour_eligible
#[test]
fn bad_values_are_errors() {
    let obj = |v: Value| v.as_object().cloned().expect("nesne");
    let q = Question {
        project: "p".into(),
        text: format!("{}embed a", cops_steward_core::consts_gen::JOB_REQUEST_PREFIX),
        ..Question::default()
    };
    let jobs = [obj(serde_json::json!({"project": "p", "created_at": "x"}))];
    assert!(job_request_gate(&q, "devam", &jobs).is_err());
    let open = Question { status: "open".into(), ..q };
    for state in [serde_json::json!({"ask_gated": 1}), serde_json::json!({"ask_seen": 1})] {
        assert!(tour_eligible(&open, &Projects::new(), &Config::default(), &obj(state), 1.0).is_err());
    }
}

// Python testlerinden kaydedilen çağrılar (`now` verilmezse kayıt anı).
parity!("steward_ask.owner_class", steward_ask_owner_class, |c| owner_class(
    &c.arg::<Question>("q"),
    &text(c, "owner_projects"),
    &text(c, "note"),
    c.opt("now").unwrap_or(c.now)
));

parity!("steward_ask.blocked_reason", steward_ask_blocked_reason, |c| blocked_reason(
    &c.arg::<Question>("q"),
    &c.arg::<Projects>("projects"),
    &c.arg::<Config>("cfg"),
    c.opt("now").unwrap_or(c.now)
));
