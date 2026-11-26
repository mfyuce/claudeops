//! H2/R1-3: Python ve Rust AYNI kilit dosyalarını kullanır (iki yazarlı e2e). Kilit sözleşmesi:
//! - `file_lock(p)` <-> `FileLock::acquire(p)`: `<normpath(abspath(p))>.lock` üzerinde `flock(LOCK_EX)`.
//! - roster.tsv + models.tsv: `<dizin>/roster.lock` (`roster_lock` <-> `Roster::lock` / `FileLock::roster`).
//! - instances.json: `instances.json.lock` (`instances._locked` <-> `FileLock::blocking`).
use cops_state::fsutil::FileLock;
use cops_state::roster::{Roster, Tsv};
use cops_state::Backend;
use std::io::{BufRead, BufReader, Write};
use std::time::{Duration, Instant};

mod common;
use common::Env;

/// Python kilidi tutar, "hazir" yazar, stdin kapanana dek bekler.
fn python_holds(e: &Env, code: &str) -> std::process::Child {
    let mut child = e.command("files", code).spawn().unwrap();
    let mut line = String::new();
    BufReader::new(child.stdout.as_mut().unwrap())
        .read_line(&mut line)
        .unwrap();
    assert_eq!(line.trim(), "hazir");
    child
}

fn release(mut child: std::process::Child) {
    drop(child.stdin.take());
    let o = child.wait_with_output().unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
}

#[test]
fn python_lock_blocks_rust_and_back() {
    let e = Env::new();
    let target = e.state.join("settings.json");
    // 1) Python file_lock tutarken Rust alamaz (farklı yazımla bile), bırakınca alır
    let child = python_holds(
        &e,
        "from claudeops.atomic_json import file_lock\nfrom claudeops.paths import CLAUDEOPS_DIR as D\n\
         with file_lock(os.path.join(D, 'alt', '..', 'settings.json')):\n    print('hazir', flush=True); sys.stdin.read()",
    );
    let t0 = Instant::now();
    let err = FileLock::acquire_within(&target, Duration::from_millis(300)).unwrap_err();
    assert_eq!(err.kind(), std::io::ErrorKind::TimedOut);
    assert!(t0.elapsed() >= Duration::from_millis(300));
    release(child);
    drop(FileLock::acquire_within(&target, Duration::from_millis(2000)).unwrap());

    // 2) Rust tutarken Python'un kilidi alamadığı aynı .lock dosyasında görülür
    let held = FileLock::acquire(&target).unwrap();
    let out = e.py(
        "files",
        "import fcntl\nfrom claudeops.paths import CLAUDEOPS_DIR as D\nfd = os.open(os.path.join(D, 'settings.json.lock'), os.O_RDWR)\n\
         try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('aldi')\nexcept BlockingIOError:\n    print('mesgul')",
    );
    assert_eq!(out.trim(), "mesgul");
    drop(held);
}

#[test]
fn roster_and_instances_locks_shared() {
    let e = Env::new();
    let docs = e.docs(Backend::Files);
    // Rust roster kilidini tutarken Python _append_tsv_line BEKLER; bırakınca ikisinin satırı da kalır
    let guard = Roster::new(&docs).lock().unwrap();
    let mut child = e
        .command(
            "files",
            "import time\nfrom claudeops.commands import web as w\nprint('basla', flush=True)\nt = time.monotonic()\n\
             w._append_tsv_line(w.ROSTER_TSV, ['py', '/p', 'm'])\nprint(round(time.monotonic() - t, 2), flush=True)",
        )
        .spawn()
        .unwrap();
    let mut out = BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    out.read_line(&mut line).unwrap();
    assert_eq!(line.trim(), "basla");
    std::thread::sleep(Duration::from_millis(600));
    guard.append(Tsv::Roster, &["rs", "/r", "m"]).unwrap();
    drop(guard);
    line.clear();
    out.read_line(&mut line).unwrap();
    let waited: f64 = line.trim().parse().unwrap();
    assert!(waited >= 0.4, "Python beklemedi: {waited}");
    assert!(child.wait().unwrap().success());
    assert_eq!(e.read("roster.tsv"), "rs\t/r\tm\npy\t/p\tm\n");

    // instances: Python _locked tutarken Rust mutate bekler
    let child = python_holds(
        &e,
        "from claudeops import instances as i\nwith i._locked():\n    print('hazir', flush=True); sys.stdin.read()",
    );
    let t = std::thread::spawn({
        let state = e.state.clone();
        move || {
            let t0 = Instant::now();
            let l = FileLock::blocking(&state.join("instances.json.lock")).unwrap();
            drop(l);
            t0.elapsed()
        }
    });
    std::thread::sleep(Duration::from_millis(500));
    let mut c = child;
    c.stdin.as_mut().unwrap().write_all(b"").unwrap();
    release(c);
    assert!(t.join().unwrap() >= Duration::from_millis(400));
}
