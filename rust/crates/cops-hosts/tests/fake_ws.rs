//! Sahte `/ws` ve `/ws/term` (aynı portta REST) ile WS kademesi: prober'ın kademe yükseltme/düşürmesi, push tüketicili
//! poller dalı, sessizlik watchdog'u, ölü/sessiz relay'in yeniden kurulması, kayıt değişince yenileme, boşta relay
//! biçme, büyük mesaj sınırı, taban yolu, görev bırakılınca soket kapanışı (fd), DNS adı loopback'e çözülünce red,
//! el sıkışma imzası, Ping/Pong ve kapanış el sıkışması (H18). "Bağlantı GİTMEDİ" iddiaları sunucu sayacıyla.

mod support;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use cops_hosts::consts::CONSECUTIVE_FAILURES_BEFORE_ERROR;
use cops_hosts::net::Connector;
use cops_hosts::tier::Tier;
use cops_hosts::{Federation, HostClient, Secret, TermOpts};
use serde_json::{json, Value};
use support::ws::*;
use support::*;
use tokio_tungstenite::tungstenite::Message;

const MIB16: usize = 16 * 1024 * 1024;

fn rest_status() -> Handler {
    handler(|_r| async {
        json(
            200,
            json!({"sessions": [{"name": "rest1", "cwd": "/w", "running": true}], "closed": [], "retired": []}),
        )
    })
}

async fn fake(opener: Opener) -> WsFake {
    WsFake::start(rest_status(), opener, None).await
}

fn fed_with(c: HostClient, src: &Arc<MemSource>) -> (Arc<Federation>, Arc<RecEvents>) {
    let ev = Arc::new(RecEvents::default());
    let mut c = c;
    c.events = ev.clone();
    (Federation::new(Arc::new(c), src.clone()), ev)
}

fn fed(src: &Arc<MemSource>) -> (Arc<Federation>, Arc<RecEvents>) {
    fed_with(client(), src)
}

fn ws_tier(fed: &Federation, name: &str) {
    fed.tiers.update(name, Tier::Ws);
    assert_eq!(fed.tiers.get(name), Tier::Ws);
}

fn term(fed: &Federation, name: &str, opts: &TermOpts) -> Value {
    fed.term_output("a", name, "en", opts)
}

fn text_of(v: &Value) -> Option<String> {
    v.get("text").and_then(Value::as_str).map(str::to_string)
}

/// `term_output` belirtilen metni verene dek okur (her okuma relay'i canlı tutar).
async fn wait_text(fed: &Federation, name: &str, opts: &TermOpts, want: &str) {
    let last = Mutex::new(Value::Null);
    let cond = || {
        let v = term(fed, name, opts);
        let hit = text_of(&v).as_deref() == Some(want);
        *last.lock().unwrap() = v;
        hit
    };
    let end = tokio::time::Instant::now() + Duration::from_secs(5);
    while !cond() {
        if tokio::time::Instant::now() >= end {
            panic!(
                "term_output never returned {want:?}; last = {}",
                last.lock().unwrap()
            );
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

fn is_connecting(v: &Value) -> bool {
    v["ok"] == false && v["code"] == "relay_connecting"
}

fn event_count(ev: &RecEvents, name: &str) -> usize {
    ev.names().iter().filter(|n| *n == name).count()
}

fn deaths(ev: &RecEvents) -> Vec<Value> {
    ev.all()
        .into_iter()
        .filter(|(n, _)| n == "push_consumer_died")
        .map(|(_, v)| v)
        .collect()
}

// ---------------------------------------------------------------- prober / kademe

#[tokio::test]
async fn ws_probe_raises_tier_at_once_and_lowers_it_only_after_tolerance() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, _) = fed(&src);

        // grpc_url boş: gRPC hiç denenmez; WS 101'e ulaşınca yeter, prob bağlantısı kapanış el sıkışmasıyla kapanır.
        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Ws);
        assert_eq!(f.upgrades(), 1);
        let r = &f.recs()[0];
        assert_eq!(r.path, "/ws");
        assert_eq!(query_value(&r.query, "token").as_deref(), Some(TOKEN));
        assert_eq!(query_value(&r.query, "name"), None);
        f.wait_ws_live(0).await;
        assert_eq!(f.client_closes(), 1, "probe closes with a close frame");

        // Yükseltme reddi (401): prob `Rest` der ama etkin kademe 4 düşük yoklama boyunca KORUNUR, 5.de düşer.
        f.refuse_upgrades(401);
        for i in 1..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            assert_eq!(fed.probe_tier(&host("a", &f.url())).await, Tier::Rest);
            fed.clone().probe_tiers_once().await;
            assert_eq!(fed.tiers.get("a"), Tier::Ws, "after {i} low probe(s)");
        }
        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Rest);
        assert_eq!(f.upgrades(), 1, "refused handshakes are not upgrades");

        // Yükselme ANINDA.
        f.refuse_upgrades(0);
        fed.clone().probe_tiers_once().await;
        assert_eq!(fed.tiers.get("a"), Tier::Ws);

        // 101 dışı her yanıt (200 dahil) WS sayılmaz.
        f.refuse_upgrades(200);
        assert_eq!(fed.probe_tier(&host("a", &f.url())).await, Tier::Rest);
        // Kapalı port.
        let dead = closed_port().await;
        assert_eq!(
            fed.probe_tier(&host("a", &format!("http://127.0.0.1:{dead}")))
                .await,
            Tier::Rest
        );
    })
    .await
}

