//! Grup 1 (TODO/TBD ekleme) paritesi.
use crate::harness::parity;
use cops_steward_core::inserts::*;

parity!("tbd_insert_answer", tbd_insert_answer_vectors, |c| {
    tbd_insert_answer(
        &c.str("text"),
        &c.str("qid"),
        &c.opt::<String>("q_text").unwrap_or_default(),
        &c.str("answer"),
        &c.str("date"),
    )
});
parity!("answer_has_action", answer_has_action_vectors, |c| { answer_has_action(&c.str("answer")) });
parity!("todo_insert_directive", todo_insert_directive_vectors, |c| todo_insert_directive(
    &c.str("body"),
    &c.str("did"),
    &c.str("summary"),
    &c.str("date")
));
parity!("todo_insert_answer", todo_insert_answer_vectors, |c| {
    todo_insert_answer(&c.str("text"), &c.str("qid"), &c.str("answer"), &c.str("date"))
});
