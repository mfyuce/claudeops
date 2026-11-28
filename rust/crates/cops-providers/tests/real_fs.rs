//! G8: gerçek dosya uygulayıcıları (okuma sözleşmesi, yazım güvenliği, SQLite, checks kaydı, günlük, ajan token'ı).

#[path = "g8/support.rs"]
mod support;

use cops_providers::real::agents::{AgentRegistry, Sources};
use cops_providers::real::diaglog::{self, DiagLog};
use cops_providers::real::effects::{self, atomic_write_text};
use cops_providers::real::probe::{HomeProjects, ProjectDirs};
use cops_providers::real::{checks, fsio, pathexec};
use cops_providers::{
    BuildArgs, BuildOutput, Cli, Effect, LiveProbe, ModelCatalog, Probe, Providers, Settings,
    SqlCell,
};
use serde_json::{json, Value};
use std::fs;
use std::os::unix::fs::symlink;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use support::{mkfifo, mode, Tmp};

#[test]
fn reading_takes_only_regular_files_and_never_blocks_on_a_fifo() {
    let t = Tmp::new();
    let fifo = t.path("work/boru");
    mkfifo(&fifo);
    let link = t.path("work/boru-bag");
    symlink(&fifo, &link).unwrap();
    let p = t.probe();
    let start = Instant::now();
    for path in [
        fifo.as_str(),
        link.as_str(),
        "/dev/zero",
        "/dev/null",
        &t.path("work"),
        &t.path("work/yok"),
        "",
        "a\0b",
    ] {
        assert_eq!(p.read_bytes(path, u64::MAX), None, "{path:?}");
        assert_eq!(p.read_tail(path, 10), None, "{path:?}");
        assert_eq!(p.read_range(path, 0, 10), None, "{path:?}");
        assert_eq!(p.read_text(path), None, "{path:?}");
        assert_eq!(
            p.sqlite_cell(path, "SELECT 1 WHERE ? IS NOT NULL", "x"),
            None,
            "{path:?}"
        );
    }
    assert!(start.elapsed() < Duration::from_secs(5));
}

#[test]
fn bounded_reads_respect_limits_and_ranges() {
    let t = Tmp::new();
    let f = t.write("work/f", b"0123456789", 0o600);
    let p = t.probe();
    assert_eq!(p.read_bytes(&f, 10).as_deref(), Some(&b"0123456789"[..]));
    assert_eq!(p.read_bytes(&f, 9), None);
    assert_eq!(p.read_tail(&f, 3).as_deref(), Some(&b"789"[..]));
    assert_eq!(p.read_tail(&f, 99).as_deref(), Some(&b"0123456789"[..]));
    assert_eq!(p.read_range(&f, 8, 99).as_deref(), Some(&b"89"[..]));
    assert_eq!(p.read_range(&f, 99, 5).as_deref(), Some(&b""[..]));
    assert_eq!(fsio::read_bytes(&f, u64::MAX).map(|d| d.len()), Some(10));
    let crlf = t.write("work/crlf", b"a\r\nb\rc", 0o600);
    assert_eq!(p.read_text(&crlf).as_deref(), Some("a\nb\nc"));
    assert_eq!(
        p.read_text(&t.write("work/bozuk", [0xffu8, b'a'], 0o600)),
        None
    );
}

#[test]
fn list_dir_keeps_the_directory_read_order() {
    let t = Tmp::new();
    for i in 0..200 {
        t.write(&format!("work/d/{}", (i * 7919) % 1000), "", 0o600);
    }
    let dir = t.path("work/d");
    let expected: Vec<String> = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    assert_eq!(t.probe().list_dir(&dir), Some(expected));
    assert_eq!(t.probe().list_dir(&t.path("work/yok")), None);
}

#[test]
fn proc_stat_reads_the_pseudo_file_of_a_live_process_only() {
    let t = Tmp::new();
    let p = t.probe();
    let own = p.proc_stat(i64::from(std::process::id())).unwrap();
    assert!(own.starts_with(format!("{} (", std::process::id()).as_bytes()));
    assert_eq!(p.proc_stat(-1), None);
    assert_eq!(p.proc_stat(i64::MAX), None);
    t.write("work/proc/7/stat", "7 (x) S", 0o600);
    assert_eq!(
        t.probe()
            .with_proc_root(t.path("work/proc"))
            .proc_stat(7)
            .as_deref(),
        Some(&b"7 (x) S"[..])
    );
}