// ---------------------------------------------------------------- poller push dalı

#[tokio::test]
async fn poller_skips_rest_only_while_a_live_push_stream_has_delivered_data() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);

        // Kademe rest: tüketici kurulmaz, her tur REST.
        fed.clone().poll_once().await;
        assert_eq!(f.count_path("/api/status"), 1);
        assert_eq!(f.upgrades(), 0);

        ws_tier(&fed, "a");
        // Yeni kurulan akışın turu yine REST'le yoklanır.
        fed.clone().poll_once().await;
        assert_eq!(f.count_path("/api/status"), 2);
        f.wait_upgrades(1).await;
        let book = fed.book.clone();
        f.wait_ws_live(1).await;
        f.send_last(Cmd::Send(status_frame("p1")));
        wait_until("ws status frame recorded", Duration::from_secs(5), || {
            book.cached("a")
                .is_some_and(|c| c.sessions.first().is_some_and(|s| s["name"] == "p1"))
        })
        .await;
        let c = fed.book.cached("a").unwrap();
        assert!(c.ok);
        assert_eq!(
            c.sessions[0]["host"], "a",
            "push rows are tagged like REST rows"
        );
        assert_eq!(c.build_running.as_deref(), Some("feedfacecafe"));
        let ws_req = f.recs().into_iter().find(|r| r.path == "/ws").unwrap();
        assert_eq!(query_value(&ws_req.query, "token").as_deref(), Some(TOKEN));

        // Veri getiren canlı akış: REST'e gidilmez, yeni bağlantı açılmaz.
        for _ in 0..3 {
            fed.clone().poll_once().await;
        }
        assert_eq!(f.count_path("/api/status"), 2);
        assert_eq!(f.upgrades(), 1);

        // Sonraki kareler önbelleğe yazılır.
        f.send_last(Cmd::Send(status_frame("pushed")));
        wait_until("pushed frame", Duration::from_secs(5), || {
            book.cached("a")
                .is_some_and(|c| c.sessions.first().is_some_and(|s| s["name"] == "pushed"))
        })
        .await;

        // Akış koptu: o tur REST + yeni akış; ölüm olayı token'sız.
        f.send_last(Cmd::Drop);
        f.wait_ws_live(0).await;
        wait_until("consumer death logged", Duration::from_secs(5), || {
            !deaths(&ev).is_empty()
        })
        .await;
        fed.clone().poll_once().await;
        assert_eq!(f.count_path("/api/status"), 3);
        f.wait_upgrades(2).await;
        let d = &deaths(&ev)[0];
        assert_eq!(d["label"], "status:a");
        assert_eq!(d["tier"], "ws");
        assert_clean(&d.to_string(), f.addr.port());

        // Kademe rest'e düşünce tüketici bırakılır: soket kapanır, REST'e dönülür.
        f.wait_ws_live(1).await;
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            fed.tiers.update("a", Tier::Rest);
        }
        fed.clone().poll_once().await;
        f.wait_ws_live(0).await;
        assert_eq!(f.count_path("/api/status"), 4);
        assert_eq!(f.upgrades(), 2);
    })
    .await
}

/// H3: REST yanıtı sürerken gelen push karesi, aynı turun (daha eski) REST sonucuyla ezilmez (poller turu ve "şimdi test et").
#[tokio::test]
async fn push_frame_that_arrives_during_rest_is_not_overwritten() {
    deadline(async {
        let rest = handler(|_r| async {
            tokio::time::sleep(Duration::from_millis(600)).await;
            json(
                200,
                json!({"sessions": [{"name": "rest1", "cwd": "/w", "running": true}]}),
            )
        });
        let f = WsFake::start(rest, default_opener(), None).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, _) = fed(&src);
        ws_tier(&fed, "a");
        let first = |name: &str| {
            fed.book.cached(name).and_then(|c| {
                c.sessions
                    .first()
                    .map(|s| s["name"].as_str().unwrap_or_default().to_string())
            })
        };

        // Akış bu turda kurulur; ilk karesi yavaş REST yanıtından önce işlenir.
        fed.clone().poll_once().await;
        assert_eq!(f.count_path("/api/status"), 1);
        assert_eq!(first("a").as_deref(), Some("s1"));

        // "Şimdi test et": dönüş kendi REST sonucu, önbellek daha yeni karede kalır.
        let (own, ()) = tokio::join!(fed.test_now("a"), async {
            wait_until("rest in flight", Duration::from_secs(5), || {
                f.count_path("/api/status") == 2
            })
            .await;
            f.send_last(Cmd::Send(status_frame("p2")));
        });
        assert_eq!(own.unwrap().0.sessions[0]["name"], "rest1");
        assert_eq!(first("a").as_deref(), Some("p2"));
    })
    .await
}

