//! G8 ikinci parça: maliyet defteri (`ucli_cost.py` testlerinin karşılığı + kapalı yön, eşzamanlılık). Yalnız geçici
//! dizin; ağ ve gerçek durum dizini yok. Python ile aynı girdi/aynı çıktı `parity_ledger`de.

#[path = "g8/support.rs"]
mod support;

use cops_providers::cost::{self, refusal, CostRefusal, BY_SESSION_TOP, RESERVE_TTL};
use cops_providers::real::ledger::{self, file_cost_settings, CostLedger, CostSettings};
use cops_providers::real::probe::CostGate;
use cops_providers::real::{RealDeps, RealProbe};
use cops_providers::settings::UcliCostConfig;
use cops_providers::{BuildArgs, BuildOutput, Cli, ModelCatalog, Providers, Settings};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use support::{mkfifo, Tmp};

/// Bugünün öğlesi: gün sınırında koşan test kararsız olmasın.
fn noon() -> f64 {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    ledger::day_start_ms(now) / 1000.0 + 43200.0
}

fn rec(t: f64, prompt: u64) -> String {
    format!(
        "{{\"t\": {}, \"usage\": {{\"prompt_tokens\": {prompt}, \"completion_tokens\": 0}}}}\n",
        t * 1000.0
    )
}

fn put(t: &Tmp, name: &str, body: &str) -> String {
    let path = t.write(&format!("usage/{name}"), body, 0o600);
    set_mtime(&path, noon());
    path
}

fn set_mtime(path: &str, at: f64) {
    let file = fs::OpenOptions::new().write(true).open(path).unwrap();
    file.set_modified(UNIX_EPOCH + Duration::from_secs_f64(at))
        .unwrap();
}

fn config(cap: f64, credit: f64) -> UcliCostConfig {
    UcliCostConfig {
        daily_cap_usd: cap,
        cache_ttl: "1h",
        credit_total_usd: credit,
        credit_since: String::new(),
        credit_until: String::new(),
        cap_problem: None,
    }
}

fn fixed(cfg: UcliCostConfig) -> CostSettings {
    Arc::new(move || Ok(cfg.clone()))
}

fn book(t: &Tmp, cap: f64) -> CostLedger {
    CostLedger::new(t.path("usage"), fixed(config(cap, 0.0))).with_clock(Arc::new(noon))
}

fn num(v: &Value, key: &str) -> f64 {
    v[key].as_f64().unwrap_or_else(|| panic!("{key} yok: {v}"))
}

#[test]
fn a_cap_refusal_carries_code_and_amounts_and_other_errors_do_not() {
    let e = CostRefusal::CapExceeded {
        today_usd: 14.081,
        cap_usd: 10.0,
    };
    assert_eq!(
        refusal(&e.to_string(), Some(&e)),
        json!({"ok": false, "code": "ucli_daily_cap", "today_usd": 14.08, "cap_usd": 10.0, "error": e.to_string()})
    );
    assert!(e.to_string().contains("(14.08 / 10.00)"));
    assert_eq!(refusal("x", None), json!({"ok": false, "error": "x"}));
    let unknown = CostRefusal::Unverifiable("neden".into());
    assert!(refusal(&unknown.to_string(), Some(&unknown))
        .get("code")
        .is_none());
}

#[test]
fn today_sums_only_todays_logs_and_uses_the_task_model() {
    let t = Tmp::new();
    let body = format!(
        "{{\"event\": \"task_start\", \"model\": \"claude-sonnet-5-5\"}}\n{}",
        rec(noon(), 1_000_000)
    );
    put(&t, "a.jsonl", &body);
    let old = put(&t, "old.jsonl", &rec(noon() - 3.0 * 86400.0, 1_000_000));
    set_mtime(&old, noon() - 3.0 * 86400.0);
    put(&t, "note.txt", &rec(noon(), 1_000_000));
    // sonnet: 1M girdi tam fiyattan
    assert_eq!(ledger::today_usd(noon(), &t.path("usage"), 1.0), 2.0);
    let names: Vec<String> = ledger::per_session_usd(noon(), &t.path("usage"), 1.0)
        .into_iter()
        .map(|(n, _)| n)
        .collect();
    assert_eq!(names, ["a"]);
    assert!(ledger::per_session_usd(noon(), &t.path("yok"), 1.0).is_empty());
    assert_eq!(ledger::today_usd(noon(), &t.path("yok"), 1.0), 0.0);
}