#[test]
fn sqlite_is_read_only_never_creates_files_and_treats_the_path_literally() {
    let t = Tmp::new();
    let p = t.probe();
    let db = t.path("work/a #?b.db");
    {
        let c = rusqlite::Connection::open_with_flags(
            &db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE | rusqlite::OpenFlags::SQLITE_OPEN_CREATE,
        )
        .unwrap();
        c.execute_batch(
            "CREATE TABLE t(k TEXT, v INTEGER); INSERT INTO t VALUES('a', 7), ('a', 8);",
        )
        .unwrap();
    }
    assert_eq!(
        p.sqlite_cell(&db, "SELECT v FROM t WHERE k = ? ORDER BY v", "a"),
        Some(SqlCell::Int(7))
    );
    assert_eq!(
        p.sqlite_cell(&db, "SELECT v FROM t WHERE k = ?", "yok"),
        None
    );
    assert!(
        !p.sqlite_rows(
            &db,
            "INSERT INTO t VALUES('x', 1) RETURNING v",
            &[],
            &mut |_| true
        ),
        "yazılabildi"
    );
    assert_eq!(
        p.sqlite_cell(&db, "SELECT count(*) FROM t WHERE k != ?", ""),
        Some(SqlCell::Int(2))
    );
    let missing = t.path("work/yok.db");
    assert!(!p.sqlite_rows(&missing, "SELECT 1", &[], &mut |_| true));
    assert!(!std::path::Path::new(&missing).exists());
    let mut seen = 0;
    assert!(p.sqlite_rows(&db, "SELECT v FROM t", &[], &mut |_| {
        seen += 1;
        false
    }));
    assert_eq!(seen, 1);
    assert_eq!(
        fs::read_dir(t.path("work")).unwrap().count(),
        1,
        "yan dosya kalmadı"
    );
}

#[test]
fn sqlite_waits_two_seconds_for_a_locked_database_then_gives_up() {
    let t = Tmp::new();
    let db = t.path("work/k.db");
    let c = rusqlite::Connection::open(&db).unwrap();
    c.execute_batch("CREATE TABLE t(v); INSERT INTO t VALUES(1); BEGIN EXCLUSIVE;")
        .unwrap();
    let start = Instant::now();
    assert_eq!(
        t.probe()
            .sqlite_cell(&db, "SELECT v FROM t WHERE ? IS NOT NULL", "x"),
        None
    );
    let waited = start.elapsed();
    assert!(
        waited >= Duration::from_millis(1500) && waited < Duration::from_secs(10),
        "{waited:?}"
    );
}

#[test]
fn secret_files_are_private_from_creation_and_links_are_not_followed() {
    let t = Tmp::new();
    let secret = t.path("work/anahtar");
    effects::apply(&Effect::WriteSecret {
        path: secret.clone(),
        content: "gizli".into(),
    })
    .unwrap();
    assert_eq!(
        (mode(&secret), fs::read_to_string(&secret).unwrap().as_str()),
        (0o600, "gizli")
    );
    fs::set_permissions(&secret, std::os::unix::fs::PermissionsExt::from_mode(0o644)).unwrap();
    effects::apply(&Effect::WriteSecret {
        path: secret.clone(),
        content: "yeni".into(),
    })
    .unwrap();
    assert_eq!(
        (mode(&secret), fs::read_to_string(&secret).unwrap().as_str()),
        (0o600, "yeni")
    );

    let victim = t.write("work/hedef", "dokunma", 0o600);
    let link = t.path("work/bag");
    symlink(&victim, &link).unwrap();
    for effect in [
        Effect::WriteSecret {
            path: link.clone(),
            content: "SIR-123".into(),
        },
        Effect::Touch { path: link.clone() },
    ] {
        let e = effects::apply(&effect).unwrap_err();
        assert!(!format!("{e} {e:?}").contains("SIR-123"));
    }
    assert_eq!(fs::read_to_string(&victim).unwrap(), "dokunma");

    // FIFO'ya yazım bloklamadan hata
    let fifo = t.path("work/boru");
    mkfifo(&fifo);
    let start = Instant::now();
    assert!(effects::apply(&Effect::WriteSecret {
        path: fifo,
        content: "SIR".into()
    })
    .is_err());
    assert!(start.elapsed() < Duration::from_secs(5));
}