#[tokio::test]
async fn junk_frames_keep_the_stream_alive_but_rest_polling_continues() {
    deadline(async {
        // Dizi, JSON olmayan, başka tür, `data` nesne değil, ikili bozuk: hiçbiri veri sayılmaz, akışı da öldürmez.
        let opener: Opener = Arc::new(|_: &Rec, _| {
            vec![
                Message::text("[1,2]"),
                Message::text("not json"),
                Message::text(r#"{"type":"term","data":{"ok":true}}"#),
                Message::text(r#"{"type":"status","data":[1]}"#),
                Message::text(r#"{"type":"status"}"#),
                // Dizi olmayan `sessions`: boş oturum listesi gibi kaydedilmez.
                Message::text(r#"{"type":"status","data":{}}"#),
                Message::text(r#"{"type":"status","data":{"sessions":5}}"#),
                Message::text(r#"{"type":"status","data":{"sessions":null}}"#),
                Message::binary(vec![0xff, 0x00]),
            ]
        });
        let f = fake(opener).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        for i in 1..=3 {
            fed.clone().poll_once().await;
            assert_eq!(
                f.count_path("/api/status"),
                i,
                "REST every turn while no data"
            );
            f.wait_upgrades(1).await;
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        assert_eq!(f.upgrades(), 1, "stream kept (alive, not silent)");
        assert_eq!(f.ws_live(), 1);
        assert!(deaths(&ev).is_empty(), "{:?}", ev.all());
        // Üç okunamayan/nesne olmayan kare (dizi, JSON değil, bozuk ikili) dakikada TEK `push_frame_skipped` (Python
        // `_ws_envelope`); geçerli ama ilgisiz nesneler loglanmaz.
        let skipped: Vec<Value> = ev
            .all()
            .into_iter()
            .filter(|(n, _)| n == "push_frame_skipped")
            .map(|(_, v)| v)
            .collect();
        assert_eq!(skipped, vec![json!({"kind": "status"})]);
        // REST sonucu yazılı (kareler önbelleğe hiçbir şey yazmadı).
        assert_eq!(fed.book.cached("a").unwrap().sessions[0]["name"], "rest1");

        // İkili çerçeve de JSON'sa veri sayılır (Python `json.loads(bytes)` ile aynı).
        f.send_last(Cmd::Send(Message::binary(
            serde_json::to_vec(
                &json!({"type":"status","data":{"sessions":[{"name":"bin","cwd":"/w"}]}}),
            )
            .unwrap(),
        )));
        let book = fed.book.clone();
        wait_until("binary status frame", Duration::from_secs(5), || {
            book.cached("a")
                .is_some_and(|c| c.sessions.first().is_some_and(|s| s["name"] == "bin"))
        })
        .await;
        fed.clone().poll_once().await;
        assert_eq!(f.count_path("/api/status"), 3, "data arrived: no more REST");
    })
    .await
}

#[tokio::test]
async fn status_silence_watchdog_boundary() {
    let f = deadline(fake(default_opener())).await;
    let h = host("a", &f.url());
    let src = MemSource::new(vec![h.clone()]);
    let (fed, ev) = fed(&src);
    ws_tier(&fed, "a");
    deadline(async {
        assert!(!fed.ensure_status_consumer(&h));
        let book = fed.book.clone();
        wait_until("first frame", Duration::from_secs(5), || {
            book.cached("a").is_some()
        })
        .await;
        assert!(fed.ensure_status_consumer(&h));
    })
    .await;

    tokio::time::pause();
    tokio::time::advance(Duration::from_secs(44)).await;
    assert!(fed.ensure_status_consumer(&h), "44 s silent: still trusted");
    assert_eq!(event_count(&ev, "status_consumer_silent"), 0);
    tokio::time::advance(Duration::from_secs(2)).await;
    assert!(
        !fed.ensure_status_consumer(&h),
        "46 s silent: replaced, this turn goes to REST"
    );
    tokio::time::resume();

    deadline(async {
        assert_eq!(event_count(&ev, "status_consumer_silent"), 1);
        let e = &ev
            .all()
            .into_iter()
            .find(|(n, _)| n == "status_consumer_silent")
            .unwrap()
            .1;
        assert_eq!(e["name"], "a");
        assert!(e["silent"].as_u64().unwrap() >= 45);
        f.wait_upgrades(2).await;
        // Eski (yarı açık) soket kapandı, yalnız yenisi açık.
        f.wait_ws_live(1).await;
        let book = fed.book.clone();
        wait_until("new stream frame", Duration::from_secs(5), || {
            book.cached("a")
                .is_some_and(|c| c.sessions.first().is_some_and(|s| s["name"] == "s1"))
        })
        .await;
        assert!(fed.ensure_status_consumer(&h));
        // Kasıtlı değiştirme ölüm kaydı DEĞİL.
        assert!(deaths(&ev).is_empty(), "{:?}", ev.all());
    })
    .await;
}

#[tokio::test]
async fn status_stream_is_rebuilt_when_address_or_token_changes_not_extra_urls() {
    deadline(async {
        let f = fake(default_opener()).await;
        let f2 = fake(default_opener()).await;
        let h = host("a", &f.url());
        let src = MemSource::new(vec![h.clone()]);
        let (fed, _) = fed(&src);
        ws_tier(&fed, "a");
        fed.ensure_status_consumer(&h);
        let book = fed.book.clone();
        wait_until("data", Duration::from_secs(5), || {
            book.cached("a").is_some()
        })
        .await;
        assert!(fed.ensure_status_consumer(&h));

        // Yalnız `extra_urls` değişti: akış aynen (Python R-18 anahtarı: base_url, grpc_url, token).
        let mut h2 = h.clone();
        h2.extra_urls = vec!["http://127.0.0.1:9".into()];
        assert!(fed.ensure_status_consumer(&h2));
        assert_eq!(f.upgrades(), 1);

        // Token değişti: yeniden kurulur, eski soket kapanır, yeni token kullanılır.
        let mut h3 = h2.clone();
        h3.token = Secret::new("NEW-tok");
        assert!(!fed.ensure_status_consumer(&h3));
        f.wait_upgrades(2).await;
        f.wait_ws_live(1).await;
        let last = f
            .recs()
            .into_iter()
            .filter(|r| r.path == "/ws")
            .last()
            .unwrap();
        assert_eq!(
            query_value(&last.query, "token").as_deref(),
            Some("NEW-tok")
        );

        // Adres değişti: yeni sunucuya.
        let mut h4 = h3.clone();
        h4.base_url = f2.url();
        assert!(!fed.ensure_status_consumer(&h4));
        f2.wait_upgrades(1).await;
        f.wait_ws_live(0).await;

        // grpc_url değişti (kademe ws iken bile anahtarın parçası).
        let mut h5 = h4.clone();
        h5.grpc_url = "http://127.0.0.1:1".into();
        assert!(!fed.ensure_status_consumer(&h5));
        f2.wait_upgrades(2).await;
        f2.wait_ws_live(1).await;
    })
    .await
}

// ---------------------------------------------------------------- term relay

#[tokio::test]
async fn term_relay_streams_frames_and_keeps_one_stream_per_option_set() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        let plain = TermOpts::default();

        let first = term(&fed, "s1", &plain);
        assert!(is_connecting(&first), "{first}");
        assert_eq!(first["error"], "relay: henüz veri gelmedi");
        wait_text(&fed, "s1", &plain, "s1#0").await;
        let r = f.recs().into_iter().find(|r| r.path == "/ws/term").unwrap();
        assert_eq!(query_value(&r.query, "name").as_deref(), Some("s1"));
        assert_eq!(query_value(&r.query, "lang").as_deref(), Some("en"));
        assert_eq!(query_value(&r.query, "token").as_deref(), Some(TOKEN));
        for k in ["lite", "interval", "viewport"] {
            assert_eq!(query_value(&r.query, k), None, "{k}");
        }

        // Aynı seçenek: aynı akış.
        for _ in 0..5 {
            term(&fed, "s1", &plain);
        }
        assert_eq!(f.upgrades(), 1);
        assert_eq!(fed.open_relays(), 1);

        // Sonraki kare.
        f.send_last(Cmd::Send(term_frame("next")));
        wait_text(&fed, "s1", &plain, "next").await;

        // Bozuk/ilgisiz kareler son kareyi ezmez.
        for m in [
            Message::text(r#"{"type":"status","data":{"text":"x"}}"#),
            Message::text(r#"{"type":"term","data":"x"}"#),
            Message::text("[]"),
        ] {
            f.send_last(Cmd::Send(m));
        }
        f.send_last(Cmd::Send(term_frame("after-junk")));
        wait_text(&fed, "s1", &plain, "after-junk").await;
        // Yalnız nesne olmayan `[]` atlama olayı üretir (Python `_ws_envelope`), tür `term`; ilgisiz nesneler loglanmaz.
        let skipped: Vec<Value> = ev
            .all()
            .into_iter()
            .filter(|(n, _)| n == "push_frame_skipped")
            .map(|(_, v)| v)
            .collect();
        assert_eq!(skipped, vec![json!({"kind": "term"})]);

        // lite / interval / viewport: ayrı akış, sorguda taşınır.
        let lite = TermOpts {
            lite: true,
            interval: Some(0.5),
            viewport: true,
        };
        wait_text(&fed, "s1", &lite, "s1#1").await;
        let r = f
            .recs()
            .into_iter()
            .filter(|r| r.path == "/ws/term")
            .last()
            .unwrap();
        assert_eq!(query_value(&r.query, "lite").as_deref(), Some("1"));
        assert_eq!(query_value(&r.query, "interval").as_deref(), Some("0.5"));
        assert_eq!(query_value(&r.query, "viewport").as_deref(), Some("1"));
        assert_eq!(fed.open_relays(), 2);
        // Geçersiz aralık (0, negatif, NaN) yok sayılır: seçeneksiz akışla aynı anahtar.
        for bad in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            let o = TermOpts {
                interval: Some(bad),
                ..Default::default()
            };
            term(&fed, "s1", &o);
        }
        assert_eq!(f.upgrades(), 2);
        assert_eq!(fed.open_relays(), 2);

        // Kayıtsız host: istek yok.
        let v = fed.term_output("nope", "s1", "en", &plain);
        assert_eq!(v["code"], "unknown_host");
        assert_eq!(f.upgrades(), 2);
    })
    .await
}

/// Python `_TermRelay` etiketi: `term:<host>/<ad>` + `?lite` + `@<aralık>s` + `+viewport`; ölüm olayı bu etiketle.
#[tokio::test]
async fn relay_death_label_names_lite_interval_and_viewport() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        let o = TermOpts {
            lite: true,
            interval: Some(2.5),
            viewport: true,
        };
        wait_text(&fed, "s1", &o, "s1#0").await;
        f.send_last(Cmd::Drop);
        let d = ev.clone();
        wait_until("relay consumer died", Duration::from_secs(5), || {
            !deaths(&d).is_empty()
        })
        .await;
        assert_eq!(deaths(&ev)[0]["label"], "term:a/s1?lite@2.5s+viewport");
        assert_eq!(deaths(&ev)[0]["tier"], "ws");
    })
    .await
}

#[tokio::test]
async fn dead_relay_never_serves_its_frozen_frame_and_is_rebuilt_after_min_interval() {
    let f = deadline(fake(default_opener())).await;
    let src = MemSource::new(vec![host("a", &f.url())]);
    let (fed, ev) = fed(&src);
    ws_tier(&fed, "a");
    let o = TermOpts::default();
    deadline(wait_text(&fed, "s1", &o, "s1#0")).await;

    // Saat durur: "kuruluştan beri 2 sn" yalnız sanal saatle ilerler (yavaş makinede oynamaz).
    tokio::time::pause();
    f.send_last(Cmd::Drop);
    let d = ev.clone();
    wait_until("relay consumer died", Duration::from_secs(1), || {
        !deaths(&d).is_empty()
    })
    .await;
    for _ in 0..20 {
        let v = term(&fed, "s1", &o);
        assert!(is_connecting(&v), "frozen frame served: {v}");
        assert_eq!(v["error"], "relay: bağlantı koptu, yeniden deneniyor");
    }
    assert_eq!(f.upgrades(), 1, "not rebuilt within 2 s of creation");
    let death = &deaths(&ev)[0];
    assert_eq!(death["label"], "term:a/s1");

    tokio::time::advance(Duration::from_secs(2)).await;
    let v = term(&fed, "s1", &o);
    assert!(is_connecting(&v), "{v}");
    assert_eq!(
        v["error"], "relay: henüz veri gelmedi",
        "fresh relay, no old frame"
    );
    tokio::time::resume();
    deadline(async {
        f.wait_upgrades(2).await;
        wait_text(&fed, "s1", &o, "s1#1").await;
        assert_eq!(fed.open_relays(), 1);
    })
    .await;
}

#[tokio::test]
async fn silent_relay_is_restarted_after_45s_without_serving_the_stale_frame() {
    let f = deadline(fake(default_opener())).await;
    let src = MemSource::new(vec![host("a", &f.url())]);
    let (fed, ev) = fed(&src);
    ws_tier(&fed, "a");
    let o = TermOpts::default();
    deadline(wait_text(&fed, "s1", &o, "s1#0")).await;

    tokio::time::pause();
    tokio::time::advance(Duration::from_secs(44)).await;
    assert_eq!(text_of(&term(&fed, "s1", &o)).as_deref(), Some("s1#0"));
    assert_eq!(event_count(&ev, "term_relay_silent_restart"), 0);
    tokio::time::advance(Duration::from_secs(2)).await;
    let v = term(&fed, "s1", &o);
    assert!(is_connecting(&v), "stale frame served after silence: {v}");
    tokio::time::resume();

    deadline(async {
        assert_eq!(event_count(&ev, "term_relay_silent_restart"), 1);
        f.wait_upgrades(2).await;
        f.wait_ws_live(1).await; // eski yarı açık soket kapandı
        wait_text(&fed, "s1", &o, "s1#1").await;
        assert!(deaths(&ev).is_empty(), "deliberate restart is not a death");
    })
    .await;
}

#[tokio::test]
async fn relay_is_rebuilt_when_the_host_record_changes() {
    deadline(async {
        let f = fake(default_opener()).await;
        let f2 = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, _) = fed(&src);
        ws_tier(&fed, "a");
        let o = TermOpts::default();
        wait_text(&fed, "s1", &o, "s1#0").await;

        // extra_urls: aynı akış.
        src.hosts.lock().unwrap()[0].extra_urls = vec!["http://127.0.0.1:9".into()];
        for _ in 0..3 {
            assert_eq!(text_of(&term(&fed, "s1", &o)).as_deref(), Some("s1#0"));
        }
        assert_eq!(f.upgrades(), 1);

        // Token: yeniden kurulur, eski kare VERİLMEZ, eski soket kapanır.
        src.hosts.lock().unwrap()[0].token = Secret::new("NEW-tok");
        assert!(is_connecting(&term(&fed, "s1", &o)));
        wait_text(&fed, "s1", &o, "s1#1").await;
        f.wait_ws_live(1).await;
        let last = f
            .recs()
            .into_iter()
            .filter(|r| r.path == "/ws/term")
            .last()
            .unwrap();
        assert_eq!(
            query_value(&last.query, "token").as_deref(),
            Some("NEW-tok")
        );

        // Adres: yeni sunucuya.
        src.hosts.lock().unwrap()[0].base_url = f2.url();
        assert!(is_connecting(&term(&fed, "s1", &o)));
        wait_text(&fed, "s1", &o, "s1#0").await;
        assert_eq!(f2.upgrades(), 1);
        f.wait_ws_live(0).await;
        assert_eq!(fed.open_relays(), 1);
    })
    .await
}

#[tokio::test]
async fn idle_relays_are_reaped_and_their_sockets_closed() {
    let f = deadline(fake(default_opener())).await;
    let src = MemSource::new(vec![host("a", &f.url())]);
    let (fed, _) = fed(&src);
    ws_tier(&fed, "a");
    let o = TermOpts::default();
    deadline(wait_text(&fed, "s1", &o, "s1#0")).await;
    // Biçici prober turunda çalışır; host listesi boşken tur ağa gitmez.
    src.hosts.lock().unwrap().clear();
    tokio::time::pause();
    tokio::time::advance(Duration::from_secs(9)).await;
    fed.clone().probe_tiers_once().await;
    assert_eq!(fed.open_relays(), 1, "read 9 s ago: kept");
    tokio::time::advance(Duration::from_secs(2)).await;
    fed.clone().probe_tiers_once().await;
    assert_eq!(fed.open_relays(), 0, "unread for 11 s: reaped");
    tokio::time::resume();
    deadline(f.wait_ws_live(0)).await;
}

// ---------------------------------------------------------------- sınırlar

fn term_of_size(total: usize) -> String {
    let empty = json!({"type":"term","data":{"ok":true,"text":""}}).to_string();
    let pad = total - empty.len();
    let s = json!({"type":"term","data":{"ok":true,"text":"x".repeat(pad)}}).to_string();
    assert_eq!(s.len(), total);
    s
}

#[tokio::test]
async fn ws_message_limit_is_16_mib_exactly() {
    deadline(async {
        let f = fake(silent_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        let o = TermOpts::default();
        assert!(is_connecting(&term(&fed, "s1", &o)));
        f.wait_ws_live(1).await;

        // Python varsayılanı (1 MiB) üstü ve tam sınır kabul.
        f.send_last(Cmd::Send(Message::text(term_of_size(MIB16))));
        let fed2 = fed.clone();
        wait_until("16 MiB frame", Duration::from_secs(20), || {
            text_of(&term(&fed2, "s1", &o)).is_some_and(|t| t.len() > MIB16 - 64)
        })
        .await;
        assert!(deaths(&ev).is_empty());

        // Bir bayt fazlası: akış ölür, son kare bir daha VERİLMEZ.
        f.send_last(Cmd::Send(Message::text(term_of_size(MIB16 + 1))));
        let d = ev.clone();
        wait_until(
            "oversized frame kills the stream",
            Duration::from_secs(20),
            || !deaths(&d).is_empty(),
        )
        .await;
        let reason = deaths(&ev)[0]["reason"].as_str().unwrap().to_string();
        assert!(
            reason.to_lowercase().contains("too long") || reason.contains("16777217"),
            "{reason}"
        );
        assert!(reason.chars().count() <= 200);
        f.wait_ws_live(0).await;
        // Kuruluştan 2 sn geçtiyse bu okuma yeni akış kurar; her iki durumda da eski kare VERİLMEZ.
        let v = term(&fed, "s1", &o);
        assert!(
            is_connecting(&v),
            "frame after death: {}",
            &v.to_string()[..100.min(v.to_string().len())]
        );
    })
    .await
}

/// Parçalı (fin=0 + devam) mesaj: her çerçeve sınırın altında, toplam üstünde. Çerçeve sınırı tek başına yakalamaz;
/// mesaj sınırı yakalar.
#[tokio::test]
async fn fragmented_ws_message_over_16_mib_is_refused() {
    use tokio_tungstenite::tungstenite::protocol::frame::coding::{Data, OpCode};
    use tokio_tungstenite::tungstenite::protocol::frame::Frame;
    deadline(async {
        let f = fake(silent_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        let o = TermOpts::default();
        assert!(is_connecting(&term(&fed, "s1", &o)));
        f.wait_ws_live(1).await;
        let send_fragmented = |total: usize| {
            let body = term_of_size(total).into_bytes();
            let half = body.len() / 2;
            f.send_last(Cmd::Send(Message::Frame(Frame::message(
                body[..half].to_vec(),
                OpCode::Data(Data::Text),
                false,
            ))));
            f.send_last(Cmd::Send(Message::Frame(Frame::message(
                body[half..].to_vec(),
                OpCode::Data(Data::Continue),
                true,
            ))));
        };
        // Tam sınır: parçalı da kabul.
        send_fragmented(MIB16);
        let fed2 = fed.clone();
        wait_until("fragmented 16 MiB message", Duration::from_secs(20), || {
            text_of(&term(&fed2, "s1", &o)).is_some_and(|t| t.len() > MIB16 - 64)
        })
        .await;
        assert!(deaths(&ev).is_empty());
        // Bir bayt fazlası (her parça ~8 MiB): akış ölür.
        send_fragmented(MIB16 + 1);
        let d = ev.clone();
        wait_until(
            "fragmented oversize kills the stream",
            Duration::from_secs(20),
            || !deaths(&d).is_empty(),
        )
        .await;
        let reason = deaths(&ev)[0]["reason"].as_str().unwrap().to_lowercase();
        assert!(
            reason.contains("too long") || reason.contains("16777217"),
            "{reason}"
        );
        f.wait_ws_live(0).await;
        assert!(is_connecting(&term(&fed, "s1", &o)));
    })
    .await
}

#[tokio::test]
async fn base_path_is_kept_for_ws_and_signed_over_it() {
    deadline(async {
        let f = fake(default_opener()).await;
        let base = format!("{}/panel", f.url());
        let src = MemSource::new(vec![host("a", &base)]);
        let signer = TestSigner::new(SignMode::Sign);
        let mut c = client();
        c.signer = Some(signer.clone());
        let (fed, _) = fed_with(c, &src);
        assert_eq!(fed.probe_tier(&host("a", &base)).await, Tier::Ws);
        ws_tier(&fed, "a");
        wait_text(&fed, "s1", &TermOpts::default(), "s1#1").await;
        let paths: Vec<String> = f.recs().into_iter().map(|r| r.path).collect();
        assert_eq!(paths, ["/panel/ws", "/panel/ws/term"]);
        let seen: Vec<String> = signer.seen().into_iter().map(|s| s.path).collect();
        assert_eq!(seen, ["/panel/ws", "/panel/ws/term"]);
    })
    .await
}

#[tokio::test]
async fn dropped_streams_close_their_sockets_and_leak_no_fds() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let o = TermOpts::default();
        // Isınma (süreç ilk kullanımda kalıcı fd açabilir).
        {
            let (fed, _) = fed(&src);
            ws_tier(&fed, "a");
            wait_text(&fed, "w", &o, "w#0").await;
        }
        f.wait_ws_live(0).await;
        let base = fd_count();
        for round in 0..10 {
            let (fed, _) = fed(&src);
            ws_tier(&fed, "a");
            for n in 0..5 {
                let name = format!("r{round}n{n}");
                assert!(is_connecting(&term(&fed, &name, &o)));
            }
            fed.ensure_status_consumer(&host("a", &f.url()));
            f.wait_ws_live(6).await;
            drop(fed); // Federation düşünce tüm relay ve tüketici görevleri iptal, soketler kapanır.
            f.wait_ws_live(0).await;
        }
        assert_eq!(f.upgrades(), 1 + 60);
        wait_until("fd count back to baseline", Duration::from_secs(5), || {
            fd_count() <= base
        })
        .await;

        // Host kayıttan silinince tur tüketiciyi bırakır.
        let (fed, _) = fed(&src);
        ws_tier(&fed, "a");
        fed.ensure_status_consumer(&host("a", &f.url()));
        f.wait_ws_live(1).await;
        src.hosts.lock().unwrap().clear();
        fed.clone().poll_once().await;
        f.wait_ws_live(0).await;
    })
    .await
}

