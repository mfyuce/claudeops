//! Grup 7: G/Ç işlevlerinin saf çekirdeği. Girdiler ve beklenen değerler `parity/io_cases.py` ile Python işlevi gerçek
//! (yalıtılmış) dosyalarla çalıştırılarak `fixtures/io/<işlev>.json.gz`a yazıldı; burada G/Ç'nin döndürdüğü değerler geri
//! çağrı/parametre olarak verilir.
use crate::harness::{py_error, same};
use cops_steward_core::cards::{build_raw_card, git_recent, RawCard};
use cops_steward_core::consts_gen::*;
use cops_steward_core::identity::OwnershipIndex;
use cops_steward_core::prompts::persona_text;
use cops_steward_core::report::{compact_log, dry_report, log_entries_for_date, missed_summary_dates, summary_text};
use cops_steward_core::store::{
    apply_review_where_answer, transfer_project, transfer_source, TransferError, UpsertContext,
};
use cops_steward_core::tour::{tour_delivery, tour_prune};
use cops_steward_core::types::{Idea, Project, Question};
use flate2::read::GzDecoder;
use indexmap::IndexMap;
use serde::de::DeserializeOwned;
use serde_json::{json, Map, Value};
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::path::PathBuf;

const NOW: f64 = 1_795_700_000.5;

fn utc() {
    static TZ: std::sync::Once = std::sync::Once::new();
    TZ.call_once(|| std::env::set_var("TZ", "UTC"));
}

fn io_cases(name: &str) -> Vec<Map<String, Value>> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/io").join(format!("{name}.json.gz"));
    let file = std::fs::File::open(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let rows: Vec<Map<String, Value>> = serde_json::from_reader(GzDecoder::new(file)).expect("io vektörü");
    assert!(!rows.is_empty(), "{name}: vektör yok");
    rows
}

fn get<T: DeserializeOwned>(r: &Map<String, Value>, k: &str) -> T {
    serde_json::from_value(r.get(k).cloned().unwrap_or(Value::Null)).unwrap_or_else(|e| panic!("{k}: {e}"))
}

fn opt_str(r: &Map<String, Value>, k: &str) -> Option<String> {
    r.get(k).and_then(Value::as_str).map(str::to_string)
}

/// Vektörde NaN/inf dizge ya da `{"__float__": "inf"}` olarak durur.
fn num(v: &Value) -> f64 {
    let text = v.get("__float__").unwrap_or(v);
    v.as_f64().unwrap_or_else(|| text.as_str().and_then(|s| s.parse().ok()).expect("sayı"))
}

/// Python `enc`in sonlu olmayan float biçimi.
fn fl(x: f64) -> Value {
    if x.is_finite() {
        json!(x)
    } else {
        json!({"__float__": if x.is_nan() { "nan".to_string() } else if x > 0.0 { "inf".into() } else { "-inf".into() }})
    }
}

/// Bilinen fark: Python `json.loads` `NaN`/`Infinity` sabitlerini kabul eder, `serde_json` reddeder.
fn has_py_nonfinite(v: &Value) -> bool {
    match v {
        Value::Object(o) => o.contains_key("__float__") || o.values().any(has_py_nonfinite),
        Value::Array(a) => a.iter().any(has_py_nonfinite),
        _ => false,
    }
}

fn check(name: &str, bad: Vec<String>, total: usize) {
    assert!(
        bad.is_empty(),
        "{name}: {}/{total} fark\n{}",
        bad.len(),
        bad.iter().take(3).cloned().collect::<Vec<_>>().join("\n")
    );
}

fn clip(v: &Value) -> String {
    v.to_string().chars().take(800).collect()
}

/// py: persona_text
#[test]
fn persona_text_io_cases() {
    let rows = io_cases("persona_text");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let bundled = opt_str(r, "bundled");
        let got = persona_text(&get::<String>(r, "override"), &|| bundled.clone());
        if r["ret"].as_str() != Some(got.as_str()) {
            bad.push(format!("#{i} {:?} -> {:?}", r["override"], pyc_head(&got)));
        }
    }
    check("persona_text", bad, rows.len());
}

