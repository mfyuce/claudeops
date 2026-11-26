//! Sahte sunucuyla vekil: bilinmeyen host, `host=local`, sır gövdesi, `input_id` yeniden denemesi, dedup, yükleme,
//! indirme, imza ve hata metinlerinin temizliği. "İstek GİTMEZ" iddiaları sunucu sayacıyla doğrulanır.

mod support;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use cops_hosts::net::Connector;
use cops_hosts::{Caller, GetOpts, HostClient};
use serde_json::{json, Map, Value};
use support::*;
use tokio::sync::Semaphore;
use tokio::time::Instant;

fn obj(v: Value) -> Map<String, Value> {
    v.as_object().unwrap().clone()
}

const DEDUP: GetOpts = GetOpts {
    dedup: true,
    timeout: None,
};
const NO_DEDUP: GetOpts = GetOpts {
    dedup: false,
    timeout: None,
};

fn empty_body() -> ChanBody {
    chan_body().1
}

// ---------------------------------------------------------------- vekil

#[tokio::test]
async fn unknown_host_sends_nothing_and_does_not_sign() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let mut c = client();
        let signer = TestSigner::new(SignMode::Sign);
        c.signer = Some(signer.clone());
        let p = principal("alice");
        let u = Caller::User(&p);
        let hosts = vec![host("a", &f.url())];
        let want = (
            json!({"ok": false, "error": "unknown host: zz", "code": "unknown_host"}),
            200,
        );
        assert_eq!(
            c.proxy_get(&hosts, "zz", "/api/instances", &[], DEDUP, u)
                .await,
            want
        );
        assert_eq!(
            c.proxy_action(&hosts, "zz", "/api/start", obj(json!({})), None, u)
                .await,
            want
        );
        assert_eq!(
            c.proxy_term_action(
                &hosts,
                "zz",
                "/api/term/input",
                obj(json!({"input_id": "i1"})),
                u
            )
            .await,
            want
        );
        assert_eq!(
            c.proxy_post_raw(
                &hosts,
                "zz",
                "/api/files/upload",
                &[],
                empty_body(),
                0,
                "a/b",
                u
            )
            .await,
            want
        );
        let e = c
            .proxy_get_raw(&hosts, "zz", "/api/files/download", &[], u)
            .await
            .unwrap_err();
        assert_eq!(e, (200, "unknown host: zz".to_string()));
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(f.accepted(), 0);
        assert_eq!(signer.calls(), 0);
    })
    .await
}

