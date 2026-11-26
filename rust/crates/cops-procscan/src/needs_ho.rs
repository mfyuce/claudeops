//! Oturum devir (ho) gerektiriyor mu (`needs_ho.py`): git sinyalleri ve transkript.

use crate::transcript::Line;
use crate::{proc_cmd, py};
use serde::Serialize;
use serde_json::{Map, Value};
use sha1::{Digest, Sha1};
use std::fmt::Write;
use std::fs::File;
use std::io::{BufReader, Write as _};
use std::ops::ControlFlow;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

const RFH: &str = "READY FOR HANDOVER";
const GIT_TIMEOUT: Duration = Duration::from_secs(15);

/// Transkript kararı ve atlanan beklenmeyen tipte kayıt sayısı (nesne olmayan satır, nesne olmayan `message`,
/// dizgi olmayan `text` bloğu). TBD#365: Python da artık bunları atlayıp sayar (`needs_ho._skipped`), karar düşmez.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct Checked {
    pub value: bool,
    pub skipped: u32,
}

/// Başarısız/zaman aşımlı git = boş dizgi.
fn git(cwd: &str, args: &[&str]) -> String {
    let mut cmd = Command::new("git");
    cmd.arg("-C").arg(cwd).args(args);
    match proc_cmd::run(cmd, GIT_TIMEOUT) {
        Some((st, out)) if st.success() => String::from_utf8(out).map(|s| py::strip(&s).to_owned()).unwrap_or_default(),
        _ => String::new(),
    }
}

fn is_git_repo(cwd: &str) -> bool {
    !git(cwd, &["rev-parse", "--git-dir"]).is_empty()
}

/// İzlenen değişiklik/staged, push edilmemiş ya da remote ileride. İzlenmeyen dosya sayılmaz.
pub fn repo_dirty(cwd: &str) -> bool {
    if !is_git_repo(cwd) {
        return false;
    }
    if py::splitlines(&git(cwd, &["status", "--porcelain"])).any(|l| !l.starts_with("??")) {
        return true;
    }
    let branch = git(cwd, &["branch", "--show-current"]);
    if branch.is_empty() {
        return false; // detached HEAD
    }
    let remotes = git(cwd, &["remote"]);
    for r in py::splitlines(&remotes).map(py::strip).filter(|r| !r.is_empty()) {
        let reference = format!("{r}/{branch}");
        if git(cwd, &["rev-parse", "--verify", &reference]).is_empty() {
            continue;
        }
        let nonzero = |range: String| py::int(&git(cwd, &["rev-list", "--count", &range])).is_some_and(|n| n > 0);
        if nonzero(format!("{reference}..HEAD")) || nonzero(format!("HEAD..{reference}")) {
            return true;
        }
    }
    false
}

pub fn repo_untracked_count(cwd: &str) -> usize {
    if !is_git_repo(cwd) {
        return 0;
    }
    let out = git(cwd, &["ls-files", "--others", "--exclude-standard"]);
    py::splitlines(&out).filter(|l| !py::strip(l).is_empty()).count()
}

/// Depo kök yolunun sha1'i (baseline dosya adı).
fn repo_key(cwd: &str) -> Option<String> {
    let top = git(cwd, &["rev-parse", "--show-toplevel"]);
    if top.is_empty() {
        return None;
    }
    Some(Sha1::digest(top.as_bytes()).iter().fold(String::new(), |mut s, b| {
        let _ = write!(s, "{b:02x}");
        s
    }))
}

/// Karşılaştırma için zaman: (duvar saati mikrosaniye, varsa UTC farkı mikrosaniye).
type IsoTime = (i64, Option<i64>);

fn two(s: &[u8]) -> Option<i64> {
    match s {
        [a, b] if a.is_ascii_digit() && b.is_ascii_digit() => Some(i64::from((a - b'0') * 10 + (b - b'0'))),
        _ => None,
    }
}

