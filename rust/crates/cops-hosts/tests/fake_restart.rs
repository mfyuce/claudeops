//! Poller'ın takılma ([`POLLER_STALL`]) ve panik sonrası kendini yeniden başlatması (Python poller watchdog'u karşılığı).
//! Sanal saat (`start_paused`): ağ adımı zaman aşımı takılma eşiğinden uzun tutulur, böylece saat kendiliğinden ilerlese
//! bile sıra belirlenimci (önce takılma eşiği dolar). Mutlak tavan da sanal saatle: gerçek G/Ç asılı kalırsa saat
//! ilerler ve test DÜŞER (asılı kalmaz).

mod support;

use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use cops_hosts::consts::{CAPABILITY_PROBE_INTERVAL, POLLER_STALL, POLL_INTERVAL};
use cops_hosts::{Federation, HostClient};
use serde_json::json;
use support::*;

async fn virtual_deadline<F: std::future::Future>(f: F) -> F::Output {
    tokio::time::timeout(Duration::from_secs(3600), f)
        .await
        .expect("virtual deadline exceeded")
}

fn fed_events(src: &Arc<MemSource>, status_timeout: Duration) -> (Arc<Federation>, Arc<RecEvents>) {
    let ev = Arc::new(RecEvents::default());
    let mut c = HostClient::new(cops_hosts::net::Connector::default());
    c.timeouts = timeouts();
    c.timeouts.status = status_timeout;
    c.timeouts.total_cap = Duration::from_secs(600);
    c.events = ev.clone();
    (Federation::new(Arc::new(c), src.clone()), ev)
}

fn restarted(ev: &RecEvents) -> Vec<bool> {
    ev.all()
        .into_iter()
        .filter(|(n, _)| n == "host_poller_restarted")
        .map(|(_, v)| v["stalled"].as_bool().unwrap())
        .collect()
}

#[tokio::test(start_paused = true)]
async fn stalled_turn_is_cancelled_and_the_poller_restarts_then_recovers() {
    virtual_deadline(async {
        let raw = Raw::start(hold_until_eof).await;
        let good = Fake::start(handler(|_r| async {
            json(200, json!({"sessions": [], "closed": [], "retired": []}))
        }))
        .await;
        let src = MemSource::new(vec![host("a", &raw.url())]);
        // Adım sınırı (200 sn) takılma eşiğinden (90 sn) uzun: tur ancak watchdog'la biter.
        let (fed, ev) = fed_events(&src, Duration::from_secs(200));
        assert!(Duration::from_secs(200) > POLLER_STALL);
        let run = fed.start();

        let t0 = tokio::time::Instant::now();
        wait_until("first stall restart", Duration::from_secs(600), || {
            !restarted(&ev).is_empty()
        })
        .await;
        let waited = t0.elapsed();
        assert!(
            waited >= POLLER_STALL && waited < POLLER_STALL + Duration::from_secs(5),
            "{waited:?}"
        );
        assert_eq!(restarted(&ev), [true]);
        let h = fed.poller_health(&run);
        assert!(h.alive);
        assert_eq!(h.restarts, 1);
        assert!(
            h.age.unwrap() >= POLLER_STALL,
            "beat not refreshed by a stalled turn"
        );

        // Takılan turlar birikmez: iptal edilen turun soketi kapanır.
        wait_until("three stall restarts", Duration::from_secs(600), || {
            restarted(&ev).len() >= 3
        })
        .await;
        assert!(raw.accepted() >= 3);
        assert!(
            raw.live() <= 1,
            "stalled turns leaked sockets: {}",
            raw.live()
        );

        // Host düzelince tur tamamlanır, kalp atışı tazelenir, sayaç artmaz.
        src.hosts.lock().unwrap()[0].base_url = good.url();
        let book = fed.book.clone();
        wait_until("recovered turn", Duration::from_secs(600), || {
            book.cached("a").is_some_and(|c| c.ok)
        })
        .await;
        let n = restarted(&ev).len();
        tokio::time::sleep(POLL_INTERVAL * 4).await;
        let h = fed.poller_health(&run);
        assert!(
            h.age.unwrap() <= POLL_INTERVAL + Duration::from_secs(1),
            "{h:?}"
        );
        assert_eq!(restarted(&ev).len(), n);
        assert_eq!(h.restarts as usize, n);

        drop(run);
        raw.wait_no_live().await;
    })
    .await
}

