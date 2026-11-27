//! Parite için gereken Python davranışları (`shlex.quote`, `str()`, `int()`, `float()`, `:g`, `json.dumps`).

use serde_json::Value;

/// `shlex.quote`.
pub fn quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    if s.bytes()
        .all(|b| b.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&b))
    {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// `" ".join(shlex.quote(a) for a in argv)`.
pub fn join_quoted<S: AsRef<str>>(argv: &[S]) -> String {
    argv.iter()
        .map(|a| quote(a.as_ref()))
        .collect::<Vec<_>>()
        .join(" ")
}

/// Python `str.isspace()` / `str.strip()`: tek kaynak rs/state `pycompat`.
pub use cops_state::pycompat::{is_space as py_isspace, strip};

/// Unicode başlık harfleri (Lt).
fn is_titlecase(c: char) -> bool {
    matches!(c as u32, 0x1C5 | 0x1C8 | 0x1CB | 0x1F2 | 0x1F88..=0x1F8F | 0x1F98..=0x1F9F | 0x1FA8..=0x1FAF | 0x1FBC | 0x1FCC | 0x1FFC)
}

/// `str.islower()`: en az bir küçük harf var, hiç büyük ya da başlık harfi yok (harf olmayanlar serbest).
pub fn py_islower(s: &str) -> bool {
    !s.chars().any(|c| c.is_uppercase() || is_titlecase(c)) && s.chars().any(char::is_lowercase)
}

/// `str.splitlines()` (tek kaynak rs/proc `py::splitlines`).
pub fn splitlines(s: &str) -> Vec<&str> {
    cops_procscan::py::splitlines(s).collect()
}

/// Python doğruluk değeri.
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_none_or(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `str(v)`: skalerler birebir; liste/sözlük JSON metni (Python repr'inden farklı, yalnız bozuk girdide görülür).
pub fn str_of(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => match (n.is_f64(), n.as_f64()) {
            (true, Some(f)) => float_repr(f),
            _ => n.to_string(),
        },
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// `str(v or "")`.
pub fn str_or_empty(v: Option<&Value>) -> String {
    match v {
        Some(v) if truthy(v) => str_of(v),
        _ => String::new(),
    }
}

/// `repr(float)`: sonlu değerler için tek kaynak rs/state `py_float_repr` (o JSON yazımı: `NaN`, `Infinity`).
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        "nan".into()
    } else if f.is_infinite() {
        if f > 0.0 { "inf" } else { "-inf" }.into()
    } else {
        cops_state::json::py_float_repr(f)
    }
}

/// `repr(str)`: tek kaynak rs/state `pycompat` (Python 3.10 tabloları).
pub use cops_state::pycompat::repr_str as py_str_repr;

/// `unicodedata.decimal`.
pub use cops_state::pycompat::decimal_value;

/// `int(s)` (rs/state `parse_int`; i64'e sığmayan değer None).
pub fn parse_int(s: &str) -> Option<i64> {
    cops_state::pycompat::parse_int(s).and_then(|n| n.as_i64())
}

/// `float(s)`.
pub use cops_state::pycompat::parse_float;

/// `float(v)` bir JSON değeri üzerinde: sayı, bool (0/1) ve dize (`float(str)`); başka tip `TypeError` (None).
pub fn py_float(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Value::String(s) => parse_float(s),
        _ => None,
    }
}

/// `int(v)` bir JSON değeri üzerinde: tam sayı aynen, float sıfıra doğru kesilir, bool 0/1, dize `int(str)`.
pub fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|f| f.is_finite())
                .map(|f| f.trunc() as i64)
        }),
        Value::Bool(b) => Some(i64::from(*b)),
        Value::String(s) => parse_int(s),
        _ => None,
    }
}

