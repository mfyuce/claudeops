//! G9 birim testleri: hayalet temizliği (Python `ReclaimTest` karşılıkları), bekçi sahte saatle, `GnomeTerminal` sahte
//! betikle, `copy2`, `repo_dir_of`, `SystemClock`. Gerçek gnome-terminal/tmux/ağ YOK; her şey geçici dizinde. Betikler
//! alt süreçle yazılır (`write_exe`: paralel `fork` yazım tanıtıcısını taşırsa `ETXTBSY`); her bekleme zaman aşımlı.

use cops_providers::real::launch::{repo_dir_of, GnomeTerminal, SystemClock};
use cops_providers::real::routing_sync::{copy2, sync_global_files};
use cops_providers::real::Env;
use cops_providers::spawn_exec::{
    fallback_watchdog, reclaim_ghost_session, Clock, DiagSink, LaunchError, Launcher, SpawnTmux,
    Terminal, FALLBACK_ATTEMPT_WAIT_SECONDS, FALLBACK_POLL_SECONDS, FALLBACK_RETRY_COUNT,
};
use cops_providers::{Diag, Paths, Settings};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::fs::{self, FileTimes};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime};
use tempfile::TempDir;

#[path = "g8/support.rs"]
mod support;

// ------------------------------------------------------------------------------------------------------- sahteler

#[derive(Default)]
struct Log {
    calls: Mutex<Vec<String>>,
    diags: Mutex<Vec<Diag>>,
}

struct FakeTmux {
    log: Arc<Log>,
    available: bool,
    ghost: bool,
    capture: Option<String>,
    has: Mutex<VecDeque<bool>>,
    has_default: bool,
    direct_ok: bool,
}

impl FakeTmux {
    fn new(log: &Arc<Log>) -> FakeTmux {
        FakeTmux {
            log: log.clone(),
            available: true,
            ghost: true,
            capture: Some("Out of credits\n$ ".into()),
            has: Mutex::new(VecDeque::new()),
            has_default: false,
            direct_ok: true,
        }
    }
    fn call(&self, s: String) {
        self.log.calls.lock().unwrap().push(s);
    }
}

impl SpawnTmux for FakeTmux {
    fn available(&self) -> bool {
        self.available
    }
    fn new_session_fragment(&self, name: &str, _cwd: &str, _inner: &str) -> Result<String, String> {
        Ok(format!("frag {name}"))
    }
    fn attach_fragment(&self, name: &str) -> Result<String, String> {
        Ok(format!("attach {name}"))
    }
    fn spawn_direct(
        &self,
        name: &str,
        _cwd: &str,
        _inner: &str,
        _env: &[(String, String)],
    ) -> bool {
        self.call(format!("direct {name}"));
        self.direct_ok
    }
    fn has_session(&self, name: &str) -> bool {
        self.call(format!("has {name}"));
        self.has
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or(self.has_default)
    }
    fn ghost_session(&self, name: &str) -> bool {
        self.call(format!("ghost {name}"));
        self.ghost
    }
    fn capture(&self, name: &str, lines: u32) -> Option<String> {
        self.call(format!("capture {name} {lines}"));
        self.capture.clone()
    }
    fn kill_session(&self, name: &str) {
        self.call(format!("kill {name}"));
    }
}

struct FakeTerm {
    log: Arc<Log>,
    results: Mutex<VecDeque<Result<bool, LaunchError>>>,
}

impl Terminal for FakeTerm {
    fn available(&self) -> bool {
        true
    }
    fn path_exists(&self, _path: &str) -> bool {
        false
    }
    fn launch(&self, argv: &[String], _env: &[(String, String)]) -> Result<bool, LaunchError> {
        self.log
            .calls
            .lock()
            .unwrap()
            .push(format!("launch {}", argv[2]));
        self.results.lock().unwrap().pop_front().unwrap_or(Ok(true))
    }
}

/// Sahte saat: `sleep` yalnız sayacı ilerletir (gerçek bekleme yok).
struct FakeClock {
    t: Mutex<f64>,
    sleeps: Mutex<Vec<f64>>,
}

impl Clock for FakeClock {
    fn monotonic(&self) -> f64 {
        *self.t.lock().unwrap()
    }
    fn sleep(&self, secs: f64) {
        self.sleeps.lock().unwrap().push(secs);
        *self.t.lock().unwrap() += secs;
    }
}

