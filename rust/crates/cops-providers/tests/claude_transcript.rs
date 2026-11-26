//! claude transkripti okuyucularının parite dışında kalan sözleşmesi: pencere sınırı, tarama sırasında büyüyen/kısalan
//! dosya, okuma hatası, bozuk girdide panik olmaması ve önbellek adaylarının seçimi. Sahte, bellek içi `Probe`.

use cops_providers::bg_work::Clock;
use cops_providers::claude_transcript::{FIRST_WINDOW_BYTES, MAX_WINDOW_BYTES};
use cops_providers::ucli_opts::Toolchain;
use cops_providers::{Cli, Live, LiveProbe, McpRegisterError, Paths, Probe, Settings, SqlCell};
use std::cell::RefCell;
use std::collections::HashMap;

#[derive(Default)]
struct Mem {
    files: HashMap<String, Vec<u8>>,
    /// `file_size`in bildirdiği boyut (dosyanın okuma anındaki içeriğinden farklı olabilir).
    stale_size: Option<u64>,
    /// Bu sıradaki (0 tabanlı) okumadan itibaren hata.
    fail_from_read: Option<usize>,
    /// (başlangıç, uzunluk)
    reads: RefCell<Vec<(u64, u64)>>,
}

impl Probe for Mem {
    fn is_file(&self, path: &str) -> bool {
        self.files.contains_key(path)
    }
    fn file_size(&self, path: &str) -> Option<u64> {
        let real = self.files.get(path)?.len() as u64;
        Some(self.stale_size.unwrap_or(real))
    }
    fn is_dir(&self, _: &str) -> bool {
        unreachable!()
    }
    fn exists(&self, _: &str) -> bool {
        unreachable!()
    }
    fn is_symlink(&self, _: &str) -> bool {
        unreachable!()
    }
    fn is_executable_file(&self, _: &str) -> bool {
        unreachable!()
    }
    fn read_text(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn realpath(&self, _: &str) -> String {
        unreachable!()
    }
    fn which(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn env_var(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn claude_help(&self, _: &str) -> String {
        unreachable!()
    }
    fn ucli_chat_help(&self, _: &str) -> String {
        unreachable!()
    }
    fn path_executables(&self) -> Vec<String> {
        unreachable!()
    }
    fn rust_toolchain(&self) -> Result<Toolchain, String> {
        unreachable!()
    }
    fn searxng_url(&self, _: &str, _: bool) -> Option<String> {
        unreachable!()
    }
    fn checks_registry(&self, _: &str) -> Result<(), String> {
        unreachable!()
    }
    fn claude_cost_gate(&self, _: &str) -> Result<(), String> {
        unreachable!()
    }
    fn issue_agent_token(&self, _: &str) -> Result<String, String> {
        unreachable!()
    }
    fn panel_port(&self) -> Option<u16> {
        unreachable!()
    }
    fn register_mcp(&self, _: &str, _: &str, _: &[String]) -> Result<(), McpRegisterError> {
        unreachable!()
    }
}

impl LiveProbe for Mem {
    fn read_range(&self, path: &str, start: u64, len: u64) -> Option<Vec<u8>> {
        let nth = self.reads.borrow().len();
        self.reads.borrow_mut().push((start, len));
        if self.fail_from_read.is_some_and(|f| nth >= f) {
            return None;
        }
        let data = self.files.get(path)?;
        let from = (start as usize).min(data.len());
        let to = from.saturating_add(len as usize).min(data.len());
        Some(data[from..to].to_vec())
    }
    fn claude_session_sid(&self, pid: i64) -> Option<String> {
        (pid == 42).then(|| "from-pid".to_string())
    }
    fn claude_project_dir(&self, _: &str) -> String {
        "/p".into()
    }
    fn claude_transcript(&self, _: &str, sid: Option<&str>) -> Option<String> {
        let path = format!("/p/{}.jsonl", sid?);
        self.files.contains_key(&path).then_some(path)
    }
    fn read_bytes(&self, _: &str, _: u64) -> Option<Vec<u8>> {
        unreachable!()
    }
    fn read_tail(&self, _: &str, _: u64) -> Option<Vec<u8>> {
        unreachable!()
    }
    fn list_dir(&self, _: &str) -> Option<Vec<String>> {
        unreachable!()
    }
    fn codex_rollout(&self, _: &str, _: Option<&str>) -> Option<String> {
        unreachable!()
    }
    fn copilot_resume_id(&self, _: &str) -> Option<String> {
        unreachable!()
    }
    fn sqlite_cell(&self, _: &str, _: &str, _: &str) -> Option<SqlCell> {
        unreachable!()
    }
    fn sqlite_rows(&self, _: &str, _: &str, _: &[SqlCell], _: &mut dyn FnMut(Vec<SqlCell>) -> bool) -> bool {
        unreachable!()
    }
    fn agy_resume_id(&self, _: &str) -> Option<String> {
        unreachable!()
    }
}

fn with<T>(mem: &Mem, f: impl FnOnce(&Live<'_>) -> T) -> T {
    let settings = Settings::default();
    let paths = Paths { claudeops_dir: "/s".into(), home: "/h".into(), repo_dir: "/r".into() };
    f(&Live { settings: &settings, paths: &paths, probe: mem, clock: Clock { now: 0.0, utc_offset_secs: 0 } })
}

fn one(data: impl Into<Vec<u8>>) -> Mem {
    Mem { files: HashMap::from([("/p/s.jsonl".to_string(), data.into())]), ..Default::default() }
}

fn row(second: u32, model: &str) -> String {
    format!(
        r#"{{"type":"assistant","timestamp":"2027-01-15T08:00:{second:02}Z","effort":"high","message":{{"model":"{model}","usage":{{"input_tokens":1}}}}}}"#
    )
}

/// `row` + dolgu; satır başı dosya sonundan `distance` bayt geride.
fn behind(distance: u64) -> Vec<u8> {
    let mut data = b"{}\n".to_vec();
    data.extend(format!("{}\n", row(1, "hedef")).into_bytes());
    data.resize(3 + distance as usize, b' ');
    data
}

fn model(mem: &Mem) -> Option<String> {
    with(mem, |l| l.last_assistant_model("/p/s.jsonl", None))
}

#[test]
fn window_grows_four_times_and_stops_at_the_limit() {
    let inside = one(behind(FIRST_WINDOW_BYTES));
    assert_eq!(model(&inside).as_deref(), Some("hedef"));
    assert_eq!(inside.reads.borrow().len(), 1);
    let outside = one(behind(FIRST_WINDOW_BYTES + 1));
    assert_eq!(model(&outside).as_deref(), Some("hedef"));
    assert_eq!(outside.reads.borrow().len(), 2);
    let last = one(behind(MAX_WINDOW_BYTES));
    assert_eq!(model(&last).as_deref(), Some("hedef"));
    let gone = one(behind(MAX_WINDOW_BYTES + 1));
    assert_eq!(model(&gone), None);
    // 64K, 256K, 1M, 4M: dördüncüden sonra büyümez; hiçbir okuma tavanı aşmaz
    let lengths: Vec<u64> = gone.reads.borrow().iter().map(|r| r.1).collect();
    assert_eq!(lengths, [FIRST_WINDOW_BYTES, 262_144, 1_048_576, MAX_WINDOW_BYTES]);
    let huge = one(vec![b'x'; 3 * MAX_WINDOW_BYTES as usize]);
    assert_eq!(model(&huge), None);
    assert!(huge.reads.borrow().iter().all(|r| r.1 <= MAX_WINDOW_BYTES));
}

#[test]
fn since_stops_the_scan_without_reading_further() {
    let mut data = vec![b' '; 200_000];
    data.extend(format!("\n{}\n", row(1, "eski")).into_bytes());
    let mem = one(data);
    // 2027-01-15T08:00:30Z
    assert_eq!(with(&mem, |l| l.last_assistant_model("/p/s.jsonl", Some(1_800_000_030.0))), None);
    assert_eq!(mem.reads.borrow().len(), 1);
}

#[test]
fn rows_appended_after_the_size_was_read_are_not_seen() {
    let old = format!("{}\n", row(1, "eski"));
    let mut mem = one(format!("{old}{}\n", row(2, "yeni")));
    mem.stale_size = Some(old.len() as u64);
    assert_eq!(model(&mem).as_deref(), Some("eski"));
}

#[test]
fn truncated_file_and_read_errors_mean_unknown() {
    let mut mem = one("{}\n");
    mem.stale_size = Some(10 * MAX_WINDOW_BYTES);
    assert_eq!(model(&mem), None);
    let mut mem = one(behind(FIRST_WINDOW_BYTES + 1));
    mem.fail_from_read = Some(1); // ikinci pencere okunamaz
    assert_eq!(model(&mem), None);
    assert_eq!(model(&Mem::default()), None);
}

#[test]
fn truncated_and_mutated_input_never_panics() {
    let base = format!("{}\n{}\n", row(1, "a"), row(2, "claude-sonnet-5")).into_bytes();
    let read = |data: Vec<u8>| {
        let mem = one(data);
        with(&mem, |l| {
            let _ = l.last_assistant_model("/p/s.jsonl", Some(1.0));
            let _ = l.last_assistant_effort("/p/s.jsonl", None);
            let _ = l.last_real_request_epoch("/p/s.jsonl");
        });
    };
    let mut state = 0x9e37_79b9_u64;
    let mut next = move |n: usize| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state % n as u64) as usize
    };
    for cut in 0..=base.len() {
        read(base[..cut].to_vec());
        read(base[cut..].to_vec());
    }
    for _ in 0..5000 {
        let mut data = base.clone();
        for _ in 0..1 + next(4) {
            let at = next(data.len());
            data[at] = next(256) as u8;
        }
        read(data);
    }
    read(vec![b'['; 1_000_000]);
    for model in ["claude-", "claude-sonnet-5-", &"claude-sonnet-5-".repeat(100_000), "İ🙂"] {
        let _ = Cli::Claude.effort_switch_keeps_cache(Some(model));
    }
}

#[test]
fn cache_candidates_are_exact_files_and_newest_wins() {
    let files = [("/p/cmd.jsonl", row(1, "m")), ("/p/from-pid.jsonl", row(9, "m")), ("/p/sibling.jsonl", row(50, "m"))];
    let mem = Mem { files: files.into_iter().map(|(p, r)| (p.to_string(), r.into_bytes())).collect(), ..Default::default() };
    let at = |cli, sid, pid| with(&mem, |l| l.last_request_epoch(cli, "/w", sid, pid));
    assert_eq!(at(Cli::Claude, Some("cmd"), None), Some(1_800_000_001.0));
    assert_eq!(at(Cli::Claude, Some("cmd"), Some(42)), Some(1_800_000_009.0));
    assert_eq!(at(Cli::Claude, None, Some(42)), Some(1_800_000_009.0));
    assert_eq!(at(Cli::Claude, None, Some(7)), None);
    assert_eq!(at(Cli::Claude, Some("missing"), None), None);
    for cli in Cli::ALL.into_iter().filter(|c| *c != Cli::Claude) {
        assert_eq!(at(cli, Some("cmd"), Some(42)), None);
        assert_eq!(cli.prompt_cache_ttl_seconds(), None);
        assert!(cli.effort_switch_keeps_cache(Some("claude-sonnet-5")));
    }
    assert_eq!(Cli::Claude.prompt_cache_ttl_seconds(), Some(3600));
}

#[test]
fn synthetic_and_unexpected_rows_do_not_hide_the_real_model() {
    let data = format!(
        "{}\n{}\n5\n{}\n{}\n",
        row(1, "gercek"),
        r#"{"type":"assistant","message":{"model":"<synthetic>"}}"#,
        r#"{"type":"assistant","message":null}"#,
        r#"{"type":"assistant","message":{"model":["x"]}}"#
    );
    let mem = one(data);
    assert_eq!(with(&mem, |l| l.live_or_spawn_model("claude", "/w", Some("s"), "spawn")), "gercek");
    assert_eq!(with(&mem, |l| l.live_or_spawn_effort("claude", "/w", Some("s"), "spawn")), "high");
    assert_eq!(with(&mem, |l| l.live_or_spawn_model("bogus", "/w", Some("s"), "spawn")), "spawn");
    assert_eq!(with(&mem, |l| l.live_or_spawn_model("claude", "/w", None, "spawn")), "spawn");
}