/// `f"{x:g}"` (6 anlamlı basamak).
pub fn fmt_g(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() {
            "-0".into()
        } else {
            "0".into()
        };
    }
    let sci = format!("{x:.5e}");
    let (mantissa, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let trim = |s: &str| -> String {
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s.to_string()
        }
    };
    if !(-4..6).contains(&exp) {
        format!(
            "{}e{}{:02}",
            trim(mantissa),
            if exp < 0 { '-' } else { '+' },
            exp.abs()
        )
    } else {
        let decimals = (5 - exp).max(0) as usize;
        trim(&format!("{x:.decimals$}"))
    }
}

/// `json.dumps(s)` (varsayılan `ensure_ascii=True`).
pub fn json_ascii(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{u:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

/// `os.path.basename` (POSIX).
pub fn basename(p: &str) -> &str {
    p.rsplit('/').next().unwrap_or("")
}

/// Ek alacak (`{ad}.jsonl`, `{kimlik}.db`) dosya adının başı olarak yola eklenebilir mi (oturum adı, konuşma
/// kimliği): boş değil, `/` ve NUL yok (mutlak ya da `../` taşıyan değer dizinin dışını açmasın). Bugünkü geçerli
/// adların (harf, rakam, `.`, `-`, `_`) hiçbiri reddedilmez. Python `providers.base._path_part_ok`.
pub fn is_path_part(s: &str) -> bool {
    !s.is_empty() && !s.contains(['/', '\0'])
}

/// `os.path.join` (POSIX, iki parça).
pub fn join_path(a: &str, b: &str) -> String {
    if b.starts_with('/') || a.is_empty() {
        b.into()
    } else if a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// `os.path.normpath` (POSIX): `//` ve `.` düşer, `..` metin olarak çözülür; baştaki tam iki eğik çizgi korunur.
pub fn normpath(p: &str) -> String {
    let slashes = match p.len() - p.trim_start_matches('/').len() {
        0 => 0,
        2 => 2,
        _ => 1,
    };
    let mut parts: Vec<&str> = Vec::new();
    for c in p.split('/') {
        match c {
            "" | "." => {}
            ".." if parts.last().is_some_and(|l| *l != "..") => {
                parts.pop();
            }
            ".." if slashes > 0 => {}
            c => parts.push(c),
        }
    }
    let out = format!("{}{}", "/".repeat(slashes), parts.join("/"));
    if out.is_empty() {
        ".".into()
    } else {
        out
    }
}

/// `os.path.abspath`: göreli yol `cwd`ye (sürecin çalışma dizini) eklenir.
pub fn abspath(p: &str, cwd: &str) -> String {
    if p.starts_with('/') {
        normpath(p)
    } else {
        normpath(&join_path(cwd, p))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn g_format() {
        for (x, want) in [
            (8.0, "8"),
            (0.5, "0.5"),
            (1234567.0, "1.23457e+06"),
            (0.00001, "1e-05"),
            (100.0, "100"),
        ] {
            assert_eq!(fmt_g(x), want, "{x}");
        }
    }

    #[test]
    fn path_normalisation() {
        // beklenen değerler `posixpath.normpath`
        for (p, want) in [
            ("", "."),
            (".", "."),
            ("/", "/"),
            ("//a//b/", "//a/b"),
            ("///a", "/a"),
            ("a/./b/..", "a"),
            ("../..", "../.."),
            ("a/../../b", "../b"),
            ("/..", "/"),
            ("/a/../..", "/"),
            ("a/..", "."),
        ] {
            assert_eq!(normpath(p), want, "{p}");
        }
        assert_eq!(abspath("w/p", "/r"), "/r/w/p");
        assert_eq!(abspath("", "/r"), "/r");
    }

    #[test]
    fn quoting() {
        assert_eq!(quote(""), "''");
        assert_eq!(quote("a/b-c"), "a/b-c");
        assert_eq!(quote("it's"), "'it'\"'\"'s'");
        assert_eq!(quote("ğ"), "'ğ'");
    }
}
