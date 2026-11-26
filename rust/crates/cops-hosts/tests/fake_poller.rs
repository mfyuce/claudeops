//! Sahte sunucuyla poller/prober: ardışık hata toleransı, stale-while-error, `extra_urls` yedeği ve https'ten düz
//! http'ye düşmeme, `probe_choice`, bozuk uzak yanıt tipleri, `merge_status` sıralaması, `/api/hosts` satırlarında
//! token olmaması, hız sınırlı `probe_host`, `Running` düşünce döngülerin durması. "İstek GİTMEDİ" iddiaları sunucu
//! sayacıyla.

mod support;

use std::collections::{BTreeSet, HashSet};
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use cops_hosts::consts::CONSECUTIVE_FAILURES_BEFORE_ERROR;
use cops_hosts::status::{finalize, HostStatus, StatusBook};
use cops_hosts::{Federation, HostRecord};
use serde_json::{json, Map, Value};
use support::*;

/// 0 = sağlıklı `/api/status`, 1 = 500 JSON, 2 = bağlantıyı yanıtsız kapat, 3 = `body` aynen (durum `code`).
#[derive(Clone)]
struct Mode(Arc<Mutex<(u8, u16, String)>>);

impl Mode {
    fn new() -> Mode {
        Mode(Arc::new(Mutex::new((0, 200, String::new()))))
    }
    fn set(&self, m: u8) {
        self.0.lock().unwrap().0 = m;
    }
    fn raw(&self, code: u16, body: &str) {
        *self.0.lock().unwrap() = (3, code, body.into());
    }
}

fn status_body() -> Value {
    json!({
        "sessions": [{"name": "s1", "cwd": "/w", "running": true, "host": "local"}],
        "closed": [{"name": "c1", "cwd": "/w", "host": "local"}],
        "retired": [],
        "cli_list": ["claude"],
        "cli_options": {"claude": {"models": ["m1"]}},
        "dups": [],
        "build": {"running": "0123456789abcdef"},
    })
}

async fn status_fake(mode: &Mode) -> Fake {
    let mode = mode.clone();
    Fake::start(handler(move |_r| {
        let m = mode.0.lock().unwrap().clone();
        async move {
            match m.0 {
                0 => json(200, status_body()),
                1 => json(500, json!({"ok": false, "error": "boom"})),
                2 => Act::Drop,
                _ => Act::Reply(
                    hyper::Response::builder()
                        .status(m.1)
                        .header("content-type", "application/json")
                        .body(body_of(m.2))
                        .unwrap(),
                ),
            }
        }
    }))
    .await
}

fn fed_with(src: &Arc<MemSource>) -> Arc<Federation> {
    Federation::new(Arc::new(client()), src.clone())
}

fn fed_events(src: &Arc<MemSource>) -> (Arc<Federation>, Arc<RecEvents>) {
    let ev = Arc::new(RecEvents::default());
    let mut c = client();
    c.events = ev.clone();
    (Federation::new(Arc::new(c), src.clone()), ev)
}

fn hrec(name: &str, base: &str, extra: &[&str]) -> HostRecord {
    let mut h = host(name, base);
    h.extra_urls = extra.iter().map(|s| s.to_string()).collect();
    h
}

// ---------------------------------------------------------------- tolerans