#[tokio::test]
async fn outgoing_host_is_forced_local_and_caller_query_is_filtered() {
    deadline(async {
        let f = Fake::start(handler(|r: Rec| async move {
            if r.path.ends_with("/api/files/download") {
                Act::Reply(
                    hyper::Response::builder()
                        .status(200)
                        .body(body_of("bin"))
                        .unwrap(),
                )
            } else {
                json(200, json!({"ok": true}))
            }
        }))
        .await;
        let c = client();
        let hosts = vec![
            host("a", &f.url()),
            host("p", &format!("{}/prefix", f.url())),
        ];
        let (v, _) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/start",
                obj(json!({"host": "evil", "sid": "s1"})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(v["ok"], true);
        let r = &f.recs()[0];
        assert_eq!(r.method, "POST");
        assert_eq!(r.json(), json!({"host": "local", "sid": "s1"}));
        assert_eq!(r.query, format!("token={TOKEN}"));
        assert_eq!(
            r.header("content-type").as_deref(),
            Some("application/json")
        );

        let q = [
            ("host", "x"),
            ("token", "bad"),
            ("ticket", "t"),
            ("q", "a b/ç"),
        ];
        let want_q = format!("q=a+b%2F%C3%A7&token={TOKEN}");
        c.proxy_get(
            &hosts,
            "a",
            "/api/files/list",
            &q,
            NO_DEDUP,
            Caller::Unbound,
        )
        .await;
        c.proxy_get_raw(&hosts, "a", "/api/files/download", &q, Caller::Unbound)
            .await
            .unwrap();
        c.proxy_post_raw(
            &hosts,
            "a",
            "/api/files/upload",
            &q,
            empty_body(),
            0,
            "a/b",
            Caller::Unbound,
        )
        .await;
        // Taban yolu korunur.
        c.proxy_get(
            &hosts,
            "p",
            "/api/instances",
            &[],
            NO_DEDUP,
            Caller::Unbound,
        )
        .await;
        let recs = f.recs();
        assert_eq!(recs.len(), 5);
        for r in &recs[1..4] {
            assert_eq!(r.query, want_q, "{}", r.path);
        }
        assert_eq!(recs[4].path, "/prefix/api/instances");
        assert_eq!(recs[4].header("host"), Some(f.addr.to_string()));
    })
    .await
}

#[tokio::test]
async fn secret_body_never_goes_to_plain_http_and_dns_loopback_is_blocked() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let calls = Arc::new(AtomicUsize::new(0));
        let mut c = HostClient::new(Connector {
            resolver: counting_resolver(f.addr, calls.clone()),
            tls: None,
        });
        c.timeouts = timeouts();
        let port = f.addr.port();
        let hosts = vec![
            host("lan", &format!("http://fake-lan.test:{port}")),
            host("lo", &f.url()),
        ];
        let secret = json!({"provider": "x", "value": "sk-very-secret"});
        let (v, st) = c
            .proxy_action(
                &hosts,
                "lan",
                "/api/settings/byok",
                obj(secret.clone()),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["code"], "insecure_host");
        assert!(!v.to_string().contains("sk-very-secret"));
        assert_eq!(
            calls.load(Ordering::SeqCst),
            0,
            "refused before any name lookup"
        );
        assert_eq!(f.accepted(), 0);

        // Loopback adresine sır gider (tünel).
        let (v, _) = c
            .proxy_action(
                &hosts,
                "lo",
                "/api/settings/byok",
                obj(secret.clone()),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(v["ok"], true);
        assert_eq!(f.recs()[0].json()["value"], "sk-very-secret");

        // `value` yoksa süzgeç devreye girmez; ama DNS adı loopback'e çözülünce bağlantı kurulmaz (sunucu CANLI).
        let (v, st) = c
            .proxy_action(
                &hosts,
                "lan",
                "/api/settings/byok",
                obj(json!({"provider": "x"})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        assert!(v["error"].as_str().unwrap().contains("blocked"), "{v}");
        assert_clean(&v.to_string(), port);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(f.accepted(), 1, "only the loopback-literal host connected");
    })
    .await
}

#[tokio::test]
async fn term_input_retries_three_times_with_same_input_id() {
    deadline(async {
        let f = Fake::start(handler(|r: Rec| async move {
            match r.path.as_str() {
                "/api/term/input" | "/api/term/resize" => Act::Drop,
                "/api/term/key" => json(200, json!({"ok": false, "error": "no session"})),
                "/api/term/raw" => {
                    tokio::time::sleep(Duration::from_secs(10)).await;
                    json(200, json!({"ok": true}))
                }
                _ => json(200, json!({"ok": true})),
            }
        }))
        .await;
        let mut c = client();
        c.timeouts.term_attempt = Duration::from_millis(300);
        let signer = TestSigner::new(SignMode::Sign);
        c.signer = Some(signer.clone());
        let p = principal("alice");
        let u = Caller::User(&p);
        let hosts = vec![host("a", &f.url())];
        let count = |path: &str| f.recs().iter().filter(|r| r.path == path).count();

        let (v, st) = c
            .proxy_term_action(
                &hosts,
                "a",
                "/api/term/input",
                obj(json!({"input_id": "in-1", "text": "x"})),
                u,
            )
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        let recs: Vec<_> = f
            .recs()
            .into_iter()
            .filter(|r| r.path == "/api/term/input")
            .collect();
        assert_eq!(recs.len(), 3);
        assert!(recs.iter().all(|r| r.json()["input_id"] == "in-1"));
        let mut sigs: Vec<_> = recs
            .iter()
            .map(|r| r.header("x-test-sig").unwrap())
            .collect();
        sigs.dedup();
        assert_eq!(sigs.len(), 3, "each attempt signed anew");

        // Uzağın kendi ok:false cevabı yeniden denenmez.
        let (v, _) = c
            .proxy_term_action(
                &hosts,
                "a",
                "/api/term/key",
                obj(json!({"input_id": "in-2"})),
                u,
            )
            .await;
        assert_eq!(v["error"], "no session");
        assert_eq!(count("/api/term/key"), 1);

        // input_id yok / geçersiz / yeniden denenmeyen yol: tek deneme.
        for body in [
            json!({"text": "x"}),
            json!({"input_id": "a b"}),
            json!({"input_id": ""}),
        ] {
            let before = count("/api/term/input");
            c.proxy_term_action(&hosts, "a", "/api/term/input", obj(body.clone()), u)
                .await;
            assert_eq!(count("/api/term/input"), before + 1, "{body}");
        }
        c.proxy_term_action(
            &hosts,
            "a",
            "/api/term/resize",
            obj(json!({"input_id": "in-3"})),
            u,
        )
        .await;
        assert_eq!(count("/api/term/resize"), 1);

        // Asılan uzak: deneme başı kısa sınır (300 ms) x 3; eylem zaman aşımı (3 sn) beklenmez.
        let t0 = Instant::now();
        let (v, _) = c
            .proxy_term_action(
                &hosts,
                "a",
                "/api/term/raw",
                obj(json!({"input_id": "in-4"})),
                u,
            )
            .await;
        let took = t0.elapsed();
        assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        assert_eq!(count("/api/term/raw"), 3);
        assert!(
            took >= Duration::from_millis(850) && took < Duration::from_secs(3),
            "{took:?}"
        );
    })
    .await
}

// ---------------------------------------------------------------- dedup

fn gated(gate: Arc<Semaphore>) -> Handler {
    let n = Arc::new(AtomicUsize::new(0));
    handler(move |r: Rec| {
        let gate = gate.clone();
        let seq = n.fetch_add(1, Ordering::SeqCst) + 1;
        async move {
            gate.acquire().await.unwrap().forget();
            if r.path == "/api/files/download" {
                Act::Reply(
                    hyper::Response::builder()
                        .status(200)
                        .body(body_of(format!("file-{seq}")))
                        .unwrap(),
                )
            } else {
                json(200, json!({"ok": true, "seq": seq}))
            }
        }
    })
}

type Shared = (Arc<HostClient>, Arc<Vec<cops_hosts::HostRecord>>);

fn spawn_get(
    s: &Shared,
    uid: Option<&str>,
    opts: GetOpts,
) -> tokio::task::JoinHandle<(Value, u16)> {
    let (c, hosts) = (s.0.clone(), s.1.clone());
    let uid = uid.map(str::to_string);
    tokio::spawn(async move {
        let p = uid.map(|u| principal(&u));
        let caller = p.as_ref().map_or(Caller::Unbound, Caller::User);
        c.proxy_get(
            &hosts,
            "a",
            "/api/term/output",
            &[("session", "s")],
            opts,
            caller,
        )
        .await
    })
}

async fn shared(f: &Fake) -> Shared {
    (Arc::new(client()), Arc::new(vec![host("a", &f.url())]))
}

#[tokio::test]
async fn concurrent_same_url_sends_one_request_and_reuses_last_good() {
    deadline(async {
        let gate = Arc::new(Semaphore::new(0));
        let f = Fake::start(gated(gate.clone())).await;
        let s = shared(&f).await;
        let a = spawn_get(&s, None, DEDUP);
        f.wait_count(1).await;
        let t0 = Instant::now();
        let (v, st) = spawn_get(&s, None, DEDUP).await.unwrap();
        assert!(t0.elapsed() < Duration::from_secs(1));
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        assert!(v["error"].as_str().unwrap().contains("busy"), "{v}");
        gate.add_permits(1);
        assert_eq!(a.await.unwrap(), (json!({"ok": true, "seq": 1}), 200));
        assert_eq!(f.count(), 1);

        // İkinci tur: üst üste binen istek son başarılı yanıtı alır, sunucuya gitmez.
        let a = spawn_get(&s, None, DEDUP);
        f.wait_count(2).await;
        assert_eq!(
            spawn_get(&s, None, DEDUP).await.unwrap(),
            (json!({"ok": true, "seq": 1}), 200)
        );
        gate.add_permits(1);
        assert_eq!(a.await.unwrap().0["seq"], 2);
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(f.count(), 2);
    })
    .await
}

#[tokio::test]
async fn dedup_key_includes_identity() {
    deadline(async {
        let gate = Arc::new(Semaphore::new(0));
        let f = Fake::start(gated(gate.clone())).await;
        let s = shared(&f).await;
        let a = spawn_get(&s, Some("alice"), DEDUP);
        f.wait_count(1).await;
        let b = spawn_get(&s, Some("bob"), DEDUP);
        f.wait_count(2).await;
        let n = spawn_get(&s, None, DEDUP);
        f.wait_count(3).await;
        // Aynı kimlik aynı URL: uçuşta, gitmez.
        let (v, _) = spawn_get(&s, Some("alice"), DEDUP).await.unwrap();
        assert!(v["error"].as_str().unwrap().contains("busy"), "{v}");
        gate.add_permits(3);
        for h in [a, b, n] {
            assert_eq!(h.await.unwrap().0["ok"], true);
        }
        assert_eq!(f.count(), 3);
    })
    .await
}

#[tokio::test]
async fn cancelled_task_releases_its_flight() {
    deadline(async {
        let gate = Arc::new(Semaphore::new(0));
        let f = Fake::start(gated(gate.clone())).await;
        let s = shared(&f).await;
        let a = spawn_get(&s, None, DEDUP);
        f.wait_count(1).await;
        a.abort();
        assert!(a.await.unwrap_err().is_cancelled());
        let b = spawn_get(&s, None, DEDUP);
        f.wait_count(2).await;
        gate.add_permits(2);
        assert_eq!(b.await.unwrap().0["ok"], true);
    })
    .await
}

#[tokio::test]
async fn dedup_off_lets_concurrent_requests_through() {
    deadline(async {
        let gate = Arc::new(Semaphore::new(0));
        let f = Fake::start(gated(gate.clone())).await;
        let s = shared(&f).await;
        let a = spawn_get(&s, None, NO_DEDUP);
        let b = spawn_get(&s, None, NO_DEDUP);
        f.wait_count(2).await;
        gate.add_permits(2);
        assert_eq!(a.await.unwrap().0["ok"], true);
        assert_eq!(b.await.unwrap().0["ok"], true);
    })
    .await
}

#[tokio::test]
async fn concurrent_same_download_is_refused_not_cached() {
    deadline(async {
        let gate = Arc::new(Semaphore::new(0));
        let f = Fake::start(gated(gate.clone())).await;
        let (c, hosts) = shared(&f).await;
        let (c2, h2) = (c.clone(), hosts.clone());
        let a = tokio::spawn(async move {
            c2.proxy_get_raw(
                &h2,
                "a",
                "/api/files/download",
                &[("path", "x")],
                Caller::Unbound,
            )
            .await
        });
        f.wait_count(1).await;
        let e = c
            .proxy_get_raw(
                &hosts,
                "a",
                "/api/files/download",
                &[("path", "x")],
                Caller::Unbound,
            )
            .await
            .unwrap_err();
        assert_eq!(e.0, 200);
        assert!(e.1.contains("unreachable: busy"), "{}", e.1);
        assert_clean(&e.1, f.addr.port());
        gate.add_permits(1);
        assert_eq!(&a.await.unwrap().unwrap().body[..], b"file-1");
        assert_eq!(f.count(), 1);
    })
    .await
}

// ---------------------------------------------------------------- yükleme / indirme

fn upload_echo() -> Handler {
    handler(|r: Rec| async move {
        if r.query.contains("mode=html") {
            text(200, "<html>")
        } else {
            json(200, json!({"ok": true, "len": r.body.len()}))
        }
    })
}

#[tokio::test]
async fn upload_body_ending_early_or_overflowing_is_an_error() {
    deadline(async {
        let f = Fake::start(upload_echo()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];

        let (tx, body) = chan_body();
        tx.send(Bytes::from(vec![1u8; 50])).await.unwrap();
        drop(tx);
        let (v, st) = c
            .proxy_post_raw(
                &hosts,
                "a",
                "/api/files/upload",
                &[],
                body,
                100,
                "application/octet-stream",
                Caller::Unbound,
            )
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        assert!(
            v["error"]
                .as_str()
                .unwrap()
                .contains("ended early, 50 bytes missing"),
            "{v}"
        );
        assert_clean(&v.to_string(), f.addr.port());

        let (tx, body) = chan_body();
        tx.send(Bytes::from(vec![1u8; 20])).await.unwrap();
        drop(tx);
        let (v, _) = c
            .proxy_post_raw(
                &hosts,
                "a",
                "/api/files/upload",
                &[],
                body,
                10,
                "application/octet-stream",
                Caller::Unbound,
            )
            .await;
        assert!(
            v["error"]
                .as_str()
                .unwrap()
                .contains("longer than declared"),
            "{v}"
        );

        f.wait_no_live().await;
        assert_eq!(f.count(), 0, "no complete request reached the server");
    })
    .await
}

#[tokio::test]
async fn slow_but_progressing_upload_is_not_cut() {
    deadline(async {
        let f = Fake::start(upload_echo()).await;
        let mut c = client();
        c.timeouts.action = Duration::from_millis(300);
        let hosts = vec![host("a", &f.url())];
        let (tx, body) = chan_body();
        let feeder = tokio::spawn(async move {
            for i in 0..10u8 {
                tokio::time::sleep(Duration::from_millis(100)).await;
                tx.send(Bytes::from(vec![i; 100])).await.unwrap();
            }
        });
        let t0 = Instant::now();
        let (v, st) = c
            .proxy_post_raw(
                &hosts,
                "a",
                "/api/files/upload",
                &[("path", "d/f")],
                body,
                1000,
                "application/x-test",
                Caller::Unbound,
            )
            .await;
        assert!(t0.elapsed() >= Duration::from_millis(900));
        assert_eq!((v, st), (json!({"ok": true, "len": 1000}), 200));
        feeder.await.unwrap();
        let r = &f.recs()[0];
        let want: Vec<u8> = (0..10u8).flat_map(|i| vec![i; 100]).collect();
        assert_eq!(&r.body[..], &want[..]);
        assert_eq!(
            r.header("content-type").as_deref(),
            Some("application/x-test")
        );
        assert_eq!(r.header("content-length").as_deref(), Some("1000"));
        assert_eq!(r.query, format!("path=d%2Ff&token={TOKEN}"));
    })
    .await
}

#[tokio::test]
async fn stalled_upload_times_out_and_bad_reply_is_reported() {
    deadline(async {
        let f = Fake::start(upload_echo()).await;
        let mut c = client();
        c.timeouts.action = Duration::from_millis(300);
        let hosts = vec![host("a", &f.url())];
        let (tx, body) = chan_body();
        tx.send(Bytes::from_static(b"abc")).await.unwrap();
        let t0 = Instant::now();
        let (v, _) = c
            .proxy_post_raw(
                &hosts,
                "a",
                "/api/files/upload",
                &[],
                body,
                100,
                "a/b",
                Caller::Unbound,
            )
            .await;
        let took = t0.elapsed();
        assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        assert!(
            took >= Duration::from_millis(290) && took < Duration::from_millis(1500),
            "{took:?}"
        );
        drop(tx);
        f.wait_no_live().await;
        assert_eq!(f.count(), 0);

        let (tx, body) = chan_body();
        tx.send(Bytes::from_static(b"abc")).await.unwrap();
        drop(tx);
        let (v, st) = c
            .proxy_post_raw(
                &hosts,
                "a",
                "/api/files/upload",
                &[("mode", "html")],
                body,
                3,
                "a/b",
                Caller::Unbound,
            )
            .await;
        assert_eq!(
            (v, st),
            (json!({"ok": false, "error": "a: bad response"}), 200)
        );
    })
    .await
}

#[tokio::test]
async fn download_passes_raw_body_and_only_two_headers() {
    deadline(async {
        let f = Fake::start(handler(|r: Rec| async move {
            let status = if r.query.contains("path=missing") {
                404
            } else {
                200
            };
            Act::Reply(
                hyper::Response::builder()
                    .status(status)
                    .header("content-type", "application/octet-stream")
                    .header("content-disposition", "attachment; filename=\"a.bin\"")
                    .header("set-cookie", "s=1")
                    .header("x-remote-secret", "y")
                    .body(body_of(vec![0u8, 255, 1, 2]))
                    .unwrap(),
            )
        }))
        .await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let r = c
            .proxy_get_raw(
                &hosts,
                "a",
                "/api/files/download",
                &[("path", "a.bin")],
                Caller::Unbound,
            )
            .await
            .unwrap();
        assert_eq!(r.status, 200);
        assert_eq!(&r.body[..], &[0u8, 255, 1, 2]);
        let mut names: Vec<_> = r.headers.keys().map(|k| k.as_str().to_string()).collect();
        names.sort();
        assert_eq!(names, ["content-disposition", "content-type"]);
        assert_eq!(
            r.headers["content-disposition"],
            "attachment; filename=\"a.bin\""
        );
        let r = c
            .proxy_get_raw(
                &hosts,
                "a",
                "/api/files/download",
                &[("path", "missing")],
                Caller::Unbound,
            )
            .await
            .unwrap();
        assert_eq!(r.status, 404, "remote status passes through");
    })
    .await
}

// ---------------------------------------------------------------- imza

#[tokio::test]
async fn unbound_caller_is_never_signed() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let mut c = client();
        let signer = TestSigner::new(SignMode::Sign);
        c.signer = Some(signer.clone());
        let hosts = vec![host("a", &f.url())];
        c.proxy_get(
            &hosts,
            "a",
            "/api/instances",
            &[],
            NO_DEDUP,
            Caller::Unbound,
        )
        .await;
        c.proxy_action(
            &hosts,
            "a",
            "/api/start",
            obj(json!({})),
            None,
            Caller::Unbound,
        )
        .await;
        c.proxy_get_raw(&hosts, "a", "/api/files/download", &[], Caller::Unbound)
            .await
            .unwrap();
        c.proxy_post_raw(
            &hosts,
            "a",
            "/api/files/upload",
            &[],
            empty_body(),
            0,
            "a/b",
            Caller::Unbound,
        )
        .await;
        assert_eq!(f.count(), 4);
        assert_eq!(signer.calls(), 0);
        assert!(f.recs().iter().all(|r| r.header("x-test-sig").is_none()));
    })
    .await
}