#[test]
fn cap_zero_is_off_and_a_reached_cap_blocks() {
    let t = Tmp::new();
    put(&t, "a.jsonl", &rec(noon(), 1_000_000));
    assert_eq!(book(&t, 0.0).cap_exceeded(noon()), Ok(false));
    assert_eq!(book(&t, 1.0).cap_exceeded(noon()), Ok(true));
    assert_eq!(book(&t, 500.0).cap_exceeded(noon()), Ok(false));
}

#[test]
fn state_lists_the_top_sessions_by_spend_and_totals_all() {
    let t = Tmp::new();
    for i in 0..BY_SESSION_TOP + 5 {
        put(
            &t,
            &format!("s{i:02}.jsonl"),
            &rec(noon(), 1000 * (i as u64 + 1)),
        );
    }
    put(&t, "bos.jsonl", "");
    let s = book(&t, 0.0).state(noon(), false);
    let list = s["by_session"].as_array().unwrap();
    assert_eq!(list.len(), BY_SESSION_TOP);
    assert_eq!(list[0]["session"], "s14");
    assert!(s["pct"].is_null());
    let capped = book(&t, 10.0).state(noon(), false);
    assert_eq!(
        num(&capped, "pct"),
        cost::py_round(100.0 * num(&capped, "today_usd") / 10.0, 1)
    );
}

#[test]
fn the_state_is_cached_until_ttl_or_invalidate() {
    let t = Tmp::new();
    put(&t, "a.jsonl", &rec(noon(), 1000));
    let b = book(&t, 5.0);
    let first = num(&b.state(noon(), true), "today_usd");
    put(&t, "b.jsonl", &rec(noon(), 1000));
    assert_eq!(num(&b.state(noon() + 10.0, true), "today_usd"), first);
    assert!(num(&b.state(noon() + 10.0, false), "today_usd") > first);
    put(&t, "c.jsonl", &rec(noon(), 1000));
    let cached = num(&b.state(noon() + 11.0, true), "today_usd");
    b.invalidate();
    assert!(num(&b.state(noon() + 11.0, true), "today_usd") > cached);
    put(&t, "d.jsonl", &rec(noon(), 1000));
    let before = num(&b.state(noon() + 12.0, true), "today_usd");
    assert!(
        num(&b.state(noon() + 50.0, true), "today_usd") > before,
        "30 sn sonra yeniden taranır"
    );
}

#[test]
fn credit_is_hidden_when_empty_counts_old_days_and_never_goes_negative() {
    let t = Tmp::new();
    let old = put(&t, "eski.jsonl", &rec(noon() - 5.0 * 86400.0, 1_000_000));
    set_mtime(&old, noon() - 5.0 * 86400.0);
    put(&t, "bugun.jsonl", &rec(noon(), 1_000_000));
    assert!(book(&t, 0.0)
        .state(noon(), false)
        .get("credit_left_usd")
        .is_none());
    let with =
        |credit| CostLedger::new(t.path("usage"), fixed(config(0.0, credit))).state(noon(), false);
    let s = with(200.0);
    assert_eq!(num(&s, "credit_total_usd"), 200.0);
    assert!(num(&s, "spent_total_usd") > num(&s, "today_usd"));
    assert!((num(&s, "credit_left_usd") - (200.0 - num(&s, "spent_total_usd"))).abs() < 1e-3);
    assert_eq!(num(&with(0.01), "credit_left_usd"), 0.0);

    // dönem başlangıcı verilirse eski harcama sayılmaz
    let mut cfg = config(0.0, 100.0);
    cfg.credit_since = ledger_day(noon());
    let s = CostLedger::new(t.path("usage"), fixed(cfg.clone())).state(noon(), false);
    assert_eq!(num(&s, "spent_total_usd"), num(&s, "today_usd"));
    assert_eq!(s["credit_since"], json!(cfg.credit_since));
}

fn ledger_day(now: f64) -> String {
    let start = ledger::day_start_ms(now);
    // gün metni `date_ms` ile doğrulanır (yerel saat dilimi)
    let secs = (now / 86400.0).floor() as i64;
    for delta in -1..=1 {
        let (y, m, d) = civil(secs + delta);
        let text = format!("{y:04}-{m:02}-{d:02}");
        if ledger::date_ms(&text, false) == start {
            return text;
        }
    }
    panic!("gün bulunamadı");
}

/// Epoch gün sayısı -> takvim.
fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (yoe + era * 400 + i64::from(m <= 2), m, d)
}

#[test]
fn the_credit_window_gives_days_left_and_a_daily_budget() {
    let now = ledger::date_ms("2026-11-22", false) / 1000.0 + 43200.0;
    let mut cfg = config(0.0, 162.0);
    cfg.credit_until = "2026-12-01".into();
    let end = |d: &str| ledger::date_ms(d, true);
    let w = cost::credit_window(&cfg, 12.0, now, &end);
    assert_eq!(w["days_left"], json!(9.5));
    assert_eq!(w["daily_budget_usd"], json!(cost::py_round(150.0 / 9.5, 2)));
    cfg.credit_until = "2026-11-01".into();
    assert_eq!(
        cost::credit_window(&cfg, 0.0, now, &end)["days_left"],
        json!(0.0)
    );
}