#[test]
fn touch_keeps_an_existing_mode_and_remove_never_fails() {
    let t = Tmp::new();
    let marker = t.write("work/damga", "eski", 0o640);
    effects::apply(&Effect::Touch {
        path: marker.clone(),
    })
    .unwrap();
    assert_eq!(
        (mode(&marker), fs::read(&marker).unwrap().len()),
        (0o640, 0)
    );
    effects::apply(&Effect::Remove {
        path: t.path("work/yok"),
    })
    .unwrap();
    effects::apply(&Effect::Remove {
        path: t.path("work"),
    })
    .unwrap();
    assert!(std::path::Path::new(&marker).exists());
}

#[test]
fn apply_all_stops_at_the_first_failure_and_reports_where() {
    let t = Tmp::new();
    t.write("work/dosya", "x", 0o600);
    let after = t.path("work/sonraki");
    let list = [
        Effect::MkdirPrivate {
            path: t.path("work/d"),
        },
        Effect::MkdirPrivate {
            path: t.path("work/dosya/alt"),
        },
        Effect::Touch {
            path: after.clone(),
        },
    ];
    let e = effects::apply_all(&list).unwrap_err();
    assert_eq!(e.index, 1);
    assert_eq!(
        e.to_string(),
        format!("[Errno 20] Not a directory: '{}'", t.path("work/dosya/alt"))
    );
    assert!(!std::path::Path::new(&after).exists());
}