#[tokio::test]
async fn user_caller_is_signed_over_path_and_body_without_query() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let mut c = client();
        let signer = TestSigner::new(SignMode::Sign);
        c.signer = Some(signer.clone());
        let p = principal("alice");
        let u = Caller::User(&p);
        let hosts = vec![host("pfx", &format!("{}/base", f.url()))];
        c.proxy_get(&hosts, "pfx", "/api/instances", &[("x", "1")], NO_DEDUP, u)
            .await;
        c.proxy_action(
            &hosts,
            "pfx",
            "/api/start",
            obj(json!({"sid": "s"})),
            None,
            u,
        )
        .await;
        c.proxy_post_raw(
            &hosts,
            "pfx",
            "/api/files/upload",
            &[],
            empty_body(),
            0,
            "a/b",
            u,
        )
        .await;
        let recs = f.recs();
        let seen = signer.seen();
        assert_eq!((recs.len(), seen.len()), (3, 3));
        for (s, r) in seen.iter().zip(&recs) {
            assert_eq!(s.uid, "alice");
            assert_eq!(s.host_name, "pfx");
            assert_eq!(s.method, r.method);
            assert_eq!(s.path, r.path, "signed path = request path without query");
            assert!(!s.path.contains('?') && !s.path.contains(TOKEN));
            assert_eq!(r.header("x-test-uid").as_deref(), Some("alice"));
        }
        assert_eq!(seen[0].body, None);
        assert_eq!(
            seen[1].body.as_deref(),
            Some(&recs[1].body[..]),
            "signature covers exact body"
        );
        assert_eq!(seen[2].body, None, "streamed upload is signed bodiless");
    })
    .await
}

