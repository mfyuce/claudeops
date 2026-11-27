//! Sahte tonic `HostBridge` ile gRPC kademesi: `Ping` yoklaması (taşıma + kimlik + servis), kademe yükseltme/düşürme,
//! durum akışının poller'ı beslemesi, term relay, akış/ kanal kapanışı, mesaj sınırı, DNS adı loopback'e çözülünce
//! red, gRPC çağrılarının imzalanmaması (bilinen eşit davranış). "Bağlantı GİTMEDİ" iddiaları sunucu sayacıyla.

mod support;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use cops_hosts::consts::{CONSECUTIVE_FAILURES_BEFORE_ERROR, GRPC_TERM_REFUSED_TTL};
use cops_hosts::grpc::pb;
use cops_hosts::net::Connector;
use cops_hosts::tier::Tier;
use cops_hosts::{Federation, HostClient, HostRecord, Secret, TermOpts};
use serde_json::{json, Value};
use support::grpc::*;
use support::ws::{default_opener, WsFake};
use support::*;

fn rest_status() -> Handler {
    handler(|_r| async {
        json(
            200,
            json!({"sessions": [{"name": "rest1", "cwd": "/w", "running": true}], "closed": [], "retired": []}),
        )
    })
}

fn fed_with(c: HostClient, src: &Arc<MemSource>) -> (Arc<Federation>, Arc<RecEvents>) {
    let ev = Arc::new(RecEvents::default());
    let mut c = c;
    c.events = ev.clone();
    (Federation::new(Arc::new(c), src.clone()), ev)
}

fn grpc_host(base: &str, grpc: &str) -> HostRecord {
    let mut h = host("a", base);
    h.grpc_url = grpc.into();
    h
}

fn deaths(ev: &RecEvents) -> Vec<Value> {
    ev.all()
        .into_iter()
        .filter(|(n, _)| n == "push_consumer_died")
        .map(|(_, v)| v)
        .collect()
}

fn grpc_tier(fed: &Federation) {
    fed.tiers.update("a", Tier::Grpc);
    assert_eq!(fed.tiers.get("a"), Tier::Grpc);
}

async fn wait_term(fed: &Federation, opts: &TermOpts, pred: impl Fn(&Value) -> bool) -> Value {
    let end = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        let v = fed.term_output("a", "s1", "en", opts);
        if pred(&v) {
            return v;
        }
        if tokio::time::Instant::now() >= end {
            panic!("term_output never matched; last = {v}");
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

#[tokio::test]
async fn grpc_probe_needs_transport_token_and_service_and_tier_moves_like_python() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let w = WsFake::start(rest_status(), default_opener(), None).await;
        let src = MemSource::new(vec![grpc_host(&w.url(), &g.url())]);
        let (fed, _) = fed_with(client(), &src);

        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Grpc);
        let c = &g.calls()[0];
        assert_eq!(c.method, "Ping");
        assert_eq!(c.auth.as_deref(), Some(format!("Bearer {TOKEN}").as_str()));
        assert_eq!(w.upgrades(), 0, "gRPC up: WS not probed");

        // Yanlış token: Ping reddedilir (Unauthenticated), WS'e düşülür; etkin kademe 5 düşük yoklamaya dek grpc.
        src.hosts.lock().unwrap()[0].token = Secret::new("WRONG");
        for _ in 1..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed.clone().probe_tiers_once().await;
            assert_eq!(fed.tiers.get("a"), Tier::Grpc);
        }
        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Ws);
        assert!(g.calls()[1..]
            .iter()
            .all(|c| c.auth.as_deref() == Some("Bearer WRONG")));
        // Doğru token: anında grpc.
        src.hosts.lock().unwrap()[0].token = Secret::new(TOKEN);
        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Grpc);

        // grpc_url boş: gRPC'ye hiç bağlanılmaz.
        let before = g.accepted();
        assert_eq!(fed.probe_tier(&host("a", &w.url())).await, Tier::Ws);
        assert_eq!(g.accepted(), before);

        // gRPC olmayan uç (TCP kabul edip susan): yoklama süresinde (1 sn) biter, kademe ws/rest.
        let raw = Raw::start(hold_until_eof).await;
        let t0 = Instant::now();
        let dead = closed_port().await;
        assert_eq!(
            fed.probe_tier(&grpc_host(&format!("http://127.0.0.1:{dead}"), &raw.url()))
                .await,
            Tier::Rest
        );
        assert!(t0.elapsed() < Duration::from_secs(3), "{:?}", t0.elapsed());
        assert_eq!(raw.accepted(), 1);
        // HTTP/1 (WS sahtesi) konuşan uç da gRPC sayılmaz.
        assert_eq!(
            fed.probe_tier(&grpc_host(&w.url(), &w.url())).await,
            Tier::Ws
        );
    })
    .await
}

