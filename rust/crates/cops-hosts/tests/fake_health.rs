//! Değnekçi istemci parçaları: devre kesici (açılma, probe başarısında sıfırlama, yavaş okuma suçlamaz),
//! `probe_facts` (404, geçici hata önbelleğe yazılmaz), dosya kapısı, `remote_post` (yıkıcı yol reddi),
//! `exact_target` + `remote_stop` (belirsiz hedefte istek GİTMEZ). "Gitmedi" iddiaları sunucu sayacıyla.

mod support;

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use cops_hosts::health::{
    self, exact_target, files_gate, host_fresh, is_transport_error, remote_post, remote_stop,
    Breaker, Capabilities, CapabilityCache, Change, Remote, TickState, BACKOFF_SECONDS,
    BACKOFF_TICKS, CAPS_RECHECK_SECONDS, REMOTE_STALE_SECONDS,
};
use cops_hosts::status::{finalize, HostStatus};
use cops_hosts::{Caller, GetOpts, HostRecord};
use serde_json::{json, Map, Value};
use support::*;

const T: Duration = Duration::from_secs(2);

fn obj(v: Value) -> Map<String, Value> {
    v.as_object().unwrap().clone()
}

fn set(xs: &[&str]) -> HashSet<String> {
    xs.iter().map(|s| s.to_string()).collect()
}

fn tick(failed: &[&str], succeeded: &[&str]) -> TickState {
    let mut t = TickState::default();
    t.failed = set(failed);
    t.succeeded = set(succeeded);
    t
}

// ---------------------------------------------------------------- taşıma hatası sınıfı

#[test]
fn transport_error_classification() {
    let un = |e: &str| json!({"ok": false, "error": e});
    for s in [502, 503, 504] {
        assert!(is_transport_error("a", &json!({}), s));
    }
    assert!(is_transport_error("a", &un("a unreachable: timeout"), 200));
    assert!(is_transport_error("a", &un("a unreachable: x"), 0));
    // Negatifler: 404 (eski host), uygulama reddi, başka host'un adı, ok:true, 500.
    assert!(!is_transport_error("a", &un("a unreachable: x"), 404));
    assert!(!is_transport_error("a", &un("a unreachable: x"), 500));
    assert!(!is_transport_error("a", &un("no_exact_match"), 200));
    assert!(!is_transport_error("a", &un("ab unreachable: x"), 200));
    assert!(!is_transport_error("a", &un("a unreachable"), 200));
    assert!(!is_transport_error(
        "a",
        &json!({"ok": true, "error": "a unreachable: x"}),
        200
    ));
    assert!(!is_transport_error(
        "a",
        &json!({"ok": false, "error": 5}),
        200
    ));
}

// ---------------------------------------------------------------- devre kesici

#[test]
fn breaker_opens_after_three_failing_ticks_and_reports_once() {
    let b = Breaker::default();
    let now = 1000.0;
    for i in 1..BACKOFF_TICKS {
        assert!(b.settle(&tick(&["a"], &[]), now).is_empty(), "tick {i}");
        assert!(!b.backing_off("a", now));
    }
    assert_eq!(
        b.settle(&tick(&["a"], &[]), now),
        vec![Change::Down {
            host: "a".into(),
            ticks: BACKOFF_TICKS
        }]
    );
    assert!(b.backing_off("a", now));
    assert!(b.backing_off("a", now + BACKOFF_SECONDS - 1.0));
    assert!(!b.backing_off("a", now + BACKOFF_SECONDS));
    assert!(!b.backing_off("other", now), "per host");
    // Sonraki hatalar yeniden bildirilmez, geri çekilme uzar.
    assert!(b.settle(&tick(&["a"], &[]), now + 100.0).is_empty());
    assert!(b.backing_off("a", now + BACKOFF_SECONDS + 50.0));
    // Temiz tick: Up bir kez, sayaç sıfır.
    assert_eq!(
        b.settle(&tick(&[], &["a"]), now + 200.0),
        vec![Change::Up { host: "a".into() }]
    );
    assert!(!b.backing_off("a", now + 200.0));
    assert!(b.settle(&tick(&[], &["a"]), now + 201.0).is_empty());
    for _ in 1..BACKOFF_TICKS {
        b.settle(&tick(&["a"], &[]), now + 300.0);
    }
    assert!(
        !b.backing_off("a", now + 300.0),
        "streak restarted from zero"
    );
}