#[tokio::test]
async fn consecutive_failures_are_tolerated_then_rows_are_kept_stale() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let dead = closed_port().await;
        let src = MemSource::new(vec![
            host("a", &f.url()),
            host("b", &format!("http://127.0.0.1:{dead}")),
        ]);
        let fed = fed_with(&src);

        fed.clone().poll_once().await;
        let good = fed.book.cached("a").expect("polled");
        assert!(good.ok, "{good:?}");
        assert_eq!(good.sessions.len(), 1);
        assert_eq!(
            good.sessions[0]["host"], "a",
            "remote 'local' tag is overwritten"
        );
        assert_eq!(good.closed[0]["host"], "a");
        assert_eq!(good.build_running.as_deref(), Some("0123456789ab"));
        let ok_at = fed.book.last_ok_at("a");
        assert!(ok_at > 0.0);

        // Hiç başarısı olmayan host: ilk hata ANINDA görünür (tolerans yok).
        let b = fed.book.cached("b").expect("b polled");
        assert!(!b.ok && b.sessions.is_empty());
        assert!(!b.error.as_deref().unwrap().is_empty(), "{b:?}");
        assert_eq!(fed.book.last_ok_at("b"), 0.0);
        assert_clean(b.error.as_deref().unwrap(), dead);

        mode.set(1);
        for i in 1..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed.clone().poll_once().await;
            assert_eq!(fed.book.fail_streak("a"), i);
            assert_eq!(
                fed.book.cached("a").unwrap(),
                good,
                "failure {i} below the threshold must not be written"
            );
            assert_eq!(fed.book.last_ok_at("a"), ok_at);
            assert!(fed.book.last_try_at("a") >= ok_at);
        }
        let reqs = count_path(&f, "/api/status");
        assert_eq!(
            reqs, CONSECUTIVE_FAILURES_BEFORE_ERROR as usize,
            "one request per turn"
        );

        // Eşik: ok/error güncellenir, satırlar KORUNUR; sonraki hatalarda da (Python 6. hata hatası) silinmez.
        mode.set(2);
        for _ in 0..3 {
            fed.clone().poll_once().await;
            let c = fed.book.cached("a").unwrap();
            assert!(!c.ok);
            let err = c.error.clone().unwrap();
            assert_clean(&err, f.addr.port());
            assert_eq!(c.sessions, good.sessions, "rows survive the outage");
            assert_eq!(c.cli_options, good.cli_options);
            assert_eq!(fed.book.last_ok_at("a"), ok_at);
        }
        assert_eq!(
            fed.book.fail_streak("a"),
            CONSECUTIVE_FAILURES_BEFORE_ERROR + 2
        );

        mode.set(0);
        fed.clone().poll_once().await;
        assert!(fed.book.cached("a").unwrap().ok);
        assert_eq!(fed.book.fail_streak("a"), 0);
        assert!(fed.book.last_ok_at("a") >= ok_at);

        // Silinen host'un kaydı kalkar.
        src.hosts.lock().unwrap().retain(|h| h.name == "a");
        fed.clone().poll_once().await;
        assert!(fed.book.cached("b").is_none());
        assert_eq!(fed.book.last_try_at("b"), 0.0);
    })
    .await
}

// ---------------------------------------------------------------- extra_urls yedeği

#[tokio::test]
async fn extra_urls_fallback_runs_on_threshold_and_every_twentieth_failure() {
    deadline(async {
        let ma = Mode::new();
        ma.set(1);
        let fa = status_fake(&ma).await;
        let mb = Mode::new();
        mb.set(1);
        let fb = status_fake(&mb).await;
        let src = MemSource::new(vec![hrec("a", &fa.url(), &[&fb.url()])]);
        let fed = fed_with(&src);

        let mut turn = 0u32;
        let mut poll_to = |n: u32| {
            let fed = fed.clone();
            let start = turn;
            turn = n;
            async move {
                for _ in start..n {
                    fed.clone().poll_once().await;
                }
            }
        };
        poll_to(CONSECUTIVE_FAILURES_BEFORE_ERROR - 1).await;
        assert_eq!(fb.count(), 0, "short blips never touch extra_urls");
        poll_to(CONSECUTIVE_FAILURES_BEFORE_ERROR).await;
        assert_eq!(fb.count(), 1, "first real failure tries the fallback once");
        poll_to(19).await;
        assert_eq!(fb.count(), 1);
        poll_to(20).await;
        assert_eq!(fb.count(), 2, "then every 20th failing turn");
        assert!(
            src.promotes().is_empty(),
            "failing candidate is not promoted"
        );
        assert_eq!(fed.book.fail_streak("a"), 20);
        assert!(!fed.book.cached("a").unwrap().ok);
        // Aday denemesi kayıtlı token'ı taşır (bu adres sahibin kaydı).
        assert!(fb.recs()[0].query.contains("token="));

        mb.set(0);
        poll_to(39).await;
        assert_eq!(fb.count(), 2);
        poll_to(40).await;
        assert_eq!(fb.count(), 3);
        assert_eq!(src.promotes(), vec![("a".to_string(), fb.url())]);
        assert_eq!(
            src.base_url("a"),
            fb.url(),
            "working candidate is persisted"
        );
        assert_eq!(src.hosts.lock().unwrap()[0].extra_urls, vec![fa.url()]);
        let c = fed.book.cached("a").unwrap();
        assert!(c.ok, "fallback result is recorded as success: {c:?}");
        assert_eq!(c.sessions[0]["host"], "a");
        assert_eq!(fed.book.fail_streak("a"), 0);

        // Sonraki tur yeni base_url'e gider.
        let before_a = fa.count();
        fed.clone().poll_once().await;
        assert_eq!(fa.count(), before_a);
        assert_eq!(fb.count(), 4);
    })
    .await
}