#[test]
fn the_rate_scales_with_the_window_and_skips_corrupt_lines_and_bad_windows() {
    let t = Tmp::new();
    let at = |minutes: f64| rec(noon() - minutes * 60.0, 1_000_000);
    put(&t, "a.jsonl", &(at(10.0) + &at(50.0) + &at(200.0)));
    let base = t.path("usage");
    let hour = ledger::rate_usd_per_hour(noon(), 60.0, &base, 1.6);
    let quarter = ledger::rate_usd_per_hour(noon(), 15.0, &base, 1.6);
    assert!(hour > 0.0 && (quarter / hour - 2.0).abs() < 1e-6);
    put(&t, "b.jsonl", &at(5.0));
    put(&t, "c.jsonl", &format!("{{bozuk\n[]\n\n{}", at(5.0)));
    let by = ledger::rate_by_session(noon(), 60.0, &base, 1.6);
    let mut names: Vec<&str> = by.iter().map(|(n, _)| n.as_str()).collect();
    names.sort_unstable();
    assert_eq!(names, ["a", "b", "c"]);
    let sum: f64 = by.iter().map(|(_, v)| v).sum();
    assert!((sum - ledger::rate_usd_per_hour(noon(), 60.0, &base, 1.6)).abs() < 1e-9);
    assert!(ledger::rate_by_session(noon(), 0.0, &base, 1.6).is_empty());
    assert_eq!(
        ledger::rate_usd_per_hour(noon(), 60.0, &t.path("yok"), 1.6),
        0.0
    );
}

#[test]
fn reservations_share_the_cap_replace_release_and_expire() {
    let t = Tmp::new();
    let two = book(&t, 2.0);
    two.reserve("a", 1000.0).unwrap();
    two.reserve("a", 1001.0).unwrap();
    assert_eq!(two.reserved_sessions(), ["a"]);
    two.reserve("b", 1001.0).unwrap();
    assert_eq!(
        two.reserve("c", 1001.0),
        Err(CostRefusal::CapExceeded {
            today_usd: 2.0,
            cap_usd: 2.0
        })
    );
    two.release("a");
    two.release("a");
    two.reserve("c", 1001.0).unwrap();
    let one = book(&t, 1.0);
    one.reserve("a", 1000.0).unwrap();
    assert!(one.reserve("b", 1000.0).is_err());
    one.reserve("b", 1000.0 + RESERVE_TTL + 1.0).unwrap();
    assert_eq!(one.reserved_sessions(), ["b"]);
    CostGate::release(&one, "b");
    assert!(one.reserved_sessions().is_empty());
    let off = book(&t, 0.0);
    off.reserve("a", 1000.0).unwrap();
    assert!(off.reserved_sessions().is_empty());
}

#[test]
fn concurrent_starts_cannot_oversubscribe_the_cap() {
    let t = Tmp::new();
    let b = Arc::new(book(&t, 5.0));
    let passed = Arc::new(AtomicUsize::new(0));
    std::thread::scope(|s| {
        for i in 0..32 {
            let (b, passed) = (b.clone(), passed.clone());
            s.spawn(move || {
                if b.check_and_reserve(&format!("s{i}")).is_ok() {
                    passed.fetch_add(1, Ordering::SeqCst);
                }
            });
        }
    });
    assert_eq!(passed.load(Ordering::SeqCst), 5);
    assert_eq!(b.reserved_sessions().len(), 5);
}

