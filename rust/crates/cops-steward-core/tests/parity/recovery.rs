//! Grup 3 paritesi: döngü kesici, sonuç doğrulama, API hatasından kurtarma.
use crate::harness::{parity, py_error, Case};
use cops_steward_core::recovery::*;
use cops_steward_core::types::{Action, SessionView};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

type Doc = Map<String, Value>;

fn views(c: &Case) -> Vec<SessionView> {
    c.arg("views")
}

fn text(c: &Case, name: &str) -> String {
    c.opt::<String>(name).unwrap_or_default()
}

/// Python istisnası beklenen vektörde Rust da hata dönmeli (sınıf/ileti karşılaştırılmaz).
fn result<T: serde::Serialize, E: std::fmt::Display>(c: &Case, r: Result<T, E>) -> Value {
    match r {
        Ok(v) => serde_json::to_value(v).expect("serileştirme"),
        Err(e) => match c.ret.get("__error__") {
            Some(_) => c.ret.clone(),
            None => py_error("BadValue", e),
        },
    }
}

parity!("api_error_kind", api_error_kind_vectors, |c| api_error_kind(&text(c, "text")));
parity!("_loop_sig", p_loop_sig, |c| loop_sig(&c.str("name"), &views(c)));

parity!("loop_guard", loop_guard_vectors, |c| result(
    c,
    loop_guard(&c.arg::<Vec<Action>>("actions"), &views(c), &c.arg::<Doc>("st"), c.arg("now"))
));

parity!("loop_paused", loop_paused_vectors, |c| result(c, loop_paused(&c.arg::<Doc>("st"), c.arg("now"))));

parity!("_outcome_views", p_outcome_views, |c| {
    let (name, views) = (c.str("name"), views(c));
    serde_json::to_value(outcome_views(&name, &views)).expect("görünümler")
});

parity!("_outcome_project", p_outcome_project, |c| outcome_project(&c.str("name"), &views(c)));

parity!("outcome_baseline", outcome_baseline_vectors, |c| outcome_baseline(
    &c.str("kind"),
    &c.str("name"),
    &views(c),
    c.arg("now")
));

parity!("_via", p_via, |c| via(&c.arg::<Doc>("rec")));

parity!("check_outcomes", check_outcomes_vectors, |c| result(
    c,
    check_outcomes(&c.opt::<Doc>("pending").unwrap_or_default(), &views(c), c.arg("now"))
));

parity!("api_error_brief", api_error_brief_vectors, |c| result(c, api_error_brief(&c.arg::<Doc>("st"))));

parity!("plan_api_recovery", plan_api_recovery_vectors, |c| {
    // geri çağrı tablosu: `[[görünüm], sonuç]`
    let table: Vec<(SessionView, bool)> = c.callbacks["eligible"]
        .as_array()
        .expect("tablo")
        .iter()
        .map(|p| (serde_json::from_value(p[0][0].clone()).expect("görünüm"), p[1].as_bool().expect("bool")))
        .collect();
    let eligible = |v: &SessionView| {
        table.iter().find(|(known, _)| known == v).unwrap_or_else(|| panic!("kayıtsız çağrı: {}", v.name)).1
    };
    result(
        c,
        plan_api_recovery(
            &views(c),
            &eligible,
            &c.arg::<BTreeSet<String>>("skip"),
            &c.opt::<Doc>("st_err").unwrap_or_default(),
            c.args.get("st_out").unwrap_or(&json!(null)),
            c.arg("now"),
        ),
    )
});

parity!("_observe_cluster", p_observe_cluster, |c| observe_cluster(&c.arg::<Action>("a")).expect("küme"));
