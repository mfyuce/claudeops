//! G8: alt süreç koşucusu, `--help` yoklaması ve MCP kaydı (yalnız geçici dizindeki sahte kabuk betikleri).

#[path = "g8/support.rs"]
mod support;

use cops_providers::real::help::HelpCache;
use cops_providers::real::process::{self, Capture, RunError, Spec};
use cops_providers::{McpRegisterError, Probe};
use std::fs;
use std::sync::Arc;
use std::time::{Duration, Instant};
use support::{spawn_guard, Tmp};

fn run(
    t: &Tmp,
    script: &str,
    timeout_ms: u64,
    stdout: Capture,
    stderr: Capture,
) -> Result<process::Output, RunError> {
    let argv = vec![t.script("bin/s", script)];
    let env = t.env(&[]);
    process::run(&Spec {
        argv: &argv,
        cwd: None,
        env: &env,
        timeout: Duration::from_millis(timeout_ms),
        stdout,
        stderr,
    })
}

/// Süreç hâlâ var mı (zombi de "var" sayılır).
fn alive(pid: i32) -> bool {
    fs::read_to_string(format!("/proc/{pid}/stat"))
        .is_ok_and(|s| !s.rsplit(')').next().unwrap_or("").starts_with(" Z"))
}

fn wait_dead(pid: i32) {
    let start = Instant::now();
    while alive(pid) {
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "süreç {pid} yaşıyor"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn output_exit_code_signals_stdin_and_environment() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let both = Capture::Bounded(1000);
    let out = run(
        &t,
        "read x; printf 'in=[%s] %s' \"$x\" \"$HOME\"; echo err >&2; exit 3",
        5000,
        both,
        both,
    )
    .unwrap();
    assert_eq!(out.code, 3);
    assert_eq!(
        String::from_utf8(out.stdout).unwrap(),
        format!("in=[] {}", t.path("home"))
    );
    assert_eq!(out.stderr, b"err\n");
    assert_eq!(
        run(&t, "kill -TERM $$", 5000, both, both).unwrap().code,
        -15
    );
    let argv = vec![t.path("bin/yok")];
    let env = t.env(&[]);
    let spec = Spec {
        argv: &argv,
        cwd: None,
        env: &env,
        timeout: Duration::from_secs(1),
        stdout: both,
        stderr: both,
    };
    assert!(matches!(process::run(&spec), Err(RunError::Spawn(_))));
    assert!(matches!(
        process::run(&Spec { argv: &[], ..spec }),
        Err(RunError::Spawn(_))
    ));
}

#[test]
fn a_timeout_kills_the_whole_process_group_and_waits() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let pids = t.path("work/pids");
    let script = format!("sleep 60 & echo $! $$ > {pids}; wait");
    let start = Instant::now();
    let r = run(&t, &script, 700, Capture::Bounded(100), Capture::Discard);
    assert!(matches!(r, Err(RunError::Timeout)), "{r:?}");
    assert!(start.elapsed() < Duration::from_secs(10));
    let recorded = fs::read_to_string(pids).unwrap();
    for pid in recorded.split_whitespace() {
        wait_dead(pid.parse().unwrap());
    }
}

#[test]
fn a_grandchild_holding_the_pipe_hits_the_deadline_like_python() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let pid = t.path("work/pid");
    let r = run(
        &t,
        &format!("sleep 60 & echo $! > {pid}; echo bitti"),
        700,
        Capture::Bounded(100),
        Capture::Discard,
    );
    assert!(matches!(r, Err(RunError::Timeout)), "{r:?}");
    wait_dead(fs::read_to_string(pid).unwrap().trim().parse().unwrap());
}

#[test]
fn closed_pipes_with_a_running_child_still_time_out() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let start = Instant::now();
    let r = run(
        &t,
        "exec >&- 2>&-; sleep 60",
        400,
        Capture::Bounded(100),
        Capture::Bounded(100),
    );
    assert!(matches!(r, Err(RunError::Timeout)), "{r:?}");
    assert!(start.elapsed() < Duration::from_secs(10));
}

#[test]
fn bounded_capture_overflows_and_tail_capture_keeps_the_end() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let start = Instant::now();
    let r = run(
        &t,
        "yes aaaaaaaaaaaaaaa",
        20_000,
        Capture::Bounded(4096),
        Capture::Discard,
    );
    assert!(matches!(r, Err(RunError::Overflow)), "{r:?}");
    assert!(start.elapsed() < Duration::from_secs(10));
    // iki boru birlikte dolsa da kilitlenmez (stderr boşaltılır)
    let flood = "i=0; while [ $i -lt 3000 ]; do echo oooooooooooooooooooooooooooooooooooooooooooooooooooo; echo eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee >&2; i=$((i+1)); done; echo SON >&2";
    let out = run(&t, flood, 20_000, Capture::Tail(64), Capture::Tail(8)).unwrap();
    assert_eq!((out.code, out.stdout.len()), (0, 64));
    assert_eq!(out.stderr, b"eeee\nSON\n"[1..].to_vec());
    // endless output with tail capture ends at the deadline
    let r = run(&t, "yes", 500, Capture::Tail(64), Capture::Discard);
    assert!(matches!(r, Err(RunError::Timeout)), "{r:?}");
}

/// Sahte `ucli`: her koşuda `runs` dosyasına satır ekler.
fn fake_help(t: &Tmp, help: &str) -> String {
    let counter = t.path("work/runs");
    t.script(
        "bin/ucli",
        &format!("echo run >> {counter}\ncat <<'EOF'\n{help}\nEOF"),
    )
}