fn pyc_head(s: &str) -> String {
    s.chars().take(80).collect()
}

/// Uzun turda dosya yazılınca klasörde kalan adlar (Python `sorted(os.listdir(d))`); satır içinde klasör varsa dokunulmaz.
fn tour_left(pre: &[String], path: &str) -> Option<Vec<String>> {
    let mut names: Vec<String> = pre.to_vec();
    if !path.is_empty() {
        let base = path.rsplit('/').next().unwrap_or(path).to_string();
        if !names.contains(&base) {
            names.push(base);
        }
        let gone = tour_prune(&names);
        names.retain(|n| !gone.contains(n));
    } else if names.is_empty() {
        return None;
    }
    names.sort();
    Some(names)
}

/// py: tour_delivery
#[test]
fn tour_delivery_io_cases() {
    let rows = io_cases("tour_delivery");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let (prompt, ws, lang): (String, String, String) = (get(r, "prompt"), get(r, "workspace"), get(r, "lang"));
        let pre: Vec<String> = get(r, "pre");
        let got = match tour_delivery(&prompt, &ws, num(&r["now"]), &lang) {
            Ok(t) => {
                let left = tour_left(&pre, &t.path);
                if serde_json::to_value(&left).ok().as_ref() != r.get("left") {
                    bad.push(format!("#{i} kalan dosyalar: {left:?} / python {}", clip(&r["left"])));
                }
                if !t.path.is_empty() && t.dir != format!("{ws}/tours") {
                    bad.push(format!("#{i} klasör {}", t.dir));
                }
                json!([t.message, t.path])
            }
            Err(_) => r["ret"].get("__error__").map_or(json!("rust hata"), |_| r["ret"].clone()),
        };
        if got != r["ret"] {
            bad.push(format!("#{i} now={} -> {} / python {}", r["now"], clip(&got), clip(&r["ret"])));
        }
    }
    check("tour_delivery", bad, rows.len());
}

/// py: _git_recent
#[test]
fn p_git_recent_io_cases() {
    let rows = io_cases("_git_recent");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let cwd: String = get(r, "cwd");
        let has_git: bool = get(r, "has_git");
        let argv_seen = RefCell::new(None::<Vec<String>>);
        let run = |argv: &[String]| -> Option<(i32, String)> {
            *argv_seen.borrow_mut() = Some(argv.to_vec());
            let rc = r["rc"].as_i64()?;
            Some((rc as i32, get(r, "stdout")))
        };
        let want_dir = format!("{cwd}/.git");
        let exists = |p: &str| p == want_dir && has_git;
        let (lines, last) = git_recent(&cwd, get(r, "n"), &exists, &run);
        let got = json!([lines, fl(last)]);
        if !same(&got, &r["ret"]) {
            bad.push(format!("#{i} {} -> {} / python {}", clip(&r["stdout"]), got, r["ret"]));
        }
        let argv = argv_seen.borrow().clone();
        if r["rc"].is_null() {
            // Python: alt süreç istisnası (zaman aşımı); argv kaydedilmedi
        } else if serde_json::to_value(&argv).ok().as_ref() != r.get("argv") {
            bad.push(format!("#{i} argv {argv:?} / python {}", r["argv"]));
        }
    }
    check("_git_recent", bad, rows.len());
}

/// py: build_raw_card
#[test]
fn build_raw_card_io_cases() {
    let rows = io_cases("build_raw_card");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let heads: IndexMap<String, String> = get(r, "heads");
        let git: (Vec<String>, f64) = get(r, "git");
        let card =
            build_raw_card(&get::<String>(r, "cwd"), &|d| heads.get(d).cloned().unwrap_or_default(), &|| git.clone());
        let got = serde_json::to_value(&card).expect("kart");
        if !same(&got, &r["ret"]) {
            bad.push(format!("#{i} {} / python {}", clip(&got), clip(&r["ret"])));
        }
    }
    check("build_raw_card", bad, rows.len());
}

