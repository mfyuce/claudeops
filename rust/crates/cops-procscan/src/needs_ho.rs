//! Oturum devir (ho) gerektiriyor mu (`needs_ho.py`): git sinyalleri ve transkript.

use crate::{proc_cmd, py};
use serde_json::{Map, Value};
use sha1::{Digest, Sha1};
use std::fmt::Write;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::ops::ControlFlow;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

const RFH: &str = "READY FOR HANDOVER";
const GIT_TIMEOUT: Duration = Duration::from_secs(15);

/// Python'un istisna fırlattığı transkript satırı (nesne olmayan satır, dizgi olmayan `text` vb.).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BadTranscript;

impl std::fmt::Display for BadTranscript {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("transkript satırı beklenen biçimde değil")
    }
}

impl std::error::Error for BadTranscript {}

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

    /// Ho sonrası HEAD'i baseline yap. Depo değilse hiçbir şey yazmaz.
    pub fn repo_baseline_set(&self, cwd: &str) -> std::io::Result<()> {
        let key = repo_key(cwd);
        let head = git(cwd, &["rev-parse", "HEAD"]);
        if let (Some(k), false) = (key, head.is_empty()) {
            let dir = self.state_dir.join("baselines");
            std::fs::create_dir_all(&dir)?;
            std::fs::write(dir.join(k), head)?;
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
    pub fn needs_ho(&self, cwd: &str, jsonl: Option<&Path>) -> Result<bool, BadTranscript> {
        if let Some(p) = jsonl {
            if !has_real_user_turn(p)? {
                return Ok(false);
            }
        }
        if repo_dirty(cwd) || repo_untracked_count(cwd) > 0 || self.repo_committed_since(cwd) {
            return Ok(true);
        }
        match jsonl {
            Some(p) => Ok(!handover_done(p)?),
            None => Ok(false),
        }
    }
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

/// Transkriptin ayrıştırılabilen satırları. Okuma hatası `Ok(None)`.
fn each_row(
    path: &Path,
    mut f: impl FnMut(&Map<String, Value>) -> Result<ControlFlow<()>, BadTranscript>,
) -> Result<Option<()>, BadTranscript> {
    let Ok(file) = File::open(path) else { return Ok(None) };
    let mut reader = BufReader::new(file);
    let mut buf = Vec::new();
    loop {
        buf.clear();
        match reader.read_until(b'\n', &mut buf) {
            Ok(0) => return Ok(Some(())),
            Ok(_) => {}
            Err(_) => return Ok(None),
        }
        // metin kipi: `\r` de satır sonu; geçersiz utf-8 yerine U+FFFD
        for part in buf.split(|&c| c == b'\r') {
            let line = String::from_utf8_lossy(part);
            let line = py::strip(&line);
            if line.is_empty() {
                continue;
            }
            let Some(v) = py::json(line.as_bytes()) else { continue };
            let Value::Object(o) = v else { return Err(BadTranscript) };
            if f(&o)?.is_break() {
                return Ok(Some(()));
            }
        }
    }
}

fn is_type(block: &Value, kind: &str) -> bool {
    block.get("type").and_then(Value::as_str) == Some(kind)
}

fn block_text(block: &Value) -> Result<&str, BadTranscript> {
    match block.get("text") {
        None => Ok(""),
        Some(Value::String(s)) => Ok(s),
        Some(_) => Err(BadTranscript),
    }
}

/// Asistan cevabında devir işareti var ve sonrasında yeni kullanıcı isteği yok.
pub fn handover_done(path: &Path) -> Result<bool, BadTranscript> {
    let (mut last_rfh, mut last_user, mut i) = (None::<u64>, None::<u64>, 0u64);
    let read = each_row(path, |o| {
        i += 1;
        let kind = o.get("type").and_then(Value::as_str);
        let content = o.get("message").and_then(Value::as_object).and_then(|m| m.get("content"));
        let text = match content {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Array(blocks)) => {
                let mut parts = Vec::new();
                for b in blocks.iter().filter(|b| is_type(b, "text")) {
                    parts.push(block_text(b)?);
                }
                parts.join(" ")
            }
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
        Ok(ControlFlow::Continue(()))
    })?;
    Ok(read.is_some() && last_rfh.is_some() && last_rfh >= last_user)
}

/// En az bir gerçek kullanıcı mesajı (tool_result, sidechain, isMeta, boş metin sayılmaz).
pub fn has_real_user_turn(path: &Path) -> Result<bool, BadTranscript> {
    let mut found = false;
    each_row(path, |o| {
        let flag = |k: &str| o.get(k).is_some_and(py::truthy);
        if o.get("type").and_then(Value::as_str) != Some("user") || flag("isSidechain") || flag("isMeta") {
            return Ok(ControlFlow::Continue(()));
        }
        let content = match o.get("message") {
            None => None,
            Some(Value::Object(m)) => m.get("content"),
            Some(_) => return Err(BadTranscript),
        };
        match content {
            Some(Value::String(s)) => found = !py::strip(s).is_empty(),
            Some(Value::Array(blocks)) => {
                let tool = blocks.iter().any(|b| is_type(b, "tool_result"));
                let mut has_text = false;
                for b in blocks.iter().filter(|b| is_type(b, "text")) {
                    if !py::strip(block_text(b)?).is_empty() {
                        has_text = true;
                        break;
                    }
                }
                found = !tool && has_text;
            }
            _ => {}
        }
        Ok(if found {
            ControlFlow::Break(())
        } else {
            ControlFlow::Continue(())
        })
    })?;
    Ok(found)
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
        assert!(!handover_done(transcript(&[row("user", m)]).path()).unwrap());
        assert!(handover_done(transcript(&[row("user", "iş"), row("assistant", m)]).path()).unwrap());
        for kind in ["api-request-blob", "attachment", "system"] {
            let t = transcript(&[row(kind, m)]);
            assert!(!handover_done(t.path()).unwrap(), "{kind}");
            assert!(!has_real_user_turn(t.path()).unwrap(), "{kind}");
        }
        assert!(handover_done(transcript(&[row("system", m), row("assistant", m)]).path()).unwrap());
        // işaretten sonra yeni istek; tool_result istek sayılmaz
        assert!(!handover_done(transcript(&[row("assistant", m), row("user", "bir iş daha")]).path()).unwrap());
        let tool = json!({"type": "user", "message": {"content": [{"type": "tool_result"}, {"type": "text", "text": "x"}]}});
        assert!(handover_done(transcript(&[row("assistant", m), tool.clone()]).path()).unwrap());
        assert!(!has_real_user_turn(transcript(&[tool]).path()).unwrap());
    }

    #[test]
    fn real_user_turn_filters() {
        let with = |k: &str| json!({"type": "user", k: true, "message": {"content": "x"}});
        assert!(!has_real_user_turn(transcript(&[with("isMeta"), with("isSidechain"), row("user", "  ")]).path()).unwrap());
        assert!(has_real_user_turn(transcript(&[json!({"type": "user", "message": {"content": "x"}})]).path()).unwrap());
        assert!(!has_real_user_turn(transcript(&[json!({"type": "user"})]).path()).unwrap());
    }

    #[test]
    fn broken_input_like_python() {
        let f = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(
            f.path(),
            b"\n{bozuk\n\xff\xfe\r{\"type\":\"assistant\",\"message\":{\"content\":\"READY FOR HANDOVER \\ud800\"}}",
        )
        .unwrap();
        assert!(handover_done(f.path()).unwrap());
        for bad in ["123", "[]"] {
            std::fs::write(f.path(), bad).unwrap();
            assert_eq!(handover_done(f.path()), Err(BadTranscript));
            assert_eq!(has_real_user_turn(f.path()), Err(BadTranscript));
        }
        std::fs::write(f.path(), r#"{"type":"user","message":null}"#).unwrap();
        assert_eq!(has_real_user_turn(f.path()), Err(BadTranscript));
        std::fs::write(
            f.path(),
            r#"{"type":"user","message":{"content":[{"type":"text","text":1}]}}"#,
        )
        .unwrap();
        assert_eq!(handover_done(f.path()), Err(BadTranscript));
        let missing = Path::new("/nonexistent/x.jsonl");
        assert!(!handover_done(missing).unwrap() && !has_real_user_turn(missing).unwrap());
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
