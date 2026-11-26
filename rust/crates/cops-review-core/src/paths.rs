//! Çıktı yolu kuralı: `<root>/<proje>/<mode>/<altmodel>[/<effort>][/<lens>]/<ts>/<ts>.md` ve yan dosyalar.
use crate::clock;
use crate::error::{Error, Result};
use crate::py;
use crate::targets::{slug_model, ReviewConfig, ReviewTarget};
use cops_state::json::Json;
use regex::Regex;
use std::sync::LazyLock;

/// Yol katmanı için effort adı.
pub fn effort_for(cfg: &ReviewConfig, mode: &str, target: Option<&ReviewTarget>) -> String {
    let mut v = target.map_or("", |t| t.effort.as_str());
    if py::strip(v).is_empty() {
        v = match mode {
            "claude" => &cfg.review_claude_effort,
            "codex" => &cfg.review_codex_effort,
            "copilot" => &cfg.review_copilot_effort,
            _ => "",
        };
    }
    if py::strip(v).is_empty() {
        "default".into()
    } else {
        slug_model(v)
    }
}

fn is_stamp(s: &str) -> bool {
    static RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\d{14}$").unwrap());
    RE.is_match(s)
}

/// `ts`: epoch (yerel saat) ya da hazır 14 haneli dize.
pub fn review_path(root: &str, proj: &str, t: &ReviewTarget, ts: &Json, effort: &str, lens: &str) -> Result<String> {
    let stamp = match ts {
        Json::Str(s) if is_stamp(s) => s.clone(),
        v => py::float(v)
            .and_then(|f| clock::format_local(f, "%Y%m%d%H%M%S"))
            .ok_or_else(|| Error::Value(format!("review_path ts: {}", py::repr(v))))?,
    };
    let mut parts = vec![slug_model(proj), t.mode.clone(), t.slug.clone()];
    if !effort.is_empty() {
        parts.push(slug_model(effort));
    }
    let lens = if lens.is_empty() { &t.lens } else { lens };
    if !lens.is_empty() {
        parts.push(slug_model(lens));
    }
    parts.push(stamp.clone());
    parts.push(format!("{stamp}.md"));
    let refs: Vec<&str> = parts.iter().map(String::as_str).collect();
    Ok(py::path_join(root, &refs))
}

fn stem(md: &str) -> &str {
    md.strip_suffix(".md").unwrap_or(md)
}

/// Modelin kendi yazdığı rapor taslağı: `<ts>.model.md`.
pub fn draft_path(md: &str) -> String {
    format!("{}.model.md", stem(md))
}
/// ucli `--partial-file` hedefi.
pub fn partial_path(md: &str) -> String {
    format!("{}.partial.json", stem(md))
}
/// Başarısız koşunun kalıcı hata günlüğü.
pub fn error_path(md: &str) -> String {
    format!("{}.error.txt", stem(md))
}
/// Tek bulgu dosyası `<ts>.fNN.md`.
pub fn finding_path(md: &str, n: i64) -> String {
    format!("{}.f{n:02}.md", stem(md))
}

static FINDING_FILE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\.f(\d{2})\.md\n?$").unwrap());

/// Raporun yanındaki bulgu dosyaları (symlink'ler atlanır), ada göre sıralı.
pub fn finding_paths(md: &str) -> Vec<String> {
    let stem = format!("{}.", py::basename(stem(md)));
    let d = py::dirname(md);
    let Ok(rd) = std::fs::read_dir(d) else { return Vec::new() };
    let mut out = Vec::new();
    for e in rd {
        let Ok(e) = e else { return Vec::new() };
        let n = e.file_name().to_string_lossy().into_owned();
        if n.starts_with(&stem) && FINDING_FILE.is_match(&n) {
            let p = py::path_join(d, &[&n]);
            if !std::fs::symlink_metadata(&p).is_ok_and(|m| m.file_type().is_symlink()) {
                out.push(p);
            }
        }
    }
    out.sort();
    out
}

/// Evren istemine eklenen bulgu-dosyası yönergesi.
pub fn draft_prompt_suffix(draft: &str, lang: &str) -> String {
    let md = match draft.strip_suffix(".model.md") {
        Some(s) => format!("{s}.md"),
        None => draft.to_string(),
    };
    let first = finding_path(&md, 1);
    let keep = first.chars().count().saturating_sub("01.md".len());
    let pattern = format!("{}NN.md", py::head(&first, keep));
    if lang == "en" {
        return format!(
            concat!(
                "\nWrite each finding THE MOMENT you have verified it, with write_file, to its own new file {pattern} ",
                "(NN = 01, 02, ... in order; the first is {first} ; one finding per file, heading line included). Do not ",
                "keep findings for the end: a run can be cut off at any time. When you are done, write the whole report ",
                "once to the absolute path {draft} (create-only: it fails if the file exists, so write it exactly ",
                "once). You may not write anywhere else. Then also reply with the report."
            ),
            pattern = pattern,
            first = first,
            draft = draft
        );
    }
    format!(
        concat!(
            "\nHer bulguyu DOĞRULADIĞIN ANDA write_file ile kendi yeni dosyasına yaz: {pattern} (NN = 01, 02, ... ",
            "sırayla; ilki {first} ; her dosyada tek bulgu, başlık satırı dahil). Bulguları sona saklama: koşu her an ",
            "kesilebilir. Bitince tam raporu {draft} mutlak yoluna TEK SEFERDE yaz (yalnız yeni dosya: varsa hata ",
            "verir, o yüzden tam bir kez yaz). Başka hiçbir yere yazamazsın. Sonra raporu yanıt olarak da ver."
        ),
        pattern = pattern,
        first = first,
        draft = draft
    )
}