#[test]
fn an_unreadable_or_invalid_ledger_closes_an_open_cap() {
    let refused = |t: &Tmp| {
        assert!(matches!(
            book(t, 10.0).reserve("s", noon()),
            Err(CostRefusal::Unverifiable(_))
        ));
        assert!(book(t, 10.0).check_and_reserve("s").is_err());
        book(t, 0.0).reserve("s", noon()).unwrap();
    };
    for body in [
        "{\"t\": NOW, \"usage\": {\"completion_tokens\": NaN}}\n",
        "{\"t\": NOW, \"usage\": {\"prompt_tokens\": -1000000}}\n",
        "{\"t\": NOW, \"usage\": {\"input_tokens\": \"12\"}}\n",
        "{\"t\": \"yarin\", \"usage\": {\"prompt_tokens\": 1}}\n",
    ] {
        let t = Tmp::new();
        put(
            &t,
            "a.jsonl",
            &body.replace("NOW", &format!("{}", noon() * 1000.0)),
        );
        refused(&t);
    }
    // 512'den derin satır (Python okur) ve sınırdan uzun satır sayılamaz
    let t = Tmp::new();
    put(
        &t,
        "a.jsonl",
        &format!(
            "{{\"usage\": {{}}, \"x\": {}{}}}\n",
            "[".repeat(600),
            "]".repeat(600)
        ),
    );
    refused(&t);
    let t = Tmp::new();
    put(
        &t,
        "a.jsonl",
        &format!(
            "{}\n{}",
            "x".repeat(ledger::LINE_MAX_BYTES + 10),
            rec(noon(), 1000)
        ),
    );
    refused(&t);
    assert!(
        ledger::today_usd(noon(), &t.path("usage"), 1.0) > 0.0,
        "uzun satırdan sonrası okunur"
    );
    // FIFO bloklamaz
    let t = Tmp::new();
    fs::create_dir(t.path("usage")).unwrap();
    mkfifo(&t.path("usage/p.jsonl"));
    set_fifo_time(&t.path("usage/p.jsonl"));
    let start = Instant::now();
    refused(&t);
    assert!(start.elapsed() < Duration::from_secs(5));
    // dizin yerine dosya
    let t = Tmp::new();
    t.write("usage", "x", 0o600);
    refused(&t);
    // olmayan dizin harcama yok
    let t = Tmp::new();
    book(&t, 10.0).reserve("s", noon()).unwrap();
}

/// FIFO açılmadan zamanı bugüne çekilemez; yeni oluşturulduğundan `noon()`dan eskiyse de bugünündür.
fn set_fifo_time(path: &str) {
    let c = std::ffi::CString::new(path).unwrap();
    let at = libc::timespec {
        tv_sec: noon() as libc::time_t,
        tv_nsec: 0,
    };
    let times = [at, at];
    // SAFETY: geçerli yol ve iki öğeli dizi.
    assert_eq!(
        unsafe { libc::utimensat(libc::AT_FDCWD, c.as_ptr(), times.as_ptr(), 0) },
        0
    );
}

#[test]
fn a_log_with_a_non_utf8_name_still_counts() {
    use std::os::unix::ffi::OsStrExt;
    let t = Tmp::new();
    fs::create_dir(t.path("usage")).unwrap();
    let path =
        std::path::Path::new(&t.path("usage")).join(std::ffi::OsStr::from_bytes(b"a\xff.jsonl"));
    fs::write(&path, rec(noon(), 1_000_000)).unwrap();
    fs::File::options()
        .write(true)
        .open(&path)
        .unwrap()
        .set_modified(UNIX_EPOCH + Duration::from_secs_f64(noon()))
        .unwrap();
    assert!(ledger::today_usd(noon(), &t.path("usage"), 1.0) > 0.0);
}

#[test]
fn settings_are_read_on_every_call_and_an_unreadable_document_refuses() {
    let t = Tmp::new();
    put(&t, "a.jsonl", &rec(noon(), 1_000_000));
    let path = t.path("state/settings.json");
    let b = CostLedger::new(t.path("usage"), file_cost_settings(path.clone()))
        .with_clock(Arc::new(noon));
    b.check_and_reserve("s").unwrap();
    t.write(
        "state/settings.json",
        r#"{"ucli_cost": {"daily_cap_usd": 1}}"#,
        0o600,
    );
    assert!(matches!(
        b.check_and_reserve("s"),
        Err(CostRefusal::CapExceeded { .. })
    ));
    // Python `json.load` NaN kabul eder: tavan kaybolmamalı
    t.write(
        "state/settings.json",
        r#"{"x": NaN, "ucli_cost": {"daily_cap_usd": 1}}"#,
        0o600,
    );
    assert!(matches!(
        b.check_and_reserve("s"),
        Err(CostRefusal::CapExceeded { .. })
    ));
    t.write(
        "state/settings.json",
        r#"{"ucli_cost": {"daily_cap_usd": 500}}"#,
        0o600,
    );
    b.check_and_reserve("s").unwrap();
    for broken in ["{bozuk", ""] {
        t.write("state/settings.json", broken, 0o600);
        assert!(
            matches!(b.check_and_reserve("s"), Err(CostRefusal::BadSettings(_))),
            "{broken:?}"
        );
        assert_eq!(b.state(noon(), false)["cap_usd"], json!(0.0));
        assert!(b.reserved_sessions().iter().all(|n| n != "yeni"));
    }
    fs::remove_file(&path).unwrap();
    fs::create_dir(&path).unwrap();
    assert!(b.check_and_reserve("s").is_err());
}

