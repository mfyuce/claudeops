//! Sahte `/proc` ağacı (geçici dizin): gerçek süreçlere ve durum dizinine dokunmaz.

use cops_procscan::status::{OrphanTracker, Probe};
use cops_procscan::transcript::jsonl_path_for;
use cops_procscan::usage::{Totals, Usage, UsageCache, UsageReader};
use cops_procscan::{find_by_name, find_sessions, Config, CpuMode, Session};
use std::ffi::CString;
use std::fs;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::{Duration, Instant};
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
        find_sessions(&self.cfg, CpuMode::Skip).sessions
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
    let scan = find_sessions(&f.cfg, CpuMode::Skip);
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
        let sessions = find_sessions(&cfg, CpuMode::Skip).sessions;
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

/// TBD#365: nesne olmayan kök ya da dizgi olmayan `name` taramayı düşürmez (Python da düşürmüyor artık); atlanır ve
/// `session_files_bad`a girer. Sıfır/negatif pid atlanır (sayılmaz: Python'da da sessiz).
#[test]
fn bad_session_files_are_skipped_and_counted() {
    let f = Fake::new();
    f.add(P {
        pid: 50,
        cmd: "claude",
        cwd: "/work/ok",
        ..Default::default()
    });
    f.session_json("50.json", r#"{"pid":50,"name":"iyi","sessionId":"s1"}"#);
    f.session_json("a.json", "[1,2]");
    f.session_json("b.json", r#""metin""#);
    f.session_json("c.json", r#"{"pid":50,"name":5}"#);
    f.session_json("d.json", r#"{"pid":50,"name":["x"]}"#);
    f.session_json("e.json", r#"{"name":{"a":1}}"#);
    for (i, pid) in ["-1", "0", "\"-50\"", "-50.0"].iter().enumerate() {
        f.session_json(
            &format!("n{i}.json"),
            &format!(r#"{{"pid":{pid},"name":"neg{i}","cwd":"/tmp"}}"#),
        );
    }
    let scan = find_sessions(&f.cfg, CpuMode::Skip);
    let names: Vec<&str> = scan.sessions.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, ["iyi"]);
    assert_eq!(scan.sessions[0].sid.as_deref(), Some("s1"));
    assert_eq!(scan.diag.session_files_bad, 5);
    assert_eq!(scan.diag.session_files_invalid, 0);
}

/// Birleştirme kapısı (TBD#365): Python `os.kill(2**32, 0)`/`int(inf)` OverflowError ile taramayı düşürüyordu; şimdi
/// iki dilde de `pid_t`ye (i32) sığmayan pid atlanır ve sayılır. JSON'da `Infinity`/`1e400` serde'de geçersiz dosyadır
/// (`session_files_invalid`; Python `session_file`). Taşan pid'in `/proc` girdisi olsa bile kabul edilmez.
#[test]
fn overflowing_pids_are_skipped_and_counted() {
    let f = Fake::new();
    f.add(P {
        pid: 50,
        cmd: "claude",
        cwd: "/work/ok",
        ..Default::default()
    });
    f.add(P {
        pid: 2_147_483_648,
        cwd: "/work/tasan",
        ..Default::default()
    });
    f.session_json("50.json", r#"{"pid":50,"name":"iyi"}"#);
    for (i, pid) in [
        "2147483648",
        "4294967296",
        "9223372036854775808",
        "18446744073709551621",
        "1e30",
        "\"99999999999999999999999\"",
        "\"2147483648\"",
    ]
    .iter()
    .enumerate()
    {
        f.session_json(
            &format!("o{i}.json"),
            &format!(r#"{{"pid":{pid},"name":"tasan{i}","cwd":"/tmp"}}"#),
        );
    }
    f.session_json("inf.json", r#"{"pid":Infinity,"name":"sonsuz","cwd":"/tmp"}"#);
    f.session_json("big.json", r#"{"pid":1e400,"name":"dev","cwd":"/tmp"}"#);
    // C int'in alt ucu: Python'da `pid <= 0` önce gelir, sayılmaz
    f.session_json("neg.json", r#"{"pid":-9223372036854775809,"name":"eksi","cwd":"/tmp"}"#);
    let scan = find_sessions(&f.cfg, CpuMode::Skip);
    let names: Vec<&str> = scan.sessions.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, ["iyi"]);
    assert_eq!(scan.diag.session_files_bad, 7);
    assert_eq!(scan.diag.session_files_invalid, 2);
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
    let v = find_sessions(&f.cfg, CpuMode::Custom(&mut wait)).sessions;
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
    // TBD#365: sid yol parçası olarak süzülür (dizin dışı ve alt dizin dosyası var olsa da)
    fs::write(dir.join("../x.jsonl"), "").unwrap();
    fs::create_dir_all(dir.join("sub")).unwrap();
    fs::write(dir.join("sub/y.jsonl"), "").unwrap();
    for sid in ["../x", "sub/y", "/abs", "a\0b"] {
        assert_eq!(jsonl_path_for(&f.cfg, "/work/proj", Some(sid)), None, "{sid:?}");
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

/// Python `test_discovery_sid`: canlı json sid'i bayat argv sid'ini yener, sid'siz json argv sid'ini silmez,
/// başka CLI'nin json kaydı (pid yeniden kullanımı) sid bağışlamaz, her pid kendi sid'ini alır.
#[test]
fn json_sid_merge_rules_like_python() {
    let f = Fake::new();
    let claude = |pid, name: &str, resume: Option<&str>| {
        let cmd = match resume {
            Some(r) => format!("claude --remote-control {name} --model claude-sonnet-5-5 --resume {r}"),
            None => format!("claude --remote-control {name} --model claude-sonnet-5-5"),
        };
        f.add(P {
            pid,
            cmd: Box::leak(cmd.into_boxed_str()),
            ..Default::default()
        });
    };
    claude(80, "stale", Some("old-sid"));
    f.session_json("80.json", r#"{"pid":80,"name":"stale","sessionId":"new-sid"}"#);
    claude(81, "keep", Some("sid-a"));
    f.session_json("81.json", r#"{"pid":81,"name":"keep"}"#);
    claude(82, "one", None);
    claude(83, "two", None);
    f.session_json("82.json", r#"{"pid":82,"name":"one","sessionId":"sid-1"}"#);
    f.session_json("83.json", r#"{"pid":83,"name":"two","sessionId":"sid-2"}"#);
    f.add(P {
        pid: 84,
        cmd: "codex",
        env: &["COPS_NAME=cx"],
        ..Default::default()
    });
    f.session_json("84.json", r#"{"pid":84,"name":"cx","sessionId":"claude-sid"}"#);
    let v = f.scan();
    let s = by_name(&v, "stale");
    assert_eq!(
        (s.sid.as_deref(), s.resumed, s.is_fresh()),
        (Some("new-sid"), Some(true), false)
    );
    assert_eq!(by_name(&v, "keep").sid.as_deref(), Some("sid-a"));
    assert_eq!(
        (by_name(&v, "one").sid.as_deref(), by_name(&v, "two").sid.as_deref()),
        (Some("sid-1"), Some("sid-2"))
    );
    // codex satırı sid'siz; json'un claude satırı aynı (ad, pid) anahtarında ezilir (Python dict gibi)
    let cx: Vec<_> = v.iter().filter(|s| s.name == "cx").collect();
    assert_eq!(
        cx.iter().map(|s| (s.cli.as_str(), s.sid.as_deref())).collect::<Vec<_>>(),
        [("codex", None)]
    );
}

#[test]
fn sessions_carry_proc_id_and_verify_detects_reuse() {
    use cops_procscan::procfs::ProcFs;
    use cops_procscan::{Liveness, ProcId};
    let f = Fake::new();
    f.add(P {
        pid: 90,
        cmd: "claude --remote-control a",
        ..Default::default()
    });
    f.add(P {
        pid: 91,
        uid: OTHER,
        cmd: "x",
        ..Default::default()
    });
    let v = f.scan();
    let id = v[0].proc_id.expect("kimlik yok");
    assert_eq!(
        id,
        ProcId {
            pid: 90,
            start_time: 900
        }
    );
    // JSON çıktısına girmez (Python paritesi)
    assert!(serde_json::to_value(&v[0]).unwrap().get("proc_id").is_none());
    let pf = ProcFs::new(&f.cfg.proc_root, ME);
    assert_eq!(pf.verify(&id), Liveness::Same);
    assert_eq!(
        pf.verify(&ProcId {
            pid: 91,
            start_time: 910
        }),
        Liveness::NotOwn
    );
    assert_eq!(pf.verify(&ProcId { pid: 92, start_time: 1 }), Liveness::Gone);
    // aynı pid, başka başlangıç: yeniden kullanılmış
    fs::write(
        f.root.join("proc/90/stat"),
        "90 (x) S 1 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 12345 0 0\n",
    )
    .unwrap();
    assert_eq!(pf.verify(&id), Liveness::Replaced);
    fs::write(f.root.join("proc/90/stat"), "bozuk").unwrap();
    assert_eq!(pf.verify(&id), Liveness::Unknown);
    fs::write(f.root.join("proc/90/status"), "Name:\tx\n").unwrap();
    assert_eq!(pf.verify(&id), Liveness::Unknown, "Uid satırı yok: okunamadı, 'yok' değil");
}

/// Bozuk `/proc` alanları paniğe ya da yanlış satıra yol açmaz; Python gibi davranılır, sayaçlar ayrımı taşır.
#[test]
fn broken_proc_fields() {
    let f = Fake::new();
    for (pid, name) in [
        (100, "badstat"),
        (101, "nouid"),
        (102, "badutf"),
        (103, "nocwd"),
        (104, "badenv"),
    ] {
        f.add(P {
            pid,
            cmd: Box::leak(format!("claude --remote-control {name}").into_boxed_str()),
            ..Default::default()
        });
    }
    let d = |pid: u32| f.root.join("proc").join(pid.to_string());
    fs::write(d(100).join("stat"), "100 bozuk").unwrap();
    f.session_json("100.json", r#"{"pid":100,"name":"badstat","procStart":"1"}"#);
    fs::write(d(101).join("status"), "Name:\tx\nUid:\tabc\n").unwrap();
    fs::write(d(102).join("cmdline"), b"claude\0--remote-control\0bad\xffname\0").unwrap();
    fs::remove_file(d(103).join("cwd")).unwrap();
    fs::write(d(104).join("environ"), b"\xff\0=x\0NOEQ\0COPS_NAME\0").unwrap();
    f.add(P {
        pid: 105,
        cmd: "codex",
        ..Default::default()
    });
    fs::write(d(105).join("environ"), b"\xff\0=x\0NOEQ\0COPS_NAME=\0").unwrap();
    let scan = find_sessions(&f.cfg, CpuMode::Skip);
    let names: Vec<_> = scan.sessions.iter().map(|s| s.name.as_str()).collect();
    // stat bozuk: procStart denetimi atlanır (Python `except: pass`), kimlik yok
    assert!(names.contains(&"badstat"));
    assert_eq!(by_name(&scan.sessions, "badstat").proc_id, None);
    assert!(!names.contains(&"nouid"), "uid okunamayan süreç bizim sayılmaz");
    assert!(names.contains(&"bad\u{fffd}name"));
    assert!(!names.contains(&"nocwd"));
    assert!(names.contains(&"badenv"));
    assert!(names.contains(&"codex-105"), "boş COPS_NAME = ad yok: {names:?}");
    let diag = &scan.diag;
    assert_eq!((diag.procs_unreadable, diag.cwd_unreadable), (1, 1), "{diag:?}");
    assert!(diag.stat_unreadable >= 1, "{diag:?}");
    assert!(diag.proc_root_error.is_none() && diag.sessions_dir_error.is_none());
}

/// Okunamayan `/proc` kökü ve `sessions/` "yok"tan ayrılır; sonuç yine Python gibi boştur.
#[test]
fn unreadable_roots_are_not_absence() {
    let f = Fake::new();
    f.add(P {
        pid: 110,
        cmd: "claude --remote-control a",
        ..Default::default()
    });
    let clean = find_sessions(&f.cfg, CpuMode::Skip);
    assert!(clean.diag.is_clean(), "{:?}", clean.diag);

    let sessions = f.root.join("claude/sessions");
    fs::remove_dir(&sessions).unwrap();
    assert!(
        find_sessions(&f.cfg, CpuMode::Skip).diag.is_clean(),
        "sessions/ yokluğu hata değil"
    );
    fs::write(&sessions, "dosya").unwrap();
    let s = find_sessions(&f.cfg, CpuMode::Skip);
    assert!(s.diag.sessions_dir_error.is_some());
    assert_eq!(s.sessions.len(), 1);

    let mut cfg = f.cfg.clone();
    cfg.proc_root = f.root.join("yok");
    let s = find_sessions(&cfg, CpuMode::Skip);
    assert!(s.sessions.is_empty());
    assert!(s.diag.proc_root_error.is_some(), "süreç listesi bilinmiyor, 'yok' değil");
}

/// Bozuk agy dosyaları boş sayılır (Python `_load_agy_sids`/önbellek okuması gibi), sayaç artar.
#[test]
fn broken_agy_files() {
    let f = Fake::new();
    f.add(P {
        pid: 120,
        cmd: "agy",
        env: &["COPS_NAME=ag"],
        ..Default::default()
    });
    let sid_of = |f: &Fake| {
        let s = find_sessions(&f.cfg, CpuMode::Skip);
        (
            by_name(&s.sessions, "ag").sid.clone(),
            s.diag.agy_files_unreadable,
            s.agy_learned,
        )
    };
    // dosyalar yok: hata değil
    assert_eq!(sid_of(&f), (None, 0, vec![]));
    fs::write(&f.cfg.agy_cache, r#"{"/work/proj": " c1 "}"#).unwrap();
    assert_eq!(sid_of(&f), (Some("c1".into()), 0, vec![("ag".into(), "c1".into())]));
    // başka ada kayıtlı: çalınmaz
    fs::write(&f.cfg.agy_sids, r#"{"baska": "c1"}"#).unwrap();
    assert_eq!(sid_of(&f).0, None);
    for bad in [&b"[]"[..], b"{bozuk", b"\xff\xfe", b"", b"null"] {
        fs::write(&f.cfg.agy_sids, bad).unwrap();
        assert_eq!(
            sid_of(&f),
            (Some("c1".into()), 1, vec![("ag".into(), "c1".into())]),
            "{bad:?}"
        );
    }
    fs::remove_file(&f.cfg.agy_sids).unwrap();
    for bad in [&br#"{"/work/proj": 5}"#[..], br#"{"/work/proj": "  "}"#, b"[1]"] {
        fs::write(&f.cfg.agy_cache, bad).unwrap();
        let (sid, n, _) = sid_of(&f);
        assert_eq!(sid, None, "{bad:?}");
        assert_eq!(n, u32::from(bad == b"[1]"), "{bad:?}");
    }
}

/// Python `test_mirror_window`/`test_orphan_cli`/`test_web_ucli_flags` karşılıkları: başka kullanıcının görüntüleyicisi
/// sayılmaz, cmdline'ı kaybolan süreç atlanır, fd/0 okunamazsa terminal "kayıp" sayılmaz, ucli rozetleri bozuk değerde.
#[test]
fn mirrors_terminal_and_ucli_flag_edges() {
    use cops_procscan::mirrors::running_mirrors;
    let f = Fake::new();
    f.add(P {
        pid: 130,
        cmd: "python3 -m claudeops watch yuhem:a",
        ..Default::default()
    });
    f.add(P {
        pid: 131,
        uid: OTHER,
        cmd: "python3 -m claudeops watch yuhem:a",
        ..Default::default()
    });
    f.add(P {
        pid: 132,
        cmd: "python3 -m claudeops watch yuhem:b",
        ..Default::default()
    });
    fs::remove_file(f.root.join("proc/132/cmdline")).unwrap(); // tarama sırasında kayboldu
    assert_eq!(
        running_mirrors(&f.cfg),
        std::collections::BTreeMap::from([("yuhem:a".to_owned(), vec![130])])
    );
    let scan = find_sessions(&f.cfg, CpuMode::Skip);
    assert_eq!(scan.diag.cmdline_unreadable, 1);

    f.add(P {
        pid: 133,
        cmd: "ucli chat --repl --session u --max-cost-usd 1.5 --max-cost-usd bozuk",
        ..Default::default()
    });
    f.add(P {
        pid: 134,
        cmd: "ucli chat --repl --session v",
        ..Default::default()
    });
    f.add(P {
        pid: 135,
        cmd: "claude --remote-control c",
        ..Default::default()
    });
    fs::remove_file(f.root.join("proc/135/fd/0")).unwrap();
    let v = f.scan();
    let probe = Probe::new(&f.cfg);
    let u = probe.ucli_flags(by_name(&v, "u")).unwrap();
    assert_eq!(u.max_cost_usd, None, "son değer bozuk: None (Python gibi)");
    let n = probe.ucli_flags(by_name(&v, "v")).unwrap();
    assert_eq!(
        (n.write, n.exec, n.max_cost_usd, n.ask, n.checks),
        (false, false, None, false, false)
    );
    assert_eq!(probe.ucli_flags(by_name(&v, "c")), None);
    assert!(!probe.terminal_lost(135) && !probe.no_terminal(135));
}

/// Gerçek `/proc`: kendi sürecimizin ppid'i (Python `test_own_ppid`).
#[test]
fn own_ppid_from_real_proc() {
    use cops_procscan::procfs::ProcFs;
    // SAFETY: argümansız libc çağrıları.
    let (uid, ppid) = unsafe { (libc::getuid(), libc::getppid()) };
    let me = ProcFs::new(Path::new("/proc"), uid).own(std::process::id()).unwrap();
    assert_eq!(me.stat().unwrap().ppid, u32::try_from(ppid).unwrap());
}

#[test]
fn find_by_name_is_exact_and_returns_every_process() {
    let f = Fake::new();
    for (pid, name) in [(140, "a"), (141, "a1"), (142, "a"), (143, "ba")] {
        f.add(P {
            pid,
            cmd: Box::leak(format!("claude --remote-control {name}").into_boxed_str()),
            ..Default::default()
        });
    }
    let find = |n: &str| {
        let v = find_by_name(&f.cfg, n, CpuMode::Skip);
        v.iter().map(|s| (s.name.clone(), s.pid)).collect::<Vec<_>>()
    };
    assert_eq!(find("a"), [("a".to_owned(), 140), ("a".to_owned(), 142)]);
    assert_eq!(find("a1"), [("a1".to_owned(), 141)]);
    assert!(find("b").is_empty() && find("A").is_empty() && find("").is_empty());
    // CPU kipi taramaya aktarılır
    let stat = f.root.join("proc/141/stat");
    let mut wait = || {
        fs::write(&stat, stat_line(141, 1, 30)).unwrap();
        Duration::from_millis(300)
    };
    let v = find_by_name(&f.cfg, "a1", CpuMode::Custom(&mut wait));
    assert_eq!((v[0].cpu, v[0].active()), (100.0, true));
}

/// Python `test_discovery_sid`: json kaydı olmayan claude satırı argv'yi izler; claude dışı CLI'de sid argv'den,
/// `is_fresh` sid'in varlığından.
#[test]
fn is_fresh_without_json_entry_for_every_cli() {
    let f = Fake::new();
    for (pid, cmd, env) in [
        (150, "claude --remote-control zz1 --resume sid-a", &[][..]),
        (151, "claude --remote-control zz2", &[]),
        (152, "ucli chat --repl --session uc", &[]),
        (153, "ucli chat --repl", &[]),
        (154, "codex", &["COPS_NAME=cx"]),
        (155, "codex resume U", &["COPS_NAME=cr"]),
    ] {
        f.add(P {
            pid,
            cmd,
            env,
            ..Default::default()
        });
    }
    let got: Vec<_> = f.scan().iter().map(|s| (s.pid, s.sid.clone(), s.is_fresh())).collect();
    let sid = |s: &str| Some(s.to_owned());
    assert_eq!(
        got,
        [
            (150, sid("sid-a"), false),
            (151, None, true),
            (152, sid("uc"), false),
            (153, None, true),
            (154, None, true),
            (155, sid("U"), false),
        ]
    );
}

/// Python `test_status_rows_carry_usage_total_without_blocking`: ilk çağrı beklemeden `None`, sonra ana + alt ajan
/// toplamı; claude olmayan, sid'siz ya da transkriptsiz satır `None`.
#[test]
fn probe_usage_total_claude_exact_sid_without_blocking() {
    let f = Fake::new();
    let dir = f.root.join("claude/projects/-w-b");
    fs::create_dir_all(dir.join("big/subagents")).unwrap();
    let line = |id: &str, cache_read: u64| {
        format!(
            r#"{{"type":"assistant","uuid":"u{id}","requestId":"r{id}","message":{{"id":"{id}","model":"claude-sonnet-5-5","usage":{{"input_tokens":10,"cache_creation_input_tokens":100,"cache_read_input_tokens":{cache_read},"output_tokens":5}}}}}}"#
        ) + "\n"
    };
    for k in ["b0", "b1", "b2"] {
        append(&dir.join("big.jsonl"), &line(k, 1_000_000));
    }
    append(&dir.join("big/subagents/agent-1.jsonl"), &line("sub1", 0));
    append(&dir.join("cx.jsonl"), &line("c0", 1)); // dosya var, satır claude değil
    let probe = Probe::new(&f.cfg);
    let cache = UsageCache::default();
    let row = |cli: &str, sid: Option<&str>| Session {
        name: "big".into(),
        pid: 2,
        cwd: "/w/b".into(),
        cli: cli.into(),
        sid: sid.map(str::to_owned),
        ..Default::default()
    };
    let total = |s: &Session| -> Option<Usage> { probe.usage_total(&f.cfg, &cache, s) };
    let big = row("claude", Some("big"));
    assert_eq!(total(&big), None, "ilk çağrı beklemez");
    let t = Instant::now();
    let got = loop {
        if let Some(u) = total(&big) {
            break u;
        }
        assert!(t.elapsed() < Duration::from_secs(5), "arka plan yenilemesi gelmedi");
        std::thread::sleep(Duration::from_millis(10));
    };
    assert_eq!((got.main.turns, got.main.cache_read, got.subagents.n), (3, 3_000_000, 1));
    assert!(got.by_family.contains_key("sonnet"));
    // eleme önbellekten önce: yenileme beklense de değer gelmez
    let others = [
        row("codex", Some("cx")),
        row("claude", None),
        row("claude", Some("")),
        row("claude", Some("yok")),
    ];
    for _ in 0..20 {
        for s in &others {
            assert_eq!(total(s), None, "{} {:?}", s.cli, s.sid);
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

/// Python `test_all_flags`.
#[test]
fn ucli_flags_all_set() {
    let f = Fake::new();
    f.add(P {
        pid: 160,
        cmd: "ucli chat --repl --allow-edit --allow-exec-rust --max-cost-usd 1.5 --ask-dir /x --allow-checks restricted",
        ..Default::default()
    });
    let fl = Probe::new(&f.cfg).ucli_flags(&f.scan()[0]).unwrap();
    assert_eq!(
        (fl.write, fl.exec, fl.max_cost_usd, fl.ask, fl.checks),
        (true, true, Some(1.5), true, true)
    );
}

/// Python `test_process_error_returns_none_and_not_cached`: kaybolan ya da `cmdline`ı okunamayan süreç `None`
/// ("bayrak yok" değil) ve sonraki çağrı yeniden okur.
#[test]
fn ucli_flags_lost_process_is_none_and_not_cached() {
    let f = Fake::new();
    let probe = Probe::new(&f.cfg);
    let s = Session {
        pid: 170,
        cli: "ucli".into(),
        ..Default::default()
    };
    let add = || {
        f.add(P {
            pid: 170,
            cmd: "ucli chat --repl --allow-edit",
            ..Default::default()
        })
    };
    assert_eq!(probe.ucli_flags(&s), None, "süreç yok");
    add();
    assert!(probe.ucli_flags(&s).unwrap().write);
    // sahiplik okunuyor ama cmdline gitmiş (iki okuma arasında çıkan süreç)
    let cmdline = f.root.join("proc/170/cmdline");
    fs::remove_file(&cmdline).unwrap();
    assert_eq!(probe.ucli_flags(&s), None, "cmdline okunamadı");
    fs::write(&cmdline, "ucli\0--repl\0--ask-dir\0/x\0").unwrap();
    let fl = probe.ucli_flags(&s).unwrap();
    assert_eq!((fl.write, fl.ask), (false, true));
}