#[test]
fn atomic_write_keeps_the_private_mode_replaces_links_and_leaves_no_tmp() {
    let t = Tmp::new();
    // copilot config: var olan 0600 korunur
    let cfg = t.write("work/config.json", "{}", 0o600);
    atomic_write_text(&cfg, "{\"a\":1}", None).unwrap();
    assert_eq!(mode(&cfg), 0o600);
    let victim = t.write("work/hedef", "dokunma", 0o600);
    let link = t.path("work/bag");
    symlink(&victim, &link).unwrap();
    atomic_write_text(&link, "yeni", Some(0o600)).unwrap();
    assert!(!fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(fs::read_to_string(&victim).unwrap(), "dokunma");
    // hata (hedef dizin): geçici dosya kalmaz
    fs::create_dir(t.path("work/dizin")).unwrap();
    assert!(atomic_write_text(&t.path("work/dizin"), "x", None).is_err());
    let left: Vec<_> = fs::read_dir(t.path("work"))
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect();
    assert!(
        left.iter().all(|n| !n.to_string_lossy().ends_with(".tmp")),
        "{left:?}"
    );
}

#[test]
fn concurrent_atomic_writes_never_expose_a_partial_file() {
    let t = Tmp::new();
    let path = t.path("work/belge");
    let body = |c: char| std::iter::repeat_n(c, 200_000).collect::<String>();
    atomic_write_text(&path, &body('a'), None).unwrap();
    std::thread::scope(|s| {
        for c in ['b', 'c', 'd', 'e'] {
            let (path, text) = (path.clone(), body(c));
            s.spawn(move || {
                for _ in 0..15 {
                    atomic_write_text(&path, &text, None).unwrap();
                }
            });
        }
        for _ in 0..200 {
            let got = fs::read(&path).unwrap();
            assert!(got.len() == 200_000 && got.iter().all(|b| *b == got[0]));
        }
    });
    assert_eq!(fs::read_dir(t.path("work")).unwrap().count(), 1);
}

const GOOD: &str = r#"{"check": [{"name": "unittest", "argv": ["python3", "-m", "unittest"]}]}"#;

#[test]
fn checks_registry_rejects_missing_loose_mode_links_and_bad_shape() {
    let t = Tmp::new();
    let p = t.probe();
    let path = t.path("state/ucli_checks/owner.json");
    assert!(p.checks_registry(&path).unwrap_err().contains("kaydı yok"));
    t.write("state/ucli_checks/owner.json", GOOD, 0o644);
    assert!(p.checks_registry(&path).unwrap_err().contains("0600"));
    t.write(
        "state/ucli_checks/owner.json",
        r#"{"check": [{"name": "A!", "argv": ["x"]}]}"#,
        0o600,
    );
    assert!(p.checks_registry(&path).is_err());
    t.write(
        "state/ucli_checks/owner.json",
        r#"{"check": [{"name":"a","argv":["x"]},{"name":"a","argv":["y"]}]}"#,
        0o600,
    );
    assert!(p.checks_registry(&path).unwrap_err().contains("yinelendi"));
    t.write("state/ucli_checks/owner.json", GOOD, 0o600);
    assert_eq!(p.checks_registry(&path), Ok(()));
    let real = t.write("state/ucli_checks/real.json", GOOD, 0o600);
    fs::remove_file(&path).unwrap();
    symlink(real, &path).unwrap();
    assert!(p.checks_registry(&path).unwrap_err().contains("düz dosya"));
    fs::remove_file(&path).unwrap();
    mkfifo(&path);
    assert!(p.checks_registry(&path).unwrap_err().contains("düz dosya"));
    let big = t.write(
        "state/ucli_checks/big.json",
        vec![b' '; checks::MAX_BYTES as usize + 1],
        0o600,
    );
    assert_eq!(p.checks_registry(&big).unwrap_err(), "kayıt çok büyük");
    assert!(checks::registry_path("/r", "../x").is_err());
    assert_eq!(checks::registry_path("/r", "").unwrap(), "/r/owner.json");
}

fn registry(t: &Tmp) -> AgentRegistry {
    AgentRegistry::new(&t.paths())
}

fn token(path: &str) -> String {
    fs::read_to_string(path).unwrap()
}

#[test]
fn agent_token_is_0600_and_only_its_hash_is_registered() {
    let t = Tmp::new();
    let r = registry(&t);
    let path = r.issue_token("p1").unwrap();
    let tok = token(&path);
    assert_eq!(tok.len(), 64);
    assert_eq!(
        (mode(&path), mode(&t.path("state/ucli_agent_tokens"))),
        (0o600, 0o700)
    );
    let state = t.path("state/ucli_agents.json");
    assert_eq!(mode(&state), 0o600);
    assert!(!token(&state).contains(&tok));
    assert_eq!(r.parent_for_token(&tok).as_deref(), Some("p1"));
    assert!(!format!("{r:?}").contains(&tok) && !path.contains(&tok));
    // ikinci yazım da 0600 ve geçici dosya bırakmaz
    r.issue_token("p1").unwrap();
    assert_eq!(mode(&path), 0o600);
    assert_eq!(
        fs::read_dir(t.path("state/ucli_agent_tokens"))
            .unwrap()
            .count(),
        1
    );
}

#[test]
fn agent_reissue_invalidates_and_revoke_clears() {
    let t = Tmp::new();
    let r = registry(&t);
    let t1 = token(&r.issue_token("p1").unwrap());
    let t2 = token(&r.issue_token("p1").unwrap());
    assert_eq!(r.parent_for_token(&t1), None);
    assert_eq!(r.parent_for_token(&t2).as_deref(), Some("p1"));
    r.revoke_parent("p1").unwrap();
    assert_eq!(r.parent_for_token(&t2), None);
    assert!(!std::path::Path::new(&r.token_file("p1")).exists());
}

#[test]
fn agent_children_get_no_token_and_garbage_is_rejected() {
    let t = Tmp::new();
    let r = registry(&t);
    for bad in [
        "p1_aj1",
        "",
        "../x",
        "a/b",
        ".gizli",
        "a b",
        &"x".repeat(101),
    ] {
        assert_eq!(r.issue_token(bad), Err("ValueError".to_string()), "{bad:?}");
    }
    assert_eq!(r.parent_for_token(""), None);
    assert_eq!(r.parent_for_token(&"x".repeat(500)), None);
    let victim = t.write("state/victim", "x", 0o600);
    fs::create_dir_all(t.path("state/ucli_agent_tokens")).unwrap();
    r.revoke_parent("../victim").unwrap();
    assert!(std::path::Path::new(&victim).exists());
}

#[test]
fn concurrent_issue_keeps_file_and_digest_consistent() {
    let t = Tmp::in_memory();
    let r = registry(&t);
    std::thread::scope(|s| {
        for i in 0..8 {
            let r = r.clone();
            s.spawn(move || {
                for _ in 0..10 {
                    r.issue_token("p1").unwrap();
                    r.issue_token(&format!("diger{i}")).unwrap();
                }
            });
        }
    });
    assert_eq!(
        r.parent_for_token(&token(&r.token_file("p1"))).as_deref(),
        Some("p1")
    );
    for i in 0..8 {
        let name = format!("diger{i}");
        assert_eq!(
            r.parent_for_token(&token(&r.token_file(&name))),
            Some(name),
            "kayıt kayboldu"
        );
    }
}

#[test]
fn a_broken_entropy_source_or_unwritable_directory_issues_nothing() {
    let t = Tmp::new();
    let broken = registry(&t).with_sources(Sources {
        entropy: |_| Err(std::io::Error::from_raw_os_error(libc::EACCES)),
        ..Default::default()
    });
    assert_eq!(broken.issue_token("p1"), Err("PermissionError".to_string()));
    assert!(!std::path::Path::new(&t.path("state/ucli_agent_tokens")).exists());
    t.write("state/ucli_agent_tokens", "dosya", 0o600);
    assert_eq!(
        registry(&t).issue_token("p1"),
        Err("FileExistsError".to_string())
    );
}

fn build(p: &dyn Probe, t: &Tmp, dry_run: bool) -> (Result<String, String>, BuildOutput) {
    let settings = Settings::default();
    let catalog = ModelCatalog::default();
    let paths = t.paths();
    let providers = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: p,
    };
    let mut out = BuildOutput {
        dry_run,
        ..Default::default()
    };
    let cwd = t.path("work");
    let args = BuildArgs {
        cwd: &cwd,
        model: "glm-5.3",
        effort: "medium",
        session_name: "sess1",
        ..Default::default()
    };
    let cmd = providers
        .build_inner_command(Cli::Ucli, &args, &mut out)
        .map_err(|e| e.to_string());
    (cmd, out)
}

