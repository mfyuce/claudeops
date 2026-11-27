//! Grup 3 paritesi: ucli ve claude boşta planları.
use crate::harness::{by_name, parity, Case};
use cops_steward_core::cards::BadValue;
use cops_steward_core::idle::*;
use cops_steward_core::types::{Action, Config, Project, SessionView, World};
use indexmap::IndexMap;
use serde_json::{Map, Value};

type Doc = Map<String, Value>;

/// Vektördeki boşta planı girdileri.
pub struct Owned {
    pub views: Vec<SessionView>,
    pub projects: IndexMap<String, Project>,
    pub state: Doc,
    pub cfg: Config,
    pub now: f64,
    pub planned: Vec<Action>,
    pub world: Option<World>,
}

impl Owned {
    pub fn new(c: &Case, planned: &str) -> Self {
        Owned {
            views: c.arg("views"),
            projects: c.arg("projects"),
            state: c.arg("state"),
            cfg: c.arg("cfg"),
            now: c.arg("now"),
            planned: c.opt(planned).unwrap_or_default(),
            world: c.opt("world"),
        }
    }

    pub fn input(&self) -> IdleInput<'_> {
        IdleInput {
            views: &self.views,
            projects: &self.projects,
            state: &self.state,
            cfg: &self.cfg,
            now: self.now,
            planned: &self.planned,
            world: self.world.as_ref(),
        }
    }
}

fn plan(c: &Case, got: Result<IdlePlan, BadValue>) -> Value {
    match got {
        Ok(p) => serde_json::to_value(p).expect("plan"),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
}

parity!("_forced_open_nudge", p_forced_open_nudge, |c| {
    let table = by_name(c, "oldest_open");
    let oldest = |p: &str| table.as_ref().and_then(|t| t(p).as_str().map(str::to_string));
    let oldest: Option<TextOf<'_>> = if table.is_some() { Some(&oldest) } else { None };
    forced_open_nudge(oldest, &c.str("proj"), c.arg("n_open"))
});

parity!("plan_ucli_idle", plan_ucli_idle_vectors, |c| {
    let owned = Owned::new(c, "planned");
    let table = by_name(c, "open_work");
    let open_work = |p: &str| table.as_ref().and_then(|t| t(p).as_i64());
    let got = plan_ucli_idle(owned.input(), if table.is_some() { Some(&open_work) } else { None });
    plan(c, got)
});

parity!("plan_claude_idle", plan_claude_idle_vectors, |c| {
    let owned = Owned::new(c, "planned");
    let names = ["open_work", "owner_todo", "todo_sha", "oldest_open", "has_question"];
    let [work, owner, sha, oldest, question] = names.map(|n| by_name(c, n));
    let open_work = |p: &str| work.as_ref().and_then(|t| t(p).as_i64());
    let owner_todo = |p: &str| owner.as_ref().and_then(|t| t(p).as_i64());
    let todo_sha = |p: &str| sha.as_ref().and_then(|t| t(p).as_str().map(str::to_string));
    let oldest_open = |p: &str| oldest.as_ref().and_then(|t| t(p).as_str().map(str::to_string));
    let has_question = |p: &str| question.as_ref().and_then(|t| t(p).as_bool());
    let mut calls = IdleCallbacks::default();
    if work.is_some() {
        calls.open_work = Some(&open_work);
    }
    if owner.is_some() {
        calls.owner_todo = Some(&owner_todo);
    }
    if sha.is_some() {
        calls.todo_sha = Some(&todo_sha);
    }
    if oldest.is_some() {
        calls.oldest_open = Some(&oldest_open);
    }
    if question.is_some() {
        calls.has_question = Some(&has_question);
    }
    plan(c, plan_claude_idle(owned.input(), calls))
});