struct Sink(Arc<Log>);

impl DiagSink for Sink {
    fn log(&self, diag: &Diag) {
        self.0.diags.lock().unwrap().push(diag.clone());
    }
}

struct Rig {
    log: Arc<Log>,
    clock: Arc<FakeClock>,
    launcher: Launcher,
}

fn rig(tmux: impl FnOnce(&mut FakeTmux), launches: Vec<Result<bool, LaunchError>>) -> Rig {
    let log = Arc::new(Log::default());
    let mut t = FakeTmux::new(&log);
    tmux(&mut t);
    let clock = Arc::new(FakeClock {
        t: Mutex::new(1000.0),
        sleeps: Mutex::new(Vec::new()),
    });
    let launcher = Launcher {
        tmux: Arc::new(t),
        terminal: Arc::new(FakeTerm {
            log: log.clone(),
            results: Mutex::new(launches.into()),
        }),
        clock: clock.clone(),
        diag: Arc::new(Sink(log.clone())),
        parent_env: vec![("HOME".into(), "/h".into())],
    };
    Rig {
        log,
        clock,
        launcher,
    }
}

impl Rig {
    fn calls(&self) -> Vec<String> {
        self.log.calls.lock().unwrap().clone()
    }
    fn events(&self) -> Vec<(&'static str, Vec<(&'static str, Value)>)> {
        self.log
            .diags
            .lock()
            .unwrap()
            .iter()
            .map(|d| (d.event, d.fields.clone()))
            .collect()
    }
}

// ------------------------------------------------------------------------------------------- ReclaimTest karşılıkları

/// `ReclaimTest.test_ghost_killed_and_tail_logged`: ekran metni günlükte YOK, yalnız sayılar.
#[test]
fn ghost_is_killed_and_only_screen_counts_are_logged() {
    let r = rig(|_| {}, vec![]);
    reclaim_ghost_session(&r.launcher, "p", "claude");
    assert_eq!(r.calls(), ["ghost p", "capture p 40", "kill p"]);
    let ev = r.events();
    assert_eq!(ev.len(), 1);
    assert_eq!(ev[0].0, "spawn_ghost_reclaimed");
    assert_eq!(
        ev[0].1,
        vec![
            ("name", json!("p")),
            ("cli", json!("claude")),
            ("screen_lines", json!(2)),
            ("screen_chars", json!(17))
        ]
    );
}

/// `ReclaimTest.test_shell_provider_untouched`
#[test]
fn shell_provider_is_untouched() {
    let r = rig(|_| {}, vec![]);
    reclaim_ghost_session(&r.launcher, "p", "shell");
    assert!(r.calls().is_empty());
    assert!(r.events().is_empty());
}

/// `ReclaimTest.test_not_ghost_untouched` (+ tmux yokken hayalet sorulmaz).
#[test]
fn non_ghost_and_missing_tmux_are_untouched() {
    let r = rig(|t| t.ghost = false, vec![]);
    reclaim_ghost_session(&r.launcher, "p", "claude");
    assert_eq!(r.calls(), ["ghost p"]);
    assert!(r.events().is_empty());
    let r = rig(|t| t.available = false, vec![]);
    reclaim_ghost_session(&r.launcher, "p", "claude");
    assert!(r.calls().is_empty());
}

/// `ReclaimTest.test_error_never_raises`: Rust'ta tmux sınırı hata YÜKSELTEMEZ (trait dönüşleri `bool`/`Option`); Python'un
/// `spawn_ghost_reclaim_error` dalının karşılığı yok. Burada okunamayan ekran (None) ve ANSI'li, uzun ekranla panik yok.
#[test]
fn reclaim_never_panics_and_never_logs_the_screen() {
    let r = rig(|t| t.capture = None, vec![]);
    reclaim_ghost_session(&r.launcher, "p", "agy");
    assert_eq!(
        r.events()[0].1[2..],
        [("screen_lines", json!(0)), ("screen_chars", json!(0))]
    );
    let screen = format!("\u{1b}[31m{}\u{1b}[0m\n\n   \nson\n", "ğ".repeat(2000));
    let r = rig(|t| t.capture = Some(screen), vec![]);
    reclaim_ghost_session(&r.launcher, "p", "agy");
    // renk kodları ve boş satırlar sayılmaz
    assert_eq!(
        r.events()[0].1[2..],
        [("screen_lines", json!(2)), ("screen_chars", json!(2004))]
    );
    let logged = format!("{:?}", r.events());
    assert!(!logged.contains('ğ') && !logged.contains("son"), "{logged}");
}