#[tokio::test]
async fn host_without_extra_urls_never_tries_a_fallback() {
    deadline(async {
        let ma = Mode::new();
        ma.set(1);
        let fa = status_fake(&ma).await;
        let other = Fake::start(ok_handler()).await;
        let src = MemSource::new(vec![host("a", &fa.url())]);
        *src.choice.lock().unwrap() = Some(other.url());
        let fed = fed_with(&src);
        for _ in 0..21 {
            fed.clone().poll_once().await;
        }
        assert_eq!(fa.count(), 21);
        assert_eq!(other.count(), 0);
        assert!(
            src.promotes().is_empty(),
            "probe_choice is not consulted without extra_urls"
        );
    })
    .await
}

#[tokio::test]
async fn https_base_never_falls_back_to_plain_http() {
    deadline(async {
        let mb = Mode::new();
        let fb = status_fake(&mb).await;
        // TLS adayı: yalnız bağlantının denendiğini sayar (el sıkışma başarısız olur).
        let tls_try = Raw::start(|mut s| async move {
            let mut b = [0u8; 512];
            let _ = tokio::io::AsyncReadExt::read(&mut s, &mut b).await;
        })
        .await;
        let dead = closed_port().await;
        let https_base = format!("https://127.0.0.1:{dead}");
        let https_extra = format!("https://{}", tls_try.addr);
        let src = MemSource::new(vec![hrec("a", &https_base, &[&fb.url(), &https_extra])]);
        let (fed, ev) = fed_events(&src);
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed.clone().poll_once().await;
        }
        assert_eq!(
            fb.count(),
            0,
            "token must never go to a plain http candidate"
        );
        assert_eq!(fb.accepted(), 0, "not even a TCP connection");
        assert_eq!(tls_try.accepted(), 1, "https candidate is still tried");
        assert!(src.promotes().is_empty());
        assert_eq!(src.base_url("a"), https_base);
        let skipped: Vec<_> = ev
            .all()
            .into_iter()
            .filter(|(n, _)| n == "host_fallback_http_skipped")
            .collect();
        assert_eq!(skipped.len(), 1);
        assert_eq!(skipped[0].1, json!({"name": "a"}), "no URL in events");

        // probe_choice da aynı kurala bağlı: düz http aday seçilmez.
        *src.choice.lock().unwrap() = Some(fb.url());
        fed.clone().poll_once().await;
        assert!(src.promotes().is_empty());
        assert!(src.switches.lock().unwrap().is_empty());

        // Pozitif kontrol: aday reach (tünel) portundaysa izinli, denenir ve kalıcılaşır.
        *src.choice.lock().unwrap() = None;
        let src2 = MemSource::new(vec![hrec("a", &https_base, &[&fb.url()])]);
        *src2.ports.lock().unwrap() = Some(BTreeSet::from([fb.addr.port()]));
        let fed2 = fed_with(&src2);
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed2.clone().poll_once().await;
        }
        assert_eq!(fb.count(), 1);
        assert_eq!(src2.promotes(), vec![("a".to_string(), fb.url())]);
        assert!(fed2.book.cached("a").unwrap().ok);
    })
    .await
}

