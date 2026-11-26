//! G8: gerçek `ModelIo`. Yalnız loopback sahte sunuculara istek atılır; sertifikalar testte üretilir.

#[path = "g8/support.rs"]
mod support;

use cops_providers::real::docs::FileDocs;
use cops_providers::real::http::{HttpClient, HttpError};
use cops_providers::real::modelio::RealModelIo;
use cops_providers::real::Env;
use cops_providers::{HttpRequest, ModelIo, ModelSources, RunRequest, SecretValue, Settings};
use rcgen::{BasicConstraints, CertificateParams, IsCa, Issuer, KeyPair};
use serde_json::json;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::time::{Duration, Instant};
use support::{spawn_guard, Tmp};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_rustls::rustls::pki_types::PrivateKeyDer;
use tokio_rustls::rustls::{self, RootCertStore, ServerConfig};

const KEY: &str = "gizli-anahtar-123";

/// Bağlantı başına `handler` koşan loopback sunucu. Gelen istek başlıkları kanala yazılır. Dinleyici 20 sn boyunca yeni
/// bağlantı gelmezse kapanır (iş parçacığı kalmaz).
fn serve(handler: impl Fn(&[u8], &mut TcpStream) + Send + Sync + 'static) -> (u16, Receiver<Vec<u8>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let (tx, rx) = channel();
    let handler = Arc::new(handler);
    std::thread::spawn(move || {
        let mut idle = Instant::now();
        while idle.elapsed() < Duration::from_secs(20) {
            let Ok((mut stream, _)) = listener.accept() else {
                std::thread::sleep(Duration::from_millis(2));
                continue;
            };
            idle = Instant::now();
            let (tx, handler) = (tx.clone(), handler.clone());
            std::thread::spawn(move || {
                stream.set_nonblocking(false).unwrap();
                stream.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
                let head = read_head(&mut stream);
                let _ = tx.send(head.clone());
                handler(&head, &mut stream);
                let _ = stream.shutdown(Shutdown::Write);
                // istemci kapatana dek bekle (RST ile yanıt kaybolmasın)
                let _ = stream.read(&mut [0u8; 64]);
            });
        }
    });
    (port, rx)
}

fn read_head(stream: &mut TcpStream) -> Vec<u8> {
    let mut head = Vec::new();
    let mut byte = [0u8; 1];
    while !head.ends_with(b"\r\n\r\n") && matches!(stream.read(&mut byte), Ok(1)) {
        head.push(byte[0]);
    }
    head
}

fn fixed(reply: &'static [u8]) -> (u16, Receiver<Vec<u8>>) {
    serve(move |_, s| {
        let _ = s.write_all(reply);
    })
}

const OK: &[u8] = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nmerhab";

fn request(url: String, timeout_ms: u64, max_body: u64) -> HttpRequest {
    HttpRequest {
        url,
        headers: vec![("X-API-Key", SecretValue::new(KEY).unwrap())],
        timeout: Duration::from_millis(timeout_ms),
        max_body,
    }
}

fn env(vars: &[(&str, &str)]) -> Env {
    Env::fixed(vars.iter().copied())
}

fn get(vars: &[(&str, &str)], url: String) -> Result<Vec<u8>, HttpError> {
    HttpClient::new(env(vars)).get(&request(url, 5000, 1000))
}

fn text(head: &[u8]) -> String {
    String::from_utf8_lossy(head).to_lowercase()
}

fn nothing(rx: &Receiver<Vec<u8>>) {
    assert!(rx.recv_timeout(Duration::from_millis(200)).is_err(), "beklenmeyen istek");
}