fn runs(t: &Tmp) -> usize {
    fs::read_to_string(t.path("work/runs")).map_or(0, |s| s.lines().count())
}

fn cached(t: &Tmp) -> (Arc<HelpCache>, cops_providers::real::RealProbe) {
    let help = Arc::new(HelpCache::with_timeout(Duration::from_millis(800)));
    (help.clone(), t.probe_with(t.env(&[]), help))
}

#[test]
fn help_probe_runs_once_per_binary_version_and_again_after_a_new_delivery() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let bin = fake_help(&t, "  --old");
    let (_, p) = cached(&t);
    for _ in 0..3 {
        assert!(p.ucli_chat_help(&bin).contains("--old"));
    }
    assert_eq!(runs(&t), 1);
    // çıplak ad PATH'ten çözülür ve aynı girdiyi kullanır
    assert!(p.ucli_chat_help("ucli").contains("--old"));
    assert_eq!(runs(&t), 1);
    fake_help(&t, "  --search-url <U>");
    assert!(p.ucli_chat_help(&bin).contains("--search-url"));
    assert_eq!(runs(&t), 2);
    // `claude --help` ayrı argüman, ayrı girdi
    assert!(p.claude_help(&bin).contains("--search-url"));
    assert_eq!(runs(&t), 3);
}

#[test]
fn a_missing_or_non_executable_binary_is_empty_and_not_cached() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let (help, p) = cached(&t);
    assert_eq!(p.ucli_chat_help(&t.path("bin/yok")), "");
    let bin = t.write("bin/ucli", "#!/bin/sh\necho --search-url\n", 0o644);
    assert_eq!(p.ucli_chat_help(&bin), "");
    assert!(help.is_empty());
    fs::set_permissions(&bin, std::os::unix::fs::PermissionsExt::from_mode(0o755)).unwrap();
    assert!(p.ucli_chat_help(&bin).contains("--search-url"));
}

#[test]
fn empty_failed_slow_huge_or_non_utf8_help_is_not_cached() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let (help, p) = cached(&t);
    for (i, body) in [
        "true",
        "echo '  '",
        "sleep 30",
        "yes",
        "printf '\\377--flag'",
    ]
    .iter()
    .enumerate()
    {
        let bin = t.script(&format!("bin/h{i}"), body);
        let start = Instant::now();
        assert_eq!(p.claude_help(&bin), "", "{body}");
        assert!(start.elapsed() < Duration::from_secs(10));
    }
    assert!(help.is_empty());
}

fn mcp(t: &Tmp, body: &str) -> (Result<(), McpRegisterError>, String) {
    let bin = t.script("bin/ucli", body);
    let cfg = t.path("work/.ucli/mcp.json");
    let argv = vec![bin, "--root".into(), t.path("work")];
    let probe = t.probe().with_mcp_timeout(Duration::from_millis(600));
    (probe.register_mcp(&t.path("work"), &cfg, &argv), cfg)
}

#[test]
fn register_mcp_deletes_the_old_record_and_runs_in_the_workspace() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let victim = t.write("work/hedef", "dokunma", 0o600);
    fs::create_dir(t.path("work/.ucli")).unwrap();
    std::os::unix::fs::symlink(&victim, t.path("work/.ucli/mcp.json")).unwrap();
    let (r, cfg) = mcp(
        &t,
        "pwd > cwd.txt; printf '%s\\n' \"$@\" > args.txt; test ! -e .ucli/mcp.json",
    );
    assert_eq!(r, Ok(()));
    assert!(fs::symlink_metadata(&cfg).is_err());
    assert_eq!(fs::read_to_string(victim).unwrap(), "dokunma");
    assert_eq!(
        fs::read_to_string(t.path("work/cwd.txt")).unwrap().trim(),
        t.path("work")
    );
    assert_eq!(
        fs::read_to_string(t.path("work/args.txt")).unwrap(),
        format!("--root\n{}\n", t.path("work"))
    );
}

#[test]
fn register_mcp_errors_carry_python_reprs() {
    let _g = spawn_guard();
    let t = Tmp::new();
    let (r, _) = mcp(&t, "echo cikti; echo hata >&2; exit 4");
    assert_eq!(
        r,
        Err(McpRegisterError::Exit {
            rc: 4,
            stdout: "cikti\n".into(),
            stderr: "hata\n".into()
        })
    );
    let (r, _) = mcp(&t, "sleep 30");
    let Err(McpRegisterError::Spawn(text)) = r else {
        panic!("{r:?}")
    };
    assert!(
        text.starts_with("TimeoutExpired(['") && text.ends_with("'], 0.6)"),
        "{text}"
    );
    let r = t
        .probe()
        .register_mcp(&t.path("work"), &t.path("work/yok"), &[t.path("bin/yok")]);
    assert_eq!(
        r,
        Err(McpRegisterError::Spawn(
            "FileNotFoundError(2, 'No such file or directory')".into()
        ))
    );
    fs::create_dir_all(t.path("work/dizin/mcp.json")).unwrap();
    let r = t
        .probe()
        .register_mcp(&t.path("work"), &t.path("work/dizin/mcp.json"), &[]);
    assert_eq!(
        r,
        Err(McpRegisterError::Unlink(
            "IsADirectoryError(21, 'Is a directory')".into()
        ))
    );
}