#[tokio::test]
async fn grpc_status_stream_feeds_the_poller_and_a_dead_stream_falls_back_to_rest() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let w = WsFake::start(rest_status(), default_opener(), None).await;
        let src = MemSource::new(vec![grpc_host(&w.url(), &g.url())]);
        let (fed, ev) = fed_with(client(), &src);
        grpc_tier(&fed);

        fed.clone().poll_once().await;
        assert_eq!(w.count_path("/api/status"), 1, "new stream: REST this turn");
        g.wait_streams(1).await;
        // Tur bittikten sonra itilen ileti (ilk ileti REST sonucuyla yarışır, bkz. fake_ws).
        g.send_all(StreamItem::Status(status_update("g2")));
        let book = fed.book.clone();
        wait_until("grpc status recorded", Duration::from_secs(5), || {
            book.cached("a")
                .is_some_and(|c| c.sessions.first().is_some_and(|s| s["name"] == "g2"))
        })
        .await;
        let c = fed.book.cached("a").unwrap();
        assert_eq!(c.sessions[0]["host"], "a");
        assert_eq!(c.build_running.as_deref(), Some("0123456789ab"));
        assert_eq!(
            g.calls()
                .iter()
                .find(|c| c.method == "StreamStatus")
                .unwrap()
                .auth
                .as_deref(),
            Some(format!("Bearer {TOKEN}").as_str())
        );
        for _ in 0..3 {
            fed.clone().poll_once().await;
        }
        assert_eq!(w.count_path("/api/status"), 1, "live grpc stream: no REST");
        assert_eq!(g.count("StreamStatus"), 1);
        assert_eq!(w.upgrades(), 0, "grpc tier never opens WS");

        // Sunucu akışı bitirdi: ölüm kaydı (grpc), o tur REST + yeni akış.
        g.end_all();
        let d = ev.clone();
        wait_until("grpc consumer died", Duration::from_secs(5), || {
            !deaths(&d).is_empty()
        })
        .await;
        let death = &deaths(&ev)[0];
        assert_eq!(death["label"], "status:a");
        assert_eq!(death["tier"], "grpc");
        assert_eq!(death["reason"], "stream_ended");
        fed.clone().poll_once().await;
        assert_eq!(w.count_path("/api/status"), 2);
        g.wait_streams(1).await;
        assert_eq!(g.count("StreamStatus"), 2);
        assert_eq!(g.accepted(), 1, "one persistent channel per URL");
    })
    .await
}

#[tokio::test]
async fn grpc_term_relay_serves_frames_and_error_updates() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let dead = closed_port().await;
        let src = MemSource::new(vec![grpc_host(
            &format!("http://127.0.0.1:{dead}"),
            &g.url(),
        )]);
        let (fed, _) = fed_with(client(), &src);
        grpc_tier(&fed);
        let o = TermOpts::default();
        let v = wait_term(&fed, &o, |v| v["ok"] == true).await;
        assert_eq!(v["text"], "s1/en#grpc");
        assert_eq!(v["cols"], 80);
        assert!(v["rows"].is_null());
        assert!(v["mode"].is_null());
        let call = g
            .calls()
            .into_iter()
            .find(|c| c.method == "StreamTermOutput")
            .unwrap();
        assert_eq!(call.term, Some(("s1".into(), "en".into())));

        g.send_all(StreamItem::Term(pb::TermUpdate {
            ok: false,
            error: "no such session".into(),
            text: "IGNORED".into(),
            ..Default::default()
        }));
        let v = wait_term(&fed, &o, |v| {
            v["ok"] == false && v["error"] == "no such session"
        })
        .await;
        assert!(v.get("text").is_none());
    })
    .await
}