/// `HH[:MM[:SS[.fff[fff]]]]` -> mikrosaniye.
fn iso_clock(s: &[u8]) -> Option<i64> {
    let (main, frac) = match s.iter().position(|&c| c == b'.') {
        Some(i) if i == 8 => (&s[..i], Some(&s[i + 1..])),
        Some(_) => return None,
        None => (s, None),
    };
    if !matches!(main.len(), 2 | 5 | 8) {
        return None;
    }
    let mut total = 0;
    for (i, limit) in [24, 60, 60].into_iter().enumerate() {
        let at = i * 3;
        let v = if at < main.len() {
            if i > 0 && main[at - 1] != b':' {
                return None;
            }
            two(main.get(at..at + 2)?)?
        } else {
            0
        };
        if v >= limit {
            return None;
        }
        total = total * 60 + v;
    }
    let micro = match frac {
        None => 0,
        Some(f) if matches!(f.len(), 3 | 6) && f.iter().all(u8::is_ascii_digit) => {
            let n: i64 = std::str::from_utf8(f).ok()?.parse().ok()?;
            if f.len() == 3 {
                n * 1000
            } else {
                n
            }
        }
        Some(_) => return None,
    };
    Some(total * 1_000_000 + micro)
}

/// Python 3.10 `datetime.fromisoformat` biçimi.
fn from_iso(s: &str) -> Option<IsoTime> {
    let b = s.as_bytes();
    if b.len() < 10 || b[4] != b'-' || b[7] != b'-' {
        return None;
    }
    let year = two(&b[0..2])? * 100 + two(&b[2..4])?;
    let (month, day) = (two(&b[5..7])?, two(&b[8..10])?);
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let len = match month {
        2 => 28 + i64::from(leap),
        4 | 6 | 9 | 11 => 30,
        1..=12 => 31,
        _ => return None,
    };
    if year < 1 || day < 1 || day > len {
        return None;
    }
    // sivil takvimden gün sayısı
    let y = if month <= 2 { year - 1 } else { year };
    let (era, yoe) = (y.div_euclid(400), y.rem_euclid(400));
    let doy = (153 * ((month + 9) % 12) + 2) / 5 + day - 1;
    let days = era * 146_097 + yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let midnight = days * 86_400_000_000;
    if b.len() == 10 {
        return Some((midnight, None));
    }
    // ayraç herhangi tek karakter
    let sep = s.get(10..)?.chars().next()?;
    // ayraçtan sonra saat zorunlu ("2026-11-04T" geçersiz; altın vektör)
    let time = s.get(10 + sep.len_utf8()..)?.as_bytes();
    let (clock, offset) = match time.iter().position(|&c| c == b'+' || c == b'-') {
        Some(i) => {
            let tz = &time[i + 1..];
            if !matches!(tz.len(), 5 | 8 | 15) {
                return None;
            }
            let sign = if time[i] == b'-' { -1 } else { 1 };
            (&time[..i], Some(sign * iso_clock(tz)?))
        }
        None => (time, None),
    };
    Some((midnight + iso_clock(clock)?, offset))
}

/// `commit > baseline`; biri saat dilimsizse ikisinin de dilimi atılır.
fn newer(commit: IsoTime, base: IsoTime) -> bool {
    match (commit.1, base.1) {
        (Some(co), Some(bo)) => commit.0 - co > base.0 - bo,
        _ => commit.0 > base.0,
    }
}

/// Baseline durumu claudeops durum dizinindedir.
#[derive(Debug, Clone)]
pub struct NeedsHo {
    state_dir: PathBuf,
}

impl NeedsHo {
    pub fn new(state_dir: impl Into<PathBuf>) -> Self {
        NeedsHo {
            state_dir: state_dir.into(),
        }
    }

    fn baseline_get(&self, cwd: &str) -> String {
        repo_key(cwd)
            .and_then(|k| std::fs::read_to_string(self.state_dir.join("baselines").join(k)).ok())
            .map(|s| py::strip(&s).to_owned())
            .unwrap_or_default()
    }