// ---------------------------------------------------------------- adres denetimi

#[tokio::test]
async fn dns_name_resolving_to_loopback_is_refused_for_ws_before_connecting() {
    deadline(async {
        let f = fake(default_opener()).await;
        let calls = Arc::new(AtomicUsize::new(0));
        let conn = Connector {
            resolver: counting_resolver(f.addr, calls.clone()),
            ..Default::default()
        };
        let mut c = HostClient::new(conn);
        c.timeouts = timeouts();
        let dns = format!("http://fake-remote.test:{}", f.addr.port());
        let src = MemSource::new(vec![host("a", &dns)]);
        let (fed, ev) = fed_with(c, &src);

        assert_eq!(fed.probe_tier(&host("a", &dns)).await, Tier::Rest);
        assert!(calls.load(Ordering::SeqCst) >= 1, "resolver consulted");
        ws_tier(&fed, "a");
        assert!(is_connecting(&term(&fed, "s1", &TermOpts::default())));
        fed.ensure_status_consumer(&host("a", &dns));
        let d = ev.clone();
        wait_until("both streams refused", Duration::from_secs(5), || {
            deaths(&d).len() >= 2
        })
        .await;
        for d in deaths(&ev) {
            let r = d["reason"].as_str().unwrap();
            assert!(
                r.starts_with("blocked: fake-remote.test resolved to"),
                "{r}"
            );
        }
        assert_eq!(f.accepted(), 0, "no TCP connection to the loopback target");

        // Kontrol: aynı sunucu IP literaliyle (kayıt anında denetlenmiş) kabul edilir.
        assert_eq!(fed.probe_tier(&host("a", &f.url())).await, Tier::Ws);
        assert_eq!(f.accepted(), 1);
    })
    .await
}

