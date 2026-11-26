//! Python yerleşiklerinin bu crate'in ihtiyaç duyduğu kadarı, BİREBİR: `str()`, `repr()`, `str.strip()`, `str.isspace()`,
//! `str.isprintable()`, `int(str)`, `float(str)`, `re` `\d`. Ayar okuyucuları elle düzenlenebilen `settings.json`
//! değerlerini Python'un `str(x)`/`int(...)`/`float(...)` zinciriyle yorumlar; aynı sonuç için aynı dönüşüm gerekir.
//! Unicode tabloları Python 3.10'dan üretildi (`unicode_tables.rs`); parite testleri her işlevi Python'a karşı sınar.
use crate::json::{py_float_repr, Json};
use crate::unicode_tables::{DECIMAL_ZEROS, NFKC_NETLOC_BAD, NONPRINTABLE};

/// `str.isspace()` (Python `Py_UNICODE_ISSPACE`): Unicode boşlukları + U+001C..U+001F.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `str.lower()`.
pub fn lower(s: &str) -> String {
    s.to_lowercase()
}

/// `s[:n]` (kod noktası sayısı).
pub fn prefix_chars(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

/// `str.isprintable()` (tek karakter).
pub fn is_printable(c: char) -> bool {
    let c = c as u32;
    let i = NONPRINTABLE.partition_point(|&(lo, _)| lo <= c);
    !(i > 0 && c <= NONPRINTABLE[i - 1].1)
}

/// `unicodedata.decimal(c)`: Nd rakamının değeri.
pub fn decimal_value(c: char) -> Option<u32> {
    if c.is_ascii_digit() {
        return Some(c as u32 - '0' as u32);
    }
    let c = c as u32;
    let i = DECIMAL_ZEROS.partition_point(|&z| z <= c);
    let z = *DECIMAL_ZEROS.get(i.checked_sub(1)?)?;
    (c - z <= 9).then_some(c - z)
}

/// `re` `\d` (str deseni): Unicode ondalık rakam.
pub fn is_re_digit(c: char) -> bool {
    decimal_value(c).is_some()
}

/// NFKC ayrışımı `/?#@:` içeren karakter (`urllib.parse._checknetloc`).
pub(crate) fn nfkc_netloc_bad(c: char) -> bool {
    NFKC_NETLOC_BAD.binary_search(&(c as u32)).is_ok()
}

/// `repr(str)`.
pub fn repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            c if c == quote || c == '\\' => {
                out.push('\\');
                out.push(c);
            }
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c if (c as u32) < 0x7f || is_printable(c) => out.push(c),
            c if (c as u32) <= 0xff => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c if (c as u32) <= 0xffff => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => {
                out.push_str(&format!("\\U{:08x}", c as u32));
            }
        }
    }
    out.push(quote);
    out
}

fn float_str(f: f64) -> String {
    if f.is_nan() {
        "nan".into()
    } else if f.is_infinite() {
        (if f > 0.0 { "inf" } else { "-inf" }).into()
    } else {
        py_float_repr(f)
    }
}

/// `repr(x)` (JSON'dan gelen değer).
pub fn repr(v: &Json) -> String {
    match v {
        Json::Str(s) => repr_str(s),
        Json::Array(a) => {
            let items: Vec<String> = a.iter().map(repr).collect();
            format!("[{}]", items.join(", "))
        }
        Json::Object(m) => {
            let items: Vec<String> = m
                .iter()
                .map(|(k, x)| format!("{}: {}", repr_str(k), repr(x)))
                .collect();
            format!("{{{}}}", items.join(", "))
        }
        other => str_of(other),
    }
}

/// `str(x)`.
pub fn str_of(v: &Json) -> String {
    match v {
        Json::Null => "None".into(),
        Json::Bool(b) => (if *b { "True" } else { "False" }).into(),
        Json::Int(i) => i.to_string(),
        Json::BigInt(t) => t.clone(),
        Json::Float(f) => float_str(*f),
        Json::Str(s) => s.clone(),
        Json::Array(_) | Json::Object(_) => repr(v),
    }
}

/// `str(x or "")`: yok ya da Python'da yanlış (falsy) değer `""`.
pub fn str_or_empty(v: Option<&Json>) -> String {
    match v {
        Some(x) if x.truthy() => str_of(x),
        _ => String::new(),
    }
}

/// `str(x)` (yok = `None`).
pub fn str_opt(v: Option<&Json>) -> String {
    v.map_or_else(|| "None".into(), str_of)
}

/// Python `int`: sınırsız; kanonik ondalık metin olarak tutulur (`str(n)` ile aynı).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PyInt(String);

