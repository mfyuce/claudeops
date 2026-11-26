//! fd sızıntısı (ders H1, "100 zaman aşımı sonrası /proc/self/fd sayısı artmaz"). Ayrı test ikilisi: aynı süreçte
//! koşan başka testlerin soketleri sayımı bozmasın.

mod support;

use std::time::Duration;

use cops_hosts::endpoint::Endpoint;
use cops_hosts::{Caller, GetOpts};
use serde_json::json;
use support::*;

#[tokio::test]
async fn hundred_timeouts_do_not_leak_sockets() {
    deadline(async {
        let raw = Raw::start(hold_until_eof).await;
        let c = client();
        let hosts = vec![host("a", &raw.url())];
        let opts = GetOpts {
            dedup: false,
            timeout: Some(Duration::from_millis(20)),
        };
        let get = || c.proxy_get(&hosts, "a", "/api/term/output", &[], opts, Caller::Unbound);
        let post = || {
            c.proxy_action(
                &hosts,
                "a",
                "/api/start",
                json!({}).as_object().unwrap().clone(),
                Some(Duration::from_millis(20)),
                Caller::Unbound,
            )
        };
        // Isınma: çalışma zamanının tembel fd'leri ölçüme girmesin.
        let _ = get().await;
        raw.wait_no_live().await;
        let before = fd_count();
        for _ in 0..100 {
            let (v, _) = get().await;
            assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
            let (v, _) = post().await;
            assert!(v["error"].as_str().unwrap().contains("timed out"), "{v}");
        }
        assert_eq!(
            raw.accepted(),
            201,
            "each timed-out attempt used its own connection"
        );
        // Sunucu tarafı EOF okudu = istemci her soketi kapattı (sunucu hiç yanıt vermedi).
        raw.wait_no_live().await;
        wait_until("fd count back to baseline", Duration::from_secs(5), || {
            fd_count() <= before
        })
        .await;
        let key = Endpoint::parse(&raw.url()).unwrap().pool_key();
        assert_eq!(c.pool.idle_count(&key), 0);
    })
    .await
}