#[tokio::test]
async fn probe_choice_only_promotes_registered_allowed_candidates() {
    deadline(async {
        let ma = Mode::new();
        let fa = status_fake(&ma).await;
        let fb = Fake::start(ok_handler()).await;
        let src = MemSource::new(vec![hrec("a", &fa.url(), &[&fb.url()])]);
        let (fed, ev) = fed_events(&src);

        *src.choice.lock().unwrap() = Some("http://127.0.0.1:1".into());
        fed.clone().poll_once().await;
        assert!(
            src.promotes().is_empty(),
            "unregistered address is never adopted"
        );

        *src.choice.lock().unwrap() = Some(fb.url());
        fed.clone().poll_once().await;
        assert_eq!(src.promotes(), vec![("a".to_string(), fb.url())]);
        assert_eq!(*src.switches.lock().unwrap(), vec!["a".to_string()]);
        assert_eq!(fb.count(), 0, "probe choice itself goes to no network");
        let picked: Vec<_> = ev
            .all()
            .into_iter()
            .filter(|(n, _)| n == "host_url_picked")
            .collect();
        assert_eq!(
            picked,
            vec![("host_url_picked".to_string(), json!({"name": "a"}))]
        );
    })
    .await
}

// ---------------------------------------------------------------- bozuk yanıtlar

#[tokio::test]
async fn malformed_remote_status_is_an_error_or_reduced_to_empty_fields() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let fed = fed_with(&src);
        let h = host("a", &f.url());

        for (code, body, want) in [
            (200, r#"{"ok":true}"#, "unexpected response shape"),
            (200, r#"{"sessions":5}"#, "unexpected response shape"),
            (200, r#"{"sessions":{"a":1}}"#, "unexpected response shape"),
            (200, "[1,2]", "bad response (not an object)"),
            (200, "<html>", "bad response (not JSON)"),
            (200, "", "bad response (not JSON)"),
            (401, r#"{"sessions":[]}"#, "http 401"),
            (500, r#"{"sessions":[]}"#, "http 500"),
            (302, r#"{"sessions":[]}"#, "http 302"),
        ] {
            mode.raw(code, body);
            let s = fed.fetch_status(&h).await;
            assert_eq!(s, HostStatus::failed(want), "{code} {body}");
        }

        let now = json!(1_000_000.0);
        mode.raw(
            200,
            &json!({
                "sessions": [1, "x", null, [], {"name": "ok", "host": "local"}],
                "closed": "nope",
                "retired": null,
                "cli_list": "claude",
                "cli_options": {"claude": {"models": ["m"], "effort_levels": "high"}, "codex": 5},
                "dups": {"a": 1},
                "disk_clean": [],
                "orphan_watch": {"servers": " 2 ", "procs": true, "last_end": "t"},
                "build": {"running": 7},
                "fwd": {"mode": "on", "kids": ["k1", 2, "k3", "k4", "k5"], "now": now},
            })
            .to_string(),
        );
        let s = fed.fetch_status(&h).await;
        assert!(s.ok, "{s:?}");
        assert_eq!(s.sessions, vec![json!({"name": "ok", "host": "a"})]);
        assert!(s.closed.is_empty() && s.retired.is_empty());
        assert!(s.cli_list.is_empty() && s.dups.is_empty());
        let empty4 = json!({"models": [], "permission_modes": [], "effort_levels": [], "cyclable_modes": []});
        assert_eq!(
            Value::Object(s.cli_options.clone()),
            json!({"claude": {"models": ["m"], "permission_modes": [], "effort_levels": [], "cyclable_modes": []},
                   "codex": empty4})
        );
        assert_eq!(s.disk_clean, Value::Null);
        assert_eq!(s.orphan_watch, json!({"servers": 2, "procs": 1, "last_end": "t"}));
        assert_eq!(s.build_running, None);
        assert_eq!(s.fwd["mode"], "on");
        assert_eq!(s.fwd["kids"], json!(["k1", "2", "k3", "k4"]));
        assert!(s.fwd["skew"].is_number());

        for (ow, fwd) in [
            (json!({"servers": "x"}), json!({"kids": "abc"})),
            (json!([1]), json!({"now": "soon"})),
        ] {
            mode.raw(200, &json!({"sessions": [], "orphan_watch": ow, "fwd": fwd}).to_string());
            let s = fed.fetch_status(&h).await;
            assert!(s.ok);
            assert_eq!(s.orphan_watch, Value::Null, "{ow}");
            assert_eq!(s.fwd, Value::Null, "{fwd}");
        }

        // Aynı bozuk yanıt poller yolunda da hata olarak kaydedilir.
        mode.raw(200, r#"{"sessions":"x"}"#);
        fed.clone().poll_once().await;
        assert_eq!(
            fed.book.cached("a").unwrap(),
            HostStatus::failed("unexpected response shape")
        );
    })
    .await
}

#[tokio::test]
async fn irregular_host_records_are_skipped_by_the_poller() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let doc = json!([7, "x", {"base_url": f.url()}, {"name": "a", "base_url": f.url(), "token": TOKEN}]);
        let parsed = cops_hosts::record::parse_document(doc.to_string().as_bytes());
        assert!(parsed.irregular && !parsed.corrupt);
        let src = MemSource::new(parsed.hosts);
        let fed = fed_with(&src);
        fed.clone().poll_once().await;
        assert_eq!(f.count(), 1, "only the valid record is polled");
        assert!(fed.book.cached("a").unwrap().ok);
    })
    .await
}

// ---------------------------------------------------------------- merge_status

fn good(rows: Value) -> HostStatus {
    finalize("ignored", &json!({"ok": true, "sessions": rows}), 0.0)
}

fn names(v: &Value) -> Vec<String> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|r| {
            format!(
                "{}@{}",
                r["name"].as_str().unwrap_or("-"),
                r["host"].as_str().unwrap_or("-")
            )
        })
        .collect()
}

