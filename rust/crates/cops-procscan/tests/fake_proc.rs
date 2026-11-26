//! Sahte `/proc` ağacı (geçici dizin): gerçek süreçlere ve durum dizinine dokunmaz.

use cops_procscan::status::{OrphanTracker, Probe};
use cops_procscan::transcript::jsonl_path_for;
use cops_procscan::usage::{Totals, UsageReader};
use cops_procscan::{find_sessions, Config, CpuMode, Session};
use std::ffi::CString;
use std::fs;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;
use tempfile::TempDir;

const ME: u32 = 1000;
const OTHER: u32 = 1001;

struct Fake {
    _tmp: TempDir,
    root: PathBuf,
    cfg: Config,
}

struct P<'a> {
    pid: u32,
    ppid: u32,
    uid: u32,
    cmd: &'a str,
    cwd: &'a str,
    env: &'a [&'a str],
    tty: &'a str,
}

impl Default for P<'_> {
    fn default() -> Self {
        P {
            pid: 100,
            ppid: 1,
            uid: ME,
            cmd: "",
            cwd: "/work/proj",
            env: &[],
            tty: "/dev/pts/3",
        }
    }
}

fn stat_line(pid: u32, ppid: u32, ticks: u64) -> String {
    format!(
        "{pid} (x y)) S {ppid} 0 0 0 -1 0 0 0 0 0 {ticks} 0 0 0 20 0 1 0 {} 0 0\n",
        u64::from(pid) * 10
    )
}

impl Fake {
    fn new() -> Self {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().to_path_buf();
        for d in ["proc", "claude/sessions", "claude/projects"] {
            fs::create_dir_all(root.join(d)).unwrap();
        }
        fs::write(root.join("proc/stat"), "cpu 0\nbtime 1000000\n").unwrap();
        let cfg = Config {
            proc_root: root.join("proc"),
            claude_dir: root.join("claude"),
            agy_cache: root.join("agy_cache.json"),
            agy_sids: root.join("agy_sids.json"),
            uid: ME,
            clk_tck: 100,
        };
        Fake { _tmp: tmp, root, cfg }
    }

    fn add(&self, p: P) {
        let d = self.root.join("proc").join(p.pid.to_string());
        fs::create_dir_all(d.join("fd")).unwrap();
        let u = p.uid;
        fs::write(d.join("status"), format!("Name:\tx\nUid:\t{u}\t{u}\t{u}\t{u}\n")).unwrap();
        fs::write(d.join("stat"), stat_line(p.pid, p.ppid, 0)).unwrap();
        let nul = |parts: Vec<&str>| parts.iter().map(|s| format!("{s}\0")).collect::<String>();
        fs::write(d.join("cmdline"), nul(p.cmd.split(' ').filter(|s| !s.is_empty()).collect())).unwrap();
        fs::write(d.join("environ"), nul(p.env.to_vec())).unwrap();
        symlink(p.cwd, d.join("cwd")).unwrap();
        symlink(p.tty, d.join("fd/0")).unwrap();
    }

    fn session_json(&self, file: &str, body: &str) {
        fs::write(self.root.join("claude/sessions").join(file), body).unwrap();
    }

    fn scan(&self) -> Vec<Session> {
        find_sessions(&self.cfg, CpuMode::Skip).unwrap().sessions
    }
}

fn by_name<'a>(v: &'a [Session], n: &str) -> &'a Session {
    v.iter().find(|s| s.name == n).unwrap_or_else(|| panic!("{n} yok: {v:?}"))
}