#[tokio::test(start_paused = true)]
async fn panicking_turn_is_counted_and_the_poller_keeps_running() {
    virtual_deadline(async {
        let good = Fake::start(handler(|_r| async {
            json(200, json!({"sessions": [], "closed": [], "retired": []}))
        }))
        .await;
        let src = MemSource::new(vec![host("a", &good.url())]);
        let (fed, ev) = fed_events(&src, Duration::from_secs(3));
        let run = fed.start();
        tokio::time::sleep(POLL_INTERVAL * 3).await;
        assert_eq!(
            fed.poller_health(&run).restarts,
            0,
            "healthy turns never restart"
        );

        src.panic_load.store(true, Ordering::SeqCst);
        wait_until("panic restart", Duration::from_secs(60), || {
            restarted(&ev).len() >= 2
        })
        .await;
        assert!(restarted(&ev).iter().all(|s| !s), "panic, not stall");
        let h = fed.poller_health(&run);
        assert!(h.alive, "poller task survives a panicking turn");

        src.panic_load.store(false, Ordering::SeqCst);
        let before = count_path(&good, "/api/status");
        wait_until("turns resume", Duration::from_secs(60), || {
            count_path(&good, "/api/status") > before + 1
        })
        .await;
        let n = restarted(&ev).len();
        tokio::time::sleep(POLL_INTERVAL * 3).await;
        assert_eq!(restarted(&ev).len(), n);
        assert!(fed.poller_health(&run).age.unwrap() <= POLL_INTERVAL + Duration::from_secs(1));
    })
    .await
}

/// Takılan kademe yoklaması aralık dolunca iptal edilir, olay yazılır, sonraki tur yeniden dener (soket birikmez);
/// host düzelince kademe yükselir. Takılma, yoklama zaman aşımı aralıktan uzun tutularak üretilir.
#[tokio::test(start_paused = true)]
async fn stalled_probe_turn_is_cancelled_and_the_prober_keeps_probing() {
    virtual_deadline(async {
        let raw = Raw::start(hold_until_eof).await;
        let src = MemSource::new(vec![host("a", &raw.url())]);
        let ev = Arc::new(RecEvents::default());
        let mut c = HostClient::new(cops_hosts::net::Connector::default());
        c.timeouts = timeouts();
        c.timeouts.ws_probe = Duration::from_secs(600);
        c.timeouts.total_cap = Duration::from_secs(900);
        c.events = ev.clone();
        assert!(c.timeouts.ws_probe > CAPABILITY_PROBE_INTERVAL);
        let fed = Federation::new(Arc::new(c), src.clone());
        let t0 = tokio::time::Instant::now();
        let run = fed.start();
        let stalls = |ev: &RecEvents| {
            ev.names()
                .iter()
                .filter(|n| *n == "host_prober_restarted")
                .count()
        };

        wait_until("first prober restart", Duration::from_secs(600), || {
            stalls(&ev) >= 1
        })
        .await;
        let waited = t0.elapsed();
        assert!(
            waited >= CAPABILITY_PROBE_INTERVAL
                && waited < CAPABILITY_PROBE_INTERVAL + Duration::from_secs(5),
            "{waited:?}"
        );
        wait_until("three prober restarts", Duration::from_secs(900), || {
            stalls(&ev) >= 3
        })
        .await;

        drop(run);
        raw.wait_no_live().await;
    })
    .await
}