#[test]
fn breaker_ignores_idle_ticks_and_success_resets_streak() {
    let b = Breaker::default();
    b.settle(&tick(&["a"], &[]), 1.0);
    b.settle(&tick(&["a"], &[]), 2.0);
    // Eylemsiz tick sayılmaz (sıfırlamaz da).
    b.settle(&tick(&[], &[]), 3.0);
    b.settle(&tick(&[], &["b"]), 3.5);
    assert_eq!(
        b.settle(&tick(&["a"], &[]), 4.0).len(),
        1,
        "third failing tick opens"
    );

    let b = Breaker::default();
    b.settle(&tick(&["a"], &[]), 1.0);
    b.settle(&tick(&["a"], &[]), 2.0);
    b.settle(&tick(&[], &["a"]), 3.0);
    b.settle(&tick(&["a"], &[]), 4.0);
    assert!(!b.backing_off("a", 4.0), "a clean tick resets the streak");

    // Aynı tick'te hem hata hem başarı: hata sayılır (Python: `failed` önce).
    let b = Breaker::default();
    for t in 0..BACKOFF_TICKS {
        b.settle(&tick(&["a"], &["a"]), t as f64);
    }
    assert!(b.backing_off("a", 10.0));

    // Birden çok host: değişiklikler ada göre sıralı.
    let b = Breaker::default();
    let mut out = Vec::new();
    for _ in 0..BACKOFF_TICKS {
        out = b.settle(&tick(&["zz", "aa"], &[]), 1.0);
    }
    let hosts: Vec<_> = out
        .iter()
        .map(|c| match c {
            Change::Down { host, .. } | Change::Up { host } => host.clone(),
        })
        .collect();
    assert_eq!(hosts, ["aa", "zz"]);
}

#[test]
fn probe_success_clears_backoff_immediately() {
    let b = Breaker::default();
    assert!(!b.clear("a"), "unknown host was not down");
    for _ in 0..BACKOFF_TICKS {
        b.settle(&tick(&["a"], &[]), 1.0);
    }
    assert!(b.backing_off("a", 2.0));
    assert!(b.clear("a"), "was reported down");
    assert!(
        !b.backing_off("a", 2.0),
        "backoff ends at once, not after 600 s"
    );
    assert!(!b.clear("a"), "second clear: no longer down");
    // Sayaç da sıfırlandı: tekrar 3 hata gerekir; Up yeniden bildirilmez (down zaten false).
    for _ in 1..BACKOFF_TICKS {
        b.settle(&tick(&["a"], &[]), 3.0);
    }
    assert!(!b.backing_off("a", 3.0));
    assert!(b.settle(&tick(&[], &["a"]), 4.0).is_empty());

    // Bildirilmemiş (eşik altı) sayaç da sıfırlanır.
    let b = Breaker::default();
    b.settle(&tick(&["a"], &[]), 1.0);
    b.settle(&tick(&["a"], &[]), 1.0);
    assert!(!b.clear("a"));
    b.settle(&tick(&["a"], &[]), 1.0);
    assert!(!b.backing_off("a", 1.0));
}