    /// Ho sonrası HEAD'i baseline yap. Depo değilse hiçbir şey yazmaz. Atomik (Python `atomic_write_text`).
    pub fn repo_baseline_set(&self, cwd: &str) -> std::io::Result<()> {
        let key = repo_key(cwd);
        let head = git(cwd, &["rev-parse", "HEAD"]);
        if let (Some(k), false) = (key, head.is_empty()) {
            let dir = self.state_dir.join("baselines");
            std::fs::create_dir_all(&dir)?;
            write_atomic(&dir.join(k), head.as_bytes())?;
        }
        Ok(())
    }

    /// Son ho baseline'ından (yoksa son ho zaman damgasından) beri yeni commit var mı.
    pub fn repo_committed_since(&self, cwd: &str) -> bool {
        if !is_git_repo(cwd) {
            return false;
        }
        let baseline = self.baseline_get(cwd);
        if !baseline.is_empty() {
            let head = git(cwd, &["rev-parse", "HEAD"]);
            return !head.is_empty() && head != baseline;
        }
        let Ok(ts) = std::fs::read_to_string(self.state_dir.join("last-handover.ts")) else {
            return false;
        };
        committed_after(&git(cwd, &["log", "-1", "--format=%cI"]), py::strip(&ts))
    }

    /// `true` = ho gerek. Hiç gerçek kullanıcı turu olmayan transkript git durumuna bakmadan `false`.
    pub fn needs_ho(&self, cwd: &str, jsonl: Option<&Path>) -> Checked {
        let mut skipped = 0;
        if let Some(p) = jsonl {
            let real = has_real_user_turn(p);
            skipped += real.skipped;
            if !real.value {
                return Checked { value: false, skipped };
            }
        }
        if repo_dirty(cwd) || repo_untracked_count(cwd) > 0 || self.repo_committed_since(cwd) {
            return Checked { value: true, skipped };
        }
        let value = match jsonl {
            Some(p) => {
                let done = handover_done(p);
                skipped += done.skipped;
                !done.value
            }
            None => false,
        };
        Checked { value, skipped }
    }
}

/// Aynı dizinde süreç+iş parçacığına özel geçici dosya (`O_EXCL|O_NOFOLLOW`), `fsync`, `rename`; hata olursa geçici
/// dosya silinir. Eşzamanlı okuyan yarım dosya görmez.
fn write_atomic(path: &Path, data: &[u8]) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut name = path.file_name().unwrap_or_default().to_os_string();
    name.push(format!(".{}-{:?}.tmp", std::process::id(), std::thread::current().id()));
    let tmp = path.with_file_name(name);
    let _ = std::fs::remove_file(&tmp); // önceki çöküşten kalan aynı adlı geçici dosya
    let res = (|| {
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&tmp)?;
        f.write_all(data)?;
        f.sync_all()?;
        std::fs::rename(&tmp, path)?;
        if let Some(dir) = path.parent() {
            let _ = File::open(dir).and_then(|d| d.sync_all());
        }
        Ok(())
    })();
    if res.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    res
}

/// Zaman damgası dalı (`repo_committed_since`, baseline yokken): çözülemeyen commit zamanı = yeni değil,
/// çözülemeyen baseline = yeni. Python 3.10 `datetime.fromisoformat` kuralı.
pub fn committed_after(commit_iso: &str, base_iso: &str) -> bool {
    let Some(commit) = from_iso(commit_iso) else { return false };
    from_iso(base_iso).is_none_or(|base| newer(commit, base))
}

/// Devir işareti yalnız satır başında (baştaki boşluk/`#`/`*` hariç); kod bloğu içi sayılmaz.
pub fn rfh_marker_in(text: &str) -> bool {
    let mut fenced = false;
    for raw in py::splitlines(text) {
        if py::strip(raw).starts_with("```") {
            fenced = !fenced;
        } else if !fenced
            && raw
                .trim_start_matches(|c| py::is_space(c) || c == '#' || c == '*')
                .starts_with(RFH)
        {
            return true;
        }
    }
    false
}

