//! G10: tek atımlık çağrı ve onay kaydının gerçek uygulayıcısı (yalnız geçici dizindeki sahte kabuk betikleri; ağ ve
//! gerçek CLI yok). Davranış eşliği `parity.rs::parity_oneshot`ta; burada Python'a sorulamayan güvenlik ve kaynak
//! özellikleri sınanır.

#[path = "g8/support.rs"]
mod support;

use cops_providers::approval::NewRun;
use cops_providers::real::approval::ApprovalStore;
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::oneshot::{ApiKey, ChatRequest, OneShot, OUTPUT_MAX_BYTES};
use cops_providers::real::{Env, RealProbe};
use cops_providers::{Cli, ModelCatalog, Paths, Providers, Settings};
use std::fs;
use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use support::{mkfifo, mode, spawn_guard, Tmp};

const KEY: &str = "sk-g10-gizli-anahtar-0002";

struct Ctx {
    t: Tmp,
    paths: Paths,
    env: Env,
    probe: RealProbe,
    settings: Settings,
    catalog: ModelCatalog,
    approvals: ApprovalStore,
    diag: DiagLog,
}

impl Ctx {
    fn new(settings: &str) -> Ctx {
        let t = Tmp::new();
        let paths = t.paths();
        let env = t.env(&[]);
        let probe = t.probe();
        let approvals = ApprovalStore::new(&paths);
        let diag = DiagLog::new(t.path("state/diag.log"));
        let settings = Settings::from_json(settings);
        Ctx {
            paths,
            env,
            probe,
            settings,
            catalog: ModelCatalog::default(),
            approvals,
            diag,
            t,
        }
    }

    fn with<R>(&self, f: impl FnOnce(&OneShot<'_, '_>) -> R) -> R {
        let providers = Providers {
            settings: &self.settings,
            catalog: &self.catalog,
            paths: &self.paths,
            probe: &self.probe,
        };
        f(&OneShot {
            providers: &providers,
            env: &self.env,
            approvals: &self.approvals,
            diag: &self.diag,
        })
    }

    fn ucli(&self, body: &str) -> String {
        self.t.script(
            "bin/ucli",
            &format!("if [ \"$1 $2\" = 'chat --help' ]; then echo '--approval-dir <D>'; exit 0; fi\n{body}"),
        )
    }
}

/// Dizin ağacındaki bütün dosyaların içeriği.
fn all_files(dir: &str) -> String {
    let mut out = String::new();
    for entry in fs::read_dir(dir).unwrap().flatten() {
        let path = entry.path();
        if path.is_dir() {
            out.push_str(&all_files(path.to_str().unwrap()));
        } else if let Ok(text) = fs::read_to_string(&path) {
            out.push_str(&text);
        }
    }
    out
}

