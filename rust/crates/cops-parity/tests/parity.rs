//! İki sahte sunucuyla uçtan uca: normalize kuralları, güvenli istek süzgeci, `expect: local`, token'ın yalnız başlıkta gitmesi.
use cops_parity::{config, exit_code, report, run, Target, Verdict};
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

type Seen = Arc<Mutex<Vec<String>>>;

/// Yola göre sabit yanıt: `(durum, ek başlık, gövde)`.
async fn server(reply: fn(&str) -> (u16, &'static str, &'static str)) -> (SocketAddr, Seen) {
    let ln = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = ln.local_addr().unwrap();
    let seen: Seen = Default::default();
    let log = seen.clone();
    tokio::spawn(async move {
        loop {
            let (mut c, _) = ln.accept().await.unwrap();
            let log = log.clone();
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut tmp = [0u8; 4096];
                while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                    let n = c.read(&mut tmp).await.unwrap_or(0);
                    if n == 0 {
                        return;
                    }
                    buf.extend_from_slice(&tmp[..n]);
                }
                let head = String::from_utf8_lossy(&buf).to_string();
                let path = head.split_whitespace().nth(1).unwrap_or("").to_string();
                log.lock().unwrap().push(head);
                let (status, extra, body) = reply(&path);
                let out = format!(
                    "HTTP/1.1 {status} X\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = c.write_all(out.as_bytes()).await;
            });
        }
    });
    (addr, seen)
}

const JSON: &str = "Content-Type: application/json; charset=utf-8\r\n";
const LOCAL: &str = "Content-Type: application/json\r\nX-Cops-Served: local\r\n";

fn python(path: &str) -> (u16, &'static str, &'static str) {
    match path {
        "/eq" => (
            200,
            JSON,
            r#"{"a": 1.0, "b": [{"n": "x", "t": 1}, {"n": "y", "t": 2}], "ts": 10, "only_py": 1}"#,
        ),
        "/diff" => (
            200,
            JSON,
            r#"{"secret": "PY-SECRET", "ts": 1, "list": [1, 2]}"#,
        ),
        "/text" => (200, "Content-Type: text/plain\r\n", "ayni"),
        _ => (200, JSON, "{}"),
    }
}

fn rust(path: &str) -> (u16, &'static str, &'static str) {
    match path {
        "/eq" => (
            200,
            LOCAL,
            r#"{"ts": 99, "b": [{"t": 7, "n": "y"}, {"t": 8, "n": "x"}], "a": 1}"#,
        ),
        "/diff" => (
            201,
            LOCAL,
            r#"{"secret": "RS-SECRET", "ts": "1", "list": [2, 1], "extra": null}"#,
        ),
        "/text" => (
            200,
            "Content-Type: text/plain\r\nX-Cops-Served: python\r\n",
            "ayni",
        ),
        _ => (200, JSON, "{}"),
    }
}

const LIST: &str = r#"{
  "defaults": {"dynamic": ["ts"]},
  "requests": [
    {"path": "/eq", "ignore": ["only_py"], "dynamic": ["b.*.t"], "unordered": ["b"], "expect": "local"},
    {"name": "fark", "path": "/diff"},
    {"name": "metin", "path": "/text"},
    {"name": "metin-yerel", "path": "/text", "expect": "local"},
    {"name": "yazan", "method": "post", "path": "/w", "body": {"x": 1}},
    {"name": "okuyan-post", "method": "POST", "path": "/r", "side_effect_free": true},
    {"name": "yan-etkili-get", "path": "/g", "side_effect_free": false}
  ]
}"#;

