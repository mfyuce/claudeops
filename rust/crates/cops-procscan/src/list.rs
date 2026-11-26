//! `cops list` çıktısı (`commands/ls.py`).

use crate::session::{duplicates, Session};
use serde::Serialize;
use std::fmt::Write;

#[derive(Serialize)]
struct Row<'a> {
    name: &'a str,
    pid: u32,
    model: &'a str,
    cpu: f64,
    kind: &'static str,
    cwd: &'a str,
}

fn kind(s: &Session) -> &'static str {
    if s.is_fresh() {
        "fresh"
    } else {
        "resume"
    }
}

/// Süzülmüş, ada göre sıralı tablo ya da json; sondaki satır sonu dahil.
pub fn render(mut sessions: Vec<Session>, base: Option<&str>, json: bool) -> String {
    if let Some(b) = base.filter(|b| !b.is_empty()) {
        sessions.retain(|s| s.base() == b);
    }
    sessions.sort_by(|a, b| a.name.cmp(&b.name));
    if json {
        let rows: Vec<Row> = sessions
            .iter()
            .map(|s| Row {
                name: &s.name,
                pid: s.pid,
                model: s.model_short(),
                cpu: s.cpu,
                kind: kind(s),
                cwd: &s.cwd,
            })
            .collect();
        // Dizgi/sayı alanlı yapıların serileştirilmesi başarısız olamaz.
        return serde_json::to_string_pretty(&rows).unwrap_or_else(|_| "[]".into()) + "\n";
    }
    let mut out = format!(
        "{:<13}{:>8}  {:<7}{:>6}  {:<6} CWD\n{}\n",
        "NAME",
        "PID",
        "MODEL",
        "CPU%",
        "KIND",
        "-".repeat(80)
    );
    for s in &sessions {
        let _ = writeln!(
            out,
            "{:<13}{:>8}  {:<7}{:>6.1}  {:<6} {}",
            s.name,
            s.pid,
            s.model_short(),
            s.cpu,
            kind(s),
            s.cwd
        );
    }
    let dups = duplicates(&sessions);
    let tail = if dups.is_empty() {
        "dup yok".to_owned()
    } else {
        format!("⚠ DUP: {}", dups.join(", "))
    };
    let _ = writeln!(out, "\n  {} session  |  {tail}", sessions.len());
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sessions() -> Vec<Session> {
        let mk = |name: &str, pid| Session {
            name: name.into(),
            pid,
            cli: "claude".into(),
            cwd: "/w".into(),
            ..Default::default()
        };
        vec![mk("zeta", 2), mk("alfa", 1)]
    }

    #[test]
    fn json_is_sorted_valid_and_has_no_table() {
        let out = render(sessions(), None, true);
        let v: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!((v[0]["name"].as_str(), v[1]["name"].as_str()), (Some("alfa"), Some("zeta")));
        assert!(out.starts_with("[\n  {\n    \"name\": \"alfa\",\n    \"pid\": 1,\n    \"model\": \"?\",\n    \"cpu\": 0.0,"));
        assert!(!out.contains("NAME"));
        assert_eq!(render(vec![], None, true), "[]\n");
    }

    #[test]
    fn table_matches_python_layout() {
        let out = render(sessions(), None, false);
        let lines: Vec<_> = out.lines().collect();
        assert_eq!(lines[0], "NAME              PID  MODEL    CPU%  KIND   CWD");
        assert_eq!(lines[2], "alfa                1  ?         0.0  fresh  /w");
        assert!(out.ends_with("\n\n  2 session  |  dup yok\n"));
        assert!(render(sessions(), Some("alfa"), false).contains("  1 session  "));
        let mut d = sessions();
        d[0].name = "alfa".into();
        assert!(render(d, None, false).ends_with("⚠ DUP: alfa\n"));
    }
}
