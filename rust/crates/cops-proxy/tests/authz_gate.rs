//! Kaynak çıkarımı Python ile eşit; `Gate` fail-closed.

use cops_auth::authz::{
    AuditSink, AuthError, Authenticator, Authorizer, BoxFut, Principal, RequestView, Resource,
};
use cops_proxy::gate::{Decision, Gate};
use cops_proxy::resources::{resources_from, BadResource};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[test]
fn resources_match_python() {
    let v: Value = serde_json::from_str(include_str!(
        "../../cops-auth/tests/data/authz_vectors.json"
    ))
    .unwrap();
    let lookup = |k: &str| v["approvals"][k].as_str().map(str::to_string);
    let (mut same, mut rejected) = (0, 0);
    for c in v["resources"].as_array().unwrap() {
        let got = resources_from(
            c["path"].as_str().unwrap(),
            c["query"].as_str().unwrap(),
            c["body"].as_str().map(str::as_bytes),
            &lookup,
        );
        if c["rust_rejects"] == true {
            assert_eq!(got, Err(BadResource), "{c}");
            rejected += 1;
            continue;
        }
        let got: Vec<Value> = got
            .unwrap_or_else(|_| panic!("red edildi: {c}"))
            .iter()
            .map(|r| json!({"kind": r.kind, "host": r.host, "name": r.name, "cwd": r.cwd, "steward": r.steward}))
            .collect();
        assert_eq!(Value::Array(got), c["expect"], "{c}");
        same += 1;
    }
    assert!(same > 40 && rejected > 10, "{same} {rejected}");
}

#[derive(Clone, Copy, PartialEq)]
enum Act {
    Yes,
    No,
    Err,
    Panic,
    Hang,
}

struct Fake {
    authn: Act,
    authz: Act,
    deny_name: &'static str,
}

async fn play(a: Act) -> Result<bool, AuthError> {
    match a {
        Act::Yes => Ok(true),
        Act::No => Ok(false),
        Act::Err => Err(AuthError::Unavailable("depo yok".into())),
        Act::Panic => panic!("sahte saglayici"),
        Act::Hang => {
            tokio::time::sleep(Duration::from_secs(60)).await;
            Ok(true)
        }
    }
}

impl Authenticator for Fake {
    fn authenticate<'a>(
        &'a self,
        _: &'a RequestView,
    ) -> BoxFut<'a, Result<Option<Principal>, AuthError>> {
        Box::pin(async move { Ok(play(self.authn).await?.then(Principal::legacy)) })
    }
}

impl Authorizer for Fake {
    fn authorize<'a>(
        &'a self,
        _: &'a Principal,
        action: &'a str,
        res: &'a Resource,
    ) -> BoxFut<'a, Result<bool, AuthError>> {
        Box::pin(async move {
            assert_eq!(action, "session.control");
            Ok(play(self.authz).await? && res.name != self.deny_name)
        })
    }
}

#[derive(Default)]
struct Log(Mutex<Vec<(String, u16)>>, bool);

impl AuditSink for Log {
    fn record(&self, _: &Principal, _: &str, res: &Resource, status: u16) {
        self.0.lock().unwrap().push((res.name.clone(), status));
        assert!(!self.1, "sink panigi");
    }
}

fn view() -> RequestView {
    RequestView {
        method: "POST".into(),
        path: "/api/start".into(),
        raw_query: String::new(),
        headers: Vec::new(),
        client_ip: "127.0.0.1".parse().unwrap(),
        peer_loopback: true,
    }
}

fn named(names: &[&str]) -> Vec<Resource> {
    names
        .iter()
        .map(|n| Resource {
            kind: "session".into(),
            name: n.to_string(),
            ..Resource::default()
        })
        .collect()
}

async fn run(authn: Act, authz: Act, res: &[Resource], log: Arc<Log>) -> Decision {
    let fake = Arc::new(Fake {
        authn,
        authz,
        deny_name: "yasak",
    });
    Gate::new(fake.clone(), fake)
        .with_sink(log)
        .with_timeout(Duration::from_millis(200))
        .decide(view(), res)
        .await
}

#[tokio::test(flavor = "multi_thread")]
async fn authentication_failures_are_401_and_not_audited() {
    for a in [Act::No, Act::Err, Act::Panic, Act::Hang] {
        let log = Arc::new(Log::default());
        let d = run(a, Act::Yes, &named(&["a"]), log.clone()).await;
        assert_eq!(d, Decision::Unauthorized);
        assert!(log.0.lock().unwrap().is_empty());
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn authorization_failures_are_403_and_audited() {
    for a in [Act::No, Act::Err, Act::Panic, Act::Hang] {
        let log = Arc::new(Log::default());
        let d = run(Act::Yes, a, &named(&["a", "b"]), log.clone()).await;
        assert_eq!(d, Decision::Forbidden);
        assert_eq!(*log.0.lock().unwrap(), vec![("a".to_string(), 403)]);
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn every_resource_must_be_allowed_and_empty_list_is_denied() {
    let log = Arc::new(Log::default());
    let d = run(
        Act::Yes,
        Act::Yes,
        &named(&["a", "yasak", "c"]),
        log.clone(),
    )
    .await;
    assert_eq!(d, Decision::Forbidden);
    assert_eq!(
        *log.0.lock().unwrap(),
        vec![("a".to_string(), 200), ("yasak".to_string(), 403)]
    );
    let d = run(Act::Yes, Act::Yes, &named(&["a", "c"]), Arc::default()).await;
    assert_eq!(d, Decision::Allow(Principal::legacy()));
    let d = run(Act::Yes, Act::Yes, &[], Arc::default()).await;
    assert_eq!(d, Decision::Forbidden);
}

#[tokio::test(flavor = "multi_thread")]
async fn failing_sink_does_not_change_the_decision() {
    for (authz, want) in [
        (Act::Yes, Decision::Allow(Principal::legacy())),
        (Act::No, Decision::Forbidden),
    ] {
        let log = Arc::new(Log(Mutex::default(), true));
        // zehirlenen kilit ikinci kayda engel olmasın diye tek kaynak
        assert_eq!(run(Act::Yes, authz, &named(&["a"]), log).await, want);
    }
}
