//! claude süreç kaydı kanıtı (`py/tests/test_bg_work.py` `SessionRecordSignal`) GERÇEK uygulayıcıyla: geçici HOME altında
//! kayıtlar, `/proc` yalnız testin KENDİ süreci.

#[path = "g8/support.rs"]
mod support;

use cops_providers::bg_work::Clock;
use cops_providers::ucli_status::RECORD_MAX_BYTES;
use cops_providers::{Cli, Live, Settings};
use serde_json::json;
use std::fs;
use std::time::{Duration, Instant};
use support::{mkfifo, Tmp};

/// Canlı claude 2.1.332 alt satırları: (süreç kaydı `status`, alt satır, ekranda iş sayısı, çalışan iş var mı).
const LIVE_FOOTERS: [(&str, &str, u64, bool); 7] = [
    (
        "idle",
        "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent                               /rc",
        0,
        false,
    ),
    (
        "idle",
        "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent",
        0,
        false,
    ),
    (
        "idle",
        "⏵⏵ auto mode on (shift+tab to cycle)        new task? /clear to save 177.9k tokens",
        0,
        false,
    ),
    (
        "shell",
        "⏵⏵ auto mode on · 1 shell · ← 1 agent · ↓ to manage                            /rc",
        1,
        true,
    ),
    (
        "busy",
        "⏵⏵ auto mode on · 3 background tasks · ← 1 agent · ↓ to manage                 /rc",
        3,
        true,
    ),
    (
        "busy",
        "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent · ↓ to manage                 /rc",
        0,
        true,
    ),
    (
        "busy",
        "⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← 1 agent            /rc",
        0,
        true,
    ),
];

fn own_pid() -> i64 {
    i64::from(std::process::id())
}

fn own_start() -> String {
    let stat = fs::read_to_string("/proc/self/stat").unwrap();
    let fields = &stat[stat.rfind(')').unwrap() + 1..];
    fields.split_whitespace().nth(19).unwrap().to_string()
}

fn record(t: &Tmp, pid: i64, sid: &str, status: &str, start: &str) -> String {
    let body = json!({"pid": pid, "sessionId": sid, "status": status, "procStart": start});
    t.write(
        &format!("home/.claude/sessions/{pid}.json"),
        body.to_string(),
        0o600,
    )
}

fn work(t: &Tmp, footer: &str, sid: Option<&str>) -> Option<u64> {
    let settings = Settings::default();
    let paths = t.paths();
    let probe = t.probe();
    Live {
        settings: &settings,
        paths: &paths,
        probe: &probe,
        clock: Clock {
            now: 0.0,
            utc_offset_secs: 0,
        },
    }
    .background_work(
        Cli::Claude,
        &format!("❯\n  {footer}\n"),
        "/nonexistent",
        sid,
    )
}

#[test]
fn live_footers() {
    let t = Tmp::new();
    for (status, footer, screen, active) in LIVE_FOOTERS {
        assert_eq!(
            cops_providers::bg_work::screen_bg_count(footer),
            screen,
            "{footer}"
        );
        record(&t, own_pid(), "s1", status, &own_start());
        let found = work(&t, footer, Some("s1")).unwrap();
        assert_eq!(found > 0, active, "{status} {footer}");
    }
}

#[test]
fn record_of_dead_reused_or_other_session_is_ignored() {
    let t = Tmp::new();
    let idle = LIVE_FOOTERS[0].1;
    record(&t, own_pid(), "s1", "busy", &own_start());
    assert_eq!(work(&t, idle, Some("s1")), Some(1));
    for sid in [None, Some(""), Some("baska")] {
        assert_eq!(work(&t, idle, sid), Some(0), "{sid:?}");
    }
    // pid yeniden kullanılmış: başlangıç anı tutmuyor
    record(&t, own_pid(), "s1", "shell", "1");
    assert_eq!(work(&t, idle, Some("s1")), Some(0));
    // süreç yok
    fs::remove_file(record(&t, own_pid(), "s1", "idle", "1")).unwrap();
    record(&t, (1 << 22) + 7, "s1", "shell", &own_start());
    assert_eq!(work(&t, idle, Some("s1")), Some(0));
}

#[test]
fn broken_records_fifo_and_oversize_are_skipped_without_blocking() {
    let t = Tmp::new();
    let idle = LIVE_FOOTERS[0].1;
    assert_eq!(work(&t, idle, Some("s1")), Some(0)); // dizin yok
    t.write("home/.claude/sessions/1.json", "[1", 0o600);
    t.write("home/.claude/sessions/2.json", "[]", 0o600);
    t.write(
        "home/.claude/sessions/3.json",
        r#"{"pid": Infinity, "sessionId": "s1", "status": "busy", "procStart": "1"}"#,
        0o600,
    );
    mkfifo(&t.path("home/.claude/sessions/4.json"));
    let start = Instant::now();
    assert_eq!(work(&t, idle, Some("s1")), Some(0));
    let path = record(&t, own_pid(), "s1", "busy", &own_start());
    assert_eq!(work(&t, idle, Some("s1")), Some(1));
    let mut big = fs::read(&path).unwrap();
    big.extend(std::iter::repeat_n(b' ', 1024 * 1024));
    fs::write(&path, big).unwrap();
    assert_eq!(work(&t, idle, Some("s1")), Some(0));
    assert!(start.elapsed() < Duration::from_secs(5));
}

/// Hata kaydı okuma sınırı (`RECORD_MAX_BYTES`, Python sınırsız): aşan kayıt SAYILIR, yalnız hata metni boş kalır.
#[test]
fn an_oversized_failed_turn_record_is_counted_without_its_error() {
    let t = Tmp::new();
    let settings = Settings::default();
    let paths = t.paths();
    let probe = t.probe();
    let live = Live {
        settings: &settings,
        paths: &paths,
        probe: &probe,
        clock: Clock {
            now: 0.0,
            utc_offset_secs: 0,
        },
    };
    let cwd = t.path("work/p1");
    let body = br#"{"error":"patladi"}"#.to_vec();
    let padded = |len: u64| {
        let mut b = body.clone();
        b.resize(usize::try_from(len).unwrap(), b' ');
        b
    };
    let name = "work/p1/.ucli/chat/failed/s1-100-1.json";
    for (len, error) in [
        (RECORD_MAX_BYTES, Some("patladi")),
        (RECORD_MAX_BYTES + 1, None),
    ] {
        t.write(name, padded(len), 0o600);
        let got = live.live_failed_turns(Cli::Ucli, &cwd, Some("s1")).unwrap();
        assert_eq!((got.count, got.last_unix), (1, 100), "{len}");
        assert_eq!(got.last_error.as_deref(), error, "{len}");
    }
}