// ------------------------------------------------------------------------------------------------- bekçi (sahte saat)

fn watch(r: &Rig) {
    fallback_watchdog(
        &r.launcher,
        "s",
        "/w",
        "inner",
        &[("DISPLAY".into(), ":1".into())],
        "cmd",
    );
}

#[test]
fn watchdog_returns_at_once_when_the_session_exists() {
    let r = rig(|t| t.has_default = true, vec![]);
    watch(&r);
    assert_eq!(r.calls(), ["has s"]);
    assert!(r.events().is_empty());
    assert!(r.clock.sleeps.lock().unwrap().is_empty());
}

#[test]
fn watchdog_retries_then_falls_back_to_headless_tmux() {
    let r = rig(|_| {}, vec![]);
    watch(&r);
    let polls = (FALLBACK_ATTEMPT_WAIT_SECONDS / FALLBACK_POLL_SECONDS) as usize;
    let attempts = FALLBACK_RETRY_COUNT as usize + 1;
    let sleeps = r.clock.sleeps.lock().unwrap().clone();
    assert_eq!(sleeps.len(), polls * attempts);
    assert!(sleeps.iter().all(|s| *s == FALLBACK_POLL_SECONDS));
    assert_eq!(
        *r.clock.t.lock().unwrap(),
        1000.0 + FALLBACK_ATTEMPT_WAIT_SECONDS * attempts as f64
    );
    let calls = r.calls();
    assert_eq!(
        calls.iter().filter(|c| c.starts_with("launch")).count(),
        FALLBACK_RETRY_COUNT as usize
    );
    assert_eq!(
        calls.iter().filter(|c| *c == "has s").count(),
        polls * attempts + 1
    );
    assert_eq!(calls.last().unwrap(), "direct s");
    let names: Vec<&str> = r.events().iter().map(|e| e.0).collect();
    assert_eq!(names, ["spawn_retry", "spawn_retry", "spawn_fallback_used"]);
    assert_eq!(r.events()[2].1[2], ("ok", json!(true)));
}

#[test]
fn watchdog_logs_success_on_a_later_attempt() {
    let polls = (FALLBACK_ATTEMPT_WAIT_SECONDS / FALLBACK_POLL_SECONDS) as usize;
    let mut seq = vec![false; polls];
    seq.push(true);
    let r = rig(|t| *t.has.get_mut().unwrap() = seq.into(), vec![]);
    watch(&r);
    let ev = r.events();
    assert_eq!(
        ev.iter().map(|e| e.0).collect::<Vec<_>>(),
        ["spawn_retry", "spawn_retry_succeeded"]
    );
    assert_eq!(ev[1].1[2], ("attempt", json!(1)));
    assert!(!r.calls().iter().any(|c| c.starts_with("direct")));
}

#[test]
fn watchdog_failed_relaunch_is_logged_and_a_value_error_ends_it() {
    let r = rig(|t| t.direct_ok = false, vec![Ok(false)]);
    watch(&r);
    let names: Vec<&str> = r.events().iter().map(|e| e.0).collect();
    assert_eq!(
        names,
        [
            "spawn_retry",
            "spawn_retry_launch_failed",
            "spawn_retry",
            "spawn_fallback_used"
        ]
    );
    assert_eq!(r.events()[3].1[2], ("ok", json!(false)));
    // `ValueError` bekçiyi bitirir, penceresiz yedek açılmaz; günlüğe hata metni DEĞİL sınıf adı girer.
    let r = rig(
        |_| {},
        vec![Err(LaunchError::Value("API_KEY=sk-cok-gizli".into()))],
    );
    watch(&r);
    let ev = r.events();
    assert_eq!(
        ev.iter().map(|e| e.0).collect::<Vec<_>>(),
        ["spawn_retry", "spawn_retry_launch_error"]
    );
    assert_eq!(
        ev[1].1[2..],
        [("attempt", json!(1)), ("error", json!("ValueError"))]
    );
    assert!(!format!("{ev:?}").contains("gizli"));
    assert!(!r.calls().iter().any(|c| c.starts_with("direct")));
}

