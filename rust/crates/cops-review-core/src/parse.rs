//! Review çıktısından bulgu ve doğrulama kararı ayrıştırma.
use crate::py::{self, S};
use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

pub const VERDICT_MARK: &str = "STEWARD-REVIEW-VERDICT:";
pub const VERDICTS: [&str; 3] = ["verified", "refuted", "unclear"];
pub const VERDICT_REASON_MAX: usize = 500;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub r#ref: String,
    pub severity: String,
    pub r#where: String,
    pub title: String,
    pub body: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Verdict {
    pub fid: String,
    pub verdict: String,
    pub reason: String,
}

/// Kod çiti durumu: (yeni açık çit işareti, bu satır çit satırı mı).
fn fence_step(open: &'static str, line: &str) -> (&'static str, bool) {
    let s = py::lstrip(line);
    let mark = if s.starts_with("```") {
        "```"
    } else if s.starts_with("~~~") {
        "~~~"
    } else {
        return (open, false);
    };
    if open.is_empty() {
        (mark, true)
    } else {
        (if mark == open { "" } else { open }, true)
    }
}

/// `## R-n | P# | yer | başlık` bulguları (kod çiti içindekiler sayılmaz; yinelenen `ref` atlanır).
pub fn parse_findings(md: &str) -> Vec<Finding> {
    static HEAD: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(
            r"^#{{2,4}}[{S}]*(R-\d+)[{S}]*\|[{S}]*(P[123])[{S}]*\|[{S}]*(.*?)[{S}]*\|[{S}]*(.+?)[{S}]*$"
        ))
        .unwrap()
    });
    static UPPER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r"^#{{1,2}}[{S}]")).unwrap());
    let mut out: Vec<(Finding, Vec<&str>)> = Vec::new();
    let mut open = false; // `cur is not None` (her zaman son eleman)
    let mut fmark = "";
    let mut seen: HashSet<String> = HashSet::new();
    for line in py::splitlines(md) {
        let (mark, is_fence) = fence_step(fmark, line);
        fmark = mark;
        let fence = !fmark.is_empty();
        if is_fence {
            if open {
                if let Some(c) = out.last_mut() {
                    c.1.push(line);
                }
            }
            continue;
        }
        let m = if fence { None } else { HEAD.captures(line) };
        match m {
            Some(m) if !seen.contains(&m[1]) => {
                seen.insert(m[1].to_string());
                out.push((
                    Finding {
                        r#ref: m[1].to_string(),
                        severity: m[2].to_string(),
                        r#where: m[3].to_string(),
                        title: m[4].to_string(),
                        body: String::new(),
                    },
                    Vec::new(),
                ));
                open = true;
            }
            _ if open => {
                if !fence && UPPER.is_match(line) {
                    open = false;
                } else if let Some(c) = out.last_mut() {
                    c.1.push(line);
                }
            }
            _ => {}
        }
    }
    out.into_iter()
        .map(|(mut f, lines)| {
            f.body = py::strip(&lines.join("\n")).to_string();
            f
        })
        .collect()
}

/// Gerçek `STEWARD-REVIEW-VERDICT:` satırları (aynı fid için son satır geçerli, ilk görülme sırasında).
pub fn scan_verdicts(text: &str) -> Vec<Verdict> {
    static LINE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"^STEWARD-REVIEW-VERDICT:[ \t]*([A-Za-z0-9][A-Za-z0-9._:-]*)[ \t]+(verified|refuted|unclear)(?:[ \t]+(.*))?$",
        )
        .unwrap()
    });
    static PLACEHOLDER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r"^<[^<>\n]{{1,80}}>[{S}`.…]*$")).unwrap());
    let mut out: Vec<Verdict> = Vec::new();
    let mut fmark = "";
    for raw in py::splitlines(text) {
        let s = py::strip(raw);
        let (mark, is_fence) = fence_step(fmark, s);
        fmark = mark;
        if is_fence || !fmark.is_empty() || s.starts_with('>') {
            continue;
        }
        let Some(m) = LINE.captures(s) else { continue };
        let reason = py::strip(m.get(3).map_or("", |g| g.as_str()));
        if PLACEHOLDER.is_match(reason) {
            continue;
        }
        let v = Verdict {
            fid: m[1].to_string(),
            verdict: m[2].to_string(),
            reason: py::head(reason, VERDICT_REASON_MAX).to_string(),
        };
        match out.iter_mut().find(|o| o.fid == v.fid) {
            Some(slot) => *slot = v,
            None => out.push(v),
        }
    }
    out
}
