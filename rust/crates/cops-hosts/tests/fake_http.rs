//! Sahte sunucuyla HTTP katmanı: keep-alive havuzu, bayat bağlantı, zaman aşımları, yanıt tipleri.

mod support;

use std::time::Duration;

use cops_hosts::endpoint::Endpoint;
use cops_hosts::http::Attempt;
use cops_hosts::{Caller, GetOpts};
use http::Method;
use serde_json::{json, Map, Value};
use support::*;
use tokio::io::AsyncWriteExt;
use tokio::time::Instant;

fn obj(v: Value) -> Map<String, Value> {
    v.as_object().unwrap().clone()
}

fn get_opts(dedup: bool, timeout: Option<Duration>) -> GetOpts {
    GetOpts { dedup, timeout }
}

fn pool_key(url: &str) -> String {
    Endpoint::parse(url).unwrap().pool_key()
}

#[tokio::test]
async fn pool_reuses_one_keepalive_connection() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        for i in 1..=3u64 {
            let (v, st) = c
                .proxy_get(
                    &hosts,
                    "a",
                    "/api/term/output",
                    &[],
                    get_opts(true, None),
                    Caller::Unbound,
                )
                .await;
            assert_eq!((st, v["seq"].as_u64()), (200, Some(2 * i - 1)), "{v}");
            let (v, st) = c
                .proxy_action(
                    &hosts,
                    "a",
                    "/api/start",
                    obj(json!({"sid": "s"})),
                    None,
                    Caller::Unbound,
                )
                .await;
            assert_eq!((st, v["seq"].as_u64()), (200, Some(2 * i)), "{v}");
        }
        assert_eq!(f.count(), 6);
        assert_eq!(f.accepted(), 1, "keep-alive connection must be reused");
        assert!(f.recs().iter().all(|r| r.conn == 0));
        assert_eq!(c.pool.idle_count(&pool_key(&f.url())), 1);
    })
    .await
}

