//! Parite sunucusu: Python kancasından gelen `{fn, ...argümanlar}` isteğini Rust karşılığına çevirir.
use cops_review_core::prompts::LensRegistry;
use cops_review_core::{
    agy, error, export, flow, limits, parse, paths, planner, py, redact, report, store, targets,
};
use cops_review_core::{Finding, ReviewConfig, ReviewPaths, ReviewStore, ReviewTarget, Verdict};
use cops_state::{Backend, Json, Map, StateDir, StateDocs};
use std::sync::Arc;

type R = Result<Json, String>;

fn e(x: error::Error) -> String {
    x.to_string()
}

struct A<'a>(&'a Map);

impl<'a> A<'a> {
    fn raw(&self, k: &str) -> &'a Json {
        static NULL: Json = Json::Null;
        self.0.get(k).unwrap_or(&NULL)
    }
    /// `str(x or "")`
    fn s(&self, k: &str) -> String {
        py::str_or_empty(self.0.get(k))
    }
    fn f(&self, k: &str) -> Result<f64, String> {
        self.raw(k)
            .as_f64()
            .ok_or_else(|| format!("sayı değil: {k}"))
    }
    fn i(&self, k: &str) -> Result<i64, String> {
        self.raw(k)
            .as_i64()
            .ok_or_else(|| format!("tam sayı değil: {k}"))
    }
    fn b(&self, k: &str) -> bool {
        self.raw(k).truthy()
    }
    fn map(&self, k: &str) -> Result<Map, String> {
        self.raw(k)
            .as_object()
            .cloned()
            .ok_or_else(|| format!("nesne değil: {k}"))
    }
    fn list(&self, k: &str) -> &'a [Json] {
        self.raw(k).as_array().unwrap_or(&[])
    }
    fn strs(&self, k: &str) -> Vec<String> {
        self.list(k).iter().map(py::to_str).collect()
    }
    fn texts(&self) -> Vec<String> {
        self.list("texts")
            .iter()
            .map(|t| py::str_or_empty(Some(t)))
            .collect()
    }
    fn maps(&self, k: &str) -> Result<Vec<Map>, String> {
        self.list(k)
            .iter()
            .map(|v| {
                v.as_object()
                    .cloned()
                    .ok_or_else(|| "satır nesne değil".into())
            })
            .collect()
    }
}

fn refs(v: &[String]) -> Vec<&str> {
    v.iter().map(String::as_str).collect()
}

fn target(v: &Json) -> Result<ReviewTarget, String> {
    let a = v.get("__t").and_then(Json::as_array).ok_or("hedef değil")?;
    let s = |i: usize| a.get(i).map(py::to_str).unwrap_or_default();
    Ok(ReviewTarget {
        mode: s(0),
        model: s(1),
        slug: s(2),
        effort: s(3),
        lens: s(4),
    })
}

fn tj(t: &ReviewTarget) -> Json {
    let mut m = Map::new();
    m.insert(
        "__t".into(),
        Json::Array(
            [&t.mode, &t.model, &t.slug, &t.effort, &t.lens]
                .map(|s| Json::Str(s.clone()))
                .to_vec(),
        ),
    );
    Json::Object(m)
}

fn targets_arg(a: &A, k: &str) -> Result<Vec<ReviewTarget>, String> {
    a.list(k).iter().map(target).collect()
}

fn config(v: &Json) -> ReviewConfig {
    let d = ReviewConfig::default();
    let g = |k: &str, d: String| match v.get(k) {
        Some(x) => py::str_or_empty(Some(x)),
        None => d,
    };
    ReviewConfig {
        review_agy_models: g("review_agy_models", d.review_agy_models),
        review_evren_models: g("review_evren_models", d.review_evren_models),
        review_claude_models: g("review_claude_models", d.review_claude_models),
        review_codex_models: g("review_codex_models", d.review_codex_models),
        review_copilot_models: g("review_copilot_models", d.review_copilot_models),
        review_anthropic_models: g("review_anthropic_models", d.review_anthropic_models),
        review_excluded: g("review_excluded", d.review_excluded),
        review_claude_auth: g("review_claude_auth", d.review_claude_auth),
        review_claude_effort: g("review_claude_effort", d.review_claude_effort),
        review_codex_effort: g("review_codex_effort", d.review_codex_effort),
        review_copilot_effort: g("review_copilot_effort", d.review_copilot_effort),
    }
}

