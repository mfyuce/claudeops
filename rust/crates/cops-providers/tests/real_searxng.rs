//! G8 ikinci parça: yönetilen SearXNG'nin spawn yolu. Docker YOK (geçici dizinde sahte `docker` betiği; gerçek `PATH`e
//! düşülmez), ağ yalnız loopback test sunucuları. Python ile karar eşliği `parity_searxng`de.

#[path = "g8/support.rs"]
mod support;

use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::probe::{HomeProjects, SearchUrl};
use cops_providers::real::searxng::{self, ManagedSearch, Provision};
use cops_providers::real::{Env, RealDeps, RealProbe};
use cops_providers::{BuildArgs, BuildOutput, Cli, ModelCatalog, Providers, Settings};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use support::{spawn_guard, Tmp};

/// Yalnız sahte `bin`: gerçek docker erişilemez.
fn env(t: &Tmp) -> Env {
    Env::fixed([
        ("HOME", t.path("home")),
        ("PATH", t.path("bin")),
        ("USER", "deneme".to_string()),
    ])
}

fn manager(t: &Tmp, provision: Provision) -> ManagedSearch {
    ManagedSearch::new(
        &t.path("home"),
        &t.path("state"),
        env(t),
        DiagLog::new(t.path("work/diag.log")),
        provision,
    )
}

fn idle() -> Provision {
    Provision {
        argv: vec!["/bin/true".into()],
        cwd: "/".into(),
    }
}

fn events(t: &Tmp) -> Vec<String> {
    fs::read_to_string(t.path("work/diag.log"))
        .unwrap_or_default()
        .lines()
        .map(|l| {
            serde_json::from_str::<serde_json::Value>(l).unwrap()["event"]
                .as_str()
                .unwrap()
                .to_string()
        })
        .collect()
}

fn calls(t: &Tmp) -> Vec<String> {
    fs::read_to_string(t.path("work/docker.log"))
        .unwrap_or_default()
        .lines()
        .map(String::from)
        .collect()
}

fn fake_docker(t: &Tmp, body: &str) {
    t.script(
        "bin/docker",
        &format!("echo \"$@\" >> {}\n{body}", t.path("work/docker.log")),
    );
}

fn inspect_json(running: bool) -> String {
    format!(
        r#"[{{"Config": {{"Labels": {{"claudeops.managed": "searxng"}}}}, "State": {{"Running": {running}, "Status": "x"}}, "HostConfig": {{"PortBindings": {{"8080/tcp": [{{"HostPort": "8890"}}]}}}}}}]"#
    )
}

