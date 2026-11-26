//! Grup 5 paritesi: `plan_tick` (kayıtlı vektörler + `fixtures/hand`) ve altın tick (`py/tests/steward_golden_tick.json`).
use crate::harness::{by_name, parity, same, Case};
use cops_steward_core::cards::BadValue;
use cops_steward_core::identity::build_ownership_index;
use cops_steward_core::tick::{plan_tick, TickInput, TickPlan};
use cops_steward_core::types::{Config, Idea, Project, Question, SessionView, World};
use cops_steward_core::world::world_for;
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::path::PathBuf;

type Doc = Map<String, Value>;

fn plan(c: &Case, got: Result<TickPlan, BadValue>) -> Value {
    match got {
        Ok(p) => serde_json::to_value(p).expect("plan"),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
}

/// Python `str(todo_sha(p) or "")`: kayıtsız çağrı = geri çağrı istisna fırlattı (Python yutar).
fn sha_of(table: &Option<std::collections::HashMap<String, Value>>, p: &str) -> Option<String> {
    let v = table.as_ref()?.get(&json!([p]).to_string())?;
    match v {
        Value::String(s) => Some(s.clone()),
        Value::Null | Value::Bool(false) => None,
        other => Some(cops_steward_core::pyc::str_of(other)),
    }
}

parity!("plan_tick", plan_tick_vectors, |c| {
    let views: Vec<SessionView> = c.arg("views");
    let projects: IndexMap<String, Project> = c.arg("projects");
    let state: Doc = c.opt("state").unwrap_or_default();
    let cfg: Config = c.arg("cfg");
    let questions: Vec<Question> = c.arg("questions");
    let ideas: Vec<Idea> = c.arg("ideas");
    let world: Option<World> = c.opt("world");
    let names = ["open_work", "open_tbd", "claim_check", "open_work_real"];
    let [work, tbd, claims, real] = names.map(|n| by_name(c, n));
    let sha = c.callback("todo_sha");
    let open_work = |p: &str| work.as_ref().and_then(|t| t(p).as_i64());
    let open_tbd = |p: &str| tbd.as_ref().and_then(|t| t(p).as_i64());
    let open_work_real = |p: &str| real.as_ref().and_then(|t| t(p).as_i64());
    let claim_check = |p: &str| {
        claims.as_ref().map(|t| serde_json::from_value::<Vec<String>>(t(p)).expect("liste")).unwrap_or_default()
    };
    let todo_sha = |p: &str| sha_of(&sha, p);
    let got = plan_tick(TickInput {
        views: &views,
        projects: &projects,
        state: &state,
        cfg: &cfg,
        now: c.arg("now"),
        questions: &questions,
        ideas: &ideas,
        world: world.as_ref(),
        open_work: if work.is_some() { Some(&open_work) } else { None },
        open_tbd: if tbd.is_some() { Some(&open_tbd) } else { None },
        claim_check: if claims.is_some() { Some(&claim_check) } else { None },
        todo_sha: if sha.is_some() || c.args.contains_key("todo_sha") { Some(&todo_sha) } else { None },
        open_work_real: if real.is_some() { Some(&open_work_real) } else { None },
    });
    // girdi `state` değişmez (Python kopya üzerinde çalışır)
    assert!(c.after.get("state").is_none(), "Python state'i yerinde değiştirdi?");
    plan(c, got)
});

// ── altın tick ────────────────────────────────────────────────────────────────

fn read_json(path: PathBuf) -> Value {
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).expect("JSON")
}

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// `_ser(acts, st)`: `{"actions": [[kind, name, reason, payload]], "state": st - pending_list}`.
fn ser(plan: &TickPlan) -> Value {
    let actions: Vec<Value> = plan.0.iter().map(|a| json!([a.kind, a.name, a.reason, a.payload])).collect();
    let mut st = plan.1.clone();
    st.shift_remove("pending_list");
    json!({"actions": actions, "state": st})
}

enum WorldMode {
    /// `world=None` (eski yol)
    None,
    /// Python'un kurduğu default dünyası (girdi dosyasında)
    Recorded,
    /// Rust `build_ownership_index` + `world_for` ile kurulan default dünyası
    Built,
}

