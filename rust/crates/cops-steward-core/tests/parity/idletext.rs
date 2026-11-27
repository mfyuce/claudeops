//! Grup 3 paritesi: boşta kararlarının metin okuyucuları.
use crate::harness::{as_set, by_name, parity, Case};
use cops_steward_core::idletext::*;
use cops_steward_core::types::{Config, Project, Question};
use serde_json::json;

fn text(c: &Case, name: &str) -> String {
    c.opt::<String>(name).unwrap_or_default()
}

fn lang(c: &Case) -> String {
    c.or("lang", "tr".to_string())
}

parity!("next_none_stated", next_none_stated_vectors, |c| next_none_stated(&text(c, "text")));
parity!("turn_failed", turn_failed_vectors, |c| turn_failed(&text(c, "text")));
parity!("waiting_for_gate", waiting_for_gate_vectors, |c| waiting_for_gate(&text(c, "text")));
parity!("one_line", one_line_vectors, |c| one_line(&text(c, "text"), c.or("limit", 400)));
parity!("notes_wait", notes_wait_vectors, |c| notes_wait(&c.arg::<Project>("proj")));
parity!("ucli_idle_threshold", ucli_idle_threshold_vectors, |c| ucli_idle_threshold(
    &c.arg::<Config>("cfg"),
    &text(c, "cache_ttl")
));
parity!("is_negative_answer", is_negative_answer_vectors, |c| is_negative_answer(&text(c, "text")));
parity!("is_open_answer", is_open_answer_vectors, |c| is_open_answer(&text(c, "text")));
parity!("_held_instruction_item", p_held_instruction_item, |c| held_instruction_item(&c.arg::<Question>("q")));
parity!("expired_handover_note", expired_handover_note_vectors, |c| expired_handover_note(
    &text(c, "last_assistant"),
    &lang(c)
));
parity!("is_fable_polish", is_fable_polish_vectors, |c| is_fable_polish(&text(c, "text")));

parity!("next_work_hint", next_work_hint_vectors, |c| {
    let table = by_name(c, "open_work");
    let open_work = |p: &str| table.as_ref().and_then(|t| t(p).as_i64());
    next_work_hint(
        &c.arg::<Project>("proj"),
        if table.is_some() { Some(&open_work) } else { None },
        c.or("real_only", false),
    )
});

parity!("_note_words", p_note_words, |c| as_set(c, note_words(&text(c, "text"))));
parity!("stale_next_note", stale_next_note_vectors, |c| stale_next_note(
    &text(c, "notes"),
    &text(c, "todo_text"),
    &text(c, "done_text")
));

parity!("without_stale_note", without_stale_note_vectors, |c| {
    let proj: Project = c.arg("proj");
    let got = without_stale_note(&proj, &text(c, "todo_text"), &lang(c), &text(c, "done_text"));
    json!(*got)
});

parity!("next_line", next_line_vectors, |c| next_line(&text(c, "text")));
parity!("_last_next_line", p_last_next_line, |c| {
    let t = text(c, "text");
    last_next_line(&t).map(|(what, tail)| (what.to_string(), tail.iter().map(ToString::to_string).collect::<Vec<_>>()))
});
parity!("stated_next_work", stated_next_work_vectors, |c| stated_next_work(&text(c, "text")));
parity!("owner_wait", owner_wait_vectors, |c| owner_wait(&text(c, "text")));
parity!("_done_at_line_end", p_done_at_line_end, |c| done_at_line_end(&text(c, "line")));
parity!("idle_finish_marker", idle_finish_marker_vectors, |c| idle_finish_marker(&text(c, "text")));
