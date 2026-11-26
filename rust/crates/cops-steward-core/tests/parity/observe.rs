//! Grup 4 paritesi: gözlem kipi süzgeci.
use crate::harness::{parity, Case};
use cops_steward_core::observe::observe_filter;
use cops_steward_core::types::Action;
use serde_json::{Map, Value};

type Doc = Map<String, Value>;

parity!("observe_filter", observe_filter_vectors, |c| run(c));

fn run(c: &Case) -> Value {
    let actions: Vec<Action> = c.arg("actions");
    match observe_filter(&actions, &c.str("mode"), &c.arg::<Doc>("state"), c.arg("now")) {
        Ok(got) => serde_json::to_value(got).expect("süzgeç"),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
}
