//! Grup 1 (bildirim, özet, soru sayfası, devir notu) paritesi.
use crate::harness::parity;
use cops_steward_core::consts_gen::PENDING_DIGEST_HOURS;
use cops_steward_core::notify::*;
use cops_steward_core::types::Question;

fn default_sid() -> String {
    "default".to_string()
}

parity!("question_link", question_link_vectors, |c| question_link(
    &c.arg("q"),
    &c.opt::<String>("base").unwrap_or_default(),
    &c.or("sid", default_sid())
));
parity!("ask_hint", ask_hint_vectors, |c| ask_hint(&c.str("question_id"), &c.or("sid", default_sid())));
parity!("ask_prefix", ask_prefix_vectors, |c| ask_prefix(
    &c.opt::<String>("project").unwrap_or_default(),
    &c.or("sid", default_sid()),
    &c.opt::<String>("host").unwrap_or_default()
));
parity!("pending_digest_slot", pending_digest_slot_vectors, |c| {
    pending_digest_slot(c.arg("now"), &c.or("hours", PENDING_DIGEST_HOURS.to_vec()))
});
parity!("pending_digest_text", pending_digest_text_vectors, |c| {
    pending_digest_text(
        &c.arg::<Vec<Question>>("questions"),
        c.arg("now"),
        &c.or("lang", "tr".to_string()),
        &c.or("sid", default_sid()),
    )
});
parity!("question_notification", question_notification_vectors, |c| question_notification(
    &c.arg("q"),
    &c.str("link"),
    &c.or("lang", "tr".to_string()),
    &c.or("sid", default_sid()),
    &c.opt::<String>("host").unwrap_or_default()
));
parity!("question_page_html", question_page_html_vectors, |c| {
    question_page_html(
        c.opt::<Question>("q").as_ref(),
        &c.or("lang", "tr".to_string()),
        &c.or("state", "ask".to_string()),
        &c.or("error", String::new()),
        &c.or("action", String::new()),
    )
});
parity!("handover_questions_note", handover_questions_note_vectors, |c| handover_questions_note(
    &c.arg::<Vec<Question>>("questions"),
    &c.str("name"),
    &c.or("lang", "tr".to_string()),
    &c.or("project", String::new())
));