#[tokio::test]
async fn end_to_end() {
    let (py, py_seen) = server(python).await;
    let (rs, rs_seen) = server(rust).await;
    let t = Target {
        python: py,
        rust: rs,
        token: Some("tok-NOT-REAL".into()),
        timeout: Duration::from_secs(5),
    };
    let cases = config::parse(LIST).unwrap();
    let out = run(&cases, &t, false).await;
    let by = |n: &str| out.iter().find(|o| o.name == n).unwrap();

    assert_eq!(
        by("GET /eq").verdict,
        Verdict::Pass,
        "{}",
        report(&out, true)
    );
    assert_eq!(by("GET /eq").served.as_deref(), Some("local"));
    let d = by("fark");
    assert_eq!(d.verdict, Verdict::Fail);
    assert!(d.notes.iter().any(|n| n.starts_with("durum")), "{d:?}");
    let at: Vec<(&str, &str)> = d.diffs.iter().map(|x| (x.at.as_str(), x.what)).collect();
    assert_eq!(
        at,
        [
            ("extra", "Python'da yok"),
            ("list.0", "değer"),
            ("list.1", "değer"),
            ("secret", "değer"),
            ("ts", "tür"),
        ]
    );
    assert_eq!(by("metin").verdict, Verdict::Pass);
    assert_eq!(by("metin-yerel").verdict, Verdict::Fail);
    assert_eq!(by("yazan").verdict, Verdict::Skipped);
    assert_eq!(by("okuyan-post").verdict, Verdict::Pass);
    assert_eq!(by("yan-etkili-get").verdict, Verdict::Skipped);

    let quiet = report(&out, false);
    assert!(!quiet.contains("SECRET"), "{quiet}");
    assert!(report(&out, true).contains("PY-SECRET"));
    assert_eq!(exit_code(&out), 1);

    for (seen, marked) in [(py_seen, false), (rs_seen, true)] {
        let seen = seen.lock().unwrap();
        assert!(!seen
            .iter()
            .any(|h| h.contains(" /w ") || h.contains(" /g ")));
        for head in seen.iter() {
            let lower = head.to_ascii_lowercase();
            assert!(
                lower.contains("authorization: bearer tok-not-real"),
                "{head}"
            );
            assert!(!head.lines().next().unwrap().contains("tok-NOT-REAL"));
            assert_eq!(lower.contains("x-cops-parity"), marked, "{head}");
        }
    }
}

#[tokio::test]
async fn unreachable_side_is_an_error_and_nothing_run_is_not_a_pass() {
    let (py, _) = server(python).await;
    let closed = std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap();
    let t = Target {
        python: py,
        rust: closed,
        token: None,
        timeout: Duration::from_secs(5),
    };
    let cases = config::parse(r#"{"requests": [{"path": "/eq"}]}"#).unwrap();
    let out = run(&cases, &t, false).await;
    assert_eq!(out[0].verdict, Verdict::Error);
    assert_eq!(exit_code(&out), 1);
    assert_eq!(exit_code(&[]), 1);
}

#[test]
fn list_is_validated_strictly() {
    for bad in [
        r#"{"requests": [{"path": "/a", "ignroe": []}]}"#,
        r#"{"requests": [{"path": "http://x/a"}]}"#,
        r#"{"requests": [{"path": "//x/a"}]}"#,
        r#"{"requests": [{"path": "/a b"}]}"#,
        r#"{"requests": [{"path": "/a", "expect": "python"}]}"#,
        r#"{"requests": [{"path": "/a", "ignore": ["a..b"]}]}"#,
        r#"{"requests": [{"path": "/a", "side_effect_free": "yes"}]}"#,
        r#"{"reqests": []}"#,
    ] {
        assert!(config::parse(bad).is_err(), "{bad}");
    }
    let sample = include_str!("../requests/basic.json");
    assert!(config::parse(sample).unwrap().iter().all(|c| c.safe()));
}

#[test]
fn numbers_compare_by_value_without_rounding_large_integers() {
    use cops_parity::compare::{diff, Rules};
    let eq = |a: &str, b: &str| {
        diff(
            &serde_json::from_str(a).unwrap(),
            &serde_json::from_str(b).unwrap(),
            &Rules::default(),
        )
        .is_empty()
    };
    assert!(eq("[1, 2.5, -3.0]", "[1.0, 2.5, -3]"));
    assert!(!eq("9007199254740993", "9007199254740992.0"));
    assert!(!eq("18446744073709551615", "18446744073709551614"));
    assert!(!eq("1", "true"));
}