/// TBD#392: gRPC terminali `PERMISSION_DENIED` ile reddeden uzak host → relay hemen WS'ten kurulur (2 sn yeniden
/// kurma arası beklenmez); süre dolana dek yeni relay'ler doğrudan WS, sonra gRPC yeniden denenir. Durum akışı etkilenmez.
#[tokio::test]
async fn grpc_term_refusal_falls_back_to_websocket_and_retries_grpc_later() {
    // Sanal saat süre kadar ileri alınır; tavan ondan büyük olmalı.
    deadline_within(GRPC_TERM_REFUSED_TTL * 3, async {
        let g = GrpcFake::start(None).await;
        g.refuse_term(true);
        let w = WsFake::start(rest_status(), default_opener(), None).await;
        let src = MemSource::new(vec![grpc_host(&w.url(), &g.url())]);
        let (fed, _) = fed_with(client(), &src);
        grpc_tier(&fed);
        let o = TermOpts::default();

        let t0 = Instant::now();
        let v = wait_term(&fed, &o, |v| v["ok"] == true).await;
        assert!(
            t0.elapsed() < Duration::from_millis(1500),
            "{:?}",
            t0.elapsed()
        );
        assert!(!v["text"].as_str().unwrap().contains("#grpc"), "{v}");
        assert_eq!(g.count("StreamTermOutput"), 1);
        assert_eq!(w.upgrades(), 1);
        assert_eq!(fed.tiers.get("a"), Tier::Grpc, "tier is not downgraded");

        // Aynı host'ta başka oturum: gRPC hiç denenmez.
        let end = tokio::time::Instant::now() + Duration::from_secs(5);
        while fed.term_output("a", "s2", "en", &o)["ok"] != true {
            assert!(tokio::time::Instant::now() < end);
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        assert_eq!(g.count("StreamTermOutput"), 1);
        assert_eq!(w.upgrades(), 2);

        // Süre dolunca yeni relay yine gRPC.
        g.refuse_term(false);
        tokio::time::pause();
        tokio::time::advance(GRPC_TERM_REFUSED_TTL).await;
        tokio::time::resume();
        let end = tokio::time::Instant::now() + Duration::from_secs(5);
        loop {
            let v = fed.term_output("a", "s3", "en", &o);
            if v["ok"] == true {
                assert_eq!(v["text"], "s3/en#grpc");
                break;
            }
            assert!(tokio::time::Instant::now() < end, "{v}");
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
}

/// Akış ortasında red (kip açıkken değişti) de düşürür; başka bir gRPC hatası WS'e geçirmez.
#[tokio::test]
async fn grpc_term_mid_stream_refusal_falls_back_but_other_errors_do_not() {
    deadline(async {
        for (status, falls_back) in [
            (tonic::Status::permission_denied("signature_required"), true),
            (tonic::Status::unavailable("PermissionDenied"), false),
        ] {
            let g = GrpcFake::start(None).await;
            let w = WsFake::start(rest_status(), default_opener(), None).await;
            let src = MemSource::new(vec![grpc_host(&w.url(), &g.url())]);
            let (fed, _) = fed_with(client(), &src);
            grpc_tier(&fed);
            let o = TermOpts::default();
            wait_term(&fed, &o, |v| v["text"] == "s1/en#grpc").await;
            g.fail_streams(status);
            // Yeniden kurma arası (2 sn) geçsin: iki yolda da yeni bir akış kurulur.
            tokio::time::sleep(Duration::from_millis(2200)).await;
            let v = wait_term(&fed, &o, |v| v["ok"] == true).await;
            assert_eq!(
                !v["text"].as_str().unwrap().contains("#grpc"),
                falls_back,
                "{v}"
            );
            assert_eq!(w.upgrades() > 0, falls_back);
        }
    })
    .await
}

/// Red, reddeden relay'in adresine yazılır: kayıt o arada düzenlendiyse yeni adres gRPC'den denenir.
#[tokio::test]
async fn grpc_term_refusal_is_remembered_for_the_refusing_address_only() {
    deadline(async {
        let old = GrpcFake::start(None).await;
        old.refuse_term(true);
        let new = GrpcFake::start(None).await;
        let w = WsFake::start(rest_status(), default_opener(), None).await;
        let src = MemSource::new(vec![grpc_host(&w.url(), &old.url())]);
        let (fed, ev) = fed_with(client(), &src);
        grpc_tier(&fed);
        let o = TermOpts::default();
        fed.term_output("a", "s1", "en", &o);
        wait_until("refused stream ends", Duration::from_secs(5), || {
            !deaths(&ev).is_empty()
        })
        .await;
        src.hosts.lock().unwrap()[0].grpc_url = new.url();
        let v = wait_term(&fed, &o, |v| v["ok"] == true).await;
        assert_eq!(v["text"], "s1/en#grpc", "{v}");
        assert_eq!(new.count("StreamTermOutput"), 1);
        assert_eq!(w.upgrades(), 0);
    })
    .await
}

/// Kademe gRPC iken kayıttan `grpc_url` kaldırılırsa relay ve durum akışı beklemeden WS'ten kurulur.
#[tokio::test]
async fn removed_grpc_url_moves_streams_to_websocket_at_once() {
    deadline(async {
        let w = WsFake::start(rest_status(), default_opener(), None).await;
        let src = MemSource::new(vec![host("a", &w.url())]);
        let (fed, ev) = fed_with(client(), &src);
        grpc_tier(&fed);
        let o = TermOpts::default();
        let v = wait_term(&fed, &o, |v| v["ok"] == true).await;
        assert!(!v["text"].as_str().unwrap().contains("#grpc"), "{v}");
        assert_eq!(fed.tiers.get("a"), Tier::Ws);

        grpc_tier(&fed);
        fed.ensure_status_consumer(&host("a", &w.url()));
        wait_until("status websocket", Duration::from_secs(5), || {
            w.count_path("/ws") == 1
        })
        .await;
        assert_eq!(fed.tiers.get("a"), Tier::Ws);
        assert!(deaths(&ev).is_empty());
    })
    .await
}

#[tokio::test]
async fn grpc_message_limit_is_4_mib() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let dead = closed_port().await;
        let src = MemSource::new(vec![grpc_host(
            &format!("http://127.0.0.1:{dead}"),
            &g.url(),
        )]);
        let (fed, ev) = fed_with(client(), &src);
        grpc_tier(&fed);
        let o = TermOpts::default();
        wait_term(&fed, &o, |v| v["ok"] == true).await;
        let limit = 4 * 1024 * 1024;
        // Alan 3 (text): 1 bayt etiket + 3 bayt uzunluk + metin; ok=true 2 bayt. Tam sınıra dek kabul.
        let fits = limit - 2 - 1 - 4;
        let msg = pb::TermUpdate {
            ok: true,
            text: "y".repeat(fits),
            ..Default::default()
        };
        assert_eq!(prost::Message::encoded_len(&msg), limit);
        g.send_all(StreamItem::Term(msg));
        wait_term(&fed, &o, |v| {
            v["text"].as_str().is_some_and(|t| t.len() == fits)
        })
        .await;
        g.send_all(StreamItem::Term(pb::TermUpdate {
            ok: true,
            text: "y".repeat(fits + 1),
            ..Default::default()
        }));
        let d = ev.clone();
        wait_until(
            "oversized grpc message kills the stream",
            Duration::from_secs(10),
            || !deaths(&d).is_empty(),
        )
        .await;
        let r = deaths(&ev)[0]["reason"].as_str().unwrap().to_string();
        assert!(
            r.contains("message length too large") || r.contains("OutOfRange"),
            "{r}"
        );
        let v = fed.term_output("a", "s1", "en", &o);
        assert_eq!(v["code"], "relay_connecting", "frozen frame not served");
    })
    .await
}

#[tokio::test]
async fn dropped_grpc_consumers_cancel_streams_and_removed_hosts_close_the_channel() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let src = MemSource::new(vec![grpc_host(&base, &g.url())]);
        {
            let (fed, _) = fed_with(client(), &src);
            grpc_tier(&fed);
            fed.ensure_status_consumer(&grpc_host(&base, &g.url()));
            wait_term(&fed, &TermOpts::default(), |v| v["ok"] == true).await;
            g.wait_streams(2).await;
            assert_eq!(g.live(), 1, "both streams on one HTTP/2 connection");
        }
        // Federation düştü: akışlar iptal, kanalın son kopyası düştü -> TCP kapanır.
        g.wait_streams(0).await;
        g.wait_live(0).await;

        // Host kayıttan silinince tur akışı iptal eder ve kanalı bırakır.
        let (fed, _) = fed_with(client(), &src);
        grpc_tier(&fed);
        fed.ensure_status_consumer(&grpc_host(&base, &g.url()));
        g.wait_streams(1).await;
        g.wait_live(1).await;
        src.hosts.lock().unwrap().clear();
        fed.clone().poll_once().await;
        g.wait_streams(0).await;
        g.wait_live(0).await;
        assert_eq!(g.accepted(), 2);
    })
    .await
}