#[test]
fn a_dry_run_build_issues_no_token_and_writes_nothing() {
    let t = Tmp::new();
    let _g = support::spawn_guard();
    t.script(
        "bin/ucli",
        "echo '--allow-agents <V> --metrics-file <V> --interactive'",
    );
    let p = t.probe();
    let (cmd, out) = build(&p, &t, true);
    let cmd = cmd.unwrap();
    assert!(
        cmd.contains("--allow-agents") && cmd.contains("--metrics-file"),
        "{cmd}"
    );
    assert!(out.effects.is_empty() || out.dry_run);
    assert_eq!(fs::read_dir(t.path("state")).unwrap().count(), 0);
    let (cmd, out) = build(&p, &t, false);
    effects::apply_all(&out.effects).unwrap();
    let token = token(&p.agents().token_file("sess1"));
    let cmd = cmd.unwrap();
    assert!(!cmd.contains(&token), "token komut satırında");
    assert!(cmd.contains("UCLI_AGENT_TOKEN=\"$(cat "));
    assert!(!format!("{:?}", out.diags).contains(&token));
}

fn diag_lines(path: &str) -> Vec<Value> {
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

#[test]
fn diag_log_appends_ordered_json_lines_rotates_and_never_fails_the_caller() {
    let t = Tmp::new();
    let log = DiagLog::from_env(&t.paths(), &t.env(&[("CLAUDEOPS_DIAG_LOG", "")]));
    assert_eq!(log.path(), t.path("state/diag.log"));
    assert!(log.log(
        "olay",
        &[
            ("name", json!("ğ")),
            ("n", json!(3)),
            ("event", json!("ezdi"))
        ]
    ));
    let raw = fs::read_to_string(log.path()).unwrap();
    assert!(
        raw.starts_with("{\"ts\": \"")
            && raw.ends_with("\"event\": \"ezdi\", \"name\": \"ğ\", \"n\": 3}\n"),
        "{raw}"
    );
    let ts = diag_lines(log.path())[0]["ts"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(ts.len(), 19, "{ts}");

    fs::write(log.path(), vec![b'x'; diaglog::MAX_BYTES as usize + 1]).unwrap();
    assert!(log.log("sonra", &[]));
    assert_eq!(diag_lines(log.path()).len(), 1);
    assert_eq!(
        fs::metadata(format!("{}.1", log.path())).unwrap().len(),
        diaglog::MAX_BYTES + 1
    );

    let over = DiagLog::from_env(
        &t.paths(),
        &t.env(&[("CLAUDEOPS_DIAG_LOG", &t.path("work/baska.log"))]),
    );
    assert!(over.log("a", &[]));
    assert!(!DiagLog::new(t.path("yok/dizin/diag.log")).log("a", &[]));
    let fifo = t.path("work/boru");
    mkfifo(&fifo);
    assert!(!DiagLog::new(fifo).log("a", &[]));

    let seen = Arc::new(Mutex::new(Vec::new()));
    let sink = seen.clone();
    let mirrored = over.with_mirror(Arc::new(move |stream, entry| {
        sink.lock()
            .unwrap()
            .push(format!("{stream} {}", entry.dumps()));
    }));
    assert!(mirrored.log("b", &[]));
    assert!(seen.lock().unwrap()[0].starts_with("diag {\"ts\""));
}

#[test]
fn concurrent_diag_writers_never_interleave_lines() {
    let t = Tmp::new();
    let log = DiagLog::new(t.path("state/diag.log"));
    std::thread::scope(|s| {
        for i in 0..8 {
            let log = log.clone();
            s.spawn(move || {
                let big = "y".repeat(20_000);
                for _ in 0..25 {
                    assert!(log.log("olay", &[("i", json!(i)), ("veri", json!(big))]));
                }
            });
        }
    });
    assert_eq!(diag_lines(log.path()).len(), 200);
}

#[test]
fn realpath_handles_links_loops_and_missing_parts() {
    let t = Tmp::new();
    fs::create_dir_all(t.path("work/a/b")).unwrap();
    symlink("a/b", t.path("work/k")).unwrap();
    symlink("dongu2", t.path("work/dongu1")).unwrap();
    symlink("dongu1", t.path("work/dongu2")).unwrap();
    let cwd = t.path("work");
    assert_eq!(pathexec::realpath("k/yok/..", &cwd), t.path("work/a/b"));
    assert_eq!(
        pathexec::realpath("dongu1/x", &cwd),
        t.path("work/dongu1/x")
    );
    assert_eq!(pathexec::realpath("", &cwd), cwd);
    // uzun bağlantı zinciri yığını taşırmaz
    for i in 0..400 {
        symlink(format!("z{}", i + 1), t.path(&format!("work/z{i}"))).unwrap();
    }
    assert!(pathexec::realpath("z0", &cwd).starts_with(&cwd));
}

fn toolchain_dir(t: &Tmp, name: &str) {
    for tool in ["cargo", "rustc"] {
        t.write(
            &format!("home/.rustup/toolchains/{name}/bin/{tool}"),
            "",
            0o644,
        );
    }
}

#[test]
fn rust_toolchain_never_silently_picks_another_one() {
    let t = Tmp::new();
    let pick = |env: &[(&str, &str)]| {
        t.probe_with(t.env(env), Default::default())
            .rust_toolchain()
    };
    assert!(pick(&[]).unwrap_err().contains("bulunamadı"));
    toolchain_dir(&t, "stable-x86_64-unknown-linux-gnu");
    assert!(pick(&[])
        .unwrap()
        .root
        .ends_with("stable-x86_64-unknown-linux-gnu"));
    assert!(pick(&[("RUSTUP_TOOLCHAIN", "stable")]).is_ok());
    assert!(pick(&[("RUSTUP_TOOLCHAIN", "nightly")])
        .unwrap_err()
        .contains("nightly"));
    toolchain_dir(&t, "1.98.0-x86_64-unknown-linux-gnu");
    assert!(pick(&[]).unwrap_err().contains("belirsiz"));
    t.write(
        "home/.rustup/settings.toml",
        "version = \"12\"\ndefault_toolchain = \"1.98.0-x86_64-unknown-linux-gnu\"\n",
        0o600,
    );
    assert!(pick(&[])
        .unwrap()
        .cargo
        .ends_with("1.98.0-x86_64-unknown-linux-gnu/bin/cargo"));
    assert!(pick(&[("RUSTUP_TOOLCHAIN", "stable")])
        .unwrap()
        .root
        .ends_with("stable-x86_64-unknown-linux-gnu"));
    t.write(
        "home/.rustup/settings.toml",
        "default_toolchain = \"stable\"\n",
        0o600,
    );
    assert!(pick(&[])
        .unwrap()
        .root
        .ends_with("stable-x86_64-unknown-linux-gnu"));
}

#[test]
fn exec_flags_use_the_discovered_binaries_and_only_allowed_env() {
    let t = Tmp::new();
    toolchain_dir(&t, "1.98.0-x");
    let p = t.probe();
    let tc = p.rust_toolchain().unwrap();
    let settings = Settings::default();
    let opts = cops_providers::ucli_opts::validate_opts(
        &json!({"exec_cmds": ["git"], "exec_toolchain": "rust"}),
        &settings,
        &|| p.rust_toolchain(),
    )
    .unwrap();
    let argv =
        cops_providers::ucli_opts::exec_flags(&opts, &|| p.rust_toolchain(), &|d| p.is_dir(d));
    let after = |flag: &str| -> Vec<&str> {
        argv.windows(2)
            .filter(|w| w[0] == flag)
            .map(|w| w[1].as_str())
            .collect()
    };
    assert_eq!(
        after("--allow-exec-cmd"),
        [format!("git,{},{}", tc.cargo, tc.rustc)]
    );
    assert_eq!(after("--exec-bind-ro"), [tc.root.as_str()]);
    assert!(after("--exec-env").iter().all(|e| !e.starts_with("RUSTC=")));
    assert!(after("--exec-env").contains(&"RUSTUP_TOOLCHAIN=1.98.0-x"));
}

#[test]
fn sqlite_reads_a_wal_database_while_the_writer_is_open_and_after_it_closes() {
    let t = Tmp::new();
    let db = t.path("work/wal.db");
    let p = t.probe();
    let sql = "SELECT sum(v) FROM t WHERE ? IS NOT NULL";
    let writer = rusqlite::Connection::open(&db).unwrap();
    writer
        .execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE t(v INTEGER); INSERT INTO t VALUES(5);")
        .unwrap();
    assert_eq!(p.sqlite_cell(&db, sql, "x"), Some(SqlCell::Int(5)));
    writer.execute_batch("INSERT INTO t VALUES(6)").unwrap();
    assert_eq!(p.sqlite_cell(&db, sql, "x"), Some(SqlCell::Int(11)));
    drop(writer);
    assert_eq!(p.sqlite_cell(&db, sql, "x"), Some(SqlCell::Int(11)));
}

#[test]
fn failed_turn_records_over_the_read_limit_are_ignored_by_the_real_reader() {
    let t = Tmp::new();
    let path = t.write("work/buyuk", b"", 0o600);
    fs::OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len((64 << 20) + 1)
        .unwrap();
    assert_eq!(t.probe().read_bytes(&path, 64 << 20), None);
    assert_eq!(t.probe().read_tail(&path, 16).map(|d| d.len()), Some(16));
}

#[test]
fn a_corrupt_agent_registry_is_copied_aside_and_an_unreadable_one_is_not_overwritten() {
    let t = Tmp::new();
    let r = registry(&t);
    let state = t.write("state/ucli_agents.json", "{bozuk", 0o600);
    r.issue_token("p1").unwrap();
    let copies: Vec<String> = fs::read_dir(t.path("state"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with("ucli_agents.json.corrupt-"))
        .collect();
    assert_eq!(copies.len(), 1);
    let copy = t.path(&format!("state/{}", copies[0]));
    assert_eq!(
        (fs::read_to_string(&copy).unwrap(), mode(&copy)),
        ("{bozuk".to_string(), 0o600)
    );
    fs::set_permissions(&state, std::os::unix::fs::PermissionsExt::from_mode(0o000)).unwrap();
    // SAFETY: `getuid` her zaman başarılı.
    if unsafe { libc::getuid() } != 0 {
        assert_eq!(r.issue_token("p2"), Err("PermissionError".to_string()));
        assert!(!std::path::Path::new(&r.token_file("p2")).exists());
    }
}

#[test]
fn a_non_object_parent_record_fails_the_spawn_before_any_token_is_written() {
    let t = Tmp::new();
    let _g = support::spawn_guard();
    t.script("bin/ucli", "echo '--allow-agents <V>'");
    let body = r#"{"parents": {"sess1": 5}, "children": {}}"#;
    let state = t.write("state/ucli_agents.json", body, 0o600);
    let p = t.probe();
    assert_eq!(
        p.agents().issue_token("sess1"),
        Err("TypeError".to_string())
    );
    let (cmd, _) = build(&p, &t, false);
    assert!(cmd.unwrap_err().contains("nesne değil"));
    assert!(!std::path::Path::new(&p.agents().token_file("sess1")).exists());
    assert_eq!(fs::read_to_string(state).unwrap(), body);
}

/// Proje dizini adı Python `_encode_cwd` ile aynı: ASCII harf/rakam dışındaki HER kod noktası tek `-` (TODO rs-prov G2).
#[test]
fn project_dirs_encode_cwd_like_python() {
    let cases = [
        "/w/p1",
        "/home/u/BLM308_veri_madenciliği",
        "/a b/c.d/😀/İ",
        "",
        "rel/yol",
    ];
    let code = r#"
import json, sys
sys.path.insert(0, sys.argv[1] + "/py")
from claudeops.providers import claude_provider as c
print(json.dumps([c.os.path.join(c.PROJECTS_DIR, c._encode_cwd(x)) for x in json.loads(sys.argv[2])]))
"#;
    let t = tempfile::TempDir::new().unwrap();
    let home = t.path().to_str().unwrap().to_string();
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let out = std::process::Command::new("python3")
        .args(["-I", "-c", code, repo.to_str().unwrap()])
        .arg(serde_json::to_string(&cases).unwrap())
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", &home)
        .env("CLAUDEOPS_DIR", t.path().join("state"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let want: Vec<String> = serde_json::from_slice(&out.stdout).unwrap();
    let dirs = HomeProjects::new(&home);
    for (cwd, want) in cases.iter().zip(want) {
        assert_eq!(dirs.claude_project_dir(cwd), want, "{cwd:?}");
    }
}

/// WAL kipinde yazılmış veritabanını Python (`mode=ro`) ve gerçek okuyucu aynı okur: yazar kapanmadan ölmüş, temiz
/// kapanmış, `-shm`siz kopya, salt okunur dizindeki kopya (TODO rs-prov G2). Her okuyucu kendi kopyasını açar.
#[test]
fn wal_databases_read_the_same_as_python() {
    let code = r#"
import json, os, shutil, sqlite3, sys
sys.path.insert(0, sys.argv[1] + "/py")
from claudeops.sqlite_uri import ro_sqlite_uri
root = sys.argv[2]
sql = "SELECT sum(v) FROM t WHERE ? IS NOT NULL"
def make(path, close):
    w = sqlite3.connect(path)
    w.executescript("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE t(v INTEGER); INSERT INTO t VALUES(5);")
    w.execute("INSERT INTO t VALUES(6)"); w.commit()
    if close:
        w.close()
    return w
states = ["olu-yazar", "kapali", "shm-yok", "salt-okunur-dizin", "salt-okunur-wal"]
src = os.path.join(root, "kaynak"); os.makedirs(src)
keep = make(os.path.join(src, "acik.db"), False)
make(os.path.join(src, "kapali.db"), True)
out = {}
for state in states:
    for who in ("py", "rs"):
        d = os.path.join(root, who, state); os.makedirs(d)
        name = "kapali.db" if state in ("kapali", "salt-okunur-dizin") else "acik.db"
        suffixes = [""] if name == "kapali.db" else ["", "-wal"] if state in ("shm-yok", "salt-okunur-wal") else ["", "-wal", "-shm"]
        for s in suffixes:
            shutil.copy(os.path.join(src, name + s), os.path.join(d, "x.db" + s))
        if state.startswith("salt-okunur"):
            os.chmod(d, 0o500)
    try:
        c = sqlite3.connect(ro_sqlite_uri(os.path.join(root, "py", state, "x.db")), uri=True, timeout=2.0)
        out[state] = c.execute(sql, ("x",)).fetchone()[0]
        c.close()
    except sqlite3.Error:
        out[state] = None
print(json.dumps(out), flush=True)
os._exit(0)
"#;
    let t = Tmp::new();
    let root = t.path("work/wal-parite");
    fs::create_dir_all(&root).unwrap();
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let out = std::process::Command::new("python3")
        .args(["-I", "-c", code, repo.to_str().unwrap(), &root])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", t.path("work"))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let want: serde_json::Map<String, Value> = serde_json::from_slice(&out.stdout).unwrap();
    let probe = t.probe();
    let mut got = serde_json::Map::new();
    for state in want.keys() {
        let db = format!("{root}/rs/{state}/x.db");
        let cell = probe.sqlite_cell(&db, "SELECT sum(v) FROM t WHERE ? IS NOT NULL", "x");
        got.insert(
            state.clone(),
            match cell {
                Some(cops_providers::SqlCell::Int(i)) => json!(i),
                None => Value::Null,
                other => panic!("{state}: {other:?}"),
            },
        );
        for who in ["py", "rs"] {
            let dir = format!("{root}/{who}/{state}");
            fs::set_permissions(dir, std::os::unix::fs::PermissionsExt::from_mode(0o700)).unwrap();
        }
    }
    println!("{want:?}");
    assert_eq!(got, want);
    assert_eq!(want["olu-yazar"], json!(11));
}