/// Paralel okumalar: aynı host'un tek yavaş oturumu (zaman aşımı) host'u düşürmez, hepsi yavaşsa düşürür.
#[tokio::test]
async fn slow_single_read_does_not_blame_a_reachable_host() {
    deadline(async {
        let f = Fake::start(handler(|r| async move {
            if r.query.contains("name=slow") {
                tokio::time::sleep(Duration::from_secs(3)).await;
            }
            json(
                200,
                json!({"ok": true, "supported": true, "assistant": "hi"}),
            )
        }))
        .await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let opts = GetOpts {
            dedup: false,
            timeout: Some(Duration::from_millis(300)),
        };
        let read = |name: &'static str| {
            let c = &c;
            let hosts = &hosts;
            async move {
                c.proxy_get(
                    hosts,
                    "a",
                    "/api/term/chat",
                    &[("name", name), ("mode", "last")],
                    opts,
                    Caller::Unbound,
                )
                .await
            }
        };
        let classify = |rs: &[(Value, u16)]| {
            let (mut bad, mut good) = (HashSet::new(), HashSet::new());
            for (body, status) in rs {
                if is_transport_error("a", body, *status) {
                    bad.insert("a".to_string());
                } else {
                    good.insert("a".to_string());
                }
            }
            (bad, good)
        };

        let (slow, fast) = tokio::join!(read("slow"), read("fast"));
        assert!(is_transport_error("a", &slow.0, slow.1), "{slow:?}");
        assert_eq!(fast.0["assistant"], "hi");
        let (bad, good) = classify(&[slow, fast]);
        let mut t = TickState::default();
        t.record_reads(&bad, &good);
        assert!(
            t.failed.is_empty(),
            "one slow session does not blame the host"
        );
        assert!(!t.blocked("a"));

        let (s1, s2) = tokio::join!(read("slow"), read("slow"));
        let (bad, good) = classify(&[s1, s2]);
        let mut t = TickState::default();
        t.record_reads(&bad, &good);
        assert_eq!(
            t.failed,
            set(&["a"]),
            "every read timed out: host is blamed"
        );
        assert!(t.blocked("a"));
    })
    .await
}

// ---------------------------------------------------------------- tazelik + dosya kapısı

fn ok_status(rows: Value) -> HostStatus {
    finalize("a", &json!({"ok": true, "sessions": rows}), 0.0)
}

#[test]
fn freshness_and_files_gate() {
    let now = 10_000.0;
    let ok = ok_status(json!([]));
    assert!(host_fresh(Some(&ok), now - REMOTE_STALE_SECONDS, now));
    assert!(
        !host_fresh(Some(&ok), now - REMOTE_STALE_SECONDS - 0.1, now),
        "stale"
    );
    assert!(!host_fresh(Some(&ok), 0.0, now), "never succeeded");
    assert!(!host_fresh(None, now, now), "never polled");
    let mut kept = ok.clone();
    kept.ok = false;
    assert!(
        !host_fresh(Some(&kept), now, now),
        "stale-while-error rows are not fresh"
    );

    let hosts = vec![host("a", "http://127.0.0.1:1")];
    assert!(files_gate(&hosts, "a", true, true, false));
    for (h, actions, fresh, backoff) in [
        ("a", false, true, false),
        ("a", true, false, false),
        ("a", true, true, true),
        ("zz", true, true, false),
        ("", true, true, false),
    ] {
        assert!(
            !files_gate(&hosts, h, actions, fresh, backoff),
            "{h} {actions} {fresh} {backoff}"
        );
    }
}

// ---------------------------------------------------------------- probe_facts

#[derive(Clone)]
struct Reply(Arc<std::sync::Mutex<(u16, String, bool)>>);

impl Reply {
    fn new(code: u16, body: Value) -> Reply {
        Reply(Arc::new(std::sync::Mutex::new((
            code,
            body.to_string(),
            false,
        ))))
    }
    fn set(&self, code: u16, body: Value) {
        *self.0.lock().unwrap() = (code, body.to_string(), false);
    }
    fn drop_conn(&self) {
        self.0.lock().unwrap().2 = true;
    }
}

async fn scripted(r: &Reply) -> Fake {
    let r = r.clone();
    Fake::start(handler(move |_req| {
        let (code, body, drop) = r.0.lock().unwrap().clone();
        async move {
            if drop {
                return Act::Drop;
            }
            Act::Reply(
                hyper::Response::builder()
                    .status(code)
                    .header("content-type", "application/json")
                    .body(body_of(body))
                    .unwrap(),
            )
        }
    }))
    .await
}

const NOW: f64 = 50_000.0;

