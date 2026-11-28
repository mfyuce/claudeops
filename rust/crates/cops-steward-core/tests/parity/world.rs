//! Grup 2 paritesi: kimlik görünümü, izlenen oturumlar, satır seçimi, teslim.
use crate::harness::{parity, same, Case};
use cops_steward_core::identity::OwnershipIndex;
use cops_steward_core::types::{Action, Config, Project, SessionView, World};
use cops_steward_core::world::*;
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

type Projects = IndexMap<String, Project>;
type Doc = Map<String, Value>;

fn me(c: &Case) -> World {
    c.arg("self")
}

fn bp(c: &Case) -> Option<String> {
    c.opt("blueprint")
}

parity!("World.start_held", world_start_held, |c| me(c).start_held(&c.str("project")));
parity!("World.host_of", world_host_of, |c| me(c).host_of(&c.str("project")).to_string());
parity!("World.owner_of", world_owner_of, |c| me(c).owner_of(&c.str("project")).to_string());
parity!("World.owns", world_owns, |c| me(c).owns(&c.str("project")));
parity!("World.own_projects", world_own_projects, |c| me(c).own_projects(&c.arg::<Projects>("projects")));
parity!("World._owner_tag", world_p_owner_tag, |c| me(c).owner_tag(&c.str("project")).to_string());
parity!("World.resolve", world_resolve, |c| me(c).resolve(&c.str("name")));
parity!("World._class", world_p_class, |c| me(c).class(&c.str("kind"), &c.str("key")));
parity!("World.name_class", world_name_class, |c| me(c).name_class(&c.str("name")));
parity!("World.session_class", world_session_class, |c| me(c).session_class(&c.str("name"), bp(c).as_deref()));
parity!("World.owned_key", world_owned_key, |c| me(c).owned_key(&c.str("name"), bp(c).as_deref()));
parity!("World.is_manual", world_is_manual, |c| me(c).is_manual(&c.str("name"), bp(c).as_deref()));
parity!("World.project_key", world_project_key, |c| me(c).project_key(&c.str("name")));

parity!("world_for", world_for_vectors, |c| {
    let owned = c.opt::<Doc>("owned");
    // bazı Python testleri `conflicts`i ad listesi olarak verir (işlev yalnız adlarına bakar)
    let mut index: Value = c.arg("index");
    if let Some(names) = index["conflicts"].as_array() {
        index["conflicts"] =
            names.iter().map(|n| (n.as_str().expect("ad").to_string(), json!([]))).collect::<Doc>().into();
    }
    world_for(
        &c.str("sid"),
        &serde_json::from_value::<OwnershipIndex>(index).expect("indeks"),
        &c.opt::<String>("brain_name").unwrap_or_default(),
        c.opt("starts_left"),
        owned.as_ref(),
    )
});

parity!("owned_evidence", owned_evidence_vectors, |c| owned_evidence(
    &c.arg::<Vec<Doc>>("events"),
    &c.str("name"),
    &c.str("project"),
    c.arg("started_at")
));

parity!("update_owned", update_owned_vectors, |c| {
    let table = c.callback("evidence");
    let evidence = |name: &str, project: &str, started_at: f64| {
        let table = table.as_ref().expect("geri çağrı");
        table
            .iter()
            .find(|(key, _)| {
                let a: Vec<Value> = serde_json::from_str(key).expect("anahtar");
                a[0] == name && a[1] == project && a[2].as_f64() == Some(started_at)
            })
            .unwrap_or_else(|| panic!("kayıtsız kanıt çağrısı: {name} {project}"))
            .1
            .as_bool()
            .expect("bool")
    };
    let given = table.is_some();
    update_owned(
        &c.opt::<IndexMap<String, String>>("owned").unwrap_or_default(),
        &c.arg::<Vec<SessionView>>("views"),
        &c.arg("world"),
        &c.arg::<Projects>("projects"),
        c.or("seeding", false),
        if given { Some(&evidence) } else { None },
    )
});

parity!("select_rows", select_rows_vectors, |c| select_rows(
    &c.arg::<Vec<Doc>>("rows"),
    &c.arg("world"),
    &c.opt::<BTreeSet<String>>("fresh_hosts").unwrap_or_default()
));

parity!("_sibling_running", p_sibling_running, |c| sibling_running(
    &c.arg::<Vec<SessionView>>("views"),
    &c.str("name"),
    &c.arg::<Projects>("projects"),
    &c.arg::<Config>("cfg"),
    c.opt::<World>("world").as_ref()
));

parity!("pick_delivery_view", pick_delivery_view_vectors, |c| pick_delivery_view(
    &c.arg::<Vec<SessionView>>("views"),
    &c.str("project"),
    &c.opt::<String>("source").unwrap_or_default()
));

// Elle girdiler: `entries` = [[proje, eylem türü]]; `make(v)` = `Action(tür, v.name, proje)`.
parity!("plan_deliveries", plan_deliveries_vectors, |c| {
    let entries = c.arg::<Vec<(String, String)>>("entries");
    let mut taken: BTreeSet<String> = c.arg("taken");
    let makes = entries.iter().map(|(project, kind)| {
        (project, move |v: &SessionView| Action::new(kind, &v.name, project.as_str(), Map::new()))
    });
    let got = plan_deliveries(
        makes,
        &c.arg::<Vec<SessionView>>("mine"),
        &mut taken,
        &c.arg::<Doc>("state"),
        c.arg("now"),
        c.arg("limit"),
    )
    .expect("teslim");
    let want = c.after.get("taken").cloned().unwrap_or_else(|| c.args["taken"].clone());
    assert!(same(&json!(taken), &want), "taken: {taken:?} != {want}");
    got
});

parity!("bg_blocks_message", bg_blocks_message_vectors, |c| bg_blocks_message(&c.arg("v")));

parity!("holds_total_slot", holds_total_slot_vectors, |c| holds_total_slot(
    &c.arg("v"),
    c.arg("now"),
    c.or("last_directive_at", 0.0)
));
