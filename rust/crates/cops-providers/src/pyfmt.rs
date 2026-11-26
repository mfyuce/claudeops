//! Parite için gereken Python davranışları (`shlex.quote`, `str()`, `int()`, `float()`, `:g`, `json.dumps`).

use serde_json::Value;

/// `shlex.quote`.
pub fn quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    if s.bytes().all(|b| b.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&b)) {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// `" ".join(shlex.quote(a) for a in argv)`.
pub fn join_quoted<S: AsRef<str>>(argv: &[S]) -> String {
    argv.iter().map(|a| quote(a.as_ref())).collect::<Vec<_>>().join(" ")
}

/// `str.strip()`: Python `\x1c..\x1f`i de boşluk sayar.
pub fn strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
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

fn float_repr(f: f64) -> String {
    if f.is_finite() && f.fract() == 0.0 && f.abs() < 1e16 {
        format!("{f:.1}")
    } else if f.is_nan() {
        "nan".into()
    } else {
        f.to_string()
    }
}

/// Rakamlar arasındaki tek `_` ayraçlarını (Python sayı sözdizimi) kaldırır; geçersiz yerde `_` = None.
fn drop_underscores(s: &str) -> Option<String> {
    let b = s.as_bytes();
    for (i, c) in b.iter().enumerate() {
        if *c == b'_' && !(i > 0 && b[i - 1].is_ascii_digit() && b.get(i + 1).is_some_and(u8::is_ascii_digit)) {
            return None;
        }
    }
    Some(s.replace('_', ""))
}

/// `int(s)` (yalnız ASCII rakam; i64'e sığmayan değer None).
pub fn parse_int(s: &str) -> Option<i64> {
    drop_underscores(strip(s))?.parse::<i64>().ok()
}

/// `float(s)`.
pub fn parse_float(s: &str) -> Option<f64> {
    drop_underscores(strip(s))?.parse::<f64>().ok()
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
        return if x.is_sign_negative() { "-0".into() } else { "0".into() };
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
        format!("{}e{}{:02}", trim(mantissa), if exp < 0 { '-' } else { '+' }, exp.abs())
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn g_format() {
        for (x, want) in [(8.0, "8"), (0.5, "0.5"), (1234567.0, "1.23457e+06"), (0.00001, "1e-05"), (100.0, "100")] {
            assert_eq!(fmt_g(x), want, "{x}");
        }
    }

    #[test]
    fn quoting() {
        assert_eq!(quote(""), "''");
        assert_eq!(quote("a/b-c"), "a/b-c");
        assert_eq!(quote("it's"), "'it'\"'\"'s'");
        assert_eq!(quote("ğ"), "'ğ'");
    }
}
