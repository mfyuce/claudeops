//! `cops self`: bu komutu çağıran claude oturumunun kimliği. Python CLI'da (`py/cops`) bu komut YOK (`invalid choice`, çıkış 2);
//! karşılığı eski bash `./claudeops` `cmd_self` + `find_self_claude_pid` (Python yardımcısı `handover.ancestor_pids`):
//! 1. `CLAUDE_CODE_SESSION_ID` doluysa `~/.claude/sessions/*.json` (ada göre sıralı) içinde `sessionId`i eşleşen kaydın `pid`i;
//! 2. yoksa kendi süreçten başlayıp ata zincirinde `comm` = `claude` olan ilk süreç (en çok 64 adım, döngü korumalı);
//! 3. `~/.claude/sessions/<pid>.json` alanları bash ile aynı biçimde yazılır (Python `print(etiket, değer)`).
//!
//! Yalnız KENDİ uid'imizin süreçleri: eşleşen kayıttaki pid canlı ve bizim değilse o kayıt atlanır (bash, ölü pid'li bayat
//! kaydı ilk sıradaysa onu seçer: docs/rs-cli.md "Python hatası?" 9, düzeltilmedi); ata zincirinde başka uid'in `claude`u seçilmez.
//! Kökler ([`SelfCfg`]) enjekte edilir.

use serde_json::Value;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

/// Okunan kökler.
#[derive(Debug, Clone)]
pub struct SelfCfg {
    /// `~/.claude/sessions`
    pub sessions_dir: PathBuf,
    /// `/proc`
    pub proc_root: PathBuf,
    /// Gerçek uid
    pub uid: u32,
    /// Başlangıç süreci (kendimiz)
    pub pid: u32,
    /// `CLAUDE_CODE_SESSION_ID`
    pub session_id: Option<String>,
}

/// Python `str(v)`.
pub fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => py_repr(other),
    }
}

/// Python `repr(v)` (JSON değerleri için; ondalık sayılar yaklaşık, bkz. docs/rs-cli.md S6).
pub fn py_repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => {
            if n.is_f64() {
                let f = n.as_f64().unwrap_or(0.0);
                if f.fract() == 0.0 && f.abs() < 1e16 {
                    format!("{f:.1}")
                } else {
                    format!("{f}")
                }
            } else {
                n.to_string()
            }
        }
        Value::String(s) => {
            let q = if s.contains('\'') && !s.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut o = String::new();
            o.push(q);
            for c in s.chars() {
                match c {
                    '\\' => o.push_str("\\\\"),
                    '\n' => o.push_str("\\n"),
                    '\r' => o.push_str("\\r"),
                    '\t' => o.push_str("\\t"),
                    c if c == q => {
                        o.push('\\');
                        o.push(c)
                    }
                    c => o.push(c),
                }
            }
            o.push(q);
            o
        }
        Value::Array(a) => format!("[{}]", a.iter().map(py_repr).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, v)| format!("{}: {}", py_repr(&Value::String(k.clone())), py_repr(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// Python doğruluk değeri.
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

fn proc_uid(proc_root: &Path, pid: u32) -> Option<u32> {
    std::fs::metadata(proc_root.join(pid.to_string()))
        .ok()
        .map(|m| m.uid())
}

/// `/proc/<pid>/stat` ppid (son `)` sonrası 2. alan; Python `paths.parse_proc_stat`).
fn ppid(proc_root: &Path, pid: u32) -> Option<u32> {
    let raw = std::fs::read(proc_root.join(pid.to_string()).join("stat")).ok()?;
    let s = String::from_utf8_lossy(&raw);
    let i = s.rfind(')')?;
    s[i + 1..].split_whitespace().nth(1)?.parse().ok()
}

fn comm(proc_root: &Path, pid: u32) -> Option<String> {
    let raw = std::fs::read(proc_root.join(pid.to_string()).join("comm")).ok()?;
    // bash: `ps -o comm= | tr -d ' '`
    Some(
        String::from_utf8_lossy(&raw)
            .trim_end_matches('\n')
            .replace(' ', ""),
    )
}

fn json_files(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "json") && p.is_file())
        .collect();
    v.sort();
    v
}

fn read_json(p: &Path) -> Option<Value> {
    serde_json::from_slice(&std::fs::read(p).ok()?).ok()
}