fn s(x: impl Into<String>) -> Json {
    Json::Str(x.into())
}
fn b(x: bool) -> Json {
    Json::Bool(x)
}
fn f(x: f64) -> Json {
    Json::Float(x)
}
fn i(x: i64) -> Json {
    Json::Int(x)
}
fn opt(x: Option<f64>) -> Json {
    x.map_or(Json::Null, Json::Float)
}
fn arr(x: impl IntoIterator<Item = Json>) -> Json {
    Json::Array(x.into_iter().collect())
}
fn strs(x: impl IntoIterator<Item = impl Into<String>>) -> Json {
    arr(x.into_iter().map(|v| s(v)))
}

fn usage_json(u: &limits::AgyUsage) -> Json {
    Json::Object(
        u.iter()
            .map(|(p, kinds)| {
                let m: Map = kinds
                    .iter()
                    .map(|(k, (a, t))| (k.clone(), arr([f(*a), f(*t)])))
                    .collect();
                (p.clone(), Json::Object(m))
            })
            .collect(),
    )
}

fn usage_from(v: &Json) -> limits::AgyUsage {
    v.as_object()
        .map(|m| {
            m.iter()
                .map(|(p, kinds)| {
                    let k = kinds
                        .as_object()
                        .map(|k| {
                            k.iter()
                                .map(|(n, pair)| {
                                    let at = |i: usize| {
                                        pair.as_array()
                                            .and_then(|a| a.get(i))
                                            .and_then(Json::as_f64)
                                    };
                                    (n.clone(), (at(0).unwrap_or(0.0), at(1).unwrap_or(0.0)))
                                })
                                .collect()
                        })
                        .unwrap_or_default();
                    (p.clone(), k)
                })
                .collect()
        })
        .unwrap_or_default()
}

fn findings_arg(a: &A) -> Result<Vec<Finding>, String> {
    a.maps("parsed")?
        .iter()
        .map(|m| {
            let g = |k: &str| {
                m.get(k)
                    .map(py::to_str)
                    .ok_or_else(|| format!("KeyError {k}"))
            };
            Ok(Finding {
                r#ref: g("ref")?,
                severity: g("severity")?,
                r#where: g("where")?,
                title: g("title")?,
                body: g("body")?,
            })
        })
        .collect()
}

/// Depo işlevleri: `root` Python tarafının dosyaları kopyaladığı dizin.
fn store_for(a: &A) -> ReviewStore {
    let root = a.s("root");
    let docs = Arc::new(StateDocs::isolated(
        StateDir::at(&root),
        Some(Backend::Files),
        "",
    ));
    let mut p = ReviewPaths::at(&root);
    p.reviews = a.s("reviews").into();
    ReviewStore::new(docs, p)
}