fn transfer_err(e: &TransferError) -> Value {
    match e {
        TransferError::Value(m) => py_error("ValueError", m),
        TransferError::Reviewer(r) => py_error("ReviewerRefused", r),
    }
}

/// py: transfer_project
#[test]
fn transfer_project_io_cases() {
    let rows = io_cases("transfer_project");
    let mut bad = Vec::new();
    let mut moved = 0;
    for (i, r) in rows.iter().enumerate() {
        let (name, to): (String, String) = (get(r, "name"), get(r, "to_sid"));
        let ids: BTreeSet<String> = get(r, "steward_ids");
        let reviewers: BTreeSet<String> = get(r, "reviewers");
        let store = |side: &str, sid: &str, k: &str| r[side][sid][k].clone();
        let projects = |side: &str, sid: &str| -> IndexMap<String, Project> {
            serde_json::from_value(store(side, sid, "projects")).expect("projeler")
        };
        let questions = |side: &str, sid: &str| -> Vec<Question> {
            serde_json::from_value(store(side, sid, "questions")).expect("sorular")
        };
        let got = transfer_source(&name, &to, &ids, &reviewers, &get::<String>(r, "owner")).and_then(|s| {
            let mut locks = [s.src.clone(), to.clone()];
            locks.sort();
            assert_eq!(s.locks, locks);
            transfer_project(
                &name,
                &to,
                &s.src,
                projects("before", &s.src),
                projects("before", &to),
                questions("before", &s.src),
                questions("before", &to),
                &store("before", &s.src, "jobs"),
                &store("before", &to, "jobs"),
            )
            .map(|plan| (s.src, plan))
        });
        let ret = match &got {
            Ok((src, _)) => Value::from(src.clone()),
            Err(e) => transfer_err(e),
        };
        if ret != r["ret"] {
            bad.push(format!("#{i} {name}->{to}: {ret} / python {}", r["ret"]));
            continue;
        }
        let Ok((src, plan)) = got else { continue };
        moved += 1;
        let pairs = [
            (serde_json::to_value(&plan.src_projects), store("after", &src, "projects")),
            (serde_json::to_value(&plan.dst_projects), store("after", &to, "projects")),
            (serde_json::to_value(&plan.src_questions), store("after", &src, "questions")),
            (serde_json::to_value(&plan.dst_questions), store("after", &to, "questions")),
            (
                serde_json::to_value(plan.src_jobs.clone().map(Value::from).unwrap_or(store("before", &src, "jobs"))),
                store("after", &src, "jobs"),
            ),
            (
                serde_json::to_value(plan.dst_jobs.clone().map(Value::from).unwrap_or(store("before", &to, "jobs"))),
                store("after", &to, "jobs"),
            ),
        ];
        for (k, (g, w)) in pairs.into_iter().enumerate() {
            let g = g.expect("plan");
            if !same(&g, &w) {
                bad.push(format!("#{i} alan {k}: {} / python {}", clip(&g), clip(&w)));
            }
        }
        let want_log = |peer: (&str, &str)| json!([{"event": "transfer", "name": name, peer.0: peer.1, "questions": plan.questions, "jobs": plan.jobs}]);
        if r["logs"][&src] != want_log(("to", &to)) || r["logs"][&to] != want_log(("frm", &src)) {
            bad.push(format!("#{i} günlük {}", r["logs"]));
        }
    }
    check("transfer_project", bad, rows.len());
    assert!(moved >= 10, "başarılı devir vektörü az: {moved}");
}

/// Ham bayt vektörü (`key`: bayt listesi) ya da metin alanı.
fn bytes_of(r: &Map<String, Value>, raw: &str, text: &str) -> Option<Vec<u8>> {
    match r.get(raw) {
        Some(v) => Some(serde_json::from_value(v.clone()).expect("bayt listesi")),
        None => opt_str(r, text).map(String::into_bytes),
    }
}