#[test]
fn discovers_each_cli_and_names() {
    let f = Fake::new();
    f.add(P {
        pid: 10,
        cmd: "/bin/claude --remote-control cl --model claude-sonnet-5-5 --resume S1",
        ..Default::default()
    });
    f.add(P {
        pid: 11,
        cmd: "claude",
        ..Default::default()
    }); // adsız claude görünmez
    f.add(P {
        pid: 12,
        cmd: "codex",
        env: &["A=1", "COPS_NAME=cx"],
        ..Default::default()
    });
    f.add(P {
        pid: 13,
        cmd: "agy",
        ..Default::default()
    });
    f.add(P {
        pid: 14,
        cmd: "ucli chat --repl",
        cwd: "/work/koder",
        ..Default::default()
    });
    f.add(P {
        pid: 15,
        cmd: "claudeops-shell -",
        env: &["COPS_NAME=sh"],
        ..Default::default()
    });
    f.add(P {
        pid: 16,
        cmd: "vim claude",
        ..Default::default()
    });
    f.add(P {
        pid: 17,
        cmd: "python3 -m claudeops watch yuhem:a",
        ..Default::default()
    });
    let scan = find_sessions(&f.cfg, CpuMode::Skip).unwrap();
    let names: Vec<_> = scan.sessions.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, ["cl", "cx", "agy-13", "ucli@koder#14", "sh"]);
    let cl = by_name(&scan.sessions, "cl");
    assert_eq!(
        (cl.sid.as_deref(), cl.resumed, cl.is_fresh()),
        (Some("S1"), Some(true), false)
    );
    assert_eq!(scan.mirrors["yuhem:a"], [17]);
}

#[test]
fn other_users_processes_are_never_read() {
    let f = Fake::new();
    f.add(P {
        pid: 20,
        uid: OTHER,
        cmd: "claude --remote-control yabanci",
        ..Default::default()
    });
    // İçerik dosyaları FIFO: okumaya kalkan kod takılır.
    for file in ["cmdline", "environ", "stat"] {
        let p = f.root.join("proc/20").join(file);
        fs::remove_file(&p).unwrap();
        let c = CString::new(p.as_os_str().as_bytes()).unwrap();
        // SAFETY: geçerli, NUL sonlu yol.
        assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o600) }, 0);
    }
    // sessions json başkasının pid'ini gösteriyor; bizim süreç onun çocuğu.
    f.session_json("20.json", r#"{"pid":20,"name":"yabanci","sessionId":"x"}"#);
    f.add(P {
        pid: 21,
        ppid: 20,
        cmd: "claudeops-shell",
        env: &["COPS_NAME=mine"],
        tty: "/dev/null",
        ..Default::default()
    });
    let cfg = f.cfg.clone();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let sessions = find_sessions(&cfg, CpuMode::Skip).unwrap().sessions;
        let probe = Probe::new(&cfg);
        let flags = (
            probe.is_tmux_backed(21),
            probe.is_tmux_backed(20),
            probe.terminal_lost(20),
            probe.started_at(20),
        );
        tx.send((sessions, flags)).unwrap();
    });
    let (sessions, flags) = rx
        .recv_timeout(Duration::from_secs(10))
        .expect("başka kullanıcının dosyası okundu");
    assert_eq!(sessions.iter().map(|s| s.name.as_str()).collect::<Vec<_>>(), ["mine"]);
    assert_eq!(flags, (false, false, false, None));
}