#[test]
fn a_broken_document_or_an_invalid_cap_refuses_but_absent_empty_and_zero_stay_open() {
    let t = Tmp::new();
    put(&t, "a.jsonl", &rec(noon(), 1_000_000));
    let path = t.path("state/settings.json");
    let b = CostLedger::new(t.path("usage"), file_cost_settings(path)).with_clock(Arc::new(noon));
    let refused = |doc: &str, why: &str| {
        t.write("state/settings.json", doc, 0o600);
        let got = b.check_and_reserve("s");
        assert_eq!(got, Err(CostRefusal::BadSettings(why.into())), "{doc}");
        assert!(b.reserved_sessions().is_empty(), "{doc}");
        assert!(refusal("x", got.as_ref().err()).get("code").is_none());
    };
    for doc in ["{bozuk", "", "[]", "5", "null"] {
        refused(doc, "settings.json okunamadı ya da bozuk");
    }
    for v in [
        r#""abc""#, r#""-5""#, "-5", r#""inf""#, "Infinity", "NaN", "1e400", "true", "false", "[]",
        "{}", "[20]",
    ] {
        refused(
            &format!(r#"{{"ucli_cost": {{"daily_cap_usd": {v}}}}}"#),
            "ucli_cost.daily_cap_usd geçersiz",
        );
    }
    for v in [r#""bozuk""#, "5", "[]", "false", "NaN"] {
        refused(
            &format!(r#"{{"ucli_cost": {v}}}"#),
            "ucli_cost ayarı geçersiz",
        );
    }
    let mut open = vec![
        "{}".to_string(),
        r#"{"ucli_cost": {}}"#.into(),
        r#"{"ucli_cost": null}"#.into(),
        r#"{"ucli_cost": ""}"#.into(),
    ];
    for v in [
        "0", "0.0", "-0.0", r#""0""#, r#""0,0""#, r#"" 0 ""#, r#""""#, r#""  ""#, "null",
    ] {
        open.push(format!(r#"{{"ucli_cost": {{"daily_cap_usd": {v}}}}}"#));
    }
    for doc in open {
        t.write("state/settings.json", &doc, 0o600);
        assert_eq!(b.check_and_reserve("s"), Ok(()), "{doc}");
        assert!(b.reserved_sessions().is_empty(), "{doc}");
    }
}

/// Başka süreç (ucli yerine kabuk) satırları parça parça eklerken okuma: hata ve sahte "bozuk" yok, toplam geri gitmez.
#[test]
fn reading_while_another_process_appends_never_flags_or_loses_records() {
    let t = Tmp::new();
    let log = put(&t, "a.jsonl", "");
    let line = rec(noon(), 1000);
    let (head, rest) = line.split_at(line.len() / 2);
    let script = format!(
        "i=0; while [ $i -lt 300 ]; do printf '%s' '{head}' >> {log}; printf '%s\\n' '{}' >> {log}; i=$((i+1)); \
         done; echo bitti",
        rest.trim_end()
    );
    let _guard = support::spawn_guard();
    let mut writer = Command::new("/bin/sh")
        .args(["-c", &script])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    drop(_guard);
    let done = Arc::new(AtomicBool::new(false));
    let flag = done.clone();
    let out = writer.stdout.take().unwrap();
    let waiter = std::thread::spawn(move || {
        let mut text = String::new();
        let _ = BufReader::new(out).read_line(&mut text);
        flag.store(true, Ordering::SeqCst);
    });
    let mut last = 0.0;
    let start = Instant::now();
    while !done.load(Ordering::SeqCst) {
        assert!(start.elapsed() < Duration::from_secs(60));
        let scan = ledger::scan_usage(&log, "", 0.0, 1.0);
        assert_eq!(scan.problem, None);
        assert!(scan.total >= last);
        last = scan.total;
    }
    waiter.join().unwrap();
    assert!(writer.wait().unwrap().success());
    let one = ledger::scan_usage(put(&t, "bir.jsonl", &line), "", 0.0, 1.0).total;
    let total = ledger::scan_usage(&log, "", 0.0, 1.0).total;
    assert!((total - 300.0 * one).abs() < 1e-9);
}

/// `ProviderRaisesTests`: spawn kurulumu tavanda reddedilir; neden `BuildOutput`ta, metin Python ile aynı.
#[test]
fn a_claude_service_build_is_refused_over_the_cap() {
    let t = Tmp::new();
    let _g = support::spawn_guard();
    t.script("bin/ucli", "echo '--provider <P> --usage-log <P>'");
    put(&t, "a.jsonl", &rec(noon(), 10_000_000));
    let ledger = Arc::new(book(&t, 10.0));
    let env = t.env(&[]);
    let deps = RealDeps {
        docs: support::file_docs(&t.paths()),
        projects: Arc::new(support::Projects(t.path("home"))),
        cost: ledger.clone(),
        search: Arc::new(support::NoSearch),
        help: Arc::default(),
        panel_port: None,
    };
    let probe = RealProbe::new(t.paths(), env, deps);
    let settings = Settings::from_json(r#"{"byok": {"ucli": {"ANTHROPIC_API_KEY": "sk-sir"}}}"#);
    let (catalog, paths) = (ModelCatalog::default(), t.paths());
    let providers = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: &probe,
    };
    let opts = json!({"service": "claude"});
    let args = BuildArgs {
        cwd: &t.path("work"),
        model: "claude-sonnet-5-5",
        session_name: "vc",
        cli_opts: opts.as_object(),
        ..Default::default()
    };
    let mut out = BuildOutput::default();
    let error = providers
        .build_inner_command(Cli::Ucli, &args, &mut out)
        .unwrap_err()
        .to_string();
    let refused = out.cost_refusal.clone().expect("maliyet reddi");
    assert!(matches!(refused, CostRefusal::CapExceeded { cap_usd, .. } if cap_usd == 10.0));
    assert_eq!(refusal(&error, Some(&refused))["code"], "ucli_daily_cap");
    assert!(!error.contains("sk-sir"));
    assert!(ledger.reserved_sessions().is_empty());
}

#[test]
fn a_panic_while_reserving_does_not_poison_later_starts() {
    // zehirlenen kilit spawn'ı kalıcı bozmaz
    let t = Tmp::new();
    let fail = Arc::new(Mutex::new(true));
    let flag = fail.clone();
    let settings: CostSettings = Arc::new(move || {
        let first = std::mem::replace(&mut *flag.lock().unwrap(), false);
        assert!(!first, "ilk çağrı düşer");
        Ok(config(5.0, 0.0))
    });
    let b = CostLedger::new(t.path("usage"), settings);
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| b.reserve("a", 1.0))).is_err()
    );
    b.reserve("a", 1.0).unwrap();
}

// ---- §3.7 (S5 = b): açılış denetimi her günlüğü TEK geçişte okur ----

/// `f` süresince `dirs`teki dosyaların açılış sayısı (inotify). Kapanışlar da izlenir: aynı dosyanın ardışık açılışları
/// kuyrukta tek olayda birleşmesin. Anahtar `<dizin sırası>/<ad>`.
fn opens(dirs: &[&str], f: impl FnOnce()) -> BTreeMap<String, usize> {
    // SAFETY: bayraklar geçerli; dönen tanıtıcı aşağıda `File`a devredilir.
    let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
    assert!(fd >= 0, "inotify açılamadı");
    // SAFETY: `fd` az önce açıldı ve başka sahibi yok.
    let mut queue = unsafe { <fs::File as std::os::fd::FromRawFd>::from_raw_fd(fd) };
    let mask = libc::IN_OPEN | libc::IN_CLOSE_NOWRITE | libc::IN_CLOSE_WRITE;
    let watches: Vec<i32> = dirs
        .iter()
        .map(|d| {
            let c = std::ffi::CString::new(*d).unwrap();
            // SAFETY: geçerli tanıtıcı ve NUL sonlu yol.
            let w = unsafe { libc::inotify_add_watch(fd, c.as_ptr(), mask) };
            assert!(w >= 0, "izlenemedi: {d}");
            w
        })
        .collect();
    f();
    let mut seen = BTreeMap::new();
    let mut buf = [0u8; 16384];
    loop {
        let n = match queue.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
            Err(e) => panic!("{e}"),
        };
        let mut at = 0;
        // struct inotify_event { i32 wd; u32 mask, cookie, len; char name[len] }
        while at < n {
            let word =
                |i: usize| u32::from_ne_bytes(buf[at + 4 * i..at + 4 * i + 4].try_into().unwrap());
            let (wd, mask, len) = (word(0) as i32, word(1), word(3) as usize);
            assert_eq!(mask & libc::IN_Q_OVERFLOW, 0);
            let name: Vec<u8> = buf[at + 16..at + 16 + len]
                .iter()
                .copied()
                .take_while(|b| *b != 0)
                .collect();
            if mask & libc::IN_OPEN != 0 && mask & libc::IN_ISDIR == 0 && !name.is_empty() {
                let dir = watches.iter().position(|w| *w == wd).unwrap();
                let key = format!("{dir}/{}", String::from_utf8_lossy(&name));
                *seen.entry(key).or_insert(0) += 1;
            }
            at += 16 + len;
        }
    }
    seen
}