/// py: log_entries_for_date
#[test]
fn log_entries_for_date_io_cases() {
    let rows = io_cases("log_entries_for_date");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let bytes = bytes_of(r, "raw", "text").expect("içerik");
        let got = Value::from(log_entries_for_date(&bytes, &get::<String>(r, "date")));
        // bilinen fark: NaN/Infinity içeren satırı Python çözer, Rust bozuk sayıp atlar
        let want: Vec<Value> =
            r["ret"].as_array().expect("liste").iter().filter(|e| !has_py_nonfinite(e)).cloned().collect();
        if r["case"] != "nan" && want.len() != r["ret"].as_array().map_or(0, Vec::len) {
            bad.push(format!("#{i} NaN yalnız 'nan' vakasında beklenir"));
        }
        if !same(&got, &Value::from(want)) {
            bad.push(format!("#{i} {} {} -> {} / python {}", r["case"], r["date"], clip(&got), clip(&r["ret"])));
        }
    }
    check("log_entries_for_date", bad, rows.len());
}

/// py: compact_log
#[test]
fn compact_log_io_cases() {
    let rows = io_cases("compact_log");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let Some(bytes) = bytes_of(r, "raw", "text") else {
            assert_eq!(r["ret"], json!(0), "dosya yoksa Python 0 döner");
            continue;
        };
        let date: String = get(r, "date");
        let (after, n) = match compact_log(&date, &bytes) {
            Some((after, n)) => (after.into_bytes(), n),
            None => (bytes, 0),
        };
        let want_after = bytes_of(r, "after_raw", "after").expect("sonuç içeriği");
        if r["case"] == "nan" && r["ret"].as_i64() != Some(n) {
            // bilinen fark: NaN/Infinity'li iki tick satırını Python katlar, Rust bozuk sayıp yerinde bırakır
            assert_eq!(r["ret"].as_i64(), Some(n + 2), "nan vakası");
            assert!(
                String::from_utf8_lossy(&after).contains("\"x\": NaN}")
                    && String::from_utf8_lossy(&after).contains("\"mode\": Infinity}"),
                "bozuk satırlar yerinde"
            );
            continue;
        }
        if r["ret"].as_i64() != Some(n) || after != want_after {
            let got = String::from_utf8_lossy(&after);
            bad.push(format!("#{i} {} {}: {n} {got:?} / python {} {}", r["case"], r["date"], r["ret"], r["after"]));
        }
    }
    check("compact_log", bad, rows.len());
}

/// py: dry_report
#[test]
fn dry_report_io_cases() {
    utc();
    let rows = io_cases("dry_report");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let logs: Vec<Option<Vec<u8>>> = match r.get("raw_logs") {
            Some(_) => get(r, "raw_logs"),
            None => get::<Vec<Option<String>>>(r, "logs").into_iter().map(|t| t.map(String::into_bytes)).collect(),
        };
        let refs: Vec<Option<&[u8]>> = logs.iter().map(Option::as_deref).collect();
        let got = Value::Object(dry_report(&refs, num(&r["hours"]), num(&r["now"])));
        if !same(&got, &r["ret"]) {
            bad.push(format!("#{i} {} h={} -> {} / python {}", r["case"], r["hours"], clip(&got), clip(&r["ret"])));
        }
    }
    check("dry_report", bad, rows.len());
}

/// py: missed_summary_dates
#[test]
fn missed_summary_dates_io_cases() {
    utc();
    let rows = io_cases("missed_summary_dates");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let dailies: Vec<String> = get(r, "dailies");
        let text = opt_str(r, "text");
        let has_daily = |d: &str| dailies.iter().any(|x| x == d);
        let has_entries = |d: &str| text.as_deref().is_some_and(|t| !log_entries_for_date(t.as_bytes(), d).is_empty());
        let got = match missed_summary_dates(num(&r["now"]), get(r, "days"), &has_daily, &has_entries) {
            Ok(v) => Value::from(v),
            Err(_) => r["ret"].get("__error__").map_or(json!("rust hata"), |_| r["ret"].clone()),
        };
        if got != r["ret"] {
            bad.push(format!("#{i} days={} -> {got} / python {}", r["days"], r["ret"]));
        }
    }
    check("missed_summary_dates", bad, rows.len());
}