#[test]
fn a_2xx_body_is_returned_for_every_framing() {
    for reply in [
        &b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nmerhab"[..],
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nmer\r\n3\r\nhab\r\n0\r\n\r\n",
        b"HTTP/1.0 200 OK\r\n\r\nmerhab",
        b"HTTP/1.1 299 Tuhaf\r\nContent-Length: 6\r\n\r\nmerhab",
    ] {
        let (port, _rx) = serve(move |_, s| {
            let _ = s.write_all(reply);
        });
        assert_eq!(get(&[], format!("http://127.0.0.1:{port}/models")).as_deref(), Ok(&b"merhab"[..]));
    }
}

#[test]
fn the_request_carries_the_key_only_in_its_header_and_latin1_bytes_stay_raw() {
    let (port, rx) = fixed(OK);
    let mut req = request(format!("http://127.0.0.1:{port}/a/b?q=1#parca"), 5000, 100);
    req.headers.push(("Authorization", SecretValue::new("Bearer é").unwrap()));
    HttpClient::new(env(&[])).get(&req).unwrap();
    let head = rx.recv().unwrap();
    let lower = text(&head);
    assert!(lower.starts_with("get /a/b?q=1 http/1.1\r\n"), "{lower}");
    for wanted in [format!("host: 127.0.0.1:{port}\r\n"), "accept-encoding: identity\r\n".into(), "connection: close\r\n".into()] {
        assert!(lower.contains(&wanted), "{wanted} yok: {lower}");
    }
    assert!(lower.contains(&format!("x-api-key: {KEY}\r\n")));
    assert!(head.windows(8).any(|w| w == b"Bearer \xe9"));
}

#[test]
fn redirects_are_never_followed_and_the_key_does_not_leave() {
    let (other, other_rx) = fixed(OK);
    for status in [301, 302, 303, 307, 308] {
        let (port, _rx) = serve(move |_, s| {
            let _ = write!(s, "HTTP/1.1 {status} Yon\r\nLocation: http://127.0.0.1:{other}/x\r\nContent-Length: 0\r\n\r\n");
        });
        assert_eq!(get(&[], format!("http://127.0.0.1:{port}/models")), Err(HttpError::Status(status)));
    }
    nothing(&other_rx);
}

#[test]
fn error_statuses_broken_and_truncated_answers_are_errors_without_details() {
    for (reply, wanted) in [
        (&b"HTTP/1.1 404 Yok\r\nContent-Length: 0\r\n\r\n"[..], HttpError::Status(404)),
        (b"HTTP/1.1 500 X\r\nContent-Length: 3\r\n\r\nabc", HttpError::Status(500)),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\nyarim", HttpError::Protocol),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nab", HttpError::Protocol),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n", HttpError::Protocol),
        (b"bu http degil\r\n\r\n", HttpError::Protocol),
        (b"", HttpError::Protocol),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 1001\r\n\r\n", HttpError::TooBig),
    ] {
        let (port, _rx) = serve(move |_, s| {
            let _ = s.write_all(reply);
            if reply.windows(4).any(|w| w == b"1001") {
                let _ = s.write_all(&[b'x'; 1001]);
            }
        });
        let got = get(&[], format!("http://127.0.0.1:{port}/m?anahtar={KEY}"));
        assert_eq!(got, Err(wanted), "{}", String::from_utf8_lossy(reply));
        assert!(!format!("{got:?}").contains(KEY));
    }
}

#[test]
fn an_endless_body_stops_at_the_limit() {
    let (port, _rx) = serve(|_, s| {
        let _ = s.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n");
        while s.write_all(b"4\r\nabcd\r\n").is_ok() {}
    });
    let start = Instant::now();
    assert_eq!(get(&[], format!("http://127.0.0.1:{port}/")), Err(HttpError::TooBig));
    assert!(start.elapsed() < Duration::from_secs(5));
}