#[test]
fn system_clock_is_monotonic_and_ignores_bad_sleeps() {
    let c = SystemClock;
    let a = c.monotonic();
    let started = Instant::now();
    for s in [f64::NAN, -1.0, f64::INFINITY, f64::NEG_INFINITY, 0.0, 1e300] {
        c.sleep(s);
    }
    assert!(started.elapsed() < Duration::from_secs(1));
    c.sleep(0.01);
    assert!(c.monotonic() >= a + 0.01);
}

// --------------------------------------------------------------------------------------- GnomeTerminal (sahte betik)

fn tmpdir() -> (TempDir, String) {
    let d = tempfile::Builder::new()
        .prefix("cops-g9-")
        .tempdir()
        .unwrap();
    let root = fs::canonicalize(d.path())
        .unwrap()
        .to_string_lossy()
        .into_owned();
    (d, root)
}

/// Çalıştırılabilir dosyayı ALT SÜREÇLE yaz: yazım tanıtıcısı bu süreçte hiç açılmaz, paralel `fork` onu taşıyamaz.
fn write_exe(path: &str, body: &str) {
    fs::create_dir_all(Path::new(path).parent().unwrap()).unwrap();
    let mut child = Command::new("/bin/sh")
        .args(["-c", "cat > \"$1\" && chmod 755 \"$1\"", "sh", path])
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(body.as_bytes())
        .unwrap();
    assert!(child.wait().unwrap().success());
}

/// `path` belirene dek bekle (en çok 10 sn).
fn wait_for(path: &str) -> String {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Ok(s) = fs::read_to_string(path) {
            if s.ends_with('\n') {
                return s;
            }
        }
        assert!(Instant::now() < deadline, "{path} zaman aşımı");
        std::thread::sleep(Duration::from_millis(20));
    }
}

const FAKE_GT: &str = r#"#!/bin/sh
for a in "$@"; do printf '%s\n' "$a"; done > "$OUT.argv"
/usr/bin/env > "$OUT.env"
echo stdout-cop
echo stderr-cop >&2
printf '%s\n' "$$" > "$OUT.tmp" && mv "$OUT.tmp" "$OUT.pid"
"#;

#[test]
fn gnome_terminal_runs_with_only_the_given_env_and_is_reaped() {
    let (_d, root) = tmpdir();
    write_exe(&format!("{root}/bin/gnome-terminal"), FAKE_GT);
    let out = format!("{root}/out");
    let gt = GnomeTerminal::new(Env::fixed([("PATH", format!("{root}/bin"))]));
    assert!(gt.available());
    assert!(!GnomeTerminal::new(Env::fixed([("PATH", format!("{root}/yok"))])).available());
    let argv: Vec<String> = [
        "gnome-terminal",
        "--window",
        "--title=a b",
        "--",
        "bash",
        "-c",
        "x; exec bash",
    ]
    .map(String::from)
    .into();
    let env = vec![
        ("PATH".to_string(), format!("{root}/bin:/usr/bin:/bin")),
        ("OUT".to_string(), out.clone()),
        ("DISPLAY".to_string(), ":7".to_string()),
    ];
    assert_eq!(gt.launch(&argv, &env), Ok(true));
    let pid = wait_for(&format!("{out}.pid")).trim().to_string();
    assert_eq!(
        fs::read_to_string(format!("{out}.argv")).unwrap(),
        "--window\n--title=a b\n--\nbash\n-c\nx; exec bash\n"
    );
    let child_env = fs::read_to_string(format!("{out}.env")).unwrap();
    assert!(child_env.contains("DISPLAY=:7\n") && child_env.contains(&format!("OUT={out}\n")));
    // miras YOK: test sürecinin HOME'u ve cargo değişkenleri çocuğa geçmez
    assert!(
        !child_env
            .lines()
            .any(|l| l.starts_with("HOME=") || l.starts_with("CARGO")),
        "{child_env}"
    );
    // arka planda toplanır: zombi kalmaz (yalnız bu testin kendi çocuğu)
    let deadline = Instant::now() + Duration::from_secs(10);
    while Path::new(&format!("/proc/{pid}")).exists() {
        assert!(Instant::now() < deadline, "çocuk {pid} toplanmadı");
        std::thread::sleep(Duration::from_millis(20));
    }
}

