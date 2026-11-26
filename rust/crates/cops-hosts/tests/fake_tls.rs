//! TLS: geçici kökle (`Connector.tls`, yalnız programatik) WS, gRPC ve REST birer tur; yanlış kök, yanlış ad ve
//! sistem kökleri reddedilir ve sunucuya hiçbir HTTP isteği ulaşmaz. gRPC'de kendi `Dial`imiz + `origin` ile https
//! yolunun GERÇEKTEN çalıştığı (`:scheme` = https, ALPN h2) burada kanıtlanır.

mod support;

use std::sync::Arc;
use std::time::Duration;

use cops_hosts::net::Connector;
use cops_hosts::tier::Tier;
use cops_hosts::{Federation, HostClient, HostRecord, TermOpts};
use serde_json::{json, Value};
use support::grpc::*;
use support::tls::*;
use support::ws::*;
use support::*;

fn rest_status() -> Handler {
    handler(|_r| async {
        json(
            200,
            json!({"sessions": [{"name": "rest1", "cwd": "/w", "running": true}], "closed": [], "retired": []}),
        )
    })
}

fn fed_over(conn: Connector, src: &Arc<MemSource>) -> (Arc<Federation>, Arc<RecEvents>) {
    let ev = Arc::new(RecEvents::default());
    let mut c = HostClient::new(conn);
    c.timeouts = timeouts();
    c.events = ev.clone();
    (Federation::new(Arc::new(c), src.clone()), ev)
}