async fn assert_refused(c: &HostClient, hosts: &[cops_hosts::HostRecord], reason: &str) {
    let p = principal("alice");
    let u = Caller::User(&p);
    let want = (
        json!({"ok": false, "error": format!("a: signed identity required, request not sent ({reason})"), "reason": reason}),
        502,
    );
    assert_eq!(
        c.proxy_get(hosts, "a", "/api/instances", &[], DEDUP, u)
            .await,
        want
    );
    assert_eq!(
        c.proxy_action(hosts, "a", "/api/start", obj(json!({})), None, u)
            .await,
        want
    );
    assert_eq!(
        c.proxy_term_action(
            hosts,
            "a",
            "/api/term/input",
            obj(json!({"input_id": "i"})),
            u
        )
        .await,
        want,
        "refusal is not a transport error: no retry"
    );
    assert_eq!(
        c.proxy_post_raw(
            hosts,
            "a",
            "/api/files/upload",
            &[],
            empty_body(),
            0,
            "a/b",
            u
        )
        .await,
        want
    );
    assert_eq!(
        c.proxy_get_raw(hosts, "a", "/api/files/download", &[], u)
            .await
            .unwrap_err(),
        (502, want.0["error"].as_str().unwrap().to_string())
    );
}

#[tokio::test]
async fn signer_refusal_panic_and_bad_headers_are_502_and_nothing_is_sent() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let hosts = vec![host("a", &f.url())];
        let cases: Vec<(SignMode, &str)> = vec![
            (SignMode::Refuse, "no_key"),
            (SignMode::Panic, "signer_failed"),
            (SignMode::Header("host", "evil"), "bad_header"),
            (SignMode::Header("Host", "evil"), "bad_header"),
            (SignMode::Header("content-length", "5"), "bad_header"),
            (SignMode::Header("Content-Length", "5"), "bad_header"),
            (
                SignMode::Header("transfer-encoding", "chunked"),
                "bad_header",
            ),
            (SignMode::Header("connection", "close"), "bad_header"),
            (SignMode::Header("upgrade", "h2c"), "bad_header"),
            (SignMode::Header("sec-websocket-key", "x"), "bad_header"),
            (SignMode::Header("bad name", "x"), "bad_header"),
            (SignMode::Header("x-ok", "bad\nvalue"), "bad_header"),
        ];
        for (mode, reason) in cases {
            let mut c = client();
            let signer = TestSigner::new(mode);
            c.signer = Some(signer.clone());
            assert_refused(&c, &hosts, reason).await;
            assert_eq!(
                signer.calls(),
                5,
                "{reason}: signed once per call, never retried"
            );
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(
            f.accepted(),
            0,
            "no connection opened for a refused request"
        );
    })
    .await
}