#[test]
fn json_source_merges_with_proc_scan() {
    let f = Fake::new();
    // canlı sid json'dan, ad spawn adından; bayat adlı json satırı düşer
    f.add(P {
        pid: 30,
        cmd: "claude --remote-control spawn --effort high",
        ..Default::default()
    });
    f.session_json(
        "30.json",
        r#"{"pid":30,"name":"renamed","sessionId":"LIVE","procStart":"300"}"#,
    );
    // yalnız json
    f.add(P {
        pid: 31,
        cmd: "claude",
        cwd: "/work/tui",
        ..Default::default()
    });
    f.session_json("31.json", r#"{"pid":"31","name":"tui","procStart":310}"#);
    // procStart tutmuyor, ölü pid, bozuk dosya
    f.add(P {
        pid: 32,
        cmd: "claude",
        ..Default::default()
    });
    f.session_json("32.json", r#"{"pid":32,"name":"stale","procStart":"1"}"#);
    f.session_json("99.json", r#"{"pid":99,"name":"dead"}"#);
    f.session_json("bad.json", "{");
    let v = f.scan();
    assert_eq!(v.len(), 2, "{v:?}");
    let s = by_name(&v, "spawn");
    assert_eq!((s.sid.as_deref(), s.resumed, s.is_fresh()), (Some("LIVE"), Some(false), true));
    let t = by_name(&v, "tui");
    assert_eq!((t.cwd.as_str(), t.resumed, t.is_fresh()), ("/work/tui", None, true));
}

#[test]
fn background_session_folds() {
    let f = Fake::new();
    for pid in [40, 41] {
        f.add(P {
            pid,
            cmd: "claude --remote-control a",
            ..Default::default()
        });
    }
    f.session_json(
        "40.json",
        r#"{"pid":40,"name":"a","sessionId":"front","kind":"interactive","parkedJobId":"j"}"#,
    );
    f.session_json(
        "41.json",
        r#"{"pid":41,"name":"a","sessionId":"back","kind":"bg","jobId":"j"}"#,
    );
    let v = f.scan();
    assert_eq!(v.len(), 1);
    assert_eq!((v[0].pid, v[0].bg_pid, v[0].sid.as_deref()), (40, Some(41), Some("back")));
}

#[test]
fn cpu_from_two_samples() {
    let f = Fake::new();
    f.add(P {
        pid: 50,
        cmd: "claude --remote-control busy",
        ..Default::default()
    });
    let stat = f.root.join("proc/50/stat");
    let mut wait = || {
        fs::write(&stat, stat_line(50, 1, 45)).unwrap();
        Duration::from_millis(300)
    };
    let v = find_sessions(&f.cfg, CpuMode::Custom(&mut wait)).unwrap().sessions;
    assert_eq!(v[0].cpu, 150.0);
}

#[test]
fn tmux_terminal_and_orphans() {
    let f = Fake::new();
    f.add(P {
        pid: 60,
        cmd: "/usr/bin/tmux -L cops new-session",
        ..Default::default()
    });
    f.add(P {
        pid: 61,
        ppid: 60,
        cmd: "bash",
        ..Default::default()
    });
    f.add(P {
        pid: 62,
        ppid: 61,
        cmd: "claude --remote-control in",
        tty: "/dev/null",
        ..Default::default()
    });
    f.add(P {
        pid: 63,
        cmd: "claude --remote-control lost",
        tty: "/dev/pts/9 (deleted)",
        ..Default::default()
    });
    f.add(P {
        pid: 64,
        cmd: "tmux -L other",
        ..Default::default()
    });
    f.add(P {
        pid: 65,
        ppid: 64,
        cmd: "claude --remote-control plain",
        ..Default::default()
    });
    let probe = Probe::new(&f.cfg);
    assert!(probe.is_tmux_backed(62) && !probe.no_terminal(62));
    assert!(!probe.is_tmux_backed(65) && !probe.no_terminal(65));
    assert!(probe.no_terminal(63) && probe.idle_spin(63, 50.0) && !probe.idle_spin(63, 49.9));
    assert_eq!(probe.started_at(63), Some(1_000_006.3));

    let mut sessions = f.scan();
    sessions.iter_mut().for_each(|s| s.cpu = 90.0);
    let mut tr = OrphanTracker::default();
    let r = tr.report(&probe, &sessions, 0.0);
    assert_eq!((r.len(), r[0].pid, r[0].spinning), (1, 63, false));
    assert!(!tr.report(&probe, &sessions, 599.0)[0].spinning);
    assert!(tr.report(&probe, &sessions, 600.0)[0].spinning);
    sessions.iter_mut().for_each(|s| s.cpu = 1.0);
    assert!(!tr.report(&probe, &sessions, 700.0)[0].spinning);
    sessions.iter_mut().for_each(|s| s.cpu = 90.0);
    assert!(!tr.report(&probe, &sessions, 1000.0)[0].spinning, "kesinti sayacı sıfırlar");
}

#[test]
fn ucli_flags() {
    let f = Fake::new();
    f.add(P {
        pid: 70,
        cmd: "ucli chat --repl --session u --allow-exec-cmd ls --max-cost-usd 2.5 --ask-dir /x",
        ..Default::default()
    });
    let v = f.scan();
    let fl = Probe::new(&f.cfg).ucli_flags(&v[0]).unwrap();
    assert_eq!(
        (fl.write, fl.exec, fl.max_cost_usd, fl.ask, fl.checks),
        (false, true, Some(2.5), true, false)
    );
}

#[test]
fn transcript_requires_exact_sid() {
    let f = Fake::new();
    let dir = f.root.join("claude/projects/-work-proj");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("a.jsonl"), "").unwrap();
    assert_eq!(jsonl_path_for(&f.cfg, "/work/proj", Some("a")), Some(dir.join("a.jsonl")));
    for sid in [None, Some(""), Some("b")] {
        assert_eq!(jsonl_path_for(&f.cfg, "/work/proj", sid), None);
    }
}

fn row(id: &str, req: &str, model: &str, out: u64) -> String {
    format!(
        r#"{{"type":"assistant","requestId":"{req}","message":{{"id":"{id}","model":"{model}","content":[{{"type":"text","text":"\ud800"}}],"usage":{{"input_tokens":10,"output_tokens":{out},"cache_creation_input_tokens":2,"cache_read_input_tokens":3}}}}}}"#
    ) + "\n"
}

fn append(p: &Path, s: &str) {
    fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(p)
        .unwrap()
        .write_all(s.as_bytes())
        .unwrap();
}

#[test]
fn usage_dedups_subagents_and_increments() {
    let tmp = TempDir::new().unwrap();
    let main = tmp.path().join("s.jsonl");
    let mut r = UsageReader::default();
    assert!(r.usage_for_path(&main).is_none());
    append(&main, &row("m1", "r1", "claude-sonnet-5-5", 5));
    append(&main, &row("m1", "r1", "claude-sonnet-5-5", 9)); // aynı tur: büyük olan
    append(&main, &row("m1", "r2", "claude-opus-5-5", 1)); // farklı istek: ayrı tur
    append(&main, &row("m9", "r9", "<synthetic>", 100));
    append(&main, "{\"type\":\"user\",\"message\":{\"usage\":{}}}\nbozuk \"usage\"\n");
    let half = row("m2", "r3", "x", 7);
    append(&main, &half[..20]);
    let u = r.usage_for_path(&main).unwrap();
    assert_eq!(
        u.main,
        Totals {
            input: 20,
            output: 10,
            cache_write: 4,
            cache_read: 6,
            turns: 2
        }
    );
    assert_eq!(u.by_family["sonnet"].output, 9);
    assert_eq!(u.subagents.n, 0);

    append(&main, &half[20..]);
    let sub = tmp.path().join("s/subagents");
    fs::create_dir_all(&sub).unwrap();
    append(&sub.join("agent-1.jsonl"), &row("m1", "r1", "claude-haiku-5-5", 4));
    append(&sub.join("other.jsonl"), &row("m5", "r5", "x", 4));
    let u = r.usage_for_path(&main).unwrap();
    assert_eq!((u.main.turns, u.main.output), (3, 17));
    assert_eq!(
        (u.subagents.n, u.subagents.totals.turns, u.subagents.totals.output),
        (1, 1, 4)
    );
    assert_eq!(
        u.by_family.keys().copied().collect::<Vec<_>>(),
        ["haiku", "opus", "other", "sonnet"]
    );

    fs::write(&main, row("z", "z", "x", 1)).unwrap(); // küçüldü: baştan
    assert_eq!(r.usage_for_path(&main).unwrap().main.turns, 1);
}
