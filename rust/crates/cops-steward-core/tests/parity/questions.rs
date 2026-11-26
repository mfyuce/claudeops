//! Grup 1 (soru okumaları) paritesi. Elle testlerdeki beklenen değerler Python davranışıdır.
use crate::harness::{as_set, parity, py_error, Case};
use cops_steward_core::questions::*;
use cops_steward_core::types::Question;
use serde_json::Value;
use std::collections::BTreeSet;

fn resolve(c: &Case) -> Value {
    match resolve_answer(&c.arg::<Question>("q"), &c.str("raw")) {
        Ok(s) => Value::from(s),
        Err(e @ ResolveError::NotAnInt(_)) => py_error("ValueError", e),
        Err(e @ ResolveError::MultiCharUpper(_)) => py_error("TypeError", e),
    }
}

fn now_of(c: &Case) -> f64 {
    c.opt("now").unwrap_or(c.now)
}

/// `find_*` işlevlerinin ortak argümanları.
fn find(c: &Case, f: Finder) -> Option<Question> {
    let qs: Vec<Question> = c.arg("questions");
    f(&qs, &c.str("project"), &c.str("text"), now_of(c)).cloned()
}

type Finder = for<'a> fn(&'a [Question], &str, &str, f64) -> Option<&'a Question>;

parity!("normalize_options", normalize_options_vectors, |c| {
    normalize_options(c.args.get("options").expect("options"))
});
parity!("resolve_answer", resolve_answer_vectors, |c| resolve(c));
parity!("is_defer_answer", is_defer_answer_vectors, |c| { is_defer_answer(&c.str("raw")) });
parity!("_words", p_words, |c| as_set(c, words(&c.str("text"))));
parity!("_salient", p_salient, |c| as_set(c, salient(&c.str("text"))));
parity!("topic_tokens", topic_tokens_vectors, |c| as_set(c, topic_tokens(&c.str("text"))));
parity!("_question_sentences", p_question_sentences, |c| as_set(c, question_sentences(&c.str("text"))));
parity!("_strong_topic", p_strong_topic, |c| strong_topic(&c.str("tok")));
parity!("topic_match", topic_match_vectors, |c| topic_match(
    &c.arg::<BTreeSet<String>>("a"),
    &c.arg::<BTreeSet<String>>("b")
));
parity!("similar_answers", similar_answers_vectors, |c| {
    let qs: Vec<Question> = c.arg("questions");
    let found = similar_answers(
        &c.str("text"),
        &qs,
        &c.or("project", String::new()),
        &c.or("exclude_id", String::new()),
        c.or("limit", 6),
    );
    found.into_iter().cloned().collect::<Vec<_>>()
});
parity!("find_answered_duplicate", find_answered_duplicate_vectors, |c| find(c, |q, p, t, now| {
    find_answered_duplicate(q, p, t, now)
}));
parity!("find_open_similar", find_open_similar_vectors, |c| find(c, |q, p, t, now| find_open_similar(q, p, t, now)));
parity!("find_open_topic", find_open_topic_vectors, |c| find(c, |q, p, t, now| find_open_topic(q, p, t, now)));
parity!("find_open_same_ask", find_open_same_ask_vectors, |c| find(c, |q, p, t, now| find_open_same_ask(q, p, t, now)));
parity!("find_answered_hold", find_answered_hold_vectors, |c| find(c, |q, p, t, now| find_answered_hold(q, p, t, now)));
parity!("paused_sweep_text", paused_sweep_text_vectors, |c| {
    paused_sweep_text(&c.str("project"), c.args.get("open_items").expect("open_items"))
});
parity!("recent_answers", recent_answers_vectors, |c| {
    let qs: Vec<Question> = c.arg("questions");
    let found = recent_answers(&c.str("project"), &c.or("exclude_id", String::new()), c.or("limit", 5), &qs);
    found.into_iter().cloned().collect::<Vec<_>>()
});
parity!("find_question", find_question_vectors, |c| {
    let qs: Vec<Question> = c.arg("questions");
    find_question(&c.str("question_id"), &qs).cloned()
});
parity!("open_questions", open_questions_vectors, |c| {
    let qs: Vec<Question> = c.arg("questions");
    open_questions(&qs).into_iter().cloned().collect::<Vec<_>>()
});
parity!("undelivered_answers", undelivered_answers_vectors, |c| {
    let qs: Vec<Question> = c.arg("questions");
    undelivered_answers(&qs).into_iter().cloned().collect::<Vec<_>>()
});