/// Transkriptin ayrıştırılabilen nesne satırları; nesne olmayan satır ve satır sınırını
/// ([`crate::transcript::MAX_LINE_BYTES`]) aşan satır atlanır ve `skipped`a eklenir (bellek satır başına sınırlı).
/// Okuma hatası `None`.
fn each_row(path: &Path, skipped: &mut u32, mut f: impl FnMut(&Map<String, Value>, &mut u32) -> ControlFlow<()>) -> Option<()> {
    let file = File::open(path).ok()?;
    let mut reader = BufReader::new(file);
    let mut buf = Vec::new();
    let max = crate::transcript::max_line();
    loop {
        match crate::transcript::read_line(&mut reader, &mut buf, max) {
            Ok(Line::Eof) => return Some(()),
            Ok(Line::Full(_) | Line::Partial(_)) => {}
            Ok(Line::TooLong { .. }) => {
                *skipped += 1;
                continue;
            }
            Err(_) => return None,
        }
        // metin kipi: `\r` de satır sonu; geçersiz utf-8 yerine U+FFFD
        for part in buf.split(|&c| c == b'\r') {
            let line = String::from_utf8_lossy(part);
            let line = py::strip(&line);
            if line.is_empty() {
                continue;
            }
            let Some(v) = py::json(line.as_bytes()) else { continue };
            let Value::Object(o) = v else {
                *skipped += 1;
                continue;
            };
            if f(&o, skipped).is_break() {
                return Some(());
            }
        }
    }
}

fn is_type(block: &Value, kind: &str) -> bool {
    block.get("type").and_then(Value::as_str) == Some(kind)
}

/// `type: text` blokların dizgi metinleri; dizgi olmayan `text` yok sayılır ve sayılır.
fn text_blocks<'a>(blocks: &'a [Value], skipped: &mut u32) -> Vec<&'a str> {
    let mut out = Vec::new();
    for b in blocks.iter().filter(|b| is_type(b, "text")) {
        match b.get("text") {
            None => out.push(""),
            Some(Value::String(s)) => out.push(s),
            Some(_) => *skipped += 1,
        }
    }
    out
}

/// Asistan cevabında devir işareti var ve sonrasında yeni kullanıcı isteği yok.
pub fn handover_done(path: &Path) -> Checked {
    let (mut last_rfh, mut last_user, mut i) = (None::<u64>, None::<u64>, 0u64);
    let mut skipped = 0;
    let read = each_row(path, &mut skipped, |o, skipped| {
        i += 1;
        let kind = o.get("type").and_then(Value::as_str);
        let content = o.get("message").and_then(Value::as_object).and_then(|m| m.get("content"));
        let text = match content {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Array(blocks)) => text_blocks(blocks, skipped).join(" "),
            _ => String::new(),
        };
        if kind == Some("assistant") && rfh_marker_in(&text) {
            last_rfh = Some(i);
        }
        if kind == Some("user") {
            let real = match content {
                Some(Value::Array(blocks)) => !blocks.iter().any(|b| is_type(b, "tool_result")) && !py::strip(&text).is_empty(),
                Some(Value::String(s)) => !py::strip(s).is_empty(),
                _ => false,
            };
            if real {
                last_user = Some(i);
            }
        }
        ControlFlow::Continue(())
    });
    Checked {
        value: read.is_some() && last_rfh.is_some() && last_rfh >= last_user,
        skipped,
    }
}

