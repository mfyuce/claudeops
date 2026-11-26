//! Grup 4 paritesi: günlük özet ve ölçüm raporu.
use crate::harness::{parity, Case};
use cops_steward_core::identity::{PathsArg, StewardPaths};
use cops_steward_core::report::*;
use cops_steward_core::types::Project;
use indexmap::IndexMap;
use serde_json::{Map, Value};

type Doc = Map<String, Value>;

fn result<T: serde::Serialize, E: std::fmt::Display>(c: &Case, r: Result<T, E>) -> Value {
    match r {
        Ok(v) => serde_json::to_value(v).expect("serileştirme"),
        Err(e) if c.ret.get("__error__").is_none() => panic!("hata: {e}"),
        Err(_) => c.ret.clone(),
    }
}

fn refs(entries: &[Doc]) -> Vec<&Doc> {
    entries.iter().collect()
}

parity!("daily_path", daily_path_vectors, |c| {
    let date = c.str("date");
    // elle girdiler `base` + `sid`, kayıtlı vektörler Python `paths` nesnesini taşır
    let ret = c.ret.as_str().expect("yol");
    if let Some(base) = c.opt::<String>("base") {
        let sid: Option<String> = c.opt("sid");
        let arg = sid.as_deref().map_or(PathsArg::Default, PathsArg::Sid);
        daily_path(&base, &date, arg).expect("kimlik")
    } else {
        let paths;
        let arg = match c.args.get("paths") {
            None | Some(Value::Null) => PathsArg::Default,
            Some(Value::String(s)) => PathsArg::Sid(s),
            Some(_) => {
                paths = c.arg::<StewardPaths>("paths");
                PathsArg::Paths(&paths)
            }
        };
        // varsayılan/kimlik yolunda kök vektörün kendisinden alınır
        let base = ret.split_once("/daily/").map_or(ret, |(b, _)| b);
        let base = base.split_once("/stewards/").map_or(base, |(b, _)| b);
        daily_path(base, &date, arg).expect("kimlik")
    }
});

parity!("dry_report_text", dry_report_text_vectors, |c| result(
    c,
    dry_report_text(&c.arg::<Doc>("rep"), c.or("hours", 72.0), &c.or("lang", "tr".to_string()))
));

parity!("dry_ask_due", dry_ask_due_vectors, |c| result(
    c,
    dry_ask_due(&c.arg::<Doc>("rep"), c.args.get("asked").unwrap_or(&Value::Null), c.arg("now"), c.or("hours", 72.0))
));

parity!("summary_due", summary_due_vectors, |c| summary_due(&c.arg::<Doc>("state"), c.arg("now"), c.arg("hour")));

parity!("_count_or_zero", p_count_or_zero, |c| count_or_zero(c.args.get("value")));

parity!("_names", p_names, |c| names_line(&c.arg::<Vec<String>>("names"), c.or("n", 5)));

parity!("_kind_counts", p_kind_counts, |c| {
    let entries: Vec<Doc> = c.arg("entries");
    kind_counts(&refs(&entries), &c.or("key", "kind".to_string()))
});

parity!("_ask_gate_lines", p_ask_gate_lines, |c| ask_gate_lines(
    &c.arg::<Vec<Doc>>("events"),
    &c.arg::<IndexMap<String, String>>("answered_by"),
    c.arg("en")
));

parity!("daily_summary", daily_summary_vectors, |c| {
    let (pending, orphans): (Option<Doc>, Option<Doc>) = (c.opt("pending"), c.opt("orphans"));
    let answered: Option<IndexMap<String, String>> = c.opt("answered_by");
    let extras = SummaryExtras { pending: pending.as_ref(), orphans: orphans.as_ref(), answered_by: answered.as_ref() };
    daily_summary(&c.arg::<Vec<Doc>>("entries"), &c.str("date"), &c.or("lang", "tr".to_string()), extras)
});

parity!("summarize_projects", summarize_projects_vectors, |c| summarize_projects(
    &c.arg::<IndexMap<String, Project>>("projects")
));