async fn wait_term(fed: &Federation, pred: impl Fn(&Value) -> bool) -> Value {
    let end = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        let v = fed.term_output("a", "s1", "en", &TermOpts::default());
        if pred(&v) {
            return v;
        }
        if tokio::time::Instant::now() >= end {
            panic!("term_output never matched; last = {v}");
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

fn grpc_host(base: &str, grpc: &str) -> HostRecord {
    let mut h = host("a", base);
    h.grpc_url = grpc.into();
    h
}

#[tokio::test]
async fn wss_and_https_rest_work_with_a_custom_root() {
    deadline(async {
        let ca = Ca::new("cops-test-ca");
        let w = WsFake::start(
            rest_status(),
            default_opener(),
            Some(ca.acceptor(&["127.0.0.1"], &[])),
        )
        .await;
        let base = w.https_url();
        let src = MemSource::new(vec![host("a", &base)]);
        let (fed, _) = fed_over(connector_trusting(&ca, None), &src);

        // REST
        let st = fed.fetch_status(&host("a", &base)).await;
        assert!(st.ok, "{st:?}");
        assert_eq!(st.sessions[0]["name"], "rest1");
        // WS yoklaması + wss term akışı
        assert_eq!(fed.probe_tier(&host("a", &base)).await, Tier::Ws);
        fed.tiers.update("a", Tier::Ws);
        let v = wait_term(&fed, |v| v["ok"] == true).await;
        assert!(v["text"].as_str().unwrap().starts_with("s1#"));
        assert_eq!(w.tls_failed(), 0);
        let paths: Vec<String> = w.recs().into_iter().map(|r| r.path).collect();
        assert_eq!(paths, ["/api/status", "/ws", "/ws/term"]);
    })
    .await
}

#[tokio::test]
async fn wrong_root_wrong_name_or_system_roots_refuse_tls_and_send_no_request() {
    deadline(async {
        let ca = Ca::new("cops-test-ca");
        let other = Ca::new("someone-else");
        // Doğru köke zincirli ama 127.0.0.1 için DEĞİL.
        let wrong_name = WsFake::start(
            rest_status(),
            default_opener(),
            Some(ca.acceptor(&["127.0.0.2", "other.example"], &[])),
        )
        .await;
        let good = WsFake::start(
            rest_status(),
            default_opener(),
            Some(ca.acceptor(&["127.0.0.1"], &[])),
        )
        .await;
        let cases: Vec<(&str, Connector, &WsFake)> = vec![
            ("untrusted root", connector_trusting(&other, None), &good),
            ("system roots only", Connector::default(), &good),
            ("name mismatch", connector_trusting(&ca, None), &wrong_name),
        ];
        for (what, conn, srv) in cases {
            let base = srv.https_url();
            let src = MemSource::new(vec![host("a", &base)]);
            let (fed, ev) = fed_over(conn, &src);
            let before = srv.tls_failed();
            let st = fed.fetch_status(&host("a", &base)).await;
            assert!(!st.ok, "{what}: REST over bad TLS succeeded");
            assert_clean(st.error.as_deref().unwrap(), srv.addr.port());
            assert_eq!(
                fed.probe_tier(&host("a", &base)).await,
                Tier::Rest,
                "{what}"
            );
            fed.tiers.update("a", Tier::Ws);
            fed.term_output("a", "s1", "en", &TermOpts::default());
            let d = ev.clone();
            wait_until("relay refused", Duration::from_secs(5), || {
                d.names().iter().any(|n| n == "push_consumer_died")
            })
            .await;
            // İstemci reddedince sunucu tarafı el sıkışma hatasını biraz sonra görür.
            wait_until(
                &format!("{what}: 3 handshakes rejected"),
                Duration::from_secs(5),
                || srv.tls_failed() >= before + 3,
            )
            .await;
            assert!(srv.recs().is_empty(), "{what}: an HTTP request got through");
        }
    })
    .await
}

#[tokio::test]
async fn grpc_over_https_works_through_own_dial_and_origin() {
    deadline(async {
        let ca = Ca::new("cops-test-ca");
        let g = GrpcFake::start(Some(ca.acceptor(&["127.0.0.1"], &[b"h2"]))).await;
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let src = MemSource::new(vec![grpc_host(&base, &g.https_url())]);
        let (fed, _) = fed_over(connector_trusting(&ca, None), &src);

        assert_eq!(
            fed.probe_tier(&grpc_host(&base, &g.https_url())).await,
            Tier::Grpc
        );
        let ping = &g.calls()[0];
        assert_eq!(ping.method, "Ping");
        assert_eq!(ping.scheme.as_deref(), Some("https"), "origin sets :scheme");
        assert_eq!(ping.authority.as_deref(), Some(g.addr.to_string().as_str()));

        // Akışlar da aynı TLS kanalından.
        fed.tiers.update("a", Tier::Grpc);
        fed.ensure_status_consumer(&grpc_host(&base, &g.https_url()));
        let v = wait_term(&fed, |v| v["ok"] == true).await;
        assert_eq!(v["text"], "s1/en#grpc");
        g.wait_streams(2).await;
        assert_eq!(g.tls_failed(), 0);
        assert_eq!(
            g.accepted(),
            1,
            "one TLS connection for probe and both streams"
        );
        assert!(g
            .calls()
            .iter()
            .all(|c| c.scheme.as_deref() == Some("https")));
    })
    .await
}

#[tokio::test]
async fn grpc_plain_http_sends_http_scheme() {
    deadline(async {
        let g = GrpcFake::start(None).await;
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let src = MemSource::new(vec![]);
        let (fed, _) = fed_over(Connector::default(), &src);
        assert_eq!(
            fed.probe_tier(&grpc_host(&base, &g.url())).await,
            Tier::Grpc
        );
        assert_eq!(g.calls()[0].scheme.as_deref(), Some("http"));
    })
    .await
}

#[tokio::test]
async fn grpc_tls_with_wrong_root_or_name_is_refused_and_no_call_arrives() {
    deadline(async {
        let ca = Ca::new("cops-test-ca");
        let other = Ca::new("someone-else");
        let good = GrpcFake::start(Some(ca.acceptor(&["127.0.0.1"], &[b"h2"]))).await;
        let wrong_name =
            GrpcFake::start(Some(ca.acceptor(&["127.0.0.2", "other.example"], &[b"h2"]))).await;
        let dead = closed_port().await;
        let base = format!("http://127.0.0.1:{dead}");
        let cases: Vec<(&str, Connector, &GrpcFake)> = vec![
            ("untrusted root", connector_trusting(&other, None), &good),
            ("system roots only", Connector::default(), &good),
            ("name mismatch", connector_trusting(&ca, None), &wrong_name),
        ];
        for (what, conn, srv) in cases {
            let src = MemSource::new(vec![grpc_host(&base, &srv.https_url())]);
            let (fed, ev) = fed_over(conn, &src);
            let before = srv.tls_failed();
            assert_eq!(
                fed.probe_tier(&grpc_host(&base, &srv.https_url())).await,
                Tier::Rest,
                "{what}"
            );
            fed.tiers.update("a", Tier::Grpc);
            fed.term_output("a", "s1", "en", &TermOpts::default());
            let d = ev.clone();
            wait_until("grpc relay refused", Duration::from_secs(10), || {
                d.names().iter().any(|n| n == "push_consumer_died")
            })
            .await;
            wait_until(
                &format!("{what}: handshake rejected"),
                Duration::from_secs(5),
                || srv.tls_failed() > before,
            )
            .await;
            assert!(srv.calls().is_empty(), "{what}: a gRPC call got through");
        }
    })
    .await
}