#[test]
fn merge_status_resorts_globally_and_keeps_host_rows() {
    let book = StatusBook::default();
    let hosts = vec![
        host("h1", "http://127.0.0.1:1"),
        host("h2", "http://127.0.0.1:2"),
    ];
    let mut st = finalize(
        "h1",
        &json!({"ok": true,
            "sessions": [{"name": "beta", "cwd": "/a"}, {"name": "Alpha", "cwd": "/c"}, {"cwd": "/m"}],
            "closed": [{"name": "c1", "cwd": "/x"}],
            "retired": [{"name": "r0", "cwd": "/q"}],
            "cli_list": ["claude"]}),
        0.0,
    );
    st.build_running = Some("abc".into());
    book.record("h1", st, 1.0);

    let local = || -> Map<String, Value> {
        json!({
            "sessions": [{"name": "Zeta", "cwd": "/b", "host": "local"},
                         {"name": "alpha", "cwd": "/z", "host": "local"},
                         {"name": "beta", "cwd": "/a", "host": "local"}],
            "closed": [{"name": "c1", "cwd": "/x", "host": "local"}],
            "retired": "bad",
            "keep": 1,
        })
        .as_object()
        .unwrap()
        .clone()
    };

    // Ad önce (büyük/küçük harf duyarsız), eşitlikte cwd; tam eşit anahtar = kararlı (yerel önce).
    let mut p = local();
    book.merge_status(&mut p, &hosts, None, false);
    assert_eq!(
        names(&p["sessions"]),
        [
            "-@h1",
            "Alpha@h1",
            "alpha@local",
            "beta@local",
            "beta@h1",
            "Zeta@local"
        ]
    );
    assert_eq!(names(&p["closed"]), ["c1@local", "c1@h1"]);
    assert_eq!(
        names(&p["retired"]),
        ["r0@h1"],
        "non-array local list becomes empty"
    );
    assert_eq!(p["keep"], 1, "other fields untouched");
    assert!(
        p["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .all(|r| r.get("mirror_open").is_none()),
        "unknown mirror state adds no field"
    );
    assert_eq!(
        p["hosts"],
        json!([
            {"name": "h1", "ok": true, "error": null, "cli_list": ["claude"], "cli_options": {}, "dups": [],
             "disk_clean": null, "orphan_watch": null, "fwd": null, "build_running": "abc"},
            {"name": "h2", "ok": false, "error": "not polled yet", "cli_list": [], "cli_options": {}, "dups": []},
        ])
    );

    // cwd önce.
    let mut p = local();
    book.merge_status(&mut p, &hosts, None, true);
    assert_eq!(
        names(&p["sessions"]),
        [
            "beta@local",
            "beta@h1",
            "Zeta@local",
            "Alpha@h1",
            "-@h1",
            "alpha@local"
        ]
    );

    // mirror_open yalnız uzak satırlarda, "host:ad" anahtarıyla.
    let open: HashSet<String> = ["h1:beta".to_string(), "local:Zeta".to_string()].into();
    let mut p = local();
    book.merge_status(&mut p, &hosts, Some(&open), false);
    for r in p["sessions"].as_array().unwrap() {
        match (r["host"].as_str().unwrap(), r["name"].as_str()) {
            ("local", _) => assert!(r.get("mirror_open").is_none(), "{r}"),
            ("h1", Some("beta")) => assert_eq!(r["mirror_open"], true),
            ("h1", _) => assert_eq!(r["mirror_open"], false, "{r}"),
            _ => unreachable!(),
        }
    }

    // Kayıtsız host'un önbelleği karışmaz; host sırası kayıt sırası.
    book.record("ghost", good(json!([{"name": "g"}])), 1.0);
    let mut p = local();
    book.merge_status(&mut p, &[hosts[1].clone(), hosts[0].clone()], None, false);
    assert!(!names(&p["sessions"]).iter().any(|n| n.starts_with("g@")));
    let order: Vec<_> = p["hosts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| h["name"].clone())
        .collect();
    assert_eq!(order, [json!("h2"), json!("h1")]);

    // Kesintide (eşik aşıldı) satırlar yine birleşir, host satırı ok:false.
    for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
        book.record("h1", HostStatus::failed("http 500"), 2.0);
    }
    let mut p = Map::new();
    book.merge_status(&mut p, &hosts, None, false);
    assert_eq!(names(&p["sessions"]), ["-@h1", "Alpha@h1", "beta@h1"]);
    assert_eq!(p["hosts"][0]["ok"], false);
    assert_eq!(p["hosts"][0]["error"], "http 500");
    assert_eq!(p["closed"].as_array().unwrap().len(), 1);
}

// ---------------------------------------------------------------- /api/hosts satırları

#[tokio::test]
async fn public_rows_never_carry_the_token() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let dead = closed_port().await;
        let mut c = host("c", &f.url());
        c.grpc_url = "https://127.0.0.1:9".into();
        c.extra_urls = vec![format!("http://127.0.0.1:{dead}")];
        let src = MemSource::new(vec![
            host("a", &f.url()),
            host("b", &format!("http://127.0.0.1:{dead}")),
            c,
            host("n", &f.url()),
        ]);
        let fed = fed_with(&src);
        fed.clone().poll_once().await;
        mode.set(2);
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed.clone().poll_once().await;
        }
        let probed = Mutex::new(Vec::new());
        let rows = fed.public_rows(Some("0123456789ab"), |n| {
            probed.lock().unwrap().push(n.to_string());
            json!({"ms": 5})
        });
        assert_eq!(*probed.lock().unwrap(), ["a", "b", "c", "n"]);
        let all = serde_json::to_string(&rows).unwrap();
        assert!(!all.contains(TOKEN), "token leaked: {all}");
        assert!(!all.contains("token="), "{all}");
        for r in &rows {
            let o = r.as_object().unwrap();
            assert!(!o.contains_key("token"));
            assert_eq!(o["has_token"], true);
            assert_eq!(o["tier"], "rest");
            assert_eq!(o["probe"], json!({"ms": 5}));
            if let Some(e) = o["error"].as_str() {
                assert_clean(e, dead);
                assert_clean(e, f.addr.port());
            }
        }
        assert_eq!(rows[0]["ok"], false);
        assert_eq!(rows[0]["build_running"], "0123456789ab");
        assert_eq!(rows[0]["build_diff"], false);
        assert_eq!(rows[1]["build_running"], Value::Null);
        assert_eq!(rows[1]["build_diff"], false);
        assert_eq!(rows[2]["grpc_url"], "https://127.0.0.1:9");

        let rows = fed.public_rows(Some("ffff"), |_| Value::Null);
        assert_eq!(rows[0]["build_diff"], true);
        let rows = fed.public_rows(Some("0123"), |_| Value::Null);
        assert_eq!(rows[0]["build_diff"], false, "prefix of the same commit");
        let rows = fed.public_rows(None, |_| Value::Null);
        assert_eq!(rows[0]["build_diff"], false);

        // Hiç yoklanmamış host.
        src.hosts.lock().unwrap().push(host("new", &f.url()));
        let rows = fed.public_rows(None, |_| Value::Null);
        assert_eq!(rows[4]["ok"], false);
        assert_eq!(rows[4]["error"], "not polled yet");
    })
    .await
}