#[tokio::test]
async fn probe_facts_reads_caps_and_facts_in_one_request() {
    deadline(async {
        let r = Reply::new(
            200,
            json!({"ok": true, "api": 2, "capabilities": ["exact_target", 5, "facts"],
                   "sessions": {"s1": {"started_age_s": 3}}}),
        );
        let f = scripted(&r).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let cache = CapabilityCache::default();
        let mut t = TickState::default();
        let (caps, facts) = cache
            .probe_facts(&c, &hosts, "a", &["s1", "s2"], T, NOW, Some(&mut t))
            .await;
        assert_eq!(caps.api, 2);
        assert!(caps.has("exact_target") && caps.has("facts"));
        assert_eq!(caps.capabilities.len(), 2, "non-string capability dropped");
        assert_eq!(facts, Remote::Ok(obj(json!({"s1": {"started_age_s": 3}}))));
        assert!(t.failed.is_empty());
        let rec = &f.recs()[0];
        assert_eq!(rec.path, "/api/session/facts");
        assert!(
            rec.query.starts_with("names=s1%2Cs2&token="),
            "{}",
            rec.query
        );
        assert_eq!(cache.cached("a", NOW), Some(caps.clone()));

        // api>0 kaydı her çağrıda yeniden sorulur (olgular canlı veri).
        cache.probe_facts(&c, &hosts, "a", &[], T, NOW, None).await;
        assert_eq!(f.count(), 2);

        // sessions nesne değilse boş olgu; api tamsayı değilse kabul edilmez.
        r.set(200, json!({"api": 3, "sessions": [1]}));
        let (caps, facts) = cache.probe_facts(&c, &hosts, "a", &[], T, NOW, None).await;
        assert_eq!(caps.api, 3);
        assert!(caps.capabilities.is_empty());
        assert_eq!(facts, Remote::Ok(Map::new()));
        // Python `_caps_put` (TBD#372): dizi olmayan `capabilities` boş, metin karakterlere bölünmez.
        for caps_val in [
            json!("exact_target"),
            json!({"exact_target": 1}),
            json!(5),
            json!(null),
        ] {
            r.set(
                200,
                json!({"api": 3, "capabilities": caps_val.clone(), "sessions": {}}),
            );
            let (caps, _) = cache.probe_facts(&c, &hosts, "a", &[], T, NOW, None).await;
            assert!(caps.capabilities.is_empty(), "{caps_val}");
        }
        for bad in [
            json!({"api": true}),
            json!({"api": 2.5}),
            json!({"api": "2"}),
            json!({"ok": false, "api": 4}),
        ] {
            r.set(200, bad.clone());
            let (caps, facts) = cache.probe_facts(&c, &hosts, "a", &[], T, NOW, None).await;
            assert_eq!(caps.api, 3, "{bad}: cache untouched");
            assert!(matches!(facts, Remote::Unreachable(_)), "{bad}: {facts:?}");
        }
    })
    .await
}

#[tokio::test]
async fn probe_facts_404_caches_old_host_and_stops_asking() {
    deadline(async {
        let r = Reply::new(404, json!({"ok": false, "error": "not found"}));
        let f = scripted(&r).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let cache = CapabilityCache::default();
        let mut t = TickState::default();
        let (caps, facts) = cache
            .probe_facts(&c, &hosts, "a", &["s1"], T, NOW, Some(&mut t))
            .await;
        assert_eq!((caps.api, facts), (0, Remote::Unsupported));
        assert!(t.failed.is_empty(), "404 is not a transport error");
        assert_eq!(cache.cached("a", NOW), Some(Capabilities::default()));

        // Taze api 0 kaydı varken istek GİTMEZ.
        let (_, facts) = cache
            .probe_facts(
                &c,
                &hosts,
                "a",
                &["s1"],
                T,
                NOW + CAPS_RECHECK_SECONDS - 1.0,
                None,
            )
            .await;
        assert_eq!(facts, Remote::Unsupported);
        assert_eq!(f.count(), 1);

        // 10 dk sonra yeniden yoklanır; host güncellendiyse yükselir.
        r.set(
            200,
            json!({"api": 1, "capabilities": ["exact_target"], "sessions": {}}),
        );
        let later = NOW + CAPS_RECHECK_SECONDS;
        assert!(cache.cached("a", later).is_none());
        let (caps, facts) = cache
            .probe_facts(&c, &hosts, "a", &[], T, later, None)
            .await;
        assert_eq!(f.count(), 2);
        assert_eq!(caps.api, 1);
        assert_eq!(facts, Remote::Ok(Map::new()));
        assert_eq!(
            cache.cached("a", later + 10_000.0).unwrap().api,
            1,
            "api>0 never expires"
        );
    })
    .await
}