#[tokio::test]
async fn server_closed_idle_connection_does_not_fail_post() {
    deadline(async {
        let f = Fake::start(ok_handler()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let (v, _) = c
            .proxy_get(
                &hosts,
                "a",
                "/api/instances",
                &[],
                get_opts(false, None),
                Caller::Unbound,
            )
            .await;
        assert_eq!(v["ok"], true);
        assert_eq!(c.pool.idle_count(&pool_key(&f.url())), 1);
        // Sunucu boştaki keep-alive bağlantısını kapatır; istemcinin bağlantı görevi EOF'u görsün.
        f.kill_connections();
        f.wait_no_live().await;
        tokio::time::sleep(Duration::from_millis(200)).await;
        // Kapalı bağlantı ya havuzdan elenir ya da istek ona hiç yazılamadığı (`!sent`) için taze bağlantıyla
        // denenir; ikisi de doğru. İstek karşıya ulaşmış sayılsaydı POST yeniden denenmez ve burada düşerdi.
        let (v, st) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/start",
                obj(json!({"sid": "s"})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!((st, &v["ok"]), (200, &json!(true)), "{v}");
        assert_eq!(f.accepted(), 2);
        assert_eq!(f.count(), 2);
        assert_eq!(f.recs()[1].conn, 1);
        assert_eq!(c.pool.idle_count(&pool_key(&f.url())), 1);
    })
    .await
}

/// Bağlantı 0'daki 2. istek okunur ve yanıtsız kapatılır (bayat ama "canlı görünen" havuz bağlantısı).
fn drop_second_on_first_conn() -> Handler {
    handler(|r: Rec| async move {
        if r.conn == 0 && r.idx == 1 {
            Act::Drop
        } else {
            json(200, json!({"ok": true, "conn": r.conn, "idx": r.idx}))
        }
    })
}

#[tokio::test]
async fn stale_pooled_get_is_retried_once_with_fresh_signature() {
    deadline(async {
        let f = Fake::start(drop_second_on_first_conn()).await;
        let mut c = client();
        let signer = TestSigner::new(SignMode::Sign);
        c.signer = Some(signer.clone());
        let p = principal("alice");
        let hosts = vec![host("a", &f.url())];
        for _ in 0..2 {
            let (v, st) = c
                .proxy_get(
                    &hosts,
                    "a",
                    "/api/term/output",
                    &[],
                    get_opts(false, None),
                    Caller::User(&p),
                )
                .await;
            assert_eq!((st, &v["ok"]), (200, &json!(true)), "{v}");
        }
        let recs = f.recs();
        assert_eq!(recs.len(), 3, "stale GET retried exactly once");
        assert_eq!((recs[1].conn, recs[1].idx), (0, 1));
        assert_eq!((recs[2].conn, recs[2].idx), (1, 0));
        let sigs: Vec<_> = recs
            .iter()
            .map(|r| r.header("x-test-sig").unwrap())
            .collect();
        assert_eq!(
            sigs,
            ["sig-1", "sig-2", "sig-3"],
            "every attempt gets a new signature"
        );
        assert_eq!(signer.calls(), 3);
    })
    .await
}

#[tokio::test]
async fn stale_pooled_post_that_reached_server_is_not_retried() {
    deadline(async {
        let f = Fake::start(drop_second_on_first_conn()).await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let (v, _) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/start",
                obj(json!({"sid": "s"})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(v["ok"], true);
        let (v, st) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/start",
                obj(json!({"sid": "s"})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["ok"], false);
        assert_eq!(v["code"], "host_unreachable");
        assert_clean(&v.to_string(), f.addr.port());
        tokio::time::sleep(Duration::from_millis(200)).await;
        assert_eq!(
            f.count(),
            2,
            "POST that reached the server must not be sent again"
        );
        assert_eq!(f.accepted(), 1, "no fresh connection opened for a retry");
    })
    .await
}

#[tokio::test]
async fn silent_server_times_out_and_socket_is_closed() {
    deadline(async {
        let raw = Raw::start(hold_until_eof).await;
        let c = client();
        let hosts = vec![host("a", &raw.url())];
        let t0 = Instant::now();
        let (v, st) = c
            .proxy_get(
                &hosts,
                "a",
                "/api/term/output",
                &[],
                get_opts(false, Some(Duration::from_millis(300))),
                Caller::Unbound,
            )
            .await;
        let took = t0.elapsed();
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        assert!(
            took >= Duration::from_millis(290) && took < Duration::from_secs(2),
            "{took:?}"
        );
        assert_clean(&v.to_string(), raw.addr.port());
        // POST zaman aşımı: yeniden denenmez (yeni bağlantı yok).
        let (v, _) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/start",
                obj(json!({})),
                Some(Duration::from_millis(300)),
                Caller::Unbound,
            )
            .await;
        assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        assert_eq!(raw.accepted(), 2);
        raw.wait_no_live().await;
        assert_eq!(c.pool.idle_count(&pool_key(&raw.url())), 0);
    })
    .await
}

#[tokio::test]
async fn drip_feed_response_is_cut_by_total_cap() {
    deadline(async {
        let raw = Raw::start(|mut s| async move {
            if !read_head(&mut s).await {
                return;
            }
            let head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n";
            if s.write_all(head).await.is_err() {
                return;
            }
            write_until_error(&mut s, b" ", Duration::from_millis(50)).await;
        })
        .await;
        let mut c = client();
        c.timeouts.total_cap = Duration::from_secs(1);
        let hosts = vec![host("a", &raw.url())];
        let t0 = Instant::now();
        let (v, _) = c
            .proxy_get(
                &hosts,
                "a",
                "/api/term/output",
                &[],
                get_opts(false, Some(Duration::from_millis(300))),
                Caller::Unbound,
            )
            .await;
        let took = t0.elapsed();
        assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        // Her parça adım sınırının (300 ms) içinde gelir; yalnız mutlak tavan keser.
        assert!(took >= Duration::from_millis(950) && took < Duration::from_secs(3), "{took:?}");
        raw.wait_no_live().await;
    })
    .await
}

#[tokio::test]
async fn huge_response_body_is_refused_and_connection_dropped() {
    deadline(async {
        let raw = Raw::start(|mut s| async move {
            if !read_head(&mut s).await {
                return;
            }
            let head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1099511627776\r\n\r\n";
            if s.write_all(head).await.is_err() {
                return;
            }
            write_until_error(&mut s, &[b' '; 65536], Duration::ZERO).await;
        })
        .await;
        let c = client();
        let hosts = vec![host("a", &raw.url())];
        let (v, st) = c
            .proxy_get(&hosts, "a", "/api/files/read", &[], get_opts(false, None), Caller::Unbound)
            .await;
        assert_eq!(st, 200);
        assert_eq!(v["code"], "host_unreachable");
        assert!(v["error"].as_str().unwrap().contains("response too large"), "{v}");
        raw.wait_no_live().await;
    })
    .await
}

#[tokio::test]
async fn max_body_boundary_is_exact() {
    deadline(async {
        let f = Fake::start(handler(|r: Rec| async move {
            let n: usize = r.path.trim_start_matches("/n/").parse().unwrap();
            text(200, &"x".repeat(n))
        }))
        .await;
        let c = client();
        let ep = Endpoint::parse(&f.url()).unwrap();
        let attempt = |target: &'static str| Attempt {
            method: Method::GET,
            endpoint: &ep,
            target,
            headers: vec![],
            body: None,
            timeout: Duration::from_secs(2),
            total: Duration::from_secs(5),
            max_body: 1024,
        };
        let ok = c.pool.attempt(attempt("/n/1024")).await.unwrap();
        assert_eq!(ok.body.len(), 1024);
        let err = c.pool.attempt(attempt("/n/1025")).await.unwrap_err();
        assert_eq!(err.message, "response too large");
        assert!(err.sent);
        assert!(err.from_pool);
        // Yarım okunan bağlantı havuza geri dönmez.
        assert_eq!(c.pool.idle_count(&ep.pool_key()), 0);
        assert_eq!(f.accepted(), 1);
    })
    .await
}

#[tokio::test]
async fn non_json_non_object_and_error_statuses() {
    deadline(async {
        let f = Fake::start(handler(|r: Rec| async move {
            match r.path.as_str() {
                "/api/term/output" => text(200, "<html>hello</html>"),
                "/api/files/list" => json(200, json!([1, 2])),
                "/api/files/read" => text(200, ""),
                "/api/instances" => text(502, "Bad Gateway"),
                "/api/cli/status" => json(404, json!({"ok": false, "error": "not found"})),
                _ => json(500, json!({"ok": false, "error": "boom"})),
            }
        }))
        .await;
        let c = client();
        let hosts = vec![host("a", &f.url())];
        let get = |path: &'static str| {
            let c = &c;
            let hosts = &hosts;
            async move {
                c.proxy_get(
                    hosts,
                    "a",
                    path,
                    &[],
                    get_opts(false, None),
                    Caller::Unbound,
                )
                .await
            }
        };
        for (path, want) in [
            ("/api/term/output", "a unreachable: bad response (not JSON)"),
            (
                "/api/files/list",
                "a unreachable: bad response (not an object)",
            ),
            ("/api/files/read", "a unreachable: bad response (not JSON)"),
            ("/api/instances", "a unreachable: bad response (not JSON)"),
        ] {
            let (v, st) = get(path).await;
            assert_eq!(st, 200, "{path}");
            assert_eq!(v["error"], want, "{path}");
            assert_eq!(v["code"], "host_unreachable", "{path}");
        }
        // JSON nesnesi olan hata yanıtı durumuyla AYNEN geçer (Python ile aynı).
        assert_eq!(
            get("/api/cli/status").await,
            (json!({"ok": false, "error": "not found"}), 404)
        );
        let (v, st) = c
            .proxy_action(
                &hosts,
                "a",
                "/api/stop",
                obj(json!({})),
                None,
                Caller::Unbound,
            )
            .await;
        assert_eq!((v, st), (json!({"ok": false, "error": "boom"}), 500));
        assert_eq!(f.count(), 6);
    })
    .await
}