// ---------------------------------------------------------------- probe_host

#[tokio::test]
async fn probe_host_is_rate_limited_and_records_like_the_poller() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let fed = fed_with(&src);
        assert_eq!(fed.probe_host("zz").await, None);
        assert_eq!(f.count(), 0);

        assert_eq!(fed.probe_host("a").await, Some(true));
        assert!(fed.book.cached("a").unwrap().ok);
        assert_eq!(fed.probe_host("a").await, None, "within PROBE_MIN_GAP");
        assert_eq!(f.count(), 1, "rate-limited probe sends nothing");

        // Saati ileri al (ağ beklemesi gerçek saatle).
        tokio::time::pause();
        tokio::time::advance(Duration::from_secs(16)).await;
        tokio::time::resume();
        mode.set(1);
        assert_eq!(fed.probe_host("a").await, Some(false));
        assert_eq!(f.count(), 2);
        // Tek hata önceki başarıyı ezmez (poller ile aynı tolerans).
        assert!(fed.book.cached("a").unwrap().ok);
        assert_eq!(fed.book.fail_streak("a"), 1);
    })
    .await
}

#[tokio::test]
async fn test_now_returns_the_fresh_result_not_the_smoothed_one() {
    deadline(async {
        let mode = Mode::new();
        let f = status_fake(&mode).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let fed = fed_with(&src);
        fed.clone().poll_once().await;
        mode.set(1);
        let (r, tier) = fed.test_now("a").await.unwrap();
        assert!(!r.ok, "the button shows the real result");
        assert_eq!(r.error.as_deref(), Some("http 500"));
        assert_eq!(tier, cops_hosts::Tier::Rest);
        assert!(
            fed.book.cached("a").unwrap().ok,
            "shared cache still tolerates the blip"
        );
        assert!(fed.test_now("zz").await.is_none());
    })
    .await
}

