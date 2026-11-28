//! G9 gerçek tmux uygulayıcısı ([`CopsTmux`]): YALNIZ bu testin açtığı yalıtılmış sunucu (geçici `TMUX_TMPDIR` + rastgele
//! soket; `cops-tmux` testlerinin düzeni). Kullanıcının sunucusuna, `-L cops` soketine, gnome-terminal'e, `~/.claude`a
//! dokunulmaz; sunucu yalnız kendi soketiyle `kill-server` ile kapatılır. Her bekleme zaman aşımlı.

use cops_providers::real::tmux::{CopsTmux, BAD_NAME};
use cops_providers::real::Env;
use cops_providers::spawn_exec::{
    fallback_watchdog, open_window, reclaim_ghost_session, Clock, DiagSink, LaunchError, Launcher,
    SpawnTmux, Terminal,
};
use cops_providers::Diag;
use cops_tmux::Tmux;
use serde_json::Value;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tempfile::TempDir;

/// Depo kökü (`<depo>/py/claudeops/data/tmux.conf` buradan).
fn repo() -> String {
    std::fs::canonicalize(concat!(env!("CARGO_MANIFEST_DIR"), "/../../.."))
        .unwrap()
        .to_string_lossy()
        .into_owned()
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

struct Server {
    socket: String,
    dir: TempDir,
}

impl Server {
    fn new() -> Server {
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let socket = format!(
            "cxprov{}-{}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .subsec_nanos(),
            SEQ.fetch_add(1, Ordering::Relaxed),
            std::process::id()
        );
        Server {
            socket,
            dir: tempfile::tempdir().unwrap(),
        }
    }

    fn path(&self) -> &Path {
        self.dir.path()
    }

    fn client(&self) -> Tmux {
        Tmux::with_socket(self.socket.clone()).tmpdir(self.path())
    }

    /// Gerçek sağlayıcı; hayalet yaşı `age` saniye ileri alınmış saatle.
    fn cops(&self, age: f64) -> CopsTmux {
        CopsTmux::new(
            self.client(),
            &repo(),
            Env::fixed([("PATH", "/usr/bin:/bin")]),
        )
        .with_wall_clock(Arc::new(move || now() + age))
    }

    /// Pane ortamı: kullanıcının kabuk ayarlarından bağımsız, yalnız bu değişkenler.
    fn pane_env(&self) -> Vec<(String, String)> {
        [
            ("PATH", "/usr/bin:/bin"),
            ("HOME", self.path().to_str().unwrap()),
            ("SHELL", "/bin/sh"),
            ("TERM", "xterm-256color"),
            ("LANG", "C.UTF-8"),
            ("COPS_TEST_MARK", "evet"),
        ]
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
    }

    fn cwd(&self) -> String {
        self.path().to_str().unwrap().to_string()
    }

    fn sessions(&self) -> Vec<String> {
        self.client()
            .list_sessions()
            .map(|v| v.into_iter().map(|s| s.name).collect())
            .unwrap_or_default()
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", &self.socket, "kill-server"])
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output();
    }
}

fn wait_until(mut done: impl FnMut() -> bool, what: &str) {
    let deadline = Instant::now() + Duration::from_secs(10);
    while !done() {
        assert!(Instant::now() < deadline, "beklenen durum oluşmadı: {what}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn screen(t: &CopsTmux, name: &str) -> String {
    cops_tmux::strip_ansi(&t.capture(name, 50).unwrap_or_default()).replace('\n', "")
}

#[test]
fn spawn_direct_runs_inner_with_only_the_given_env_in_the_exact_session() {
    let s = Server::new();
    let t = s.cops(0.0);
    assert!(t.available());
    assert!(Path::new(t.conf()).is_file(), "{}", t.conf());
    // Bu test sürecinin ortamındaki `CARGO_MANIFEST_DIR` pane'e SIZMAMALI (ortam miras alınmaz).
    assert!(std::env::var_os("CARGO_MANIFEST_DIR").is_some());
    let inner = r#"echo "mark=$COPS_TEST_MARK leak=${CARGO_MANIFEST_DIR-yok} cwd=$(pwd)""#;
    assert!(t.spawn_direct("p1", &s.cwd(), inner, &s.pane_env()));
    let want = format!("mark=evet leak=yok cwd={}", s.cwd());
    wait_until(|| screen(&t, "p1").contains(&want), "pane çıktısı");
    assert!(t.has_session("p1"));
    // Ön ek eşleşmesi yok: `p` ne var sayılır ne de yakalanır/kapatılır.
    assert!(!t.has_session("p"));
    assert_eq!(t.capture("p", 10), None);
    t.kill_session("p");
    assert!(t.has_session("p1"));
    // `-A`: var olan oturumda ikinci oturum açılmaz (terminal yok: bağlanma başarısız, Python gibi False).
    assert!(!t.spawn_direct("p1", "/", "sleep 60", &s.pane_env()));
    assert_eq!(s.sessions(), ["p1"]);
    t.kill_session("p1");
    assert!(!t.has_session("p1"));
    t.kill_session("p1"); // yok: hata yutulur
}

#[test]
fn unaddressable_names_run_no_tmux_command_and_open_nothing() {
    let s = Server::new();
    let t = s.cops(100.0);
    for name in [
        "",
        "$0",
        "a:b",
        "a#(touch x)",
        "victim#{?0,x,}",
        "a\tb",
        "a\u{1b}b",
    ] {
        assert_eq!(
            t.new_session_fragment(name, "/", "true"),
            Err(BAD_NAME.to_string()),
            "{name:?}"
        );
        assert_eq!(
            t.attach_fragment(name),
            Err(BAD_NAME.to_string()),
            "{name:?}"
        );
        assert!(
            !t.spawn_direct(name, &s.cwd(), "true", &s.pane_env()),
            "{name:?}"
        );
        assert!(!t.has_session(name), "{name:?}");
        assert!(!t.ghost_session(name), "{name:?}");
        assert_eq!(t.capture(name, 10), None, "{name:?}");
        t.kill_session(name);
    }
    // Hiçbir komut sunucu başlatmadı.
    assert!(s.client().list_sessions().is_err());
    assert!(!s.path().join("touch").exists() && !Path::new("x").exists());
}

#[test]
fn no_server_means_false_and_none() {
    let s = Server::new();
    let t = s.cops(0.0);
    assert!(!t.has_session("yok"));
    assert!(!t.ghost_session("yok"));
    assert_eq!(t.capture("yok", 10), None);
    t.kill_session("yok");
}

#[test]
fn available_follows_the_given_path_like_shutil_which() {
    let s = Server::new();
    let none = CopsTmux::new(s.client(), &repo(), Env::fixed([("PATH", s.cwd())]));
    assert!(!none.available());
    let empty = CopsTmux::new(
        s.client(),
        &repo(),
        Env::fixed(Vec::<(String, String)>::new()),
    );
    // `PATH` yoksa Python `os.defpath` (`/bin:/usr/bin`).
    assert_eq!(
        empty.available(),
        Path::new("/usr/bin/tmux").exists() || Path::new("/bin/tmux").exists()
    );
}

/// Python `tmux_new_session_shell_fragment` / `tmux_attach_shell_fragment` ile aynı metin (aynı depo, aynı conf).
#[test]
fn fragments_match_python() {
    let s = Server::new();
    let t = CopsTmux::live(&repo(), Env::fixed([("PATH", "/usr/bin:/bin")]));
    let cases: Vec<(&str, &str, &str)> = vec![
        ("s1", "/work/p1", "cd /work/p1 && claude --resume x"),
        ("a b'c", "/w/x y", "echo 'tek' \"çift\" $HOME"),
        ("semi;", "/w/semi;", "true;"),
        ("ş-ğ.ü", "/w/#{pane_pid}#[x]", "echo #{session_name}"),
        ("=x", "", ""),
    ];
    let code = r#"
import json, sys
sys.path.insert(0, sys.argv[1] + "/py")
from claudeops import tmux_backend as t
out = []
for n, c, i in json.loads(sys.argv[2]):
    out.append([t.tmux_new_session_shell_fragment(n, c, i), t.tmux_attach_shell_fragment(n)])
print(json.dumps(out))
"#;
    let arg = serde_json::to_string(&cases).unwrap();
    let home = s.path().join("home");
    std::fs::create_dir_all(&home).unwrap();
    // Yeni oturum parçası SÜREÇ PATH'ini süzüp başa koyar (TBD#450, Python `os.environ`): Python'a da aynısı verilir.
    let path = std::env::var_os("PATH").unwrap_or_default();
    let out = Command::new("/usr/bin/python3")
        .args(["-I", "-c", code, &repo(), &arg])
        .env_clear()
        .env("PATH", path)
        .env("HOME", &home)
        .env("CLAUDEOPS_DIR", s.path().join("state"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let py: Vec<(String, String)> = serde_json::from_slice(&out.stdout).unwrap();
    for ((n, c, i), (want_new, want_attach)) in cases.iter().zip(py) {
        assert_eq!(t.new_session_fragment(n, c, i).unwrap(), want_new, "{n:?}");
        assert_eq!(t.attach_fragment(n).unwrap(), want_attach, "{n:?}");
    }
}

// ------------------------------------------------------------------- spawn_exec akışı gerçek tmux ile (pencere sahte)

#[derive(Default)]
struct Log {
    diags: Mutex<Vec<Diag>>,
    launches: Mutex<Vec<Vec<String>>>,
}

/// Pencere açmayan terminal (gnome-terminal ÇALIŞTIRILMAZ): yalnız argv kaydı.
struct NoWindow(Arc<Log>);

impl Terminal for NoWindow {
    fn available(&self) -> bool {
        true
    }
    fn path_exists(&self, _path: &str) -> bool {
        false
    }
    fn launch(&self, argv: &[String], _env: &[(String, String)]) -> Result<bool, LaunchError> {
        self.0.launches.lock().unwrap().push(argv.to_vec());
        Ok(true)
    }
    fn window_list(&self, _display: &str) -> Option<Vec<u8>> {
        None
    }
}

/// Bekçi beklemesi gerçek zamanda kısa: her `sleep` saati 1 sn ilerletir, gerçek bekleme 10 ms.
struct FastClock(Mutex<f64>);

impl Clock for FastClock {
    fn monotonic(&self) -> f64 {
        *self.0.lock().unwrap()
    }
    fn sleep(&self, _secs: f64) {
        std::thread::sleep(Duration::from_millis(10));
        *self.0.lock().unwrap() += 1.0;
    }
}

struct Sink(Arc<Log>);

impl DiagSink for Sink {
    fn log(&self, diag: &Diag) {
        self.0.diags.lock().unwrap().push(diag.clone());
    }
}

fn launcher(t: CopsTmux, log: &Arc<Log>) -> Launcher {
    Launcher {
        tmux: Arc::new(t),
        terminal: Arc::new(NoWindow(log.clone())),
        clock: Arc::new(FastClock(Mutex::new(0.0))),
        diag: Arc::new(Sink(log.clone())),
        parent_env: vec![("PATH".into(), "/usr/bin:/bin".into())],
    }
}

fn events(log: &Log) -> Vec<(&'static str, Vec<(&'static str, Value)>)> {
    log.diags
        .lock()
        .unwrap()
        .iter()
        .map(|d| (d.event, d.fields.clone()))
        .collect()
}

/// `ReclaimTest` gerçek tmux'ta: çıplak kabukla kalan (CLI'si çıkmış) TAM adlı oturum kapanır; ön ek kardeşi, meşgul
/// oturum ve genç oturum kalır; ekran metni günlüğe girmez.
#[test]
fn reclaim_kills_only_the_exact_old_childless_shell() {
    let s = Server::new();
    let t = s.cops(100.0);
    let cwd = s.cwd();
    assert!(t.spawn_direct("g", &cwd, "echo GIZLI-EKRAN", &s.pane_env()));
    assert!(t.spawn_direct("g_1", &cwd, "true", &s.pane_env()));
    assert!(t.spawn_direct("busy", &cwd, "sleep 60", &s.pane_env()));
    wait_until(|| t.ghost_session("g") && t.ghost_session("g_1"), "hayalet");
    wait_until(|| screen(&t, "g").contains("GIZLI-EKRAN"), "ekran");
    let log = Arc::new(Log::default());
    let l = launcher(t.clone(), &log);
    reclaim_ghost_session(&l, "g", "claude");
    reclaim_ghost_session(&l, "busy", "claude");
    reclaim_ghost_session(&l, "g_1", "shell");
    let mut left = s.sessions();
    left.sort();
    assert_eq!(left, ["busy", "g_1"]);
    let ev = events(&log);
    assert_eq!(ev.len(), 1, "{ev:?}");
    assert_eq!(ev[0].0, "spawn_ghost_reclaimed");
    assert!(!format!("{ev:?}").contains("GIZLI"), "{ev:?}");
    // Genç oturum (gerçek saat) hayalet değil.
    let young = s.cops(0.0);
    assert!(!young.ghost_session("g_1"));
}

/// Bekçi: pencere hiç oturum getirmezse denemelerden sonra penceresiz tmux (gerçek `spawn_direct`) açar; oturum zaten
/// varsa hiçbir şey yapmaz.
#[test]
fn watchdog_falls_back_to_a_real_headless_session() {
    let s = Server::new();
    let log = Arc::new(Log::default());
    let l = launcher(s.cops(0.0), &log);
    let env = s.pane_env();
    fallback_watchdog(&l, "w1", &s.cwd(), "echo BEKCI-ACTI", &env, "WINDOWCMD");
    assert!(l.tmux.has_session("w1"));
    wait_until(
        || screen(&s.cops(0.0), "w1").contains("BEKCI-ACTI"),
        "yedek oturum çıktısı",
    );
    let names: Vec<&str> = events(&log).iter().map(|e| e.0).collect();
    assert_eq!(names, ["spawn_retry", "spawn_retry", "spawn_fallback_used"]);
    assert_eq!(log.launches.lock().unwrap().len(), 2);
    // Oturum var: bekçi ilk yoklamada döner, ikinci oturum açılmaz.
    let log2 = Arc::new(Log::default());
    let l2 = launcher(s.cops(0.0), &log2);
    fallback_watchdog(&l2, "w1", &s.cwd(), "echo IKINCI", &env, "WINDOWCMD");
    assert!(events(&log2).is_empty());
    assert_eq!(s.sessions(), ["w1"]);
}

/// `open_window`: var olan oturuma TAM hedefli `attach-session` parçasıyla pencere; oturum yoksa hiçbir şey açılmaz.
#[test]
fn open_window_attaches_to_the_exact_existing_session() {
    let s = Server::new();
    let t = s.cops(0.0);
    let log = Arc::new(Log::default());
    let l = launcher(t.clone(), &log);
    assert_eq!(open_window(&l, "ow", &s.cwd(), Some(":7")), Ok(false));
    assert!(log.launches.lock().unwrap().is_empty());
    assert!(t.spawn_direct("ow_1", &s.cwd(), "sleep 60", &s.pane_env()));
    assert_eq!(
        open_window(&l, "ow", &s.cwd(), Some(":7")),
        Ok(false),
        "ön ek eşleşmesi yok"
    );
    assert!(t.spawn_direct("ow", &s.cwd(), "sleep 60", &s.pane_env()));
    assert_eq!(open_window(&l, "ow", &s.cwd(), Some(":7")), Ok(true));
    let launches = log.launches.lock().unwrap();
    let cmd = launches[0].last().unwrap();
    assert!(
        cmd.ends_with(&format!(
            "-L {} -f {} attach-session -t =ow:; exec bash",
            s.socket,
            t.conf()
        )),
        "{cmd}"
    );
}
