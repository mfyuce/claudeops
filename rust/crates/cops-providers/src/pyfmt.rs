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

/// Python `str.isspace()` (tek karakter): Unicode boşlukları + `\x1c..\x1f`.
pub fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Unicode başlık harfleri (Lt).
fn is_titlecase(c: char) -> bool {
    matches!(c as u32, 0x1C5 | 0x1C8 | 0x1CB | 0x1F2 | 0x1F88..=0x1F8F | 0x1F98..=0x1F9F | 0x1FA8..=0x1FAF | 0x1FBC | 0x1FCC | 0x1FFC)
}

/// `str.islower()`: en az bir küçük harf var, hiç büyük ya da başlık harfi yok (harf olmayanlar serbest).
pub fn py_islower(s: &str) -> bool {
    !s.chars().any(|c| c.is_uppercase() || is_titlecase(c)) && s.chars().any(char::is_lowercase)
}

/// `str.splitlines()`: `\n`, `\r`, `\r\n`, `\x0b`, `\x0c`, `\x1c-\x1e`, `\x85`, `\u2028`, `\u2029` satır sınırıdır;
/// sondaki sınır boş satır üretmez.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if matches!(c, '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}') {
            out.push(&s[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r' && it.peek().is_some_and(|(_, n)| *n == '\n') {
                it.next();
                end += 1;
            }
            start = end;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// `str.strip()`: Python `\x1c..\x1f`i de boşluk sayar.
pub fn strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// `int()`/`float()`ın kendi kırpması: ASCII'de yalnız ` \t\n\v\f\r` (`\x1c..\x1f` DEĞİL), ASCII dışında Unicode boşlukları.
fn num_strip(s: &str) -> &str {
    s.trim_matches(|c: char| if c.is_ascii() { " \t\n\x0b\x0c\r".contains(c) } else { c.is_whitespace() })
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

/// `repr(float)` (Python `short` biçimi): en kısa gidiş-dönüş basamakları; ondalık üs -4 <= e < 16 ise sabit nokta
/// (`.0` eki), değilse bilimsel (`1e+16`, `1.5e-07`).
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let sci = format!("{f:e}");
    let (mantissa, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    if f == 0.0 || (-4..16).contains(&exp) {
        let fixed = format!("{f}");
        if fixed.contains('.') {
            fixed
        } else {
            fixed + ".0"
        }
    } else {
        format!("{mantissa}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// `repr(str)`: tek tırnak (metinde `'` var `"` yoksa çift tırnak); `\\`, `\n`, `\r`, `\t` ve denetim karakterleri kaçışlı.
pub fn py_str_repr(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::from(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || (0x7f..0xa0).contains(&(c as u32)) => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(q);
    out
}

/// Unicode `Nd` (ondalık rakam) bloklarının sıfır kod noktaları (Python 3.10 / Unicode 13). Python `int()`, `float()` ve
/// `re` `\\d` bu rakamları kabul eder.
const ND_ZEROS: [u32; 65] = [
    0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66, 0xDE6, 0xE50, 0xED0, 0xF20,
    0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900,
    0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450,
    0x114D0, 0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50, 0x11DA0, 0x16A60, 0x16B50, 0x1D7CE, 0x1D7D8,
    0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E950, 0x1FBF0,
];

/// Unicode ondalık rakamın değeri (`unicodedata.decimal`).
pub fn decimal_value(c: char) -> Option<u32> {
    let cp = c as u32;
    ND_ZEROS.iter().rev().find(|z| **z <= cp).map(|z| cp - z).filter(|d| *d < 10)
}

/// Unicode rakamları ASCII'ye çevirir (Python `int`/`float` öncesi normalleştirmesi).
fn ascii_digits(s: &str) -> String {
    s.chars().map(|c| decimal_value(c).map_or(c, |d| char::from(b'0' + d as u8))).collect()
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
    drop_underscores(&ascii_digits(num_strip(s)))?.parse::<i64>().ok()
}

/// `float(s)`.
pub fn parse_float(s: &str) -> Option<f64> {
    drop_underscores(&ascii_digits(num_strip(s)))?.parse::<f64>().ok()
}

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
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().filter(|f| f.is_finite()).map(|f| f.trunc() as i64)),
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