// ---------------------------------------------------------------- Running

#[tokio::test(start_paused = true)]
async fn dropping_running_stops_poller_and_prober() {
    let src = MemSource::new(Vec::new());
    let fed = fed_with(&src);
    let run = fed.start();
    tokio::time::sleep(Duration::from_secs(31)).await;
    let n1 = src.loads.load(Ordering::SeqCst);
    // ~11 poller turu (3 sn) + 1 prober turu.
    assert!(n1 >= 11, "loops are running: {n1}");
    let h = fed.poller_health(&run);
    assert!(h.alive);
    assert_eq!(h.restarts, 0);
    assert!(h.age.unwrap() <= Duration::from_secs(4), "{h:?}");
    assert!(Arc::strong_count(&fed) > 1, "tasks hold the federation");

    tokio::time::sleep(Duration::from_secs(30)).await;
    let n2 = src.loads.load(Ordering::SeqCst);
    assert!(n2 > n1, "still running while Running is held");

    drop(run);
    let start = tokio::time::Instant::now();
    while Arc::strong_count(&fed) > 1 {
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "tasks did not end"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let n3 = src.loads.load(Ordering::SeqCst);
    tokio::time::sleep(Duration::from_secs(600)).await;
    assert_eq!(
        src.loads.load(Ordering::SeqCst),
        n3,
        "no turn after Running is dropped"
    );
}

#[tokio::test(start_paused = true)]
async fn poller_beat_age_stays_within_one_interval() {
    let src = MemSource::new(Vec::new());
    let fed = fed_with(&src);
    let run = fed.start();
    for _ in 0..20 {
        tokio::time::sleep(Duration::from_millis(2900)).await;
        let age = fed.poller_health(&run).age.unwrap();
        assert!(age <= Duration::from_secs(3), "{age:?}");
    }
    assert_eq!(fed.poller_health(&run).restarts, 0);
}