// ---------------------------------------------------------------- imza

#[tokio::test]
async fn ws_handshake_carries_a_fresh_panel_signature_per_connection() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let signer = TestSigner::new(SignMode::Sign);
        let mut c = client();
        c.signer = Some(signer.clone());
        let (fed, _) = fed_with(c, &src);
        assert_eq!(fed.probe_tier(&host("a", &f.url())).await, Tier::Ws);
        ws_tier(&fed, "a");
        fed.ensure_status_consumer(&host("a", &f.url()));
        wait_text(&fed, "s1", &TermOpts::default(), "s1#2").await;
        let recs = f.recs();
        assert_eq!(recs.len(), 3);
        let mut sigs: Vec<String> = recs
            .iter()
            .map(|r| r.header("x-test-sig").unwrap())
            .collect();
        sigs.sort();
        sigs.dedup();
        assert_eq!(sigs.len(), 3, "a fresh signature per handshake");
        let legacy = cops_hosts::sign::Principal::legacy().uid;
        for (r, s) in recs.iter().zip(signer.seen()) {
            assert_eq!(r.header("x-test-uid").unwrap(), legacy);
            assert_eq!(s.uid, legacy, "panel identity, not a user");
            assert_eq!(s.host_name, "a");
            assert_eq!(s.method, "GET");
            assert!(s.body.is_none());
            assert!(
                !s.path.contains('?') && !s.path.contains(TOKEN),
                "{}",
                s.path
            );
        }
    })
    .await
}