#[test]
fn the_timeout_is_the_total_time_not_per_read() {
    let (silent, _a) = serve(|_, _| std::thread::sleep(Duration::from_secs(3)));
    let (drip, _b) = serve(|_, s| {
        let _ = s.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n");
        for _ in 0..100 {
            if s.write_all(b"x").is_err() {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    });
    for port in [silent, drip] {
        let start = Instant::now();
        let r = HttpClient::new(env(&[])).get(&request(format!("http://127.0.0.1:{port}/"), 400, 1000));
        assert_eq!(r, Err(HttpError::Timeout));
        assert!(start.elapsed() < Duration::from_secs(2), "{:?}", start.elapsed());
    }
}

#[test]
fn unusable_addresses_send_nothing() {
    let (port, rx) = fixed(OK);
    let base = format!("127.0.0.1:{port}");
    for url in [
        format!("ftp://{base}/"),
        "file:///etc/hostname".into(),
        format!("{base}/semasiz"),
        format!("http://kul:{KEY}@{base}/"),
        format!("http://{base}/bos luk"),
        format!("http://{base}/\r\nX: 1"),
        "http://".into(),
        "".into(),
        "http://127.0.0.1:99999/".into(),
        "http://127.0.0.1:abc/".into(),
    ] {
        let r = get(&[], url.clone());
        assert!(r.is_err(), "{url:?}");
    }
    nothing(&rx);
    let closed = {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        l.local_addr().unwrap().port()
    };
    assert_eq!(get(&[], format!("http://127.0.0.1:{closed}/")), Err(HttpError::Connect));
}

#[test]
fn it_can_be_called_from_inside_an_async_runtime() {
    let (port, _rx) = fixed(OK);
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    let got = runtime.block_on(async { get(&[], format!("http://127.0.0.1:{port}/")) });
    assert_eq!(got.as_deref(), Ok(&b"merha"[..]));
}

#[test]
fn http_goes_through_the_environment_proxy_with_basic_auth_unless_bypassed() {
    let (proxy, proxy_rx) = fixed(OK);
    let (direct, direct_rx) = fixed(OK);
    let proxy_url = format!("http://kul%40x:pa%3Ass@127.0.0.1:{proxy}/");
    get(&[("http_proxy", &proxy_url)], "http://hedef.invalid:81/m?a=1".into()).unwrap();
    let head = text(&proxy_rx.recv().unwrap());
    assert!(head.starts_with("get http://hedef.invalid:81/m?a=1 http/1.1\r\n"), "{head}");
    assert!(head.contains("host: hedef.invalid:81\r\n"));
    // base64("kul@x:pa:ss")
    assert!(head.contains("proxy-authorization: basic a3vsqhg6cge6c3m="), "{head}");

    let url = format!("http://127.0.0.1:{direct}/");
    get(&[("http_proxy", &proxy_url), ("no_proxy", "127.0.0.1")], url.clone()).unwrap();
    assert!(!text(&direct_rx.recv().unwrap()).contains("proxy-authorization"));
    // https değişkeni ve all_proxy http hedefi etkilemez
    get(&[("https_proxy", &proxy_url), ("all_proxy", &proxy_url)], url.clone()).unwrap();
    direct_rx.recv().unwrap();
    // kullanılamayan proxy: doğrudan gidilmez
    assert_eq!(get(&[("http_proxy", "socks5://127.0.0.1:1")], url.clone()), Err(HttpError::Proxy));
    assert_eq!(get(&[("http_proxy", "http:/tek-egik")], url), Err(HttpError::Proxy));
    nothing(&direct_rx);
    nothing(&proxy_rx);
}

struct Pki {
    roots: RootCertStore,
    server: Arc<ServerConfig>,
}

fn pki(names: &[&str]) -> Pki {
    let ca_key = KeyPair::generate().unwrap();
    let mut ca = CertificateParams::new(Vec::<String>::new()).unwrap();
    ca.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    let ca_cert = ca.self_signed(&ca_key).unwrap();
    let issuer = Issuer::new(ca, ca_key);
    let key = KeyPair::generate().unwrap();
    let names: Vec<String> = names.iter().map(|n| n.to_string()).collect();
    let leaf = CertificateParams::new(names).unwrap().signed_by(&key, &issuer).unwrap();
    let mut roots = RootCertStore::empty();
    roots.add(ca_cert.der().clone()).unwrap();
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let server = ServerConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_no_client_auth()
        .with_single_cert(vec![leaf.der().clone()], PrivateKeyDer::try_from(key.serialize_der()).unwrap())
        .unwrap();
    Pki { roots, server: Arc::new(server) }
}

/// Tek loopback TLS sunucusu; el sıkışmadan sonra okunan istek başlıkları kanala yazılır.
fn tls_server(config: Arc<ServerConfig>) -> (u16, Receiver<Vec<u8>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
        runtime.block_on(async {
            let listener = tokio::net::TcpListener::from_std(listener).unwrap();
            let acceptor = tokio_rustls::TlsAcceptor::from(config);
            while let Ok(Ok((tcp, _))) = tokio::time::timeout(Duration::from_secs(10), listener.accept()).await {
                let Ok(mut tls) = acceptor.accept(tcp).await else { continue };
                let mut head = Vec::new();
                while !head.ends_with(b"\r\n\r\n") {
                    match tls.read_u8().await {
                        Ok(b) => head.push(b),
                        Err(_) => break,
                    }
                }
                if head.is_empty() {
                    continue;
                }
                let _ = tx.send(head);
                let _ = tls.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\ntls").await;
                let _ = tls.shutdown().await;
            }
        });
    });
    (port, rx)
}