/// Ortak dizin + ikinci örneğin dizini; her pencereye düşen kayıtlar ve dönemden eski bir dosya.
fn two_dirs(t: &Tmp) -> (String, String) {
    let n = noon();
    let mixed = [n, n - 300.0, n - 1800.0, n - 3.0 * 86400.0]
        .map(|at| rec(at, 100_000))
        .concat();
    put(t, "good.jsonl", &mixed);
    let old = put(t, "eski.jsonl", &rec(n - 3.0 * 86400.0, 100_000));
    set_mtime(&old, n - 3.0 * 86400.0);
    for (name, body) in [
        ("good.jsonl", rec(n, 7000)),
        ("yeni.jsonl", rec(n - 1200.0, 5000)),
    ] {
        let path = t.write(&format!("own/{name}"), &body, 0o600);
        set_mtime(&path, n);
    }
    (t.path("usage"), t.path("own"))
}

fn dated(cap: f64, since: &str) -> CostSettings {
    let mut cfg = config(cap, 100.0);
    cfg.credit_since = since.to_string();
    fixed(cfg)
}

#[test]
fn every_log_is_opened_once_per_start() {
    let t = Tmp::new();
    let (shared, own) = two_dirs(&t);
    let want = |extra: &[&str]| {
        [
            "0/good.jsonl",
            "0/eski.jsonl",
            "1/good.jsonl",
            "1/yeni.jsonl",
        ]
        .iter()
        .chain(extra)
        .map(|k| (k.to_string(), 1))
        .collect::<BTreeMap<_, _>>()
    };
    let ledger = |cap: f64| CostLedger::new(&shared, dated(cap, "")).with_write_dir(own.clone());
    let dirs = [shared.as_str(), own.as_str()];

    // izin verilen açılış
    let got = opens(&dirs, || {
        ledger(1e9).check_and_reserve_at("s", noon()).unwrap()
    });
    assert_eq!(got, want(&[]));
    // tavan aşıldı
    let got = opens(&dirs, || {
        let r = ledger(0.001).check_and_reserve_at("s", noon());
        assert!(matches!(r, Err(CostRefusal::CapExceeded { .. })), "{r:?}");
    });
    assert_eq!(got, want(&[]));
    // kredi dönemi: dönemden önce son yazılmış dosya hiç açılmaz
    let since = ledger_day(noon() - 86400.0);
    let b = CostLedger::new(&shared, dated(1e9, &since)).with_write_dir(own.clone());
    let got = opens(&dirs, || b.check_and_reserve_at("s", noon()).unwrap());
    let mut trimmed = want(&[]);
    trimmed.remove("0/eski.jsonl");
    assert_eq!(got, trimmed);
    // sayılamayan harcama ve kapalı tavan
    put(
        &t,
        "bozuk.jsonl",
        &format!(
            "{{\"t\": {}, \"usage\": {{\"input_tokens\": -1}}}}\n",
            noon() * 1000.0
        ),
    );
    let got = opens(&dirs, || {
        let r = ledger(1e9).check_and_reserve_at("s", noon());
        assert_eq!(
            r,
            Err(CostRefusal::Unverifiable(
                "bozuk.jsonl: geçersiz sayaç".into()
            ))
        );
    });
    assert_eq!(got, want(&["0/bozuk.jsonl"]));
    let got = opens(&dirs, || {
        ledger(0.0).check_and_reserve_at("s", noon()).unwrap()
    });
    assert_eq!(got, want(&["0/bozuk.jsonl"]));
}

