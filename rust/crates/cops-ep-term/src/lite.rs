//! `web_term_lite`: lite kare (`to_lite`, memo'suz REST yolu), `viewport_text`, URL/yol adayları. Saf işlevler.
//!
//! Desenler `web_term_lite._URL_RE/_PATH_RE/_TRAILING_PUNCT_RE` ile aynı dil; Python `\s` U+001C..U+001F'i de kapsadığı için
//! sınıfa açıkça eklenir ([`crate::mode::PY_SPACE_CLASS`] ile aynı küme).
use cops_state::{Json, Map};
use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

pub const MAX_URLS: usize = 3;
pub const MAX_PATH_CANDIDATES: usize = 8;

static URL_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"https?://[^\s\x1c-\x1f<>"'\x1b\x07]+"#).expect("sabit desen"));
static PATH_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?:~/|\.\.?/|/)[^\s\x1c-\x1f<>"'\x1b\x07]+"#).expect("sabit desen")
});
static TRAILING_PUNCT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"[.,;:)\]}>'"]+$"#).expect("sabit desen"));

/// `_newest_first`: sondan başa, sondaki noktalama kırpılmış, tekil, `cap` ile sınırlı, en az `min_len` kod noktası.
fn newest_first(matches: &[&str], cap: usize, min_len: usize) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for m in matches.iter().rev() {
        if out.len() >= cap {
            break;
        }
        let cand = TRAILING_PUNCT_RE.replace(m, "").into_owned();
        if cand.chars().count() >= min_len && seen.insert(cand.clone()) {
            out.push(cand);
        }
    }
    out
}

/// `extract_urls(text)`.
pub fn extract_urls(text: &str) -> Vec<String> {
    let clean = cops_tmux::strip_ansi(text);
    let all: Vec<&str> = URL_RE.find_iter(&clean).map(|m| m.as_str()).collect();
    newest_first(&all, MAX_URLS, 1)
}

/// `extract_path_candidates(text)`.
pub fn extract_path_candidates(text: &str) -> Vec<String> {
    let clean = cops_tmux::strip_ansi(text);
    let all: Vec<&str> = PATH_RE.find_iter(&clean).map(|m| m.as_str()).collect();
    newest_first(&all, MAX_PATH_CANDIDATES, 2)
}

/// `viewport_text(text, rows)`: son `rows` satır, sondaki `\n`siz. Python `[-rows:]`: `rows == 0` TÜM satırlar.
pub fn viewport_text(text: &str, rows: u64) -> String {
    let body = text.strip_suffix('\n').unwrap_or(text);
    let lines: Vec<&str> = body.split('\n').collect();
    let keep = if rows == 0 {
        lines.len()
    } else {
        lines.len().min(usize::try_from(rows).unwrap_or(usize::MAX))
    };
    lines[lines.len() - keep..].join("\n")
}

/// `to_lite(payload)` (memo'suz): çevrilemeyen kare AYNEN döner.
pub fn to_lite(payload: Json) -> Json {
    let Json::Object(mut m) = payload else {
        return payload;
    };
    let truthy = |k: &str| m.get(k).is_some_and(Json::truthy);
    if !truthy("ok") || truthy("lite") {
        return Json::Object(m);
    }
    // Python `isinstance(rows, int)` ve `bool` değil, `rows >= 1`; kareyi bu crate kurduğu için yalnız `Int` görülür.
    let (Some(Json::Str(text)), Some(&Json::Int(rows))) = (m.get("text"), m.get("rows")) else {
        return Json::Object(m);
    };
    if rows < 1 {
        return Json::Object(m);
    }
    let urls = extract_urls(text);
    let paths = extract_path_candidates(text);
    let view = viewport_text(text, rows as u64);
    m.insert("text".into(), Json::Str(view));
    m.insert("lite".into(), Json::Bool(true));
    m.insert("urls".into(), strs(urls));
    m.insert("paths".into(), strs(paths));
    Json::Object(m)
}

pub fn strs(v: Vec<String>) -> Json {
    Json::Array(v.into_iter().map(Json::Str).collect())
}

/// Boş `Map` kısaltması (kare kurucuları).
pub fn obj(pairs: Vec<(&str, Json)>) -> Json {
    let mut m = Map::new();
    for (k, v) in pairs {
        m.insert(k.into(), v);
    }
    Json::Object(m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn viewport_keeps_last_rows_without_trailing_newline() {
        assert_eq!(viewport_text("a\nb\nc\n", 2), "b\nc");
        assert_eq!(viewport_text("a\nb\nc\n", 0), "a\nb\nc");
        assert_eq!(viewport_text("a\nb", 9), "a\nb");
        assert_eq!(viewport_text("", 3), "");
        assert_eq!(viewport_text("\n", 3), "");
    }

    #[test]
    fn url_and_path_candidates_newest_first() {
        let t = "\x1b[1mhttps://a.test/x).\x1b[0m https://b.test https://a.test/x ./p/q, ~/r /s /";
        assert_eq!(extract_urls(t), vec!["https://a.test/x", "https://b.test"]);
        assert_eq!(
            extract_path_candidates(t),
            vec!["/s", "~/r", "./p/q", "//a.test/x", "//b.test"]
        );
    }

    #[test]
    fn to_lite_leaves_unconvertible_frames() {
        let bad = obj(vec![
            ("ok", Json::Bool(false)),
            ("text", Json::Str("x".into())),
        ]);
        assert_eq!(to_lite(bad.clone()), bad);
        let no_rows = obj(vec![
            ("ok", Json::Bool(true)),
            ("text", Json::Str("x".into())),
            ("rows", Json::Null),
        ]);
        assert_eq!(to_lite(no_rows.clone()), no_rows);
        let lite = obj(vec![("ok", Json::Bool(true)), ("lite", Json::Bool(true))]);
        assert_eq!(to_lite(lite.clone()), lite);
    }
}