#[test]
fn tls_verification_is_on_for_untrusted_roots_and_wrong_names() {
    let pki = pki(&["localhost"]);
    let (port, rx) = tls_server(pki.server.clone());
    let url = format!("https://localhost:{port}/models");
    // sistem kökleri bu kökü tanımaz
    assert_eq!(get(&[], url.clone()), Err(HttpError::Tls));
    // güvenilen kök ama sertifika adı eşleşmiyor
    let trusted = HttpClient::with_roots(env(&[]), pki.roots.clone());
    let wrong = request(format!("https://127.0.0.1:{port}/models"), 5000, 100);
    assert_eq!(trusted.get(&wrong), Err(HttpError::Tls));
    // boş kök deposu
    let empty = HttpClient::with_roots(env(&[]), RootCertStore::empty());
    assert!(empty.get(&request(url.clone(), 5000, 100)).is_err());
    nothing(&rx); // doğrulama düşünce anahtar HİÇ gönderilmedi
    assert_eq!(trusted.get(&request(url, 5000, 100)).as_deref(), Ok(&b"tls"[..]));
    assert!(text(&rx.recv().unwrap()).contains(KEY));
    // düz metin konuşan sunucuya https (istek beklemeden yanıt yazar)
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let plain = listener.local_addr().unwrap().port();
    let speaker = std::thread::spawn(move || {
        let (mut s, _) = listener.accept().unwrap();
        let _ = s.write_all(OK);
        let _ = s.shutdown(Shutdown::Write);
        s.set_read_timeout(Some(Duration::from_secs(3))).unwrap();
        let mut seen = Vec::new();
        let _ = s.read_to_end(&mut seen);
        assert!(!seen.windows(KEY.len()).any(|w| w == KEY.as_bytes()));
    });
    assert_eq!(trusted.get(&request(format!("https://localhost:{plain}/"), 2000, 100)), Err(HttpError::Tls));
    speaker.join().unwrap();
}

fn splice(client: &mut TcpStream, port: u16) {
    let mut upstream = TcpStream::connect(("127.0.0.1", port)).unwrap();
    client.write_all(b"HTTP/1.0 200 Connection established\r\nX: y\r\n\r\n").unwrap();
    let (mut c2, mut u2) = (client.try_clone().unwrap(), upstream.try_clone().unwrap());
    let up = std::thread::spawn(move || {
        let _ = std::io::copy(&mut c2, &mut u2);
        let _ = u2.shutdown(Shutdown::Write);
    });
    let _ = std::io::copy(&mut upstream, client);
    let _ = client.shutdown(Shutdown::Write);
    let _ = up.join();
}

