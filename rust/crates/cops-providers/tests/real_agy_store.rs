//! G8: gerçek `AgySidStore` (`flock` + atomik yazım). Süreçler arası eşzamanlılık: hem Rust alt süreçleri hem Python
//! `_remember_agy_sid` aynı geçici belgeye yazar; hiçbir kayıt kaybolmamalı.

#[path = "g8/support.rs"]
mod support;

use cops_providers::agy_resume::remember_agy_sid;
use cops_providers::pyjson::Py;
use cops_providers::real::docs::{DocAgySidStore, DocStore, FileDocs};
use cops_providers::real::lock::FileLock;
use cops_providers::{AgySidStore, Paths};
use std::fs;
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};
use support::{mode, Tmp};

const WORKERS: usize = 4;
const WRITES: usize = 40;

fn store(paths: &Paths, env: cops_providers::real::Env) -> DocAgySidStore {
    DocAgySidStore::new(paths, Arc::new(FileDocs::new(paths, env)))
}

/// Alt süreç kipi: `COPS_G8_WORKER=<kök>|<ad>` verilmediyse hiçbir şey yapmaz.
#[test]
fn worker_process() {
    let Ok(spec) = std::env::var("COPS_G8_WORKER") else { return };
    let (root, id) = spec.split_once('|').unwrap();
    let paths = Paths { claudeops_dir: format!("{root}/state"), home: format!("{root}/home"), repo_dir: root.into() };
    let store = store(&paths, cops_providers::real::Env::fixed([("CLAUDEOPS_STORE_BACKEND", "files")]));
    for i in 0..WRITES {
        remember_agy_sid(&store, &format!("{id}-{i}"), &format!("sid-{id}-{i}"), false).unwrap();
    }
}