#[tokio::test]
async fn ws_signer_refusal_panic_or_bad_header_opens_no_connection() {
    deadline(async {
        let f = fake(default_opener()).await;
        let modes = [
            SignMode::Refuse,
            SignMode::Panic,
            SignMode::Header("connection", "close"),
            SignMode::Header("sec-websocket-key", "x"),
            SignMode::Header("upgrade", "h2c"),
            SignMode::Header("bad header", "x"),
        ];
        for mode in modes {
            let src = MemSource::new(vec![host("a", &f.url())]);
            let signer = TestSigner::new(mode);
            let mut c = client();
            c.signer = Some(signer.clone());
            let (fed, ev) = fed_with(c, &src);
            assert_eq!(fed.probe_tier(&host("a", &f.url())).await, Tier::Rest);
            ws_tier(&fed, "a");
            assert!(is_connecting(&term(&fed, "s1", &TermOpts::default())));
            fed.ensure_status_consumer(&host("a", &f.url()));
            let d = ev.clone();
            wait_until("streams refused", Duration::from_secs(5), || {
                deaths(&d).len() >= 2
            })
            .await;
            for d in deaths(&ev) {
                let r = d["reason"].as_str().unwrap();
                assert!(r.starts_with("outbound refused: "), "{r}");
            }
            assert!(signer.calls() >= 3);
        }
        assert_eq!(f.accepted(), 0, "refused handshakes never open a socket");
    })
    .await
}