fn run_golden(mode: WorldMode) -> Vec<Value> {
    let input = read_json(crate_dir().join("fixtures/golden_tick_input.json"));
    let by_sid: IndexMap<String, Option<Vec<String>>> =
        serde_json::from_value(input["projects_by_sid"].clone()).expect("projects_by_sid");
    let index = build_ownership_index(&by_sid, None, None, None);
    let mut out = Vec::new();
    for chain in input["chains"].as_array().expect("chains") {
        let cfg: Config = serde_json::from_value(chain["cfg"].clone()).expect("cfg");
        let mut st: Doc = serde_json::from_value(chain["state"].clone()).expect("state");
        for step in chain["steps"].as_array().expect("steps") {
            let arg = |k: &str| step[k].clone();
            let views: Vec<SessionView> = serde_json::from_value(arg("views")).expect("views");
            let projects: IndexMap<String, Project> = serde_json::from_value(arg("projects")).expect("projects");
            let questions: Vec<Question> = serde_json::from_value(arg("questions")).expect("questions");
            let ideas: Vec<Idea> = serde_json::from_value(arg("ideas")).expect("ideas");
            let recorded: World = serde_json::from_value(arg("world")).expect("world");
            let built = world_for("default", &index, &cfg.brain_name, None, None);
            assert_eq!(built, recorded, "Rust default dünyası Python'unkinden farklı");
            let world = match mode {
                WorldMode::None => None,
                WorldMode::Recorded => Some(&recorded),
                WorldMode::Built => Some(&built),
            };
            let plan = plan_tick(TickInput {
                views: &views,
                projects: &projects,
                state: &st,
                cfg: &cfg,
                now: arg("now").as_f64().expect("now"),
                questions: &questions,
                ideas: &ideas,
                world,
                open_work: None,
                open_tbd: None,
                claim_check: None,
                todo_sha: None,
                open_work_real: None,
            })
            .expect("tick");
            out.push(ser(&plan));
            st = plan.1;
        }
    }
    out
}

/// `_golden()` (`world=None`) ya da `_golden_world()` (`degnekci_kitap` görünümünün eylemi ve `seen_assistant` kaydı yok).
fn golden(world: bool) -> Vec<Value> {
    let path = crate_dir().join("../../../py/tests/steward_golden_tick.json");
    let mut recs: Vec<Value> = serde_json::from_value(read_json(path)).expect("altın kayıt");
    if world {
        for rec in &mut recs {
            if let Some(acts) = rec["actions"].as_array_mut() {
                acts.retain(|a| a[1] != "degnekci_kitap");
            }
            if let Some(seen) = rec["state"].get_mut("seen_assistant").and_then(Value::as_object_mut) {
                seen.shift_remove("degnekci_kitap");
            }
        }
    }
    recs
}

fn assert_golden(got: Vec<Value>, want: Vec<Value>) {
    assert_eq!(got.len(), want.len(), "tick sayısı");
    for (i, (g, w)) in got.iter().zip(&want).enumerate() {
        assert!(same(g, w), "altın tick #{i} farklı\n  python: {w}\n  rust:   {g}");
    }
}

/// py: test_steward_multi.TestGolden.test_world_none_is_byte_identical, plan_tick
#[test]
fn golden_world_none() {
    assert_golden(run_golden(WorldMode::None), golden(false));
}

/// py: test_steward_multi.TestGolden.test_default_world_is_identical, plan_tick
#[test]
fn golden_default_world() {
    assert_golden(run_golden(WorldMode::Recorded), golden(true));
}

/// py: test_steward_multi.TestGolden.test_default_world_from_disk_index_is_identical, plan_tick
#[test]
fn golden_default_world_built_index() {
    assert_golden(run_golden(WorldMode::Built), golden(true));
}

/// Girdi `state` sözlüğü değişmez; bozuk tipli alan `BadValue` (Python istisna) döner.
///
/// py: plan_tick
#[test]
fn bad_state_types_are_errors() {
    let cfg = Config::default();
    for (key, val) in [
        ("ho_pending", json!([1])),
        ("done_confirm", json!({"p": "x"})),
        ("pause_close", json!("abc")),
        ("blocked_tours", json!({"q": "x"})),
        ("skip_seen", json!(5)),
    ] {
        let mut st = Doc::new();
        st.insert(key.into(), val.clone());
        let before = st.clone();
        let got = plan_tick(TickInput {
            views: &[],
            projects: &IndexMap::new(),
            state: &st,
            cfg: &cfg,
            now: 1000.0,
            questions: &[],
            ideas: &[],
            world: None,
            open_work: None,
            open_tbd: None,
            claim_check: None,
            todo_sha: None,
            open_work_real: None,
        });
        assert!(got.is_err(), "{key}={val} hata vermeliydi");
        assert_eq!(st, before);
    }
}
