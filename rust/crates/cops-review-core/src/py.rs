//! Python dil davranışlarının küçük karşılıkları (parite için): boşluk kümesi, `strip`, `splitlines`, `str()`,
//! `float()`, doğruluk değeri. `review.py` bunlara dayanıyor; Rust std farklı davranır.
use crate::error::{Error, Result};
use cops_state::json::{py_float_repr, Json};

/// Python `str.isspace()`: Unicode White_Space + `\x1c..\x1f` (regex `\s` de aynı küme).
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Regex içinde Python `\s` karşılığı karakter sınıfı gövdesi.
pub const S: &str = r"\s\x1c-\x1f";

pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}
pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(is_space)
}

/// `str.split()` (argümansız).
pub fn split_ws(s: &str) -> impl Iterator<Item = &str> {
    s.split(is_space).filter(|p| !p.is_empty())
}

/// `textutil.collapse_ws`.
pub fn collapse_ws(s: &str) -> String {
    split_ws(s).collect::<Vec<_>>().join(" ")
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{0b}'
            | '\u{0c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// `str.splitlines()`.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if !is_line_break(c) {
            continue;
        }
        out.push(&s[start..i]);
        let mut end = i + c.len_utf8();
        if c == '\r' {
            if let Some(&(j, '\n')) = it.peek() {
                it.next();
                end = j + 1;
            }
        }
        start = end;
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// İlk `n` karakter (Python dilimi `s[:n]`).
pub fn head(s: &str, n: usize) -> &str {
    s.char_indices().nth(n).map_or(s, |(i, _)| &s[..i])
}

/// Son `n` karakter (Python `s[-n:]`).
pub fn tail(s: &str, n: usize) -> &str {
    let len = s.chars().count();
    if len <= n {
        return s;
    }
    s.char_indices().nth(len - n).map_or(s, |(i, _)| &s[i..])
}

fn repr_str(s: &str) -> String {
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
                o.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                o.push_str(&format!("\\x{:02x}", c as u32))
            }
            c => o.push(c),
        }
    }
    o.push(q);
    o
}

/// Python `repr(değer)` (JSON'dan gelen değerler için).
pub fn repr(v: &Json) -> String {
    match v {
        Json::Str(s) => repr_str(s),
        _ => to_str(v),
    }
}