impl PyInt {
    pub fn from_i64(n: i64) -> PyInt {
        PyInt(n.to_string())
    }
    pub fn is_positive(&self) -> bool {
        !self.0.starts_with('-') && self.0 != "0"
    }
    pub fn as_i64(&self) -> Option<i64> {
        self.0.parse().ok()
    }
    /// `i64`e sığmayan değer uca doyurulur (eşik karşılaştırmaları için).
    pub fn saturating_i64(&self) -> i64 {
        self.as_i64().unwrap_or(if self.0.starts_with('-') {
            i64::MIN
        } else {
            i64::MAX
        })
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
    /// JSON değeri (Python `json.dumps` ile aynı bayt).
    pub fn to_json(&self) -> Json {
        self.as_i64()
            .map_or_else(|| Json::BigInt(self.0.clone()), Json::Int)
    }
}

impl std::fmt::Display for PyInt {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// `_PyUnicode_TransformDecimalAndSpaceToASCII`: ASCII dışı boşluk -> ' ', ondalık rakam -> ASCII; başka ASCII dışı = hata.
fn to_ascii_number(s: &str) -> Option<String> {
    s.chars()
        .map(|c| {
            if (c as u32) < 127 {
                Some(c)
            } else if is_space(c) {
                Some(' ')
            } else {
                decimal_value(c).and_then(|d| char::from_digit(d, 10))
            }
        })
        .collect()
}

/// `Py_ISSPACE` (ASCII).
fn ascii_space(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\n' | '\u{0b}' | '\u{0c}' | '\r')
}

/// Alt çizgi yalnız iki rakam arasında (Python sayı sözdizimi); geçerliyse alt çizgisiz metin.
fn strip_underscores(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let mut out = String::with_capacity(s.len());
    for (i, &c) in b.iter().enumerate() {
        if c == b'_' {
            let prev = i.checked_sub(1).and_then(|j| b.get(j));
            if !prev.is_some_and(u8::is_ascii_digit)
                || !b.get(i + 1).is_some_and(u8::is_ascii_digit)
            {
                return None;
            }
        } else {
            out.push(c as char);
        }
    }
    Some(out)
}

/// `int(s)` (taban 10); `ValueError` = `None`.
pub fn parse_int(s: &str) -> Option<PyInt> {
    let t = to_ascii_number(s)?;
    let t = t.trim_matches(ascii_space);
    let (neg, digits) = match t.as_bytes().first() {
        Some(b'-') => (true, &t[1..]),
        Some(b'+') => (false, &t[1..]),
        _ => (false, t),
    };
    if digits.is_empty() || !digits.as_bytes()[0].is_ascii_digit() {
        return None;
    }
    let digits = strip_underscores(digits)?;
    if !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let body = digits.trim_start_matches('0');
    Some(PyInt(match (body.is_empty(), neg) {
        (true, _) => "0".into(),
        (false, true) => format!("-{body}"),
        (false, false) => body.into(),
    }))
}

/// `float(s)`; `ValueError` = `None`.
pub fn parse_float(s: &str) -> Option<f64> {
    let t = to_ascii_number(s)?;
    let t = t.trim_matches(ascii_space);
    let unsigned = t.strip_prefix(['+', '-']).unwrap_or(t);
    let lw = unsigned.to_ascii_lowercase();
    if matches!(lw.as_str(), "inf" | "infinity" | "nan") {
        let v = if lw == "nan" { f64::NAN } else { f64::INFINITY };
        return Some(if t.starts_with('-') { -v } else { v });
    }
    // Python dilbilgisi: [işaret] (rakam [. rakam*] | . rakam) [e [işaret] rakam]; alt çizgi yalnız rakam arasında.
    let clean = strip_underscores(t)?;
    let ok = {
        let b = clean.as_bytes();
        let mut i = usize::from(matches!(b.first(), Some(b'+' | b'-')));
        let int_start = i;
        while b.get(i).is_some_and(u8::is_ascii_digit) {
            i += 1;
        }
        let mut digits = i > int_start;
        if b.get(i) == Some(&b'.') {
            i += 1;
            let f = i;
            while b.get(i).is_some_and(u8::is_ascii_digit) {
                i += 1;
            }
            digits |= i > f;
        }
        if digits && matches!(b.get(i), Some(b'e' | b'E')) {
            i += 1;
            if matches!(b.get(i), Some(b'+' | b'-')) {
                i += 1;
            }
            let e = i;
            while b.get(i).is_some_and(u8::is_ascii_digit) {
                i += 1;
            }
            digits = i > e;
        }
        digits && i == b.len()
    };
    if !ok {
        return None;
    }
    clean.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn basics() {
        assert_eq!(strip("\u{1c} a \u{2028}"), "a");
        assert_eq!(prefix_chars("şçğ", 2), "şç");
        assert_eq!(prefix_chars("ab", 5), "ab");
        assert_eq!(decimal_value('٣'), Some(3));
        assert_eq!(decimal_value('a'), None);
        assert!(!is_printable('\u{2028}'));
        assert!(is_printable('ş'));
        assert_eq!(repr_str("a'b"), "\"a'b\"");
        assert_eq!(repr_str("a'\"\u{0}\u{a0}"), "'a\\'\"\\x00\\xa0'");
        assert_eq!(
            parse_int(" +0_07 ").map(|n| n.to_string()),
            Some("7".into())
        );
        assert_eq!(parse_int("-0").map(|n| n.to_string()), Some("0".into()));
        assert!(
            parse_int("1__0").is_none() && parse_int("_1").is_none() && parse_int("1_").is_none()
        );
        assert_eq!(parse_float("1_0.5"), Some(10.5));
        assert!(
            parse_float("1_.5").is_none()
                && parse_float(".").is_none()
                && parse_float("1e").is_none()
        );
        assert!(parse_float("-NaN").is_some_and(f64::is_nan));
    }
}