/// Python `host_capabilities`: önbellekte varsa istek GİTMEZ; yoksa ad listesi boş tek yoklama; geçici arıza boş yetenek
/// döner ve önbelleğe yazılmaz.
#[tokio::test]
async fn host_capabilities_uses_cache_then_probes_once() {
    deadline(async {
        let r = Reply::new(500, json!({"ok": false, "error": "boom"}));
        let f = scripted(&r).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let cache = CapabilityCache::default();
        let caps = cache.host_capabilities(&c, &hosts, "a", T, NOW).await;
        assert_eq!(caps, Capabilities::default());
        assert!(
            cache.cached("a", NOW).is_none(),
            "transient failure not cached"
        );
        assert_eq!(f.count(), 1);
        assert!(
            f.recs()[0].query.starts_with("names=&token="),
            "{}",
            f.recs()[0].query
        );

        r.set(
            200,
            json!({"api": 2, "capabilities": ["exact_target"], "sessions": {}}),
        );
        let caps = cache.host_capabilities(&c, &hosts, "a", T, NOW).await;
        assert!(caps.has("exact_target"));
        assert_eq!(f.count(), 2);
        // Önbellekte: ağa gitmez.
        r.set(500, json!({}));
        let again = cache.host_capabilities(&c, &hosts, "a", T, NOW + 1.0).await;
        assert_eq!(again, caps);
        assert_eq!(f.count(), 2);
        assert_eq!(health::CAPS_PROBE_TIMEOUT, Duration::from_secs(5));
    })
    .await
}

#[tokio::test]
async fn probe_facts_transient_failure_is_not_cached() {
    deadline(async {
        let r = Reply::new(
            200,
            json!({"api": 2, "capabilities": ["exact_target"], "sessions": {}}),
        );
        let f = scripted(&r).await;
        let dead = closed_port().await;
        let c = client();
        let hosts = vec![
            host("a", &f.url()),
            host("d", &format!("http://127.0.0.1:{dead}")),
        ];
        let cache = CapabilityCache::default();
        cache.probe_facts(&c, &hosts, "a", &[], T, NOW, None).await;
        let good = cache.cached("a", NOW).unwrap();

        // (yanıt, taşıma hatası mı)
        let cases: Vec<(Box<dyn Fn()>, bool)> = vec![
            (
                Box::new(|| r.set(500, json!({"ok": false, "error": "boom"}))),
                false,
            ),
            (
                Box::new(|| r.set(200, json!({"ok": false, "error": "denied"}))),
                false,
            ),
            (Box::new(|| r.set(502, json!({"ok": false}))), true),
            (Box::new(|| r.set(503, json!({}))), true),
            (Box::new(|| r.drop_conn()), true),
        ];
        for (i, (arrange, transport)) in cases.into_iter().enumerate() {
            arrange();
            let mut t = TickState::default();
            let (caps, facts) = cache
                .probe_facts(&c, &hosts, "a", &[], T, NOW + 1.0, Some(&mut t))
                .await;
            assert_eq!(caps, good, "case {i}: cached caps returned");
            assert!(
                matches!(facts, Remote::Unreachable(_)),
                "case {i}: {facts:?}"
            );
            assert_eq!(
                cache.cached("a", NOW + 1.0),
                Some(good.clone()),
                "case {i}: not overwritten"
            );
            assert_eq!(t.failed.contains("a"), transport, "case {i}");
        }

        // Önbellek yokken geçici hata: varsayılan (api 0) döner ama YAZILMAZ; sonraki çağrı yine sorar.
        let mut t = TickState::default();
        let (caps, facts) = cache
            .probe_facts(&c, &hosts, "d", &[], T, NOW, Some(&mut t))
            .await;
        assert_eq!(caps, Capabilities::default());
        let Remote::Unreachable(why) = facts else {
            panic!("{facts:?}")
        };
        assert_clean(&why, dead);
        assert!(
            cache.cached("d", NOW).is_none(),
            "transient failure must not pin api 0"
        );
        assert_eq!(t.failed, set(&["d"]));

        // Kayıtsız host: istek yok, taşıma hatası sayılmaz.
        let before = f.count();
        let mut t = TickState::default();
        let (_, facts) = cache
            .probe_facts(&c, &hosts, "zz", &[], T, NOW, Some(&mut t))
            .await;
        assert!(matches!(facts, Remote::Unreachable(_)));
        assert!(t.failed.is_empty());
        assert!(cache.cached("zz", NOW).is_none());
        assert_eq!(f.count(), before);
    })
    .await
}