/// py: summary_text
#[test]
fn summary_text_io_cases() {
    utc();
    let rows = io_cases("summary_text");
    let mut bad = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        let state: Map<String, Value> = get(r, "state");
        let questions: Vec<Question> = get(r, "questions");
        let ideas: Vec<Idea> = get(r, "ideas");
        let entries: Vec<Value> = get(r, "entries");
        let orphans = r.get("orphans").filter(|o| o.as_str() != Some("__raise__"));
        let (date, lang): (String, String) = (get(r, "date"), get(r, "lang"));
        let got = Value::from(summary_text(&date, &lang, &state, &questions, &ideas, &entries, orphans));
        if got != r["ret"] {
            bad.push(format!(
                "#{i} state={} orphans={:?} -> {} / python {}",
                r["state"],
                orphans,
                clip(&got),
                clip(&r["ret"])
            ));
        }
    }
    check("summary_text", bad, rows.len());
}

/// py: apply_review_where_answer
#[test]
fn apply_review_where_answer_io_cases() {
    let rows = io_cases("apply_review_where_answer");
    let mut bad = Vec::new();
    let reviewers = BTreeSet::new();
    for (i, r) in rows.iter().enumerate() {
        let q: Question = get(r, "q");
        let parsed: (String, String) = get(r, "parsed");
        let local_copy: String = get(r, "local_copy");
        let home: String = get(r, "home");
        let mut projects: IndexMap<String, Project> =
            serde_json::from_value(r["before"]["projects"].clone()).expect("p");
        let mut questions: Vec<Question> = serde_json::from_value(r["before"]["questions"].clone()).expect("q");
        let expand = |p: &str| match p.strip_prefix('~') {
            Some(rest) if rest.is_empty() || rest.starts_with('/') => format!("{home}{rest}"),
            _ => p.to_string(),
        };
        let ctx = UpsertContext {
            sid: "default",
            reviewers: &reviewers,
            host_known: &|_| false,
            owner_elsewhere: &|_| None,
            index: &OwnershipIndex::default,
            running: None,
            expanduser: &expand,
            force: false,
            now: NOW,
        };
        let out = apply_review_where_answer(
            &q,
            (&parsed.0, &parsed.1),
            &|_| local_copy.clone(),
            &mut projects,
            &ctx,
            &mut questions,
        );
        let mut events = Vec::new();
        if let Some(e) = &out.failed {
            events.push(json!({"event": "review_where_failed", "project": q.project, "error": e}));
        }
        let mut ev = Map::new();
        ev.insert("event".into(), json!("review_where"));
        ev.extend(out.event.clone());
        events.push(Value::Object(ev));
        let got = json!({"projects": projects, "questions": questions, "events": events});
        let want =
            json!({"projects": r["after"]["projects"], "questions": r["after"]["questions"], "events": r["events"]});
        if !same(&got, &want) {
            bad.push(format!("#{i} {:?} -> {} / python {}", q.answer, clip(&got), clip(&want)));
        }
        assert!(out.delivered, "soru deposunda");
    }
    check("apply_review_where_answer", bad, rows.len());
}

// ── Python testlerinin Rust karşılıkları ──

fn bundled_persona() -> Option<String> {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../py/claudeops/data/steward.md");
    std::fs::read_to_string(p).ok()
}

/// py: test_steward_core_a.StoreTest.test_persona_override_and_bundled
#[test]
fn persona_override_and_bundled() {
    assert!(persona_text("", &bundled_persona).to_lowercase().contains("değnekçi"));
    assert_eq!(persona_text("  özel  ", &|| None), "özel\n");
    assert_eq!(persona_text(" \n", &|| None), "");
}

fn card(heads: &[(&str, &str)], git: &[&str], last: f64) -> RawCard {
    let heads: IndexMap<String, String> = heads.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
    let git: Vec<String> = git.iter().map(|s| s.to_string()).collect();
    build_raw_card("r", &|d| heads.get(d).cloned().unwrap_or_default(), &|| (git.clone(), last))
}