#[test]
fn gnome_terminal_popen_failures() {
    let (_d, root) = tmpdir();
    write_exe(&format!("{root}/bin/gnome-terminal"), "#!/bin/sh\nexit 0\n");
    // izinsiz (0644) dosya: hiç çalıştırılmaz, ETXTBSY riski yok
    fs::create_dir_all(format!("{root}/noexec")).unwrap();
    fs::write(format!("{root}/noexec/gnome-terminal"), "#!/bin/sh\n").unwrap();
    let gt = GnomeTerminal::new(Env::fixed([("PATH", format!("{root}/bin"))]));
    let argv = |a: &str| vec!["gnome-terminal".to_string(), a.to_string()];
    let env = |p: &str| vec![("PATH".to_string(), p.to_string())];
    // `OSError` (yok, çalıştırılamaz) = false; `env`deki PATH aranır, çağıranınki değil
    assert_eq!(
        gt.launch(&argv("x"), &env(&format!("{root}/yok"))),
        Ok(false)
    );
    assert_eq!(
        gt.launch(&argv("x"), &env(&format!("{root}/noexec"))),
        Ok(false)
    );
    assert_eq!(gt.launch(&[], &env(&format!("{root}/bin"))), Ok(false));
    // `ValueError` (Python `Popen` öncesi denetimler): spawn reddi
    let nul = Err(LaunchError::Value("embedded null byte".into()));
    assert_eq!(gt.launch(&argv("a\0b"), &env(&format!("{root}/bin"))), nul);
    assert_eq!(gt.launch(&argv("x"), &[("A".into(), "v\0".into())]), nul);
    assert_eq!(gt.launch(&argv("x"), &[("A\0".into(), "v".into())]), nul);
    assert_eq!(
        gt.launch(&argv("x"), &[("A=B".into(), "v".into())]),
        Err(LaunchError::Value(
            "illegal environment variable name".into()
        ))
    );
    // gerçek çalıştırılabilir: true
    assert_eq!(
        gt.launch(&argv("x"), &env(&format!("{root}/bin"))),
        Ok(true)
    );
}

// ---------------------------------------------------------------------------------------------------- copy2, REPO_DIR