// ---------------------------------------------------------------- remote_post

#[tokio::test]
async fn remote_post_refuses_destructive_paths_and_host_field() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let mut t = TickState::default();
        for p in ["/api/stop", "/api/close", "/api/retire", "/api/compact"] {
            let out = remote_post(
                &c,
                &hosts,
                "a",
                p,
                obj(json!({"name": "s1"})),
                T,
                Some(&mut t),
            )
            .await;
            assert_eq!(out["ok"], false);
            assert_eq!(out["code"], "needs_exact_target", "{p}");
        }
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/start",
            obj(json!({"name": "s1", "host": "b"})),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out["code"], "bad_request");
        assert_eq!(f.count(), 0, "nothing was sent");
        assert_eq!(f.accepted(), 0);
        assert!(
            t.failed.is_empty() && t.succeeded.is_empty(),
            "refusals are not health signals"
        );

        // Pozitif kontrol: yıkıcı olmayan yol gider, gövdede host=local zorlanır.
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/start",
            obj(json!({"name": "s1"})),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out["ok"], true);
        assert_eq!(f.count(), 1);
        let rec = &f.recs()[0];
        assert_eq!(rec.path, "/api/start");
        assert_eq!(rec.json(), json!({"name": "s1", "host": "local"}));
        assert_eq!(t.succeeded, set(&["a"]));
    })
    .await
}

#[tokio::test]
async fn remote_post_breaker_and_error_marking() {
    deadline(async {
        let r = Reply::new(200, json!({"ok": true}));
        let f = scripted(&r).await;
        let ev = Arc::new(RecEvents::default());
        let mut c = client();
        c.events = ev.clone();
        let hosts = vec![host("a", &f.url())];

        // 404: remote_not_found, taşıma değil (succeeded).
        r.set(404, json!({"error": "nope"}));
        let mut t = TickState::default();
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/new-chat",
            Map::new(),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out["code"], "remote_not_found");
        assert_eq!(out["host"], "a");
        assert_eq!(t.succeeded, set(&["a"]));
        assert!(t.failed.is_empty());

        // Uygulama reddi aynen döner, devre kesiciyi açmaz.
        r.set(200, json!({"ok": false, "error": "busy"}));
        let mut t = TickState::default();
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/new-chat",
            Map::new(),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out, json!({"ok": false, "error": "busy"}));
        assert!(t.failed.is_empty());

        // Bağlantı yanıtsız kapanır: POST yeniden denenmez, host_down işaretlenir, tick'te host bloklanır.
        r.drop_conn();
        let mut t = TickState::default();
        let before = f.count();
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/new-chat",
            Map::new(),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(
            f.count(),
            before + 1,
            "a POST that reached the server is not retried"
        );
        assert_eq!(out["ok"], false);
        assert_eq!(out["code"], "host_down");
        assert_eq!(out["host"], "a");
        assert_clean(out["error"].as_str().unwrap(), f.addr.port());
        assert_eq!(t.failed, set(&["a"]));
        let sent = f.count();
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/new-chat",
            Map::new(),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out, json!({"ok": false, "error": "host_down", "host": "a"}));
        assert_eq!(
            f.count(),
            sent,
            "blocked host gets no further request this tick"
        );

        let logged: Vec<_> = ev
            .all()
            .into_iter()
            .filter(|(n, _)| n == "remote_transport_error")
            .collect();
        assert_eq!(logged.len(), 1);
        let s = logged[0].1.to_string();
        assert!(!s.contains(TOKEN) && !s.contains("token="), "{s}");
        assert_eq!(logged[0].1["path"], "/api/new-chat");

        // 502 de taşıma hatası.
        r.set(502, json!({"ok": false, "error": "gw"}));
        let mut t = TickState::default();
        let out = remote_post(
            &c,
            &hosts,
            "a",
            "/api/new-chat",
            Map::new(),
            T,
            Some(&mut t),
        )
        .await;
        assert_eq!(out["code"], "host_down");
        assert_eq!(t.failed, set(&["a"]));
    })
    .await
}