/// py: test_steward_core_a.CardCoreTest.test_build_raw_card_reads_doc_heads_and_git
#[test]
fn build_raw_card_doc_heads_and_git() {
    let docs = [("GOAL.md", "# amaç\nBir kitap yazmak"), ("TODO.md", "- [ ] bölüm 3")];
    let raw = card(&docs, &["abc1234 2026-01-02 ilk commit"], 1_767_323_045.0);
    assert_eq!(raw.docs.keys().collect::<Vec<_>>(), ["GOAL.md", "TODO.md"]);
    assert_eq!(raw.git_log.len(), 1);
    assert!(raw.git_log[0].contains("ilk commit"));
    assert!(raw.last_commit > 0.0);
    assert_eq!(raw.source_hash, card(&docs, &["abc1234 2026-01-02 ilk commit"], 1.0).source_hash); // kararlı
    let changed =
        card(&[docs[0], ("TODO.md", "- [ ] bölüm 3\n- [ ] bölüm 4")], &["abc1234 2026-01-02 ilk commit"], 1.0);
    assert_ne!(changed.source_hash, raw.source_hash); // belge değişti
    let more = card(&docs, &["def5678 2026-01-03 ikinci", "abc1234 2026-01-02 ilk commit"], 1.0);
    assert_ne!(more.source_hash, raw.source_hash); // commit değişti
}

/// py: test_steward_core_a.CardCoreTest.test_raw_card_without_git_or_docs
#[test]
fn raw_card_without_git_or_docs() {
    let never = |_: &[String]| -> Option<(i32, String)> { panic!(".git yokken git çalıştırılmamalı") };
    let no_git = |cwd: &str| git_recent(cwd, 5, &|_| false, &never);
    let raw = build_raw_card("plain", &|_| String::new(), &|| no_git("plain"));
    assert_eq!((raw.docs.len(), raw.git_log.len(), raw.last_commit), (0, 0, 0.0));
    let empty = build_raw_card("", &|_| panic!("cwd boşken belge okunmamalı"), &|| no_git(""));
    assert!(empty.docs.is_empty());
    // .git'i olmayan alt klasör üst deponun geçmişini ALMAZ
    let sub = git_recent("outer/sub", 5, &|p| p == "outer/.git", &never);
    assert_eq!(sub, (Vec::new(), 0.0));
}

/// py: test_steward_core_b.TourDeliveryTest.test_short_tour_inline
#[test]
fn short_tour_inline() {
    let t = tour_delivery("kısa", "/ws", 1000.0, "tr").expect("tur");
    assert_eq!((t.message.as_str(), t.path.as_str(), t.dir.as_str()), ("kısa", "", ""));
}

/// py: test_steward_core_b.TourDeliveryTest.test_long_tour_goes_to_file_and_old_files_pruned
#[test]
fn long_tour_goes_to_file_and_old_files_pruned() {
    let long = "x".repeat(usize::try_from(TOUR_INLINE_MAX_CHARS).expect("eşik") + 1);
    let mut dir: Vec<String> = Vec::new();
    let mut paths = Vec::new();
    for i in 0..8 {
        let t = tour_delivery(&long, "/ws", 1000.0 + f64::from(i), "tr").expect("tur");
        assert!(t.message.contains(&t.path));
        assert!(t.message.chars().count() < 400);
        assert_eq!(t.dir, "/ws/tours");
        dir.push(t.path.rsplit('/').next().expect("ad").to_string());
        let gone = tour_prune(&dir);
        dir.retain(|n| !gone.contains(n));
        paths.push(t.path);
    }
    assert_eq!(dir.len(), usize::try_from(TOUR_FILES_KEEP).expect("sayı"));
    assert!(dir.iter().any(|n| paths[7].ends_with(n.as_str())));
    assert!(!dir.iter().any(|n| paths[0].ends_with(n.as_str())));
}