/// `find_self_claude_pid`.
pub fn find_self_pid(c: &SelfCfg) -> Option<u32> {
    if let Some(sid) = c.session_id.as_deref().filter(|s| !s.is_empty()) {
        for f in json_files(&c.sessions_dir) {
            let Some(d) = read_json(&f) else { continue };
            let Some(got) = d.get("sessionId") else {
                continue;
            };
            if py_str(got) != sid {
                continue;
            }
            let Some(pid) = d
                .get("pid")
                .and_then(Value::as_u64)
                .and_then(|p| u32::try_from(p).ok())
            else {
                continue;
            };
            if pid > 0 && proc_uid(&c.proc_root, pid) == Some(c.uid) {
                return Some(pid);
            }
        }
    }
    let mut p = c.pid;
    let mut seen = std::collections::HashSet::new();
    for _ in 0..64 {
        if p <= 1 || !seen.insert(p) {
            return None;
        }
        if comm(&c.proc_root, p).as_deref() == Some("claude")
            && proc_uid(&c.proc_root, p) == Some(c.uid)
        {
            return Some(p);
        }
        p = ppid(&c.proc_root, p)?;
    }
    None
}

/// Komut: çıkış kodu. Çıktı `out`a, hata `err`e.
pub fn run(c: &SelfCfg, out: &mut dyn Write, err: &mut dyn Write) -> std::io::Result<i32> {
    let Some(pid) = find_self_pid(c) else {
        writeln!(out, "(claude alt-süreci değilim — self yok)")?;
        return Ok(1);
    };
    let f = c.sessions_dir.join(format!("{pid}.json"));
    let d = match std::fs::read(&f)
        .map_err(|e| e.to_string())
        .and_then(|b| serde_json::from_slice::<Value>(&b).map_err(|e| format!("JSON değil: {e}")))
    {
        Ok(d) => d,
        Err(e) => {
            writeln!(err, "cops-rs self: {}: {e}", f.display())?;
            return Ok(1);
        }
    };
    let need =
        |k: &str, out: &mut dyn Write, err: &mut dyn Write| -> std::io::Result<Option<String>> {
            match d.get(k) {
                Some(v) => Ok(Some(py_str(v))),
                None => {
                    out.flush()?;
                    writeln!(err, "cops-rs self: {}: '{k}' alanı yok", f.display())?;
                    Ok(None)
                }
            }
        };
    let get = |k: &str, dflt: &str| d.get(k).map(py_str).unwrap_or_else(|| dflt.to_string());
    let Some(v) = need("pid", out, err)? else {
        return Ok(1);
    };
    writeln!(out, "pid:         {v}")?;
    let Some(v) = need("sessionId", out, err)? else {
        return Ok(1);
    };
    writeln!(out, "sessionId:   {v}")?;
    let name = match d.get("name") {
        Some(v) if truthy(v) => py_str(v),
        _ => "-".into(),
    };
    writeln!(out, "name:        {name}")?;
    let Some(v) = need("cwd", out, err)? else {
        return Ok(1);
    };
    writeln!(out, "cwd:         {v}")?;
    writeln!(out, "status:      {}", get("status", ""))?;
    writeln!(out, "bridge:      {}", get("bridgeSessionId", "-"))?;
    match d.get("bridgeSessionId") {
        Some(Value::String(s)) if !s.is_empty() => {
            writeln!(out, "bridge-url:  https://claude.ai/code/{s}")?
        }
        Some(v) if truthy(v) => {
            out.flush()?;
            writeln!(
                err,
                "cops-rs self: {}: bridgeSessionId metin değil",
                f.display()
            )?;
            return Ok(1);
        }
        _ => writeln!(out, "bridge-url:  (no RC)")?,
    }
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn cfg(t: &Path, sid: Option<&str>) -> SelfCfg {
        SelfCfg {
            sessions_dir: t.join("sessions"),
            proc_root: t.join("proc"),
            // SAFETY: argümansız libc çağrısı.
            uid: unsafe { libc::getuid() },
            pid: 500,
            session_id: sid.map(str::to_string),
        }
    }

    fn proc(t: &Path, pid: u32, comm: &str, ppid: u32) {
        let d = t.join("proc").join(pid.to_string());
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join("comm"), format!("{comm}\n")).unwrap();
        std::fs::write(d.join("stat"), format!("{pid} ({comm} x) S {ppid} 1 1")).unwrap();
    }

    fn sess(t: &Path, file: &str, v: Value) {
        std::fs::create_dir_all(t.join("sessions")).unwrap();
        std::fs::write(t.join("sessions").join(file), v.to_string()).unwrap();
    }

    fn out(c: &SelfCfg) -> (i32, String, String) {
        let (mut o, mut e) = (Vec::new(), Vec::new());
        let rc = run(c, &mut o, &mut e).unwrap();
        (
            rc,
            String::from_utf8(o).unwrap(),
            String::from_utf8(e).unwrap(),
        )
    }

    #[test]
    fn session_id_match_prints_bash_layout() {
        let t = tempfile::tempdir().unwrap();
        proc(t.path(), 42, "claude", 1);
        sess(
            t.path(),
            "42.json",
            json!({"pid": 42, "sessionId": "S", "cwd": "/w", "status": "busy", "bridgeSessionId": "B", "name": ""}),
        );
        let (rc, o, _) = out(&cfg(t.path(), Some("S")));
        assert_eq!(rc, 0);
        assert_eq!(
            o,
            "pid:         42\nsessionId:   S\nname:        -\ncwd:         /w\nstatus:      busy\nbridge:      B\nbridge-url:  https://claude.ai/code/B\n"
        );
    }

    #[test]
    fn stale_dead_pid_record_is_skipped_for_live_one() {
        let t = tempfile::tempdir().unwrap();
        proc(t.path(), 77, "claude", 1);
        sess(
            t.path(),
            "1.json",
            json!({"pid": 31999, "sessionId": "S", "cwd": "/old"}),
        );
        sess(
            t.path(),
            "77.json",
            json!({"pid": 77, "sessionId": "S", "cwd": "/new"}),
        );
        assert_eq!(find_self_pid(&cfg(t.path(), Some("S"))), Some(77));
    }

    #[test]
    fn ancestor_walk_finds_claude_and_is_bounded() {
        let t = tempfile::tempdir().unwrap();
        proc(t.path(), 500, "bash", 400);
        proc(t.path(), 400, "claude", 300);
        proc(t.path(), 300, "systemd", 1);
        sess(
            t.path(),
            "400.json",
            json!({"pid": 400, "sessionId": "X", "cwd": "/c", "name": "n", "bridgeSessionId": null}),
        );
        let (rc, o, _) = out(&cfg(t.path(), None));
        assert_eq!(rc, 0);
        assert!(o.contains("name:        n\n"), "{o}");
        assert!(
            o.ends_with("status:      \nbridge:      None\nbridge-url:  (no RC)\n"),
            "{o}"
        );
        // döngü: 500 -> 400 -> 500
        let t2 = tempfile::tempdir().unwrap();
        proc(t2.path(), 500, "bash", 400);
        proc(t2.path(), 400, "zsh", 500);
        assert_eq!(find_self_pid(&cfg(t2.path(), None)), None);
        let (rc, o, _) = out(&cfg(t2.path(), None));
        assert_eq!(
            (rc, o.as_str()),
            (1, "(claude alt-süreci değilim — self yok)\n")
        );
    }

    #[test]
    fn missing_field_and_bad_bridge_fail_after_partial_output() {
        let t = tempfile::tempdir().unwrap();
        proc(t.path(), 42, "claude", 1);
        sess(t.path(), "42.json", json!({"pid": 42, "sessionId": "S"}));
        let (rc, o, e) = out(&cfg(t.path(), Some("S")));
        assert_eq!(rc, 1);
        assert!(o.ends_with("name:        -\n"), "{o}");
        assert!(e.contains("'cwd' alanı yok"));
        sess(
            t.path(),
            "42.json",
            json!({"pid": 42, "sessionId": "S", "cwd": "/w", "bridgeSessionId": 5}),
        );
        let (rc, o, e) = out(&cfg(t.path(), Some("S")));
        assert_eq!(rc, 1);
        assert!(o.ends_with("bridge:      5\n") && e.contains("metin değil"));
    }

    #[test]
    fn python_str_and_repr() {
        assert_eq!(py_str(&json!(null)), "None");
        assert_eq!(py_str(&json!(true)), "True");
        assert_eq!(py_str(&json!(1.0)), "1.0");
        assert_eq!(py_str(&json!(["a", 1])), "['a', 1]");
        assert_eq!(py_str(&json!({"k": "it's"})), "{'k': \"it's\"}");
    }
}