// ---------------------------------------------------------------- hata metinleri

#[tokio::test]
async fn error_texts_carry_no_url_port_or_token() {
    deadline(async {
        // Kapalı port: bağlan, bırak.
        let dead = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let dead_addr = dead.local_addr().unwrap();
        drop(dead);
        let raw = Raw::start(hold_until_eof).await;
        let bad = Fake::start(handler(|_r: Rec| async move { text(200, "nope") })).await;
        let mut c = client();
        c.timeouts.term_read = Duration::from_millis(200);
        c.timeouts.action = Duration::from_millis(200);
        let hosts = vec![
            host("dead", &format!("http://{dead_addr}")),
            host("slow", &raw.url()),
            host("bad", &bad.url()),
            host("weird", "http://[zz"),
        ];
        let mut texts = Vec::new();
        for name in ["dead", "slow", "bad", "weird"] {
            let (v, _) = c
                .proxy_get(
                    &hosts,
                    name,
                    "/api/instances",
                    &[("q", "1")],
                    NO_DEDUP,
                    Caller::Unbound,
                )
                .await;
            assert_eq!(v["ok"], false, "{name}: {v}");
            texts.push(v.to_string());
            let (v, _) = c
                .proxy_action(
                    &hosts,
                    name,
                    "/api/start",
                    obj(json!({})),
                    None,
                    Caller::Unbound,
                )
                .await;
            assert_eq!(v["ok"], false, "{name}: {v}");
            texts.push(v.to_string());
            let e = c
                .proxy_get_raw(&hosts, name, "/api/files/download", &[], Caller::Unbound)
                .await;
            if let Err((_, m)) = e {
                texts.push(m);
            }
            let (v, _) = c
                .proxy_post_raw(
                    &hosts,
                    name,
                    "/api/files/upload",
                    &[],
                    empty_body(),
                    0,
                    "a/b",
                    Caller::Unbound,
                )
                .await;
            texts.push(v.to_string());
        }
        for t in &texts {
            for port in [dead_addr.port(), raw.addr.port(), bad.addr.port()] {
                assert_clean(t, port);
            }
        }
        assert!(!format!("{hosts:?}").contains(TOKEN), "Debug redacts token");
    })
    .await
}