// ---------------------------------------------------------------- H18 çerçeveleme

#[tokio::test]
async fn server_ping_gets_pong_and_server_close_is_acknowledged() {
    deadline(async {
        let f = fake(default_opener()).await;
        let src = MemSource::new(vec![host("a", &f.url())]);
        let (fed, ev) = fed(&src);
        ws_tier(&fed, "a");
        let o = TermOpts::default();
        wait_text(&fed, "s1", &o, "s1#0").await;

        f.send_last(Cmd::Send(Message::Ping(bytes::Bytes::from_static(b"hb"))));
        wait_until("pong", Duration::from_secs(5), || f.pongs() == 1).await;
        // Ping canlılık sayılmaz ama akışı da bozmaz.
        f.send_last(Cmd::Send(term_frame("after-ping")));
        wait_text(&fed, "s1", &o, "after-ping").await;
        assert!(deaths(&ev).is_empty());

        f.send_last(Cmd::Close);
        wait_until("client close ack", Duration::from_secs(5), || {
            f.client_closes() == 1
        })
        .await;
        let d = ev.clone();
        wait_until("consumer ended", Duration::from_secs(5), || {
            !deaths(&d).is_empty()
        })
        .await;
        assert_eq!(deaths(&ev)[0]["reason"], "stream_ended");
        f.wait_ws_live(0).await;
        assert!(is_connecting(&term(&fed, "s1", &o)));
    })
    .await
}
