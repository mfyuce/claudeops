//! Onaylı bulguların TODO/TBD dosyalarına dışa aktarımı ve eskime denetimi.
use crate::error::{Error, Result};
use crate::py::{self, S};
use crate::targets::ci;
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::BTreeSet;
use std::io::Read as _;
use std::process::{Command, Stdio};
use std::sync::LazyLock;
use std::time::{Duration, Instant, UNIX_EPOCH};

pub const EXPORT_HEADING: &str = "## Review bulguları";
const GIT_TIMEOUT: Duration = Duration::from_secs(10);

/// `r['id']`: yoksa Python gibi hata.
pub(crate) fn row_id(r: &Map) -> Result<String> {
    r.get("id").map(py::to_str).ok_or_else(|| Error::Value("KeyError: 'id'".into()))
}

/// Karar gerektiren bulgu mu (RTBD'ye gider).
pub fn is_decision(row: &Map) -> bool {
    static DECISION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"(?i)\b(karar\w*|tercih\w*|seçenek\w*|politika\w*|sahip\w* karar|belirsiz\w*|trade-?off|design decision|should (?:we|it)|policy|ambiguous|undefined behaviou?r)",
        )
        .unwrap()
    });
    let body = py::str_or_empty(row.get("body"));
    let text = format!("{} {}", py::str_or_empty(row.get("title")), py::head(&body, 600));
    DECISION.is_match(&ci(&text))
}

/// `where` alanı; Markdown bağlantısıysa yalnız görünen metin.
pub fn where_text(row: &Map) -> String {
    static LINK: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r"^[{S}]*`?\[([^\]]+)\]\([^)]*\)`?")).unwrap());
    let w = py::str_or_empty(row.get("where"));
    match LINK.captures(&w) {
        Some(m) => m[1].to_string(),
        None => w,
    }
}

fn where_path(row: &Map) -> String {
    static FILE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r"^[{S}]*`?([^{S}:`]+\.[A-Za-z0-9]+)")).unwrap());
    FILE.captures(&where_text(row)).map_or_else(String::new, |m| m[1].to_string())
}

fn exists(p: &str) -> bool {
    std::fs::metadata(p).is_ok()
}
fn is_dir(p: &str) -> bool {
    std::fs::metadata(p).is_ok_and(|m| m.is_dir())
}

fn where_file(row: &Map, cwd: &str) -> String {
    let rel = where_path(row);
    if rel.is_empty() {
        return String::new();
    }
    let path = py::realpath(&py::path_join(cwd, &[&rel]));
    let root = py::realpath(cwd);
    if path.starts_with(&format!("{root}/")) && std::fs::metadata(&path).is_ok_and(|m| m.is_file()) {
        path
    } else {
        String::new()
    }
}

/// Bulgunun göreli dosya yolu; mutlak ya da `..` içeren "".
pub fn where_relpath(row: &Map) -> String {
    let rel = where_path(row);
    if rel.starts_with('/') || rel.split('/').any(|p| p == "..") {
        String::new()
    } else {
        rel
    }
}

static BACKTICK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"`([A-Za-z_][A-Za-z0-9_.]*)`").unwrap());

pub fn has_quoted_names(row: &Map) -> bool {
    BACKTICK.is_match(&py::str_or_empty(row.get("title")))
}

/// Başlıktaki backtick'li adların hiçbiri `src`de yoksa gerekçe (`src` `None` = okunamadı).
pub fn stale_reason_text(row: &Map, src: Option<&str>) -> Option<String> {
    let src = src?;
    let title = py::str_or_empty(row.get("title"));
    let names: BTreeSet<&str> = BACKTICK
        .captures_iter(&title)
        .filter_map(|c| c.get(1))
        .map(|g| g.as_str().rsplit('.').next().unwrap_or(""))
        .collect();
    if names.is_empty() || names.iter().any(|n| src.contains(n)) {
        return None;
    }
    Some(format!("tanımlayıcılar dosyada yok: {}", names.into_iter().collect::<Vec<_>>().join(", ")))
}

pub fn stale_reason(row: &Map, cwd: &str) -> Option<String> {
    let path = where_file(row, cwd);
    if path.is_empty() {
        return None;
    }
    let bytes = std::fs::read(path).ok()?;
    // metin kipi: satır sonları `\n`ye çevrilir
    let src = String::from_utf8_lossy(&bytes).replace("\r\n", "\n").replace('\r', "\n");
    stale_reason_text(row, Some(&src))
}

fn mtime(p: &str) -> Option<f64> {
    let t = std::fs::metadata(p).ok()?.modified().ok()?;
    Some(match t.duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_secs_f64(),
        Err(e) => -e.duration().as_secs_f64(),
    })
}

/// `git log -1 --format=%ct`; hata ya da 10 sn zaman aşımında `Err`.
fn git_commit_time(cwd: &str, path: &str) -> std::io::Result<String> {
    let mut child = Command::new("git")
        .args(["-C", cwd, "--literal-pathspecs", "log", "-1", "--format=%ct", "--", path])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let deadline = Instant::now() + GIT_TIMEOUT;
    while child.try_wait()?.is_none() {
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::ErrorKind::TimedOut.into());
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    // çıktı tek satır: boru dolmaz
    let mut out = String::new();
    if let Some(mut s) = child.stdout.take() {
        s.read_to_string(&mut out)?;
    }
    Ok(py::strip(&out).to_string())
}