#[test]
fn https_is_tunnelled_with_connect_and_proxy_auth_stays_outside_the_tunnel() {
    let pki = pki(&["hedef.invalid"]);
    let (target, target_rx) = tls_server(pki.server.clone());
    let (proxy, proxy_rx) = serve(move |_, s| splice(s, target));
    let proxy_url = format!("u:p@127.0.0.1:{proxy}");
    let client = HttpClient::with_roots(env(&[("https_proxy", &proxy_url)]), pki.roots.clone());
    let got = client.get(&request(format!("https://hedef.invalid:{target}/m"), 5000, 100));
    assert_eq!(got.as_deref(), Ok(&b"tls"[..]));
    let connect = text(&proxy_rx.recv().unwrap());
    assert!(connect.starts_with(&format!("connect hedef.invalid:{target} http/1.0\r\n")), "{connect}");
    assert!(connect.contains("proxy-authorization: basic dtpw\r\n") && !connect.contains(KEY));
    let inner = text(&target_rx.recv().unwrap());
    assert!(inner.starts_with("get /m http/1.1") && !inner.contains("proxy-authorization"), "{inner}");

    let (deny, deny_rx) = fixed(b"HTTP/1.1 407 Auth\r\n\r\n");
    let deny_url = format!("http://127.0.0.1:{deny}");
    let r = get(&[("HTTPS_PROXY", &deny_url)], "https://hedef.invalid/".into());
    assert_eq!(r, Err(HttpError::Proxy));
    assert!(!text(&deny_rx.recv().unwrap()).contains(KEY));
}

#[test]
fn the_real_model_io_runs_reads_and_fetches() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let io = RealModelIo::new(&t.paths(), t.env(&[]), Arc::new(FileDocs::new(&t.paths(), t.env(&[]))));
    let a = io.monotonic_secs();
    std::thread::sleep(Duration::from_millis(20));
    assert!(a > 0.0 && io.monotonic_secs() - a >= 0.015);
    assert!(io.wall_secs() > 1.7e9);
    assert_eq!(io.claude_models_doc(), None);
    t.write("state/claude_models.json", r#"{"models": ["m"]}"#, 0o600);
    assert_eq!(io.claude_models_doc(), Some(json!({"models": ["m"]})));
    let f = t.write("work/f", "abc", 0o600);
    assert_eq!(io.read_file(&f, 3).as_deref(), Some(&b"abc"[..]));
    assert_eq!(io.read_file(&f, 2), None);
    let run = |body: &str, ms: u64| {
        let bin = t.script("bin/agy", body);
        io.run_stdout(&RunRequest { argv: vec![bin], timeout: Duration::from_millis(ms), max_stdout: 100 })
    };
    // çıkış koduna bakılmaz; stderr atılır
    assert_eq!(run("echo m1; echo hata >&2; exit 9", 3000).as_deref(), Some(&b"m1\n"[..]));
    assert_eq!(run("sleep 30", 300), None);
    assert_eq!(run("yes", 3000), None);

    let (port, rx) = serve(|_, s| {
        let body = br#"{"data": [{"id": "model-a"}, {"id": "model-b"}]}"#;
        let _ = write!(s, "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n", body.len());
        let _ = s.write_all(body);
    });
    let sources = ModelSources::new(Arc::new(io));
    let settings = Settings::from_json(
        &json!({"ucli_services": [{"id": "yerel", "endpoint": format!("http://127.0.0.1:{port}/v1"), "env": "YEREL_KEY"}]})
            .to_string(),
    );
    assert_eq!(sources.service_models(&settings, "yerel", KEY), ["model-a", "model-b"]);
    assert!(text(&rx.recv().unwrap()).contains(KEY));
}