/// Python `GrpcGuardTest.test_unresolvable_is_fail_closed`: çözülemeyen gRPC adı = bağlantı yok, kademe yükselmez.
#[tokio::test]
async fn grpc_unresolvable_name_is_fail_closed() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let failing: cops_hosts::net::Resolver =
            Arc::new(|_h, _p| Box::pin(async { Err(std::io::Error::other("no such host")) }));
        let mut c = HostClient::new(Connector {
            resolver: failing,
            ..Default::default()
        });
        c.timeouts = timeouts();
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let dns = format!("http://fake-remote.test:{}", g.addr.port());
        let src = MemSource::new(vec![grpc_host(&base, &dns)]);
        let (fed, _ev) = fed_with(c, &src);
        assert_eq!(fed.probe_tier(&grpc_host(&base, &dns)).await, Tier::Rest);
        assert_eq!(g.accepted(), 0);
    })
    .await
}

#[tokio::test]
async fn grpc_dns_name_resolving_to_loopback_is_refused_before_connecting() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let calls = Arc::new(AtomicUsize::new(0));
        let conn = Connector {
            resolver: counting_resolver(g.addr, calls.clone()),
            ..Default::default()
        };
        let mut c = HostClient::new(conn);
        c.timeouts = timeouts();
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let dns = format!("http://fake-remote.test:{}", g.addr.port());
        let src = MemSource::new(vec![grpc_host(&base, &dns)]);
        let (fed, ev) = fed_with(c, &src);

        assert_eq!(fed.probe_tier(&grpc_host(&base, &dns)).await, Tier::Rest);
        grpc_tier(&fed);
        fed.ensure_status_consumer(&grpc_host(&base, &dns));
        fed.term_output("a", "s1", "en", &TermOpts::default());
        let d = ev.clone();
        wait_until("streams refused", Duration::from_secs(10), || {
            deaths(&d).len() >= 2
        })
        .await;
        assert!(calls.load(Ordering::SeqCst) >= 1, "resolver consulted");
        assert_eq!(g.accepted(), 0, "no TCP connection to the loopback target");
        // Kontrol: IP literali çalışır.
        assert_eq!(
            fed.probe_tier(&grpc_host(&base, &g.url())).await,
            Tier::Grpc
        );
        assert_eq!(g.accepted(), 1);
    })
    .await
}

#[tokio::test]
async fn grpc_calls_are_not_signed_known_parity_with_python() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let src = MemSource::new(vec![grpc_host(&base, &g.url())]);
        let signer = TestSigner::new(SignMode::Refuse);
        let mut c = client();
        c.signer = Some(signer.clone());
        let (fed, _) = fed_with(c, &src);
        // Signer reddetse bile gRPC yolu imza sormaz (Python `web_grpc` de imzalamıyor; docs/rs-hosts.md).
        assert_eq!(
            fed.probe_tier(&grpc_host(&base, &g.url())).await,
            Tier::Grpc
        );
        grpc_tier(&fed);
        wait_term(&fed, &TermOpts::default(), |v| v["ok"] == true).await;
        assert_eq!(signer.calls(), 0);
    })
    .await
}
