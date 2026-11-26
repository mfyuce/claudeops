//! Grup 3 paritesi: "neden ilerlemiyor" açıklaması.
use crate::harness::{by_name, parity, Case};
use crate::idle::Owned;
use cops_steward_core::explain::*;
use cops_steward_core::types::{Project, Question};
use serde_json::{Map, Value};

type Doc = Map<String, Value>;

parity!("_why", p_why, |c| why(
    &c.str("code"),
    &c.str("lang"),
    &c.opt::<String>("detail").unwrap_or_default(),
    c.opt::<Doc>("extra").unwrap_or_default()
));

fn run_with<T>(c: &Case, call: impl FnOnce(&ExplainInput<'_>) -> T) -> T {
    let owned = Owned::new(c, "actions");
    let questions: Vec<Question> = c.arg("questions");
    let table = by_name(c, "open_work");
    let open_work = |p: &str| table.as_ref().and_then(|t| t(p).as_i64());
    let open_work: Option<cops_steward_core::tour::OpenWork<'_>> =
        if table.is_some() { Some(&open_work) } else { None };
    call(&ExplainInput::from_idle(owned.input(), &questions, open_work))
}

parity!("explain_idle", explain_idle_vectors, |c| {
    let proj: Project = c.arg("proj");
    match run_with(c, |input| explain_idle(&proj, input)) {
        Ok(d) => Value::Object(d),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
});

parity!("explain_idle_all", explain_idle_all_vectors, |c| {
    let table = by_name(c, "owner_todo");
    let owner_todo = |p: &str| table.as_ref().and_then(|t| t(p).as_i64());
    let got = run_with(c, |input| explain_idle_all(input, if table.is_some() { Some(&owner_todo) } else { None }));
    match got {
        Ok(d) => serde_json::to_value(d).expect("harita"),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
});