/// Python `str(değer)`.
pub fn to_str(v: &Json) -> String {
    match v {
        Json::Null => "None".into(),
        Json::Bool(true) => "True".into(),
        Json::Bool(false) => "False".into(),
        Json::Int(i) => i.to_string(),
        Json::BigInt(s) => s.clone(),
        Json::Float(f) if f.is_nan() => "nan".into(),
        Json::Float(f) if f.is_infinite() => if *f > 0.0 { "inf" } else { "-inf" }.into(),
        Json::Float(f) => py_float_repr(*f),
        Json::Str(s) => s.clone(),
        Json::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Json::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, v)| format!("{}: {}", repr_str(k), repr(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// `str(x or "")`.
pub fn str_or_empty(v: Option<&Json>) -> String {
    match v {
        Some(v) if v.truthy() => to_str(v),
        _ => String::new(),
    }
}

pub fn truthy(v: Option<&Json>) -> bool {
    v.is_some_and(Json::truthy)
}

/// Python `float(str)`: boşluk kırpma, `_` ayraçları, `inf`/`nan`/`infinity`, ASCII olmayan ondalık rakamlar.
pub fn float_str(s: &str) -> Option<f64> {
    cops_state::pycompat::parse_float(s)
}

/// Python `float(değer)`; dönüştürülemezse `None` (TypeError/ValueError/OverflowError).
pub fn float(v: &Json) -> Option<f64> {
    match v {
        Json::Bool(b) => Some(f64::from(u8::from(*b))),
        Json::Int(i) => Some(*i as f64),
        Json::BigInt(s) => s.parse::<f64>().ok().filter(|f| f.is_finite()),
        Json::Float(f) => Some(*f),
        Json::Str(s) => float_str(s),
        _ => None,
    }
}

/// `review._num`: `float(v or 0)`, olmazsa ya da sonlu değilse 0 (sonlu olmayan loglanır).
pub fn num(v: Option<&Json>) -> f64 {
    let Some(v) = v.filter(|v| v.truthy()) else {
        return 0.0;
    };
    match float(v) {
        Some(f) if f.is_finite() => f,
        None if !matches!(v, Json::BigInt(_)) => 0.0,
        _ => {
            crate::badrec::log_bad("number.nonfinite", "");
            0.0
        }
    }
}

/// `float(v or 0)`; dönüştürülemezse Python gibi hata.
pub fn float_or_zero(v: Option<&Json>) -> Result<f64> {
    match v {
        Some(v) if v.truthy() => {
            float(v).ok_or_else(|| Error::Value(format!("float({})", repr(v))))
        }
        _ => Ok(0.0),
    }
}

/// `int(v or 0)`; dönüştürülemezse Python gibi hata.
pub fn int_or_zero(v: Option<&Json>) -> Result<i64> {
    let Some(v) = v.filter(|v| v.truthy()) else {
        return Ok(0);
    };
    let r = match v {
        Json::Str(s) => {
            let t = strip(s);
            let body = t.strip_prefix(['+', '-']).unwrap_or(t);
            let ok = !body.is_empty()
                && body
                    .split('_')
                    .all(|g| !g.is_empty() && g.bytes().all(|b| b.is_ascii_digit()));
            ok.then(|| t.replace('_', "").parse::<i64>().ok()).flatten()
        }
        _ => float(v)
            .filter(|f| f.is_finite() && f.abs() < 9.2e18)
            .map(|f| f.trunc() as i64),
    };
    r.ok_or_else(|| Error::Value(format!("int({})", repr(v))))
}

/// Python `==` bir dize ile.
pub fn is_str(v: Option<&Json>, s: &str) -> bool {
    matches!(v, Some(Json::Str(x)) if x == s)
}

/// `value in (dizeler)`.
pub fn str_in(v: Option<&Json>, set: &[&str]) -> bool {
    matches!(v, Some(Json::Str(x)) if set.contains(&x.as_str()))
}

/// Python `str.casefold()` + NFKD katlaması dışındaki kısım: küçük harf, `ß` -> `ss` (ascii üreten tek fark; docs/rs-rev.md).
pub fn casefold(s: &str) -> String {
    s.to_lowercase().replace('ß', "ss")
}

/// `os.path.join` (POSIX).
pub fn path_join(base: &str, parts: &[&str]) -> String {
    let mut p = base.to_string();
    for b in parts {
        if b.starts_with('/') {
            p = (*b).to_string();
        } else if p.is_empty() || p.ends_with('/') {
            p.push_str(b);
        } else {
            p.push('/');
            p.push_str(b);
        }
    }
    p
}

/// `os.path.basename`.
pub fn basename(p: &str) -> &str {
    p.rsplit('/').next().unwrap_or(p)
}

/// `os.path.dirname`.
pub fn dirname(p: &str) -> &str {
    match p.rfind('/') {
        None => "",
        Some(i) => {
            let head = &p[..i + 1];
            let t = head.trim_end_matches('/');
            if t.is_empty() {
                head
            } else {
                t
            }
        }
    }
}

/// `os.path.normpath` (POSIX).
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let slashes = if p.starts_with("//") && !p.starts_with("///") {
        2
    } else {
        usize::from(p.starts_with('/'))
    };
    let mut out: Vec<&str> = Vec::new();
    for c in p.split('/') {
        if c.is_empty() || c == "." {
            continue;
        }
        if c != ".." || (slashes == 0 && out.is_empty()) || out.last() == Some(&"..") {
            out.push(c);
        } else if !out.is_empty() {
            out.pop();
        }
    }
    let r = format!("{}{}", "/".repeat(slashes), out.join("/"));
    if r.is_empty() {
        ".".into()
    } else {
        r
    }
}

/// `os.path.abspath`.
pub fn abspath(p: &str) -> String {
    if p.starts_with('/') {
        return normpath(p);
    }
    let cwd = std::env::current_dir()
        .map(|c| c.to_string_lossy().into_owned())
        .unwrap_or_default();
    normpath(&path_join(&cwd, &[p]))
}

/// `os.path.relpath(path, start)`.
pub fn relpath(path: &str, start: &str) -> String {
    let (a, b) = (abspath(path), abspath(start));
    let x: Vec<&str> = a.split('/').filter(|s| !s.is_empty()).collect();
    let y: Vec<&str> = b.split('/').filter(|s| !s.is_empty()).collect();
    let n = x.iter().zip(&y).take_while(|(p, q)| p == q).count();
    let mut r: Vec<&str> = vec![".."; y.len() - n];
    r.extend(&x[n..]);
    if r.is_empty() {
        ".".into()
    } else {
        r.join("/")
    }
}

/// `os.path.realpath`: var olmayan kuyruk olduğu gibi kalır, sembolik bağlar izlenir.
pub fn realpath(p: &str) -> String {
    fn walk(base: String, rest: &str, depth: u32) -> String {
        let mut out = base;
        let comps = rest.split('/').filter(|c| !c.is_empty());
        for c in comps {
            match c {
                "." => {}
                ".." => out = dirname(&out).to_string(),
                _ => {
                    let next = path_join(&out, &[c]);
                    match std::fs::read_link(&next) {
                        Ok(t) if depth < 40 => {
                            let t = t.to_string_lossy().into_owned();
                            let start = if t.starts_with('/') {
                                "/".to_string()
                            } else {
                                out.clone()
                            };
                            out = walk(start, &t, depth + 1);
                        }
                        _ => out = next,
                    }
                }
            }
        }
        out
    }
    let abs = if p.starts_with('/') {
        p.to_string()
    } else {
        let cwd = std::env::current_dir()
            .map(|c| c.to_string_lossy().into_owned())
            .unwrap_or_default();
        path_join(&cwd, &[p])
    };
    walk("/".to_string(), &abs, 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_matches_python_set() {
        assert_eq!(splitlines("a\r\nb\rc\u{2028}d\n"), vec!["a", "b", "c", "d"]);
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("\n\n"), vec!["", ""]);
    }
}