/// Bulgunun dosyası rapordan sonra değişti mi; karar verilemezse `false`.
pub fn changed_after_review(row: &Map, cwd: &str) -> bool {
    let path = where_file(row, cwd);
    let report = py::str_or_empty(row.get("review_file"));
    if path.is_empty() || report.is_empty() || !exists(&report) {
        return false;
    }
    let Some(mut t) = mtime(&path) else { return false };
    if exists(&py::path_join(cwd, &[".git"])) {
        let Ok(out) = git_commit_time(cwd, &path) else { return false };
        if !out.is_empty() && out.chars().all(|c| c.is_ascii_digit()) {
            t = out.parse().unwrap_or(t);
        }
    }
    mtime(&report).is_some_and(|r| t > r)
}

/// `path` bir git worktree'siyse ana deponun kökü, değilse "".
pub fn worktree_main(path: &str) -> Result<String> {
    static GITDIR: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(r"^gitdir:[{S}]*(.+)/\.git/worktrees/[^/]+\n?$")).unwrap()
    });
    let Ok(bytes) = std::fs::read(py::path_join(path, &[".git"])) else { return Ok(String::new()) };
    let text = String::from_utf8(bytes).map_err(|_| Error::Value(format!("{path}/.git: utf-8 değil")))?;
    let line = py::head(&text, 4096).replace("\r\n", "\n").replace('\r', "\n");
    Ok(match GITDIR.captures(py::strip(&line)) {
        Some(m) if is_dir(&py::path_join(&m[1], &[".git"])) => m[1].to_string(),
        _ => String::new(),
    })
}

/// Hedef depo `cwd` değilse (satır, kök): denetim gerçek depoda yapılır, `where`in depo öneki atılır.
pub fn row_in_repo(row: &Map, root: &str, cwd: &str) -> (Map, String) {
    if root.is_empty() || py::realpath(root) == py::realpath(cwd) {
        return (row.clone(), cwd.to_string());
    }
    let w = where_text(row);
    let w = py::strip(&w).trim_matches('`');
    let rest = w.split_once('/').map_or(w, |(_, r)| r);
    let mut r = row.clone();
    r.insert("where".into(), Json::Str(rest.to_string()));
    (r, root.to_string())
}

/// Bulgunun TODO dosyasının yazılacağı depo kökü; "" = çözülemedi (YAZMA).
pub fn export_root(row: &Map, project: &str, cwd: &str, resolve: impl Fn(&str) -> String) -> Result<String> {
    let rel = where_relpath(row);
    let prefix = rel.split_once('/').map_or("", |(p, _)| p);
    if !prefix.is_empty() && prefix != project {
        let d = resolve(prefix);
        if !d.is_empty() && is_dir(&d) && exists(&py::path_join(&d, &[".git"])) {
            return Ok(d);
        }
        let main = worktree_main(&py::path_join(cwd, &[prefix]))?;
        if !main.is_empty() {
            return Ok(main);
        }
    }
    if exists(&py::path_join(cwd, &[".git"])) {
        return Ok(cwd.to_string());
    }
    if !prefix.is_empty() && is_dir(&py::path_join(cwd, &[prefix])) {
        return Ok(String::new());
    }
    Ok(cwd.to_string())
}

pub fn export_lines(rows: &[Map], reviews_root: &str) -> Result<Vec<String>> {
    let mut out = Vec::new();
    for r in rows {
        let mut src = py::str_or_empty(r.get("review_file"));
        if !reviews_root.is_empty() && src.starts_with(&format!("{}/", reviews_root.trim_end_matches('/'))) {
            src = py::relpath(&src, reviews_root);
        }
        if src.starts_with('/') {
            let parts: Vec<&str> = src.trim_end_matches('/').split('/').collect();
            src = parts[parts.len().saturating_sub(4)..].join("/");
        }
        let title = py::collapse_ws(&py::str_or_empty(r.get("title")));
        let or_q = |k: &str| {
            if py::truthy(r.get(k)) {
                py::str_or_empty(r.get(k))
            } else {
                "?".to_string()
            }
        };
        let note = if py::truthy(r.get("note")) {
            format!(" [{}]", py::str_or_empty(r.get("note")))
        } else {
            String::new()
        };
        out.push(format!(
            "- [ ] (review {}) [{}] {}: {title} (kaynak: {src}){note}",
            row_id(r)?,
            or_q("severity"),
            or_q("where")
        ));
    }
    Ok(out)
}

/// `text`in sonuna yeni bulguları ekler: (yeni içerik ya da `None`, yazılan fid'ler).
pub fn appended_export(
    text: &str,
    rows: &[Map],
    reviews_root: &str,
    stamp: &str,
) -> Result<(Option<String>, Vec<String>)> {
    let mut fresh: Vec<Map> = Vec::new();
    let mut ids = Vec::new();
    for r in rows {
        let id = row_id(r)?;
        if !text.contains(&format!("(review {id})")) {
            fresh.push(r.clone());
            ids.push(id);
        }
    }
    if fresh.is_empty() {
        return Ok((None, Vec::new()));
    }
    let lines = export_lines(&fresh, reviews_root)?.join("\n");
    let last_head = py::splitlines(text).into_iter().rev().find(|l| l.starts_with("## ")).unwrap_or("");
    let body = text.trim_end_matches('\n');
    let new = if last_head.starts_with(EXPORT_HEADING) {
        format!("{body}\n{lines}\n")
    } else {
        let sep = if body.is_empty() { String::new() } else { format!("{body}\n\n") };
        format!("{sep}{EXPORT_HEADING} ({stamp})\n{lines}\n")
    };
    Ok((Some(new), ids))
}