// ---------------------------------------------------------------- exact_target + remote_stop

fn rows_status(rows: Value) -> HostStatus {
    ok_status(rows)
}

fn caps_exact() -> Capabilities {
    Capabilities {
        api: 1,
        capabilities: vec!["exact_target".into()],
    }
}

/// Değnekçinin kullanacağı akış: kanıt yoksa istek GİTMEZ.
async fn stop_if_exact(
    c: &cops_hosts::HostClient,
    hosts: &[HostRecord],
    st: &HostStatus,
    caps: Option<&Capabilities>,
    name: &str,
    t: &mut TickState,
) -> Result<Value, &'static str> {
    let now = 5000.0;
    let target = exact_target("a", name, Some(st), now - 1.0, false, caps, now)?;
    Ok(remote_stop(c, hosts, target, "tr", T, t).await)
}

#[tokio::test]
async fn ambiguous_or_inexact_target_sends_nothing() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let caps = caps_exact();
        let mut t = TickState::default();
        let cases = [
            // iki çalışan satır aynı adla (biri "running": 1, Python doğruluk kuralı)
            (json!([{"name": "s1", "running": true}, {"name": "s1", "running": 1}]), "s1", "ambiguous_sessions"),
            (json!([{"name": "s1", "running": true}, {"name": "s1", "running": "yes"}]), "s1", "ambiguous_sessions"),
            // yalnız önek/sonek eşleşmesi
            (json!([{"name": "s1_2", "running": true}, {"name": "xs1", "running": true}]), "s1", "no_exact_row"),
            // tam ad var ama çalışmıyor
            (json!([{"name": "s1", "running": false}, {"name": "s1", "running": 0}, {"name": "s1"}]), "s1", "no_exact_row"),
            (json!([{"name": "S1", "running": true}]), "s1", "no_exact_row"),
            (json!([]), "s1", "no_exact_row"),
        ];
        for (rows, name, want) in cases {
            let st = rows_status(rows.clone());
            let r = stop_if_exact(&c, &hosts, &st, Some(&caps), name, &mut t).await;
            assert_eq!(r.unwrap_err(), want, "{rows}");
        }

        // Yetenek ve tazelik kapıları.
        let one = rows_status(json!([{"name": "s1", "running": true}]));
        let old = Capabilities { api: 0, capabilities: vec![] };
        let no_cap = Capabilities { api: 3, capabilities: vec!["facts".into()] };
        assert_eq!(stop_if_exact(&c, &hosts, &one, None, "s1", &mut t).await.unwrap_err(), "caps_unknown");
        assert_eq!(stop_if_exact(&c, &hosts, &one, Some(&old), "s1", &mut t).await.unwrap_err(), "remote_too_old");
        assert_eq!(stop_if_exact(&c, &hosts, &one, Some(&no_cap), "s1", &mut t).await.unwrap_err(), "remote_too_old");
        // Belirsizlik yetenekten ÖNCE (Python sırası).
        let two = rows_status(json!([{"name": "s1", "running": true}, {"name": "s1", "running": true}]));
        assert_eq!(stop_if_exact(&c, &hosts, &two, None, "s1", &mut t).await.unwrap_err(), "ambiguous_sessions");
        let now = 5000.0;
        for (st, last_ok) in [(Some(&one), 0.0), (Some(&one), now - REMOTE_STALE_SECONDS - 1.0), (None, now)] {
            assert_eq!(exact_target("a", "s1", st, last_ok, false, Some(&caps), now).unwrap_err(), "host_down");
        }
        // Geri çekilmedeki host (Python `_remote_rows`: `_backing_off`) taze satırla da kapalı sayılır.
        assert_eq!(exact_target("a", "s1", Some(&one), now, true, Some(&caps), now).unwrap_err(), "host_down");
        let mut kept = one.clone();
        kept.ok = false;
        assert_eq!(exact_target("a", "s1", Some(&kept), now, false, Some(&caps), now).unwrap_err(), "host_down");

        assert_eq!(f.count(), 0, "no request for any refused target");
        assert_eq!(f.accepted(), 0);
        assert!(t.failed.is_empty() && t.succeeded.is_empty());
    })
    .await
}