fn wait_all(children: Vec<Child>) {
    let deadline = Instant::now() + Duration::from_secs(120);
    for mut child in children {
        loop {
            if let Some(status) = child.try_wait().unwrap() {
                assert!(status.success(), "yazar süreç düştü");
                break;
            }
            if Instant::now() > deadline {
                // yalnız bu testin açtığı süreç
                let _ = child.kill();
                let _ = child.wait();
                panic!("yazar süreç zaman aşımı");
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

#[test]
fn rust_and_python_writers_across_processes_lose_nothing() {
    let t = Tmp::new();
    let py = format!(
        "import sys\nfrom claudeops.providers import agy_provider as a\nimport claudeops.paths as p\n\
         assert p.CLAUDEOPS_DIR == {state:?} and a.AGY_SIDS_JSON.startswith({state:?})\n\
         for i in range({WRITES}):\n    a._remember_agy_sid(f'{{sys.argv[1]}}-{{i}}', f'sid-{{sys.argv[1]}}-{{i}}')\n",
        state = t.path("state"),
    );
    let repo_py = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../py");
    let mut children = Vec::new();
    for w in 0..WORKERS {
        children.push(
            Command::new(std::env::current_exe().unwrap())
                .args(["--exact", "worker_process", "--test-threads", "1"])
                .env_clear()
                .env("COPS_G8_WORKER", format!("{}|rs{w}", t.root))
                .stdout(Stdio::null())
                .spawn()
                .unwrap(),
        );
        children.push(
            Command::new("/usr/bin/python3")
                .args(["-s", "-B", "-W", "ignore", "-c", &py, &format!("py{w}")])
                .env_clear()
                .env("HOME", t.path("home"))
                .env("CLAUDEOPS_DIR", t.path("state"))
                .env("CLAUDEOPS_EXTENSIONS", "0")
                .env("CLAUDEOPS_STORE_BACKEND", "files")
                .env("PYTHONPATH", repo_py)
                .current_dir(&t.root)
                .spawn()
                .unwrap(),
        );
    }
    wait_all(children);
    let text = fs::read_to_string(t.path("state/agy_sids.json")).unwrap();
    let Some(Py::Object(entries)) = Py::parse(&text) else { panic!("belge bozuk: {text}") };
    assert_eq!(entries.len(), 2 * WORKERS * WRITES);
    for (name, sid) in &entries {
        assert_eq!(sid.as_str(), Some(format!("sid-{name}").as_str()));
    }
}

#[test]
fn the_lock_is_the_one_python_takes_and_waiting_is_bounded() {
    let t = Tmp::new();
    let paths = t.paths();
    let holder = "import fcntl, os, sys, time\nfd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n\
                  fcntl.flock(fd, fcntl.LOCK_EX)\nprint('tutuldu', flush=True)\nsys.stdin.readline()\n";
    let mut child = Command::new("/usr/bin/python3")
        .args(["-I", "-c", holder, &format!("{}.lock", paths.agy_sids_json())])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    std::io::BufRead::read_line(&mut std::io::BufReader::new(child.stdout.take().unwrap()), &mut line).unwrap();
    assert_eq!(line.trim(), "tutuldu");
    let s = store(&paths, t.env(&[])).with_lock_timeout(Duration::from_millis(200));
    let start = Instant::now();
    let r = remember_agy_sid(&s, "a", "1", false);
    assert!(r.unwrap_err().contains("kilidi alınamadı"));
    assert!(start.elapsed() >= Duration::from_millis(200) && start.elapsed() < Duration::from_secs(5));
    assert!(s.load().is_none(), "kilitsiz yazıldı");
    drop(child.stdin.take()); // stdin kapanınca tutan süreç kendiliğinden çıkar
    child.wait().unwrap();
    assert_eq!(remember_agy_sid(&s, "a", "1", false), Ok(true));
    assert_eq!(mode(&format!("{}.lock", paths.agy_sids_json())), 0o600);
}

#[test]
fn a_symlinked_lock_file_is_refused_and_nothing_is_written() {
    let t = Tmp::new();
    let paths = t.paths();
    let victim = t.write("work/kurban", "x", 0o600);
    std::os::unix::fs::symlink(&victim, format!("{}.lock", paths.agy_sids_json())).unwrap();
    assert!(remember_agy_sid(&store(&paths, t.env(&[])), "a", "1", false).is_err());
    assert!(!std::path::Path::new(&paths.agy_sids_json()).exists());
    assert_eq!(fs::read_to_string(victim).unwrap(), "x");
    assert!(FileLock::acquire(&t.path("work/kurban2"), "/", Duration::from_millis(10)).is_ok());
}

#[test]
fn db_backend_documents_are_neither_read_from_nor_written_to_the_mirror() {
    let t = Tmp::new();
    let paths = t.paths();
    t.write("state/agy_sids.json", r#"{"a": "bayat"}"#, 0o600);
    for (settings, env, db) in [
        (r#"{"store_backend": " DB "}"#, vec![], true),
        (r#"{"store_backend": "db"}"#, vec![("CLAUDEOPS_STORE_BACKEND", "files")], false),
        (r#"{"store_backend": "files"}"#, vec![("CLAUDEOPS_STORE_BACKEND", "db")], true),
        (r#"{"store_backend": "dual"}"#, vec![], false),
        ("bozuk", vec![("CLAUDEOPS_STORE_BACKEND", "sacma")], false),
    ] {
        t.write("state/settings.json", settings, 0o600);
        let docs = FileDocs::new(&paths, t.env(&env));
        let read = docs.read("agy_sids", &paths.agy_sids_json());
        assert_eq!(read.is_none(), db, "{settings} {env:?}");
        // db hazır olmayan belge her kipte dosyadan okunur
        assert!(docs.read("baska", &paths.agy_sids_json()).is_some());
        if db {
            let s = store(&paths, t.env(&env));
            assert!(remember_agy_sid(&s, "b", "2", false).unwrap_err().contains("db"));
            assert_eq!(fs::read_to_string(paths.agy_sids_json()).unwrap(), r#"{"a": "bayat"}"#);
        }
    }
}