#[test]
fn nothing_is_kept_between_two_starts() {
    let t = Tmp::new();
    put(&t, "a.jsonl", &rec(noon(), 1000));
    let b = book(&t, 100.0);
    b.check_and_reserve("s").unwrap();
    put(&t, "a.jsonl", &rec(noon(), 1_000_000_000));
    assert!(matches!(
        b.check_and_reserve("s"),
        Err(CostRefusal::CapExceeded { .. })
    ));
}

/// Eski kapı: `cap_exceeded` + `reserve`, her biri dosyaları kendi okur (ikisi de tek tek hâlâ öyle).
fn separate_reads(b: &CostLedger, session: &str, now: f64, cap: f64) -> Result<(), CostRefusal> {
    if b.cap_exceeded(now)? {
        let today = num(&b.state(now, false), "today_usd");
        return Err(CostRefusal::CapExceeded {
            today_usd: today,
            cap_usd: cap,
        });
    }
    b.reserve(session, now)
}

#[test]
fn the_start_gate_decides_like_the_separate_reads() {
    let mut seed = 0x2026_1127_u64;
    let mut rng = move |n: u64| {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        seed % n
    };
    let n = noon();
    let ms = n * 1000.0;
    let deep = format!(
        "{{\"t\": {ms}, \"usage\": {{\"input_tokens\": 1000}}, \"x\": {}{}}}",
        "[".repeat(513),
        "]".repeat(513)
    );
    let odd: Vec<Vec<u8>> = [
        "{yarim",
        "{\"t\": NOW, \"usage\": {\"input_tokens\": -1}}",
        "{\"t\": OLD, \"usage\": {\"input_tokens\": -1}}",
        "{\"t\": NOW, \"usage\": {\"input_tokens\": Infinity}}",
        "{\"t\": OLD, \"usage\": {\"output_tokens\": NaN}}",
        "{\"t\": \"abc\", \"usage\": {\"input_tokens\": 5}}",
        "{\"t\": NaN, \"usage\": {\"input_tokens\": 5}}",
        "{\"t\": NOW, \"n\": \"\\ud800\", \"usage\": {\"input_tokens\": 500000}}",
        "{\"event\": \"task_start\", \"model\": \"claude-haiku-5-5\"}",
        "{\"event\": \"task_start\", \"model\": \"claude-sonnet-5-5\"}",
        "{\"t\": NOW, \"event\": \"task_end\", \"usage\": {\"input_tokens\": 9000000}}",
    ]
    .iter()
    .map(|s| {
        s.replace("NOW", &ms.to_string())
            .replace("OLD", &(ms - 3.0 * 86400e3).to_string())
            .into_bytes()
    })
    .chain([deep.into_bytes(), b"\xff\xfe".to_vec()])
    .collect();
    let mut kinds = BTreeMap::new();
    let mut logged = 0;
    for round in 0..400 {
        let t = Tmp::new();
        fs::create_dir(t.path("usage")).unwrap();
        fs::create_dir(t.path("own")).unwrap();
        for i in 0..1 + rng(4) {
            let dir = if rng(3) == 0 { "own" } else { "usage" };
            let path = t.path(&format!("{dir}/o{i}.jsonl"));
            let broken = rng(3) == 0;
            let mut body = Vec::new();
            for _ in 0..1 + rng(8) {
                if broken && rng(2) == 0 {
                    body.extend_from_slice(&odd[rng(odd.len() as u64) as usize]);
                    body.push(b'\n');
                } else {
                    let at = n - [0, 300, 1800, 10800, 259_200, 3_456_000][rng(6) as usize] as f64;
                    body.extend_from_slice(rec(at, rng(400_000)).as_bytes());
                }
            }
            fs::write(&path, body).unwrap();
            set_mtime(&path, n - [0, 0, 600, 259_200][rng(4) as usize] as f64);
        }
        if rng(20) == 0 {
            fs::create_dir(t.path("usage/dizin.jsonl")).unwrap();
            set_fifo_time(&t.path("usage/dizin.jsonl"));
        }
        let cap = [0.0, 1e-9, 0.3, 2.0, 1e9][rng(5) as usize];
        let since = ["".to_string(), ledger_day(n - 5.0 * 86400.0)][rng(2) as usize].clone();
        let make =
            || CostLedger::new(t.path("usage"), dated(cap, &since)).with_write_dir(t.path("own"));
        let run = |old: bool| {
            ledger::forget_bad_records();
            drop(ledger::take_bad_record_diags());
            let b = make();
            // başka bir oturumun duran payı
            let held = b.reserve("a", n).is_ok();
            ledger::forget_bad_records();
            drop(ledger::take_bad_record_diags());
            let got = if old {
                separate_reads(&b, "s", n, cap)
            } else {
                b.check_and_reserve_at("s", n)
            };
            // günlük süreç genelinde: yalnız bu ağacın olayları
            let own_tree = t.path("");
            let events: Vec<String> = ledger::take_bad_record_diags()
                .iter()
                .map(|d| format!("{d:?}"))
                .filter(|d| d.contains(&own_tree))
                .collect();
            // `to_string`: aynı toplam bit bit
            (
                held,
                got.map_err(|e| e.to_string()),
                b.state(n, true).to_string(),
                b.reserved_sessions(),
                events,
            )
        };
        let (old, new) = (run(true), run(false));
        assert_eq!(new, old, "tur {round}");
        logged += new.4.len();
        let kind = match &new.1 {
            Ok(()) => "ok",
            Err(e) if e.contains("aşıldı") => "tavan",
            Err(_) => "sayilamiyor",
        };
        *kinds.entry(kind).or_insert(0) += 1;
    }
    assert_eq!(kinds.len(), 3, "{kinds:?}");
    assert!(logged > 0, "günlük olayı hiç karşılaştırılmadı");
}