pub fn call(req: &Map, lenses: &mut LensRegistry) -> R {
    let a = A(req);
    let name = a.s("fn");
    let t = |k: &str| target(a.raw(k));
    let texts = a.texts();
    let tx = refs(&texts);
    Ok(match name.as_str() {
        "is_capacity_error" => b(targets::is_capacity_error(&tx)),
        "capacity_retry_seconds" => f(targets::capacity_retry_seconds(&tx)),
        "counts_as_attempt" => b(targets::counts_as_attempt(Some(a.raw("rec")))),
        "max_attempts" => i(targets::max_attempts(&a.s("mode"))),
        "parse_slots" => Json::Object(
            targets::parse_slots(&a.s("spec"))
                .into_iter()
                .map(|(m, n)| (m.to_string(), i(n as i64)))
                .collect(),
        ),
        "slug_model" => s(targets::slug_model(&a.s("model"))),
        "split_spec" => {
            let (m, e) = targets::split_spec(&a.s("spec"));
            arr([s(m), s(e)])
        }
        "excluded_keys" => {
            let mut k: Vec<String> = targets::excluded_keys(&config(a.raw("cfg")))
                .into_iter()
                .collect();
            k.sort();
            strs(k)
        }
        "toggle_excluded" => s(targets::toggle_excluded(
            &a.s("text"),
            &a.s("key"),
            a.b("exclude"),
        )),
        "claude_catalog" => Json::Object(targets::claude_catalog_from(Some(a.raw("state")))),
        "claude_specs" => strs(targets::claude_specs(
            &config(a.raw("cfg")),
            &a.map("catalog")?,
        )),
        "claude_is_subscription" => b(targets::claude_is_subscription(&config(a.raw("cfg")))),
        "targets_from_config" => arr(targets::targets_from_config(
            &config(a.raw("cfg")),
            &a.strs("agy_models"),
            &a.strs("evren_models"),
            &a.map("catalog")?,
        )
        .iter()
        .map(tj)),
        "review_title" => s(targets::review_title(
            &py::to_str(a.raw("project")),
            &py::to_str(a.raw("mode")),
            &py::to_str(a.raw("model")),
            Some(a.raw("ts")),
        )),
        "target_props" => {
            let t = t("t")?;
            arr([s(t.pslug()), s(t.key()), s(t.spec())])
        }
        "pair_key" => s(planner::pair_key(&a.s("proj"), &t("t")?)),
        "window_seconds" => f(planner::window_seconds(Some(a.raw("hours")))),
        "project_complete" => b(planner::project_complete(
            a.raw("history"),
            &a.s("proj"),
            &targets_arg(&a, "targets")?,
            a.f("now")?,
            a.f("window")?,
        )),
        "pool_enabled" => strs(planner::pool_enabled(a.raw("pool"))),
        "pool_focus" => strs(planner::pool_focus(a.raw("pool"))),
        "agy_pool" => s(planner::agy_pool(&a.s("model"))),
        "model_family" => s(planner::model_family(&t("t")?)),
        "next_review" => {
            let busy = a.strs("busy_projects");
            let skip = a.strs("skip_pairs");
            let heads = a.raw("heads").as_object().cloned();
            let head_of = |p: &str| py::str_or_empty(heads.as_ref().and_then(|h| h.get(p)));
            let opts = planner::PlanOpts {
                busy_projects: &busy,
                window: a.f("window")?,
                head_of: heads
                    .is_some()
                    .then_some(&head_of as &dyn Fn(&str) -> String),
                skip_pairs: &skip,
            };
            match planner::next_review(
                a.raw("pool"),
                a.raw("history"),
                &targets_arg(&a, "targets")?,
                a.f("now")?,
                &opts,
            )
            .map_err(e)?
            {
                Some((p, t)) => arr([s(p), tj(&t)]),
                None => Json::Null,
            }
        }
        "open_review_lines" => i(planner::open_review_lines(&a.s("text")) as i64),
        "backlogged_projects" => {
            let counts = a.map("counts")?;
            strs(planner::backlogged_projects(
                a.raw("pool"),
                |p| counts.get(p).and_then(Json::as_i64),
                a.i("limit")?,
            ))
        }
        "pool_sync" => {
            let (p, c) = planner::pool_sync(a.raw("pool"), &a.strs("owner_names"), a.f("now")?);
            arr([p, b(c)])
        }
        "register_lens" => {
            lenses
                .register_lens(
                    &a.s("name"),
                    &a.s("tr"),
                    &a.s("en"),
                    &a.s("format_tr"),
                    &a.s("format_en"),
                )
                .map_err(e)?;
            Json::Null
        }
        "reset_lenses" => {
            *lenses = LensRegistry::default();
            Json::Null
        }
        "lenses" => strs(lenses.lenses()),
        "build_review_prompt" => s(lenses
            .build_review_prompt(&a.s("proj"), &a.s("cwd"), &a.s("lang"), &a.s("lens"))
            .map_err(e)?),
        "parse_findings" => arr(parse::parse_findings(&a.s("md")).into_iter().map(|x| {
            Json::Object(
                [
                    ("ref", x.r#ref),
                    ("severity", x.severity),
                    ("where", x.r#where),
                    ("title", x.title),
                    ("body", x.body),
                ]
                .into_iter()
                .map(|(k, v)| (k.to_string(), s(v)))
                .collect(),
            )
        })),
        "dsn_passwords" => strs(redact::dsn_passwords(&a.s("text"))),
        "redact_secrets" => s(redact::redact_secrets(&a.s("text"), &a.strs("learned"))),
        "agy_allow_list" => strs(agy::agy_allow_list(&a.s("spec"))),
        "agy_settings" => agy::agy_settings(&a.s("cwd"), &a.strs("allow")),
        "agy_label_ok" => {
            let (ok, seen) = agy::agy_label_ok(&a.s("log_text"), &a.s("model"));
            arr([b(ok), s(seen)])
        }
        "effort_for" => {
            let tg = match a.raw("target") {
                Json::Null => None,
                v => Some(target(v)?),
            };
            s(paths::effort_for(
                &config(a.raw("cfg")),
                &a.s("mode"),
                tg.as_ref(),
            ))
        }
        "review_path" => s(paths::review_path(
            &a.s("root"),
            &a.s("proj"),
            &t("t")?,
            a.raw("ts"),
            &a.s("effort"),
            &a.s("lens"),
        )
        .map_err(e)?),
        "draft_path" => s(paths::draft_path(&a.s("md"))),
        "partial_path" => s(paths::partial_path(&a.s("md"))),
        "error_path" => s(paths::error_path(&a.s("md"))),
        "finding_path" => s(paths::finding_path(&a.s("md"), a.i("n")?)),
        "finding_paths" => strs(paths::finding_paths(&a.s("md"))),
        "draft_prompt_suffix" => s(paths::draft_prompt_suffix(&a.s("draft"), &a.s("lang"))),
        "is_daily_limit" => b(limits::is_daily_limit(&tx)),
        "next_utc_midnight" => f(limits::next_utc_midnight(a.f("now")?)),
        "next_utc_month_start" => {
            f(limits::next_utc_month_start(a.f("now")?).ok_or("aralık dışı")?)
        }
        "block_until_for_limit" => f(limits::block_until_for_limit(a.f("now")?, &tx)),
        "limit_scan_texts" => strs(limits::limit_scan_texts(
            &a.s("out"),
            &a.s("err"),
            &a.s("jerr"),
            a.b("err_has_model_text"),
        )),
        "is_short_banner" => b(limits::is_short_banner(&a.s("text"))),
        "is_quota_exhausted" => b(limits::is_quota_exhausted(&tx)),
        "is_usage_limit" => b(limits::is_usage_limit(&tx)),
        "reset_at" => opt(limits::reset_at(&tx)),
        "reset_seconds" => opt(limits::reset_seconds(&tx)),
        "quota_block_until" => f(limits::quota_block_until(a.f("now")?, &tx)),
        "parse_copilot_entries" => {
            match limits::parse_copilot_entries(
                a.raw("entries"),
                a.f("now")?,
                a.raw("base").as_f64(),
            ) {
                Some((p, r, d)) => arr([f(p), f(r), s(d)]),
                None => Json::Null,
            }
        }
        "reconcile_copilot_blocks" => {
            let mut hist = a.map("hist")?;
            let info = a.raw("info").as_array().filter(|x| x.len() == 3).map(|x| {
                (
                    x[0].as_f64().unwrap_or(0.0),
                    x[1].as_f64().unwrap_or(0.0),
                    py::to_str(&x[2]),
                )
            });
            let c = limits::reconcile_copilot_blocks(
                &mut hist,
                info.as_ref(),
                a.f("stop_pct")?,
                a.f("now")?,
            )
            .map_err(e)?;
            arr([strs(c), Json::Object(hist)])
        }
        "parse_agy_usage" => usage_json(&limits::parse_agy_usage(&a.s("text"))),
        "parse_agy_entries" => usage_json(&limits::parse_agy_entries(a.raw("entries"))),
        "agy_pool_blocked_until" => {
            match limits::agy_pool_blocked_until(
                &usage_from(a.raw("usage")),
                &a.s("pool"),
                a.f("now")?,
            ) {
                None => f(-1.0),
                Some(u) => opt(u),
            }
        }
        "reconcile_agy_blocks" => {
            let mut hist = a.map("hist")?;
            let c = limits::reconcile_agy_blocks(
                &mut hist,
                &usage_from(a.raw("usage")),
                &a.strs("target_keys"),
                a.f("now")?,
            )
            .map_err(e)?;
            arr([strs(c), Json::Object(hist)])
        }
        "blocked_modes" => strs(limits::blocked_modes(a.raw("history"), a.f("now")?).map_err(e)?),
        "migrate_r10_sub" => {
            let mut hist = a.map("hist")?;
            let n = store::migrate_r10_sub(&mut hist).map_err(e)?;
            arr([i(n as i64), Json::Object(hist)])
        }
        "finding_key" => s(store::finding_key(
            &py::to_str(a.raw("proj")),
            &a.s("where"),
            &a.s("title"),
        )),
        "scan_verdicts" => arr(parse::scan_verdicts(&a.s("text"))
            .into_iter()
            .map(|v| strs([v.fid, v.verdict, v.reason]))),
        "text_hash" => s(flow::text_hash(&a.s("text"))),
        "reviewer_slug_of" => s(flow::reviewer_slug_of(&a.s("review_file"))),
        "apply_verdicts" => {
            let mut fs = a.map("findings")?;
            let vs: Vec<Verdict> = a
                .list("verdicts")
                .iter()
                .map(|v| {
                    let at = |i: usize| {
                        v.as_array()
                            .and_then(|x| x.get(i))
                            .map(py::to_str)
                            .unwrap_or_default()
                    };
                    Verdict {
                        fid: at(0),
                        verdict: at(1),
                        reason: at(2),
                    }
                })
                .collect();
            let r = flow::apply_verdicts(
                &mut fs,
                &a.s("project"),
                &vs,
                &a.s("src_hash"),
                &a.s("session"),
                a.f("now")?,
                &a.s("verifier"),
            );
            arr([strs(r), Json::Object(fs)])
        }
        "requeue_stale_verify" => {
            let mut fs = a.map("findings")?;
            let r = flow::requeue_stale_verify(&mut fs, a.f("now")?, a.f("stale")?).map_err(e)?;
            arr([strs(r), Json::Object(fs)])
        }
        "usage_summary" => arr(report::usage_summary(&a.s("reviews_root"), &a.s("project"))
            .map_err(e)?
            .iter()
            .map(report::UsageRow::to_json)),
        "model_health" => arr(report::model_health(
            a.raw("history"),
            a.f("now")?,
            a.f("days")?,
            a.i("min_runs")?,
            a.f("max_rate")?,
        )
        .iter()
        .map(report::HealthRow::to_json)),
        "health_digest" => {
            let rows: Vec<report::HealthRow> = a
                .maps("rows")?
                .iter()
                .map(|m| report::HealthRow {
                    target: py::str_or_empty(m.get("target")),
                    runs: m.get("runs").and_then(Json::as_i64).unwrap_or(0),
                    ok: m.get("ok").and_then(Json::as_i64).unwrap_or(0),
                    error: m.get("error").and_then(Json::as_i64).unwrap_or(0),
                    rate: m.get("rate").and_then(Json::as_f64).unwrap_or(0.0),
                    candidate: py::truthy(m.get("candidate")),
                })
                .collect();
            s(report::health_digest(
                &rows,
                &a.strs("excluded"),
                a.f("days")?,
                &a.s("lang"),
            ))
        }
        "duration_summary" => arr(report::duration_summary(a.raw("history"), &a.s("project"))
            .iter()
            .map(report::DurationRow::to_json)),
        "build_verify_message" => {
            s(flow::build_verify_message(&a.maps("rows")?, &a.s("lang")).map_err(e)?)
        }
        "build_self_verify_prompt" => {
            s(flow::build_self_verify_prompt(&a.maps("rows")?, &a.s("lang")).map_err(e)?)
        }
        "is_decision" => b(export::is_decision(&a.map("row")?)),
        "where_text" => s(export::where_text(&a.map("row")?)),
        "where_relpath" => s(export::where_relpath(&a.map("row")?)),
        "has_quoted_names" => b(export::has_quoted_names(&a.map("row")?)),
        "stale_reason_text" => {
            let src = match a.raw("src") {
                Json::Null => None,
                v => Some(py::to_str(v)),
            };
            export::stale_reason_text(&a.map("row")?, src.as_deref()).map_or(Json::Null, s)
        }
        "stale_reason" => export::stale_reason(&a.map("row")?, &a.s("cwd")).map_or(Json::Null, s),
        "changed_after_review" => b(export::changed_after_review(&a.map("row")?, &a.s("cwd"))),
        "_worktree_main" => s(export::worktree_main(&a.s("path")).map_err(e)?),
        "row_in_repo" => {
            let (r, root) = export::row_in_repo(&a.map("row")?, &a.s("root"), &a.s("cwd"));
            arr([Json::Object(r), s(root)])
        }
        "export_root" => {
            let res = a.map("resolved")?;
            s(
                export::export_root(&a.map("row")?, &a.s("project"), &a.s("cwd"), |p| {
                    py::str_or_empty(res.get(p))
                })
                .map_err(e)?,
            )
        }
        "export_lines" => {
            strs(export::export_lines(&a.maps("rows")?, &a.s("reviews_root")).map_err(e)?)
        }
        "appended_export" => {
            let (new, ids) = export::appended_export(
                &a.s("text"),
                &a.maps("rows")?,
                &a.s("reviews_root"),
                &a.s("stamp"),
            )
            .map_err(e)?;
            arr([new.map_or(Json::Null, s), strs(ids)])
        }
        "report_incomplete" => b(report::report_incomplete(&a.s("text"))),
        "report_bodyless" => b(report::report_bodyless(&a.s("text"))),
        "anthropic_price" => arr(report::anthropic_price(&a.s("model")).map(f)),
        "usage_cost_usd" => f(report::usage_cost_usd(
            &a.s("path"),
            &a.s("model"),
            a.f("since_ms")?,
            a.f("write_mult")?,
        )
        .map_err(e)?),
        "anthropic_spent_usd" => f(report::anthropic_spent_usd(&a.s("reviews_root")).map_err(e)?),
        "collapse_ws" => s(py::collapse_ws(&a.s("text"))),
        // ── depolar ──
        "load_pool" => store_for(&a).load_pool().map_err(e)?,
        "save_pool" => {
            store_for(&a).save_pool(a.raw("pool")).map_err(e)?;
            Json::Null
        }
        "load_history" => Json::Object(store_for(&a).load_history().map_err(e)?),
        "save_history" => {
            store_for(&a).save_history(&a.map("hist")?).map_err(e)?;
            Json::Null
        }
        "set_block" => {
            store_for(&a)
                .set_block(&a.s("key"), a.f("until")?, &a.s("reason"))
                .map_err(e)?;
            Json::Null
        }
        "update_pair" => Json::Object(
            store_for(&a)
                .update_pair(&a.s("proj"), &t("t")?, a.map("fields")?)
                .map_err(e)?,
        ),
        "load_findings" => Json::Object(store_for(&a).load_findings().map_err(e)?),
        "save_findings" => {
            store_for(&a).save_findings(a.map("findings")?).map_err(e)?;
            Json::Null
        }
        "add_findings" => strs(
            store_for(&a)
                .add_findings(&a.s("proj"), &a.s("review_file"), &findings_arg(&a)?)
                .map_err(e)?,
        ),
        "mark_verify_sent" => strs(
            store_for(&a)
                .mark_verify_sent(
                    &a.strs("fids"),
                    &a.s("session"),
                    &a.s("baseline"),
                    a.f("now")?,
                )
                .map_err(e)?,
        ),
        "decide_finding" => store_for(&a)
            .decide_finding(&a.s("fid"), &a.s("action"), a.f("now")?, &a.s("by"))
            .map_err(e)?,
        other => return Err(format!("BİLİNMEYEN: {other}")),
    })
}