/// En az bir gerçek kullanıcı mesajı (tool_result, sidechain, isMeta, boş metin sayılmaz).
pub fn has_real_user_turn(path: &Path) -> Checked {
    let (mut found, mut skipped) = (false, 0);
    each_row(path, &mut skipped, |o, skipped| {
        let flag = |k: &str| o.get(k).is_some_and(py::truthy);
        if o.get("type").and_then(Value::as_str) != Some("user") || flag("isSidechain") || flag("isMeta") {
            return ControlFlow::Continue(());
        }
        let content = match o.get("message") {
            None => None,
            Some(Value::Object(m)) => m.get("content"),
            Some(_) => {
                *skipped += 1;
                return ControlFlow::Continue(());
            }
        };
        match content {
            Some(Value::String(s)) => found = !py::strip(s).is_empty(),
            Some(Value::Array(blocks)) => {
                let tool = blocks.iter().any(|b| is_type(b, "tool_result"));
                let has_text = text_blocks(blocks, skipped).iter().any(|t| !py::strip(t).is_empty());
                found = !tool && has_text;
            }
            _ => {}
        }
        if found {
            ControlFlow::Break(())
        } else {
            ControlFlow::Continue(())
        }
    });
    Checked { value: found, skipped }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn transcript(rows: &[Value]) -> tempfile::NamedTempFile {
        let f = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(f.path(), rows.iter().map(|r| format!("{r}\n")).collect::<String>()).unwrap();
        f
    }

    fn row(kind: &str, text: &str) -> Value {
        json!({"type": kind, "message": {"content": [{"type": "text", "text": text}]}})
    }

    #[test]
    fn prose_mention_is_not_a_marker() {
        assert!(!rfh_marker_in("satırlar `READY FOR HANDOVER` geçiyor"));
        assert!(!rfh_marker_in("yazınca READY FOR HANDOVER sayılıyor"));
        assert!(!rfh_marker_in(""));
    }

    #[test]
    fn heading_and_bare_line_count() {
        assert!(rfh_marker_in("özet\n## READY FOR HANDOVER (x)"));
        assert!(rfh_marker_in("**READY FOR HANDOVER**"));
        assert!(rfh_marker_in("  READY FOR HANDOVER"));
    }

    #[test]
    fn code_block_and_quote_do_not_count() {
        assert!(!rfh_marker_in("```\nREADY FOR HANDOVER\n```"));
        assert!(!rfh_marker_in("> READY FOR HANDOVER"));
        assert!(rfh_marker_in("```\nx\n```\nREADY FOR HANDOVER"));
    }

    #[test]
    fn only_assistant_rows_carry_the_marker() {
        let m = "## READY FOR HANDOVER";
        assert!(!handover_done(transcript(&[row("user", m)]).path()).value);
        assert!(handover_done(transcript(&[row("user", "iş"), row("assistant", m)]).path()).value);
        for kind in ["api-request-blob", "attachment", "system"] {
            let t = transcript(&[row(kind, m)]);
            assert!(!handover_done(t.path()).value, "{kind}");
            assert!(!has_real_user_turn(t.path()).value, "{kind}");
        }
        assert!(handover_done(transcript(&[row("system", m), row("assistant", m)]).path()).value);
        // işaretten sonra yeni istek; tool_result istek sayılmaz
        assert!(!handover_done(transcript(&[row("assistant", m), row("user", "bir iş daha")]).path()).value);
        let tool = json!({"type": "user", "message": {"content": [{"type": "tool_result"}, {"type": "text", "text": "x"}]}});
        assert!(handover_done(transcript(&[row("assistant", m), tool.clone()]).path()).value);
        assert!(!has_real_user_turn(transcript(&[tool]).path()).value);
    }

    #[test]
    fn real_user_turn_filters() {
        let with = |k: &str| json!({"type": "user", k: true, "message": {"content": "x"}});
        assert!(!has_real_user_turn(transcript(&[with("isMeta"), with("isSidechain"), row("user", "  ")]).path()).value);
        assert!(has_real_user_turn(transcript(&[json!({"type": "user", "message": {"content": "x"}})]).path()).value);
        assert!(!has_real_user_turn(transcript(&[json!({"type": "user"})]).path()).value);
    }

    /// Birleştirme kapısı: sınırı aşan transkript satırı atlanır ve `skipped`a girer; sınırda kabul; yarım uzun son satır.
    #[test]
    fn long_lines_are_skipped_and_counted() {
        const LIMIT: usize = 200;
        crate::transcript::TEST_MAX_LINE.with(|c| c.set(Some(LIMIT)));
        let pad =
            |row: &str, total: usize| format!("{},\"p\":\"{}\"}}", &row[..row.len() - 1], "x".repeat(total - row.len() - 7));
        let user = r#"{"type":"user","message":{"content":"iş"}}"#;
        let rfh = r#"{"type":"assistant","message":{"content":[{"type":"text","text":"READY FOR HANDOVER"}]}}"#;
        let at = pad(user, LIMIT);
        assert_eq!(at.len(), LIMIT);
        let f = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(f.path(), format!("{at}\n{}\n", pad(rfh, LIMIT + 1))).unwrap();
        assert_eq!(has_real_user_turn(f.path()), Checked { value: true, skipped: 0 });
        assert_eq!(
            handover_done(f.path()),
            Checked {
                value: false,
                skipped: 1
            }
        );
        std::fs::write(f.path(), format!("{at}\n{}\n", pad(rfh, LIMIT))).unwrap();
        assert_eq!(handover_done(f.path()), Checked { value: true, skipped: 0 });
        std::fs::write(f.path(), format!("{at}\n{}", "z".repeat(LIMIT * 3))).unwrap();
        assert!(has_real_user_turn(f.path()).value);
        assert_eq!(
            handover_done(f.path()),
            Checked {
                value: false,
                skipped: 1
            }
        );
        std::fs::write(f.path(), format!("{user}\r{rfh}\n")).unwrap();
        assert!(handover_done(f.path()).value);
        crate::transcript::TEST_MAX_LINE.with(|c| c.set(None));
    }

    #[test]
    fn broken_input_is_skipped_and_counted() {
        let f = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(
            f.path(),
            b"\n{bozuk\n\xff\xfe\r{\"type\":\"assistant\",\"message\":{\"content\":\"READY FOR HANDOVER \\ud800\"}}",
        )
        .unwrap();
        assert_eq!(handover_done(f.path()), Checked { value: true, skipped: 0 });
        // TBD#365: Python da artık istisna fırlatmaz; satır atlanır ve sayılır
        let user = r#"{"type":"user","message":{"content":"iş"}}"#;
        for bad in ["123", "[]", "\"s\"", "null"] {
            std::fs::write(f.path(), format!("{bad}\n{user}\n")).unwrap();
            assert_eq!(
                handover_done(f.path()),
                Checked {
                    value: false,
                    skipped: 1
                },
                "{bad}"
            );
            assert_eq!(has_real_user_turn(f.path()), Checked { value: true, skipped: 1 }, "{bad}");
        }
        for msg in ["null", "\"x\"", "[1]", "5"] {
            std::fs::write(f.path(), format!(r#"{{"type":"user","message":{msg}}}"#)).unwrap();
            assert_eq!(
                has_real_user_turn(f.path()),
                Checked {
                    value: false,
                    skipped: 1
                },
                "{msg}"
            );
            assert_eq!(
                handover_done(f.path()),
                Checked {
                    value: false,
                    skipped: 0
                },
                "{msg}"
            );
        }
        // dizgi olmayan metin bloğu yok sayılır, aynı satırın dizgi bloğu sayılır
        std::fs::write(
            f.path(),
            r#"{"type":"user","message":{"content":[{"type":"text","text":"y"},{"type":"text","text":1}]}}"#,
        )
        .unwrap();
        assert_eq!(has_real_user_turn(f.path()), Checked { value: true, skipped: 1 });
        assert_eq!(
            handover_done(f.path()),
            Checked {
                value: false,
                skipped: 1
            }
        );
        std::fs::write(
            f.path(),
            format!("{user}\n") + r#"{"type":"assistant","message":{"content":[{"type":"text","text":null},{"type":"text","text":"\nREADY FOR HANDOVER"}]}}"#,
        )
        .unwrap();
        assert_eq!(handover_done(f.path()), Checked { value: true, skipped: 1 });
        let missing = Path::new("/nonexistent/x.jsonl");
        assert!(!handover_done(missing).value && !has_real_user_turn(missing).value);
    }

    /// Bozuk satır kararı düşürmez: git dışı dizinde transkript dalı karar verir, atlanan satır sayılır.
    #[test]
    fn needs_ho_decides_with_bad_rows() {
        let tmp = tempfile::tempdir().unwrap();
        let t = tmp.path().join("t.jsonl");
        std::fs::write(&t, "[]\n{\"type\":\"user\",\"message\":{\"content\":\"iş\"}}\n").unwrap();
        let cwd = tmp.path().to_str().unwrap();
        let got = NeedsHo::new(tmp.path()).needs_ho(cwd, Some(&t));
        assert_eq!(got, Checked { value: true, skipped: 2 });
    }

    #[test]
    fn baseline_is_written_atomically() {
        let tmp = tempfile::tempdir().unwrap();
        let target = tmp.path().join("k");
        std::fs::write(&target, "eski").unwrap();
        write_atomic(&target, b"yeni").unwrap();
        assert_eq!(std::fs::read_to_string(&target).unwrap(), "yeni");
        let names: Vec<_> = std::fs::read_dir(tmp.path())
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect();
        assert_eq!(names, ["k"], "geçici dosya kalmadı");
        // hedef dizin yoksa yazım düşer, geçici dosya kalmaz, eski içerik bozulmaz
        assert!(write_atomic(&tmp.path().join("yok/k"), b"x").is_err());
        // geçici dosya adında sembolik bağ: izlenmez (O_NOFOLLOW + önce silme), hedef dışına yazılmaz
        let outside = tmp.path().join("dis");
        std::fs::write(&outside, "dokunma").unwrap();
        let mut name = std::ffi::OsString::from("k");
        name.push(format!(".{}-{:?}.tmp", std::process::id(), std::thread::current().id()));
        std::os::unix::fs::symlink(&outside, tmp.path().join(&name)).unwrap();
        write_atomic(&target, b"son").unwrap();
        assert_eq!(std::fs::read_to_string(&outside).unwrap(), "dokunma");
        assert_eq!(std::fs::read_to_string(&target).unwrap(), "son");
    }

    #[test]
    fn iso_times_compare_as_instants() {
        // farklı ofsetler sözlüksel değil zaman olarak
        assert!(committed_after("2026-11-04T12:00:00+03:00", "2026-11-04T08:00:00+00:00"));
        assert!(!committed_after("2026-11-04T12:00:00+03:00", "2026-11-04T10:00:00+00:00"));
        assert!(committed_after(
            "2026-11-04T12:00:00+03:00",
            "2026-11-04 11:59:59.5"[..19].trim()
        ));
        assert!(committed_after("2026-11-04T12:00:00+03:00", ""));
        assert!(committed_after("2026-11-04T12:00:00+03:00", "bozuk"));
        assert!(!committed_after("", "2026-11-04T10:00:00+00:00"));
        assert!(!committed_after("2026-11-04T12:00:00Z", "x"));
        for bad in [
            "2026-02-29",
            "2026-13-01",
            "2026-11-04T24:00",
            "2026-11-04T10:00:00+0300",
            "2026-11-04T1",
            "2026-11-04T10:00:00.5",
        ] {
            assert!(from_iso(bad).is_none(), "{bad}");
        }
        for ok in [
            "2026-11-04",
            "2024-02-29T10",
            "2026-11-04T10:00",
            "2026-11-04T10:00:00.123456-01:30",
        ] {
            assert!(from_iso(ok).is_some(), "{ok}");
        }
        assert!(from_iso("2027-01-01").unwrap().0 - from_iso("2026-12-31").unwrap().0 == 86_400_000_000);
    }
}