#[test]
fn copy2_copies_content_mode_and_times_and_follows_a_target_link() {
    let (_d, root) = tmpdir();
    let src = format!("{root}/src");
    fs::write(&src, "içerik\n").unwrap();
    fs::set_permissions(&src, fs::Permissions::from_mode(0o640)).unwrap();
    let past = SystemTime::UNIX_EPOCH + Duration::new(1_600_000_000, 123_456_789);
    let older = SystemTime::UNIX_EPOCH + Duration::new(1_500_000_000, 987_654_321);
    fs::File::options()
        .write(true)
        .open(&src)
        .unwrap()
        .set_times(FileTimes::new().set_modified(past).set_accessed(older))
        .unwrap();
    let dst = format!("{root}/dst");
    fs::write(&dst, "eski uzun içerik burada\n").unwrap();
    copy2(&src, &dst).unwrap();
    let m = fs::metadata(&dst).unwrap();
    assert_eq!(fs::read_to_string(&dst).unwrap(), "içerik\n");
    assert_eq!(m.permissions().mode() & 0o7777, 0o640);
    assert_eq!(m.modified().unwrap(), past);
    assert_eq!(m.accessed().unwrap(), older);
    // hedef bağlantıysa izlenir (Python `open(dst, "wb")`): bağlantı kalır, hedefi yazılır
    let link = format!("{root}/link");
    std::os::unix::fs::symlink(format!("{root}/target"), &link).unwrap();
    copy2(&src, &link).unwrap();
    assert!(fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(
        fs::read_to_string(format!("{root}/target")).unwrap(),
        "içerik\n"
    );
    // kaynak yok: NotFound, hedef oluşmaz
    let e = copy2(&format!("{root}/yok"), &format!("{root}/x")).unwrap_err();
    assert_eq!(e.kind(), std::io::ErrorKind::NotFound);
    assert!(!Path::new(&format!("{root}/x")).exists());
}

#[test]
fn repo_dir_resolves_links_and_two_parents() {
    let (_d, root) = tmpdir();
    let real = format!("{root}/depo/py/claudeops/paths.py");
    fs::create_dir_all(Path::new(&real).parent().unwrap()).unwrap();
    fs::write(&real, "").unwrap();
    assert_eq!(
        repo_dir_of(Path::new(&real)).as_deref(),
        Some(format!("{root}/depo").as_str())
    );
    std::os::unix::fs::symlink(&real, format!("{root}/bag.py")).unwrap();
    assert_eq!(
        repo_dir_of(Path::new(&format!("{root}/bag.py"))).as_deref(),
        Some(format!("{root}/depo").as_str())
    );
    std::os::unix::fs::symlink(format!("{root}/depo"), format!("{root}/depo-bag")).unwrap();
    let via = format!("{root}/depo-bag/py/claudeops/paths.py");
    assert_eq!(
        repo_dir_of(Path::new(&via)).as_deref(),
        Some(format!("{root}/depo").as_str())
    );
    assert_eq!(repo_dir_of(Path::new(&format!("{root}/yok.py"))), None);
    // gerçek depo: bu crate'in üç üstü
    let here = fs::canonicalize(concat!(env!("CARGO_MANIFEST_DIR"), "/../../..")).unwrap();
    let paths_py = here.join("py/claudeops/paths.py");
    assert_eq!(repo_dir_of(&paths_py).as_deref(), here.to_str());
}

/// `routing.CODEX_AGENTS` / `AGY_GEMINI` (`~` = HOME) ve varsayılan yollu `sync_global_files`: codex dosyası yoksa
/// oluşturulmaz, agy dosyası (dizini dahil) oluşturulur.
#[test]
fn default_sync_paths_are_under_home() {
    let p = Paths {
        claudeops_dir: "/s".into(),
        home: "/h ev".into(),
        repo_dir: "/r".into(),
    };
    assert_eq!(p.codex_agents_md(), "/h ev/.codex/AGENTS.md");
    assert_eq!(p.agy_gemini_md(), "/h ev/.gemini/GEMINI.md");
    let t = support::Tmp::new();
    let probe = t.probe();
    let settings = Settings::from_json(r#"{"routing_guidance_text": "yönerge"}"#);
    let log = Arc::new(Log::default());
    let out = sync_global_files(&probe, &settings, &t.paths(), &Sink(log.clone()));
    assert_eq!(
        out,
        [
            ("codex", "skipped:no file".to_string()),
            ("agy", "written".to_string())
        ]
    );
    assert!(!Path::new(&t.path("home/.codex/AGENTS.md")).exists());
    let agy = fs::read_to_string(t.path("home/.gemini/GEMINI.md")).unwrap();
    assert!(
        agy.starts_with("<!-- claudeops-routing:begin -->\nyönerge\n"),
        "{agy}"
    );
    assert!(log.diags.lock().unwrap().is_empty());
}

/// `BrokenBackupLinkTest` karşılığı: hedefsiz ya da döngülü `.bak-routing` bağlantısında ne yedek ne yönerge dosyası
/// yazılır.
#[test]
fn dangling_backup_link_writes_neither_backup_nor_target() {
    for target in ["../disarisi.md", "AGENTS.md.bak-routing"] {
        let t = support::Tmp::new();
        let probe = t.probe();
        let settings = Settings::from_json(r#"{"routing_guidance_text": "yönerge"}"#);
        let codex = t.path("home/.codex/AGENTS.md");
        let bak = format!("{codex}.bak-routing");
        fs::create_dir_all(Path::new(&codex).parent().unwrap()).unwrap();
        fs::write(&codex, "kullanıcı\n").unwrap();
        std::os::unix::fs::symlink(target, &bak).unwrap();
        let log = Arc::new(Log::default());
        let out = sync_global_files(&probe, &settings, &t.paths(), &Sink(log.clone()));
        assert_eq!(out[0], ("codex", "skipped:broken backup link".to_string()));
        assert_eq!(fs::read_to_string(&codex).unwrap(), "kullanıcı\n");
        assert_eq!(fs::read_link(&bak).unwrap(), Path::new(target));
        assert!(!Path::new(&t.path("home/disarisi.md")).exists());
        let diags = log.diags.lock().unwrap();
        assert_eq!(diags.len(), 1);
        assert_eq!(diags[0].event, "routing_guidance_backup_broken_link");
        assert_eq!(
            diags[0].fields,
            vec![("path", json!(codex)), ("backup", json!(bak))]
        );
    }
}