#[tokio::test]
async fn remote_stop_sends_one_exact_stop_per_host_per_tick() {
    deadline(async {
        let fa = Fake::start(ok_handler()).await;
        let fb = Fake::start(handler(|_r| async {
            json(
                200,
                json!({"ok": false, "error": "no_exact_match", "code": "no_exact_match"}),
            )
        }))
        .await;
        let c = client();
        let hosts = vec![host("a", &fa.url()), host("b", &fb.url())];
        let caps = caps_exact();
        let st = rows_status(
            json!([{"name": "s1", "running": true}, {"name": "s10", "running": true},
                                     {"name": "s1", "running": false}]),
        );
        let now = 5000.0;
        let mut t = TickState::default();

        let t1 = exact_target("a", "s1", Some(&st), now, false, Some(&caps), now).unwrap();
        let out = remote_stop(&c, &hosts, t1, "tr", T, &mut t).await;
        assert_eq!(out["ok"], true);
        assert_eq!(out["host"], "a");
        assert_eq!(out["name"], "s1");
        assert_eq!(fa.count(), 1);
        let rec = &fa.recs()[0];
        assert_eq!(
            (rec.method.as_str(), rec.path.as_str()),
            ("POST", "/api/stop")
        );
        assert_eq!(
            rec.json(),
            json!({"name": "s1", "exact": true, "lang": "tr", "host": "local"})
        );
        assert_eq!(t.succeeded, set(&["a"]));

        // Aynı tick'te aynı host'a ikinci yıkıcı eylem ertelenir, GİTMEZ.
        let t2 = exact_target("a", "s10", Some(&st), now, false, Some(&caps), now).unwrap();
        let out = remote_stop(&c, &hosts, t2, "tr", T, &mut t).await;
        assert_eq!(out["ok"], false);
        assert_eq!(out["code"], "destructive_budget");
        assert_eq!(fa.count(), 1);

        // Başka host'un kendi bütçesi var; uzak ret uygulanmış sayılmaz, adı/host'u taşır.
        let t3 = exact_target("b", "s1", Some(&st), now, false, Some(&caps), now).unwrap();
        let out = remote_stop(&c, &hosts, t3, "en", T, &mut t).await;
        assert_eq!(fb.count(), 1);
        assert_eq!(out["ok"], false);
        assert_eq!(out["code"], "no_exact_match");
        assert_eq!(out["name"], "s1");
        assert_eq!(out["host"], "b");
        assert!(
            t.failed.is_empty(),
            "application refusal is not a transport error"
        );

        // Yeni tick: bütçe yenilenir; bloklu host'a gitmez.
        let mut t = TickState::default();
        t.failed.insert("a".into());
        let t4 = exact_target("a", "s1", Some(&st), now, false, Some(&caps), now).unwrap();
        let out = remote_stop(&c, &hosts, t4, "tr", T, &mut t).await;
        assert_eq!(
            out,
            json!({"ok": false, "error": "host_down", "code": "host_down", "host": "a"})
        );
        assert_eq!(fa.count(), 1);
        let mut t = TickState::default();
        let t5 = exact_target("a", "s1", Some(&st), now, false, Some(&caps), now).unwrap();
        assert_eq!(
            remote_stop(&c, &hosts, t5, "tr", T, &mut t).await["ok"],
            true
        );
        assert_eq!(fa.count(), 2);

        // ok alanı olmayan uzak yanıt uygulanmış SAYILMAZ.
        let fc = Fake::start(handler(|_r| async { json(200, json!({"done": 1})) })).await;
        let hosts = vec![host("a", &fc.url())];
        let mut t = TickState::default();
        let t6 = exact_target("a", "s1", Some(&st), now, false, Some(&caps), now).unwrap();
        let out = remote_stop(&c, &hosts, t6, "tr", T, &mut t).await;
        assert_eq!(out["ok"], false);
        assert_eq!(
            health::MAX_DESTRUCTIVE_PER_HOST,
            1,
            "the budget the test above relies on"
        );
    })
    .await
}