fn wait_for(mut done: impl FnMut() -> bool) {
    let start = Instant::now();
    while !done() {
        assert!(start.elapsed() < Duration::from_secs(5), "beklenen olmadı");
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn the_container_name_is_per_user_and_per_state_directory() {
    let default = searxng::container_name("Ali Veli!", "/h", "/h/.claude/claudeops", "/");
    assert_eq!(default, "claudeops-searxng-ali-veli");
    let other = searxng::container_name("Ali Veli!", "/h", "/tmp/deneme", "/");
    assert!(
        other.starts_with("claudeops-searxng-ali-veli-") && other.len() == default.len() + 9,
        "{other}"
    );
    assert!(
        searxng::container_name("---", "/h", "/h/.claude/claudeops", "/").len()
            > "claudeops-searxng-".len()
    );
    assert_eq!(
        searxng::owner(&Env::fixed([("LOGNAME", ""), ("USER", "u2")])),
        "u2"
    );
    assert!(!searxng::owner(&Env::fixed(Vec::<(String, String)>::new())).is_empty());
}

/// Tek istekli loopback sunucusu: yanıtı yazar, istek satırını saklar.
fn serve(reply: &'static [u8]) -> (u16, Arc<Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = seen.clone();
    listener.set_nonblocking(true).unwrap();
    std::thread::spawn(move || {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(5) {
            let Ok((mut conn, _)) = listener.accept() else {
                std::thread::sleep(Duration::from_millis(5));
                continue;
            };
            conn.set_nonblocking(false).unwrap();
            conn.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let mut buf = [0u8; 2048];
            let n = conn.read(&mut buf).unwrap_or(0);
            sink.lock()
                .unwrap()
                .push(String::from_utf8_lossy(&buf[..n]).into_owned());
            let _ = conn.write_all(reply);
            return;
        }
    });
    (port, seen)
}

#[test]
fn health_is_exactly_200_on_loopback_without_following_redirects() {
    let limit = Duration::from_millis(500);
    let (port, seen) = serve(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK");
    assert!(searxng::healthy(port, limit));
    assert!(seen.lock().unwrap()[0].starts_with("GET /healthz HTTP/1.1\r\n"));
    let (target, followed) = serve(b"HTTP/1.1 200 OK\r\n\r\n");
    let reply = format!(
        "HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{target}/x\r\nContent-Length: 0\r\n\r\n"
    );
    let (port, _) = serve(Box::leak(reply.into_boxed_str()).as_bytes());
    assert!(!searxng::healthy(port, limit));
    assert!(followed.lock().unwrap().is_empty());
    for reply in [
        &b"SSH-2.0-OpenSSH\r\n"[..],
        b"HTTP/1.1 500 No\r\n\r\n",
        b"HTTP/1.1 204 No Content\r\n\r\n",
        b"",
        b"\0\0\r\n",
    ] {
        let (port, _) = serve(reply);
        assert!(!searxng::healthy(port, limit), "{reply:?}");
    }
    // yanıt vermeyen dinleyici TOPLAM süre içinde bırakılır
    let silent = TcpListener::bind("127.0.0.1:0").unwrap();
    let start = Instant::now();
    assert!(!searxng::healthy(
        silent.local_addr().unwrap().port(),
        Duration::from_millis(200)
    ));
    assert!(start.elapsed() < Duration::from_secs(2));
}

#[test]
fn the_spawn_path_never_pulls_or_creates_and_provisions_out_of_process_once() {
    let t = Tmp::new();
    let _g = spawn_guard();
    fake_docker(&t, "echo 'Error: No such container' >&2; exit 1");
    let marker = t.path("work/prov.out");
    let script = t.script(
        "bin/prov",
        &format!("{{ pwd; echo \"$@\"; echo \"$HOME\"; /bin/cat /proc/$$/stat; }} > {marker}.tmp; /bin/mv {marker}.tmp {marker}; echo gunluk"),
    );
    let provision = Provision {
        argv: vec![script, "searxng".into(), "provision".into()],
        cwd: t.path("work"),
    };
    let m = manager(&t, provision);
    assert_eq!(m.search_url("s1", false), None);
    assert_eq!(m.search_url("s2", false), None);
    wait_for(|| fs::metadata(&marker).is_ok());
    let out = fs::read_to_string(&marker).unwrap();
    let lines: Vec<&str> = out.lines().collect();
    assert_eq!(
        lines[..3],
        [
            t.path("work"),
            "searxng provision".to_string(),
            t.path("home")
        ]
    );
    // yeni oturum: süreç kendi oturumunun lideri (`start_new_session`)
    let fields: Vec<&str> = lines[3].split_whitespace().collect();
    assert_eq!(fields[0], fields[5], "{}", lines[3]);
    wait_for(|| {
        fs::read_to_string(t.path("state/searxng/provision.log")).is_ok_and(|s| s == "gunluk\n")
    });
    let name = m.container().to_string();
    assert_eq!(calls(&t), vec![format!("container inspect {name}"); 2]);
    assert_eq!(events(&t), ["searxng_provision_started"]);
}

#[test]
fn a_held_provision_lock_prevents_a_second_process() {
    let t = Tmp::new();
    let _g = spawn_guard();
    fake_docker(&t, "echo 'No such object' >&2; exit 1");
    t.write("state/searxng/.lock", "", 0o600);
    let held = fs::File::options()
        .write(true)
        .open(t.path("state/searxng/.lock"))
        .unwrap();
    held.lock().unwrap();
    assert_eq!(manager(&t, idle()).search_url("s", false), None);
    assert!(events(&t).is_empty());
    assert!(fs::metadata(t.path("state/searxng/state.json")).is_err());
    drop(held);
    assert_eq!(manager(&t, idle()).search_url("s", false), None);
    assert_eq!(events(&t), ["searxng_provision_started"]);
}

#[test]
fn a_provision_command_that_cannot_start_is_logged_and_never_reaches_the_caller() {
    let t = Tmp::new();
    let _g = spawn_guard();
    fake_docker(&t, "echo 'No such object' >&2; exit 1");
    let broken = Provision {
        argv: vec![t.path("yok")],
        cwd: "/".into(),
    };
    assert_eq!(manager(&t, broken).search_url("s", false), None);
    assert_eq!(events(&t), ["searxng_provision_spawn_failed"]);
}

#[test]
fn a_hanging_docker_is_killed_marked_down_and_not_asked_again() {
    let t = Tmp::new();
    let _g = spawn_guard();
    fake_docker(&t, "exec /bin/sleep 60");
    let m = manager(&t, idle());
    let start = Instant::now();
    assert_eq!(m.search_url("s", false), None);
    assert!(
        start.elapsed() >= searxng::INSPECT_TIMEOUT
            && start.elapsed() < searxng::INSPECT_TIMEOUT * 2
    );
    let again = Instant::now();
    assert_eq!(m.search_url("s", false), None);
    assert!(again.elapsed() < Duration::from_secs(1));
    assert_eq!(calls(&t).len(), 1);
    assert_eq!(events(&t), ["searxng_unavailable"]);
}

#[test]
fn the_state_write_waits_for_the_lock_python_takes_and_keeps_other_keys() {
    let t = Tmp::new();
    let _g = spawn_guard();
    t.write("work/out", inspect_json(true), 0o600);
    fake_docker(&t, &format!("/bin/cat {}", t.path("work/out")));
    t.write(
        "state/searxng/state.json",
        r#"{"image_id": "i", "port": 1}"#,
        0o600,
    );
    t.write("state/searxng/state.json.lock", "", 0o600);
    let held = fs::File::options()
        .write(true)
        .open(t.path("state/searxng/state.json.lock"))
        .unwrap();
    held.lock().unwrap();
    let m = Arc::new(
        manager(&t, idle())
            .with_health(|port| port == 8890)
            .with_ready_wait(Duration::ZERO),
    );
    let worker = {
        let m = m.clone();
        std::thread::spawn(move || m.search_url("s", false))
    };
    std::thread::sleep(Duration::from_millis(300));
    assert!(!worker.is_finished(), "kilit tutulurken yazıldı");
    // kilit sahibinin eklediği anahtar korunur
    t.write(
        "state/searxng/state.json",
        r#"{"image_id": "i", "port": 1, "provisioned_at": 2.0}"#,
        0o600,
    );
    drop(held);
    assert_eq!(
        worker.join().unwrap().as_deref(),
        Some("http://127.0.0.1:8890/search")
    );
    let state: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(t.path("state/searxng/state.json")).unwrap())
            .unwrap();
    assert_eq!(
        state,
        serde_json::json!({"image_id": "i", "port": 8890, "provisioned_at": 2.0})
    );
}

/// `WebArgsTests`: yönetilen adres yalnız boş adres + bayrağı tanıyan ikilide, oturum adıyla sorulur.
#[test]
fn a_build_asks_for_the_managed_address_only_when_it_should_use_it() {
    struct Recording(Mutex<Vec<(String, bool)>>);
    impl SearchUrl for Recording {
        fn search_url(&self, session: &str, preview: bool) -> Option<String> {
            self.0.lock().unwrap().push((session.to_string(), preview));
            Some("http://127.0.0.1:8891/search".into())
        }
    }
    let run = |help: &str, settings: &str| {
        let t = Tmp::new();
        let _g = spawn_guard();
        t.script("bin/ucli", &format!("echo '{help}'"));
        let search = Arc::new(Recording(Mutex::new(Vec::new())));
        let env = t.env(&[]);
        let deps = RealDeps {
            docs: support::file_docs(&t.paths()),
            projects: Arc::new(HomeProjects::new(&t.path("home"))),
            cost: Arc::new(support::OpenGate),
            search: search.clone(),
            help: Arc::default(),
            panel_port: None,
        };
        let probe = RealProbe::new(t.paths(), env, deps);
        let settings = Settings::from_json(settings);
        let (catalog, paths) = (ModelCatalog::default(), t.paths());
        let providers = Providers {
            settings: &settings,
            catalog: &catalog,
            paths: &paths,
            probe: &probe,
        };
        let args = BuildArgs {
            cwd: &t.path("work"),
            model: "glm-5.3",
            session_name: "vc",
            ..Default::default()
        };
        let command = providers
            .build_inner_command(Cli::Ucli, &args, &mut BuildOutput::default())
            .unwrap();
        let asked = search.0.lock().unwrap().clone();
        (command, asked)
    };
    let both = "--search-url <U> --search-flavor <F> --allow-fetch";
    let (command, asked) = run(both, "{}");
    assert!(
        command.contains("--search-url http://127.0.0.1:8891/search --search-flavor searxng"),
        "{command}"
    );
    assert_eq!(asked, [("vc".to_string(), false)]);
    assert!(run("--allow-fetch", "{}").1.is_empty());
    assert!(run(
        both,
        r#"{"ucli_web": {"search_url": "http://127.0.0.1:8888/search"}}"#
    )
    .1
    .is_empty());
    assert!(run(both, r#"{"ucli_web": {"search_url": "ftp://x/y"}}"#)
        .1
        .is_empty());
}