fn dead(pid: &str) -> bool {
    let start = Instant::now();
    loop {
        let alive = fs::read_to_string(format!("/proc/{pid}/stat"))
            .is_ok_and(|s| !s.rsplit(')').next().unwrap_or("").starts_with(" Z"));
        if !alive {
            return true;
        }
        if start.elapsed() > Duration::from_secs(5) {
            return false;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn the_key_reaches_only_the_child_environment() {
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let seen = c.t.path("home/gorulen");
    let suspended = "echo '{\"suspended\":{\"id\":\"a1\"}}'; exit 75";
    let bin = c.ucli(&format!(
        "echo \"$@\" > {seen}.argv; echo \"$UCLI_API_KEY\" > {seen}.env; {suspended}"
    ));
    let work = c.t.path("work");
    let mut req = ChatRequest::new(&work, "p");
    req.binary = Some(&bin);
    req.api_key = Some(ApiKey::new(KEY));
    req.approval_run_key = Some("r1");
    assert!(!format!("{req:?}").contains(KEY));
    let value = c.with(|s| s.chat_once(&req)).unwrap();
    assert_eq!(
        value.get("status").and_then(|v| v.as_str()),
        Some("suspended")
    );
    assert_eq!(
        fs::read_to_string(format!("{seen}.env")).unwrap().trim(),
        KEY
    );
    assert!(!fs::read_to_string(format!("{seen}.argv"))
        .unwrap()
        .contains(KEY));
    assert!(!all_files(&c.t.path("state")).contains(KEY));
    assert!(!format!("{:?}", c.env.with_var("UCLI_API_KEY", KEY)).contains(KEY));
    assert_eq!(mode(&c.approvals.index_path()), 0o600);
    // kayıt yazılamayan yolun günlüğü ve hata metni de anahtarsız
    let index = c.approvals.index_path();
    let bad = c.ucli(&format!(
        "echo \"$UCLI_API_KEY\" >&2; rm '{index}'; mkdir '{index}'; {suspended}"
    ));
    req.binary = Some(&bad);
    req.approval_run_key = Some("r2");
    let error = c.with(|s| s.chat_once(&req)).unwrap_err().0;
    assert!(
        error.contains("kayıt yazılamadı") && !error.contains(KEY),
        "{error}"
    );
    let log = fs::read_to_string(c.diag.path()).unwrap();
    assert!(
        log.contains("ucli_approval_record_failed") && !log.contains(KEY),
        "{log}"
    );
}

#[test]
fn the_configured_key_goes_into_the_child_only_for_the_ucli_oneshot() {
    let _g = spawn_guard();
    let c = Ctx::new(&format!(
        r#"{{"byok": {{"ucli": {{"UCLI_API_KEY": "{KEY}"}}}}}}"#
    ));
    let seen = c.t.path("work/argv");
    let bin = c.ucli(&format!(
        "echo \"$@\" > {seen}; printf '{{\"answer\":\"%s\"}}' \"${{#UCLI_API_KEY}}\""
    ));
    let settings = format!(
        r#"{{"provider_bin": {{"ucli": "{bin}"}}, "byok": {{"ucli": {{"UCLI_API_KEY": "{KEY}"}}}}}}"#
    );
    let c = Ctx {
        settings: Settings::from_json(&settings),
        ..c
    };
    let got = c
        .with(|s| s.oneshot(Cli::Ucli, "özetle", Some("m"), &c.t.path("work/notr"), 10.0))
        .unwrap();
    assert_eq!(got, Some(KEY.len().to_string()));
    assert!(!fs::read_to_string(seen).unwrap().contains(KEY));
}

#[test]
fn timeouts_kill_the_whole_group_and_return_promptly() {
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let pids = c.t.path("work/pids");
    let bin = c.ucli(&format!("sleep 60 & echo $! $$ > {pids}; wait"));
    let work = c.t.path("work");
    for oneshot in [false, true] {
        let start = Instant::now();
        let text = if oneshot {
            c.with(|s| s.run_argv("claude", std::slice::from_ref(&bin), &work, 0.7))
                .unwrap_err()
                .0
        } else {
            let mut req = ChatRequest::new(&work, "p");
            req.binary = Some(&bin);
            req.timeout = 0.7;
            c.with(|s| s.chat_once(&req)).unwrap_err().0
        };
        assert!(text.contains("içinde"), "{text}");
        assert!(start.elapsed() < Duration::from_secs(10));
        for pid in fs::read_to_string(&pids).unwrap().split_whitespace() {
            assert!(dead(pid), "süreç {pid} yaşıyor");
        }
    }
}

#[test]
fn a_live_run_key_is_refused_before_the_binary_starts() {
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let argv = vec!["eski".to_string()];
    c.approvals
        .register(
            "r1",
            NewRun {
                cwd: "/w",
                session: "s",
                argv_resume: &argv,
                owner: "ali",
            },
        )
        .unwrap();
    let before = fs::read(c.approvals.index_path()).unwrap();
    let mark = c.t.path("work/calisti");
    let bin = c.ucli(&format!("touch {mark}; echo '{{}}'"));
    let work = c.t.path("work");
    let mut req = ChatRequest::new(&work, "p");
    req.binary = Some(&bin);
    req.approval_run_key = Some("r1");
    assert!(c
        .with(|s| s.chat_once(&req))
        .unwrap_err()
        .0
        .contains("run_key kullanımda"));
    req.approval_run_key = None;
    req.prompt = "--allow-edit";
    assert!(c.with(|s| s.chat_once(&req)).is_err());
    assert!(!std::path::Path::new(&mark).exists());
    assert_eq!(fs::read(c.approvals.index_path()).unwrap(), before);
}

#[test]
fn a_fifo_key_file_or_index_is_refused_without_blocking() {
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let bin = c.ucli("echo '{\"answer\":\"x\"}'");
    let c = Ctx {
        settings: Settings::from_json(&format!(r#"{{"provider_bin": {{"ucli": "{bin}"}}}}"#)),
        ..c
    };
    let key = c.paths.ucli_key_file("");
    fs::create_dir_all(std::path::Path::new(&key).parent().unwrap()).unwrap();
    mkfifo(&key);
    let start = Instant::now();
    let error = c
        .with(|s| s.oneshot(Cli::Ucli, "p", None, &c.t.path("work/notr"), 5.0))
        .unwrap_err()
        .0;
    assert_eq!(
        error,
        "ucli: anahtar dosyası okunamadı (normal dosya değil)"
    );
    fs::create_dir(c.paths.ucli_approval_root()).unwrap();
    mkfifo(&c.approvals.index_path());
    let argv = vec!["a".to_string()];
    let run = NewRun {
        cwd: "/w",
        session: "",
        argv_resume: &argv,
        owner: "",
    };
    assert!(c
        .approvals
        .register("r1", run)
        .unwrap_err()
        .text
        .contains("normal dosya değil"));
    assert!(!c.approvals.set_state("r1", "done").unwrap());
    assert!(start.elapsed() < Duration::from_secs(10));
}

#[test]
fn oversized_output_is_refused() {
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let bin = c.ucli(&format!("head -c {} /dev/zero", OUTPUT_MAX_BYTES + 1));
    let work = c.t.path("work");
    let mut req = ChatRequest::new(&work, "p");
    req.binary = Some(&bin);
    assert_eq!(
        c.with(|s| s.chat_once(&req)).unwrap_err().0,
        "ucli çıktısı sınırı aştı"
    );
    let argv = [bin.clone()];
    assert_eq!(
        c.with(|s| s.run_argv("claude", &argv, &work, 30.0))
            .unwrap_err()
            .0,
        "claude: çıktı sınırı aşıldı"
    );
}

#[test]
fn concurrent_registrations_lose_nothing_and_one_key_has_one_winner() {
    let t = Tmp::new();
    let store = ApprovalStore::new(&t.paths());
    let winners: usize = std::thread::scope(|scope| {
        let joins: Vec<_> = (0..8)
            .map(|worker| {
                let store = store.clone();
                scope.spawn(move || {
                    let argv = vec![format!("w{worker}")];
                    let run = NewRun {
                        cwd: "/w",
                        session: "s",
                        argv_resume: &argv,
                        owner: "o",
                    };
                    for i in 0..20 {
                        let key = format!("w{worker}-{i}");
                        store.register(&key, run).unwrap();
                        assert!(store.set_state(&key, "suspended").unwrap());
                    }
                    usize::from(store.register("ortak", run).is_ok())
                })
            })
            .collect();
        joins.into_iter().map(|j| j.join().unwrap()).sum()
    });
    assert_eq!(winners, 1);
    let text = fs::read_to_string(store.index_path()).unwrap();
    let index = cops_providers::approval::parse_index(text.as_bytes()).unwrap();
    assert_eq!(index.len(), 161);
    assert_eq!(
        index
            .iter()
            .filter(|(_, r)| r.get("state").and_then(|s| s.as_str()) == Some("suspended"))
            .count(),
        160
    );
}

#[test]
fn the_lock_is_the_one_python_takes_and_a_busy_lock_writes_nothing() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let store = ApprovalStore::new(&t.paths()).with_lock_timeout(Duration::from_millis(100));
    let argv = vec!["a".to_string()];
    let run = NewRun {
        cwd: "/w",
        session: "",
        argv_resume: &argv,
        owner: "",
    };
    store.register("r1", run).unwrap();
    let before = fs::read(store.index_path()).unwrap();
    let holder = "import sys\nfrom claudeops import ucli_approval as ua\nfrom claudeops.atomic_json import file_lock\n\
                  assert ua.ROOT == sys.argv[1]\nwith file_lock(ua._index_path()):\n    print('kilitli', flush=True)\n    \
                  sys.stdin.read()\n";
    let py = format!("{}/../../../py", env!("CARGO_MANIFEST_DIR"));
    let mut child = Command::new("/usr/bin/python3")
        .args([
            "-s",
            "-B",
            "-W",
            "ignore",
            "-c",
            holder,
            &t.paths().ucli_approval_root(),
        ])
        .env_clear()
        .env("HOME", t.path("home"))
        .env("CLAUDEOPS_DIR", t.path("state"))
        .env("CLAUDEOPS_EXTENSIONS", "0")
        .env("PYTHONPATH", py)
        .env("LANG", "C.UTF-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    BufReader::new(child.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let register = store.register("r2", run);
    let change = store.set_state("r1", "done");
    drop(child.stdin.take());
    assert!(child.wait().unwrap().success());
    assert_eq!(line.trim(), "kilitli");
    assert_eq!(register.unwrap_err().class, "LockError");
    assert_eq!(change.unwrap_err().class, "LockError");
    assert_eq!(fs::read(store.index_path()).unwrap(), before);
    store.register("r2", run).unwrap();
}

/// 27 Kas (G10 aday 5): açılamayan (izin) anahtar dosyası "yok" sayılıp miras ortam anahtarıyla sürülmez: ret, ikili
/// başlatılmaz. Yok ya da dizin hâlâ anahtarsız.
#[test]
fn an_unreadable_key_file_is_refused_not_treated_as_missing() {
    use std::os::unix::fs::PermissionsExt;
    if unsafe { libc::geteuid() } == 0 {
        return; // root izin denetimini atlar
    }
    let _g = spawn_guard();
    let c = Ctx::new("{}");
    let marker = c.t.path("calisti");
    let bin = c.ucli(&format!("touch '{marker}'; echo '{{\"answer\":\"x\"}}'"));
    let c = Ctx {
        settings: Settings::from_json(&format!(r#"{{"provider_bin": {{"ucli": "{bin}"}}}}"#)),
        ..c
    };
    let key = c.paths.ucli_key_file("");
    fs::create_dir_all(std::path::Path::new(&key).parent().unwrap()).unwrap();
    fs::write(&key, "sk-gizli").unwrap();
    fs::set_permissions(&key, fs::Permissions::from_mode(0o000)).unwrap();
    let error = c
        .with(|s| s.oneshot(Cli::Ucli, "p", None, &c.t.path("work/notr"), 5.0))
        .unwrap_err()
        .0;
    assert_eq!(error, "ucli: anahtar dosyası okunamadı (açılamadı)");
    assert!(!std::path::Path::new(&marker).exists());
    fs::set_permissions(&key, fs::Permissions::from_mode(0o600)).unwrap();
    fs::remove_file(&key).unwrap();
    let out = c.with(|s| s.oneshot(Cli::Ucli, "p", None, &c.t.path("work/notr"), 5.0));
    assert_eq!(out.unwrap().as_deref(), Some("x"));
}
