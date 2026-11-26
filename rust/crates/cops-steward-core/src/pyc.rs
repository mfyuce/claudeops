//! Python davranış uyumu: `str.strip/split/splitlines`, kod noktası dilimleme, yuvarlama, yerel zaman.
//! Rust'ın karşılıkları (`trim`, `lines`, bayt dilimi) Python'dan farklıdır; taşınan kod bunları kullanır.

use chrono::{DateTime, Local, TimeZone};
use regex::Regex;
use serde_json::Value;
use std::sync::LazyLock;

/// `str.isspace()`: Unicode boşlukları + ayırıcı denetim karakterleri U+001C..U+001F.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `s.strip()`
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `s.lstrip()`
pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(is_space)
}

/// `s.rstrip()`
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_space)
}

/// `s.strip(chars)`
pub fn strip_chars<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_matches(|c| chars.contains(c))
}

/// `s.split()` (boşluk dizileri; boş parça yok)
pub fn split_ws(s: &str) -> impl Iterator<Item = &str> {
    s.split(is_space).filter(|p| !p.is_empty())
}

/// `textutil.collapse_ws`: `" ".join(s.split())`
///
/// py: collapse_ws
pub fn collapse_ws(s: &str) -> String {
    split_ws(s).collect::<Vec<_>>().join(" ")
}

fn is_line_break(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// `s.splitlines()`: Python'un tüm satır sonları; `\r\n` tek sonlandırıcı; sondaki satır sonu boş parça üretmez.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if !is_line_break(c) {
            continue;
        }
        out.push(&s[start..i]);
        start = i + c.len_utf8();
        if c == '\r' {
            if let Some(&(j, '\n')) = it.peek() {
                it.next();
                start = j + 1;
            }
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// `len(s)` (kod noktası sayısı)
pub fn len(s: &str) -> usize {
    s.chars().count()
}

/// `s[:n]` (kod noktası)
pub fn head(s: &str, n: usize) -> &str {
    s.char_indices().nth(n).map_or(s, |(i, _)| &s[..i])
}

/// `s[n:]` (kod noktası)
pub fn skip(s: &str, n: usize) -> &str {
    s.char_indices().nth(n).map_or("", |(i, _)| &s[i..])
}

/// `s[-n:]` (n = 0 için boş döner; Python'daki `s[-0:]` tuzağı çağıranda ele alınır)
pub fn tail(s: &str, n: usize) -> &str {
    let l = len(s);
    if n >= l {
        s
    } else {
        skip(s, l - n)
    }
}

/// `round(x)`: yarımda çifte yuvarlama.
pub fn round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

/// `time.localtime(ts)` karşılığı (TZ ortam değişkenine uyar).
pub fn localtime(ts: f64) -> DateTime<Local> {
    let secs = ts.floor() as i64;
    Local.timestamp_opt(secs, 0).earliest().unwrap_or_else(|| Local.timestamp_opt(0, 0).unwrap())
}

static ALPHA_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^\p{L}$").ok());
static ALNUM_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^[\p{L}\p{N}]$").ok());
static UNPRINTABLE_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^[\p{C}\p{Z}]$").ok());

fn char_matches(re: &Option<Regex>, c: char) -> bool {
    re.as_ref().is_some_and(|r| r.is_match(c.encode_utf8(&mut [0u8; 4])))
}

/// `c.isalpha()`: yalnız harf kategorisi (Rust `is_alphabetic` birleşen işaretleri de sayar).
pub fn is_alpha(c: char) -> bool {
    char_matches(&ALPHA_RE, c)
}

/// `c.isalnum()`
pub fn is_alnum(c: char) -> bool {
    char_matches(&ALNUM_RE, c)
}

/// `re.search(r"\bWORD\b", s)`: Python `\w` = `isalnum()` ya da `_` (Rust `\b` birleşen işaretleri de sözcük sayar).
pub fn contains_word(s: &str, word: &str) -> bool {
    let is_w = |c: char| c == '_' || is_alnum(c);
    let mut from = 0;
    while let Some(rel) = s.get(from..).and_then(|t| t.find(word)) {
        let at = from + rel;
        let before = s[..at].chars().next_back();
        let after = s[at + word.len()..].chars().next();
        if !before.is_some_and(is_w) && !after.is_some_and(is_w) {
            return true;
        }
        from = at + word.chars().next().map_or(1, char::len_utf8);
    }
    false
}

/// `re.match("^...$", s)`: Python'da `$` sondaki TEK satır sonundan önce de eşleşir. Desen satır sonu tüketmemeli.
pub fn match_dollar(re: &Regex, s: &str) -> bool {
    re.is_match(s.strip_suffix('\n').unwrap_or(s))
}

/// `os.path.join(a, b)` (posix)
pub fn path_join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        b.to_string()
    } else if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// Python truthiness (`x or default`).
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// `float(v)`; Python'un istisna fırlattığı değerde `None`.
pub fn to_float(v: &Value) -> Option<f64> {
    match v {
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::Number(n) => n.as_f64(),
        Value::String(s) => {
            let c: Vec<char> = strip(s).chars().collect();
            let mut out = String::new();
            for (i, &ch) in c.iter().enumerate() {
                if ch != '_' {
                    out.push(ch);
                    continue;
                }
                // `1_000`: alt çizgi yalnız iki rakam arasında
                let digit = |j: Option<usize>| j.and_then(|j| c.get(j)).is_some_and(char::is_ascii_digit);
                if !(digit(i.checked_sub(1)) && digit(Some(i + 1))) {
                    return None;
                }
            }
            out.parse().ok()
        }
        _ => None,
    }
}

/// `repr(s)` (str)
pub fn repr_str(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::from(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            _ if c == q => {
                out.push('\\');
                out.push(c);
            }
            _ if c != ' ' && char_matches(&UNPRINTABLE_RE, c) => {
                let n = u32::from(c);
                out.push_str(&match n {
                    0..=0xff => format!("\\x{n:02x}"),
                    0x100..=0xffff => format!("\\u{n:04x}"),
                    _ => format!("\\U{n:08x}"),
                });
            }
            _ => out.push(c),
        }
    }
    out.push(q);
    out
}

fn repr_float(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let sci = format!("{f:e}"); // en kısa gidiş-dönüş basamakları
    let (mant, exp) = sci.split_once('e').unwrap_or((sci.as_str(), "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    if f != 0.0 && !(-4..16).contains(&exp) {
        return format!("{mant}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
    }
    let plain = f.to_string();
    if plain.contains('.') {
        plain
    } else {
        format!("{plain}.0")
    }
}

/// `repr(v)` (JSON'dan gelen değerler)
pub fn repr_value(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        Value::Number(n) => match n.as_f64() {
            Some(f) if n.is_f64() => repr_float(f),
            _ => n.to_string(),
        },
        Value::String(s) => repr_str(s),
        Value::Array(a) => format!("[{}]", a.iter().map(repr_value).collect::<Vec<_>>().join(", ")),
        Value::Object(o) => {
            let items: Vec<String> = o.iter().map(|(k, x)| format!("{}: {}", repr_str(k), repr_value(x))).collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

/// `str(v)`
pub fn str_of(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        _ => repr_value(v),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_like_python() {
        assert_eq!(splitlines("a\r\nb\rc\u{2028}d\n"), vec!["a", "b", "c", "d"]);
        assert_eq!(splitlines("\n\n"), vec!["", ""]);
        assert!(splitlines("").is_empty());
    }

    #[test]
    fn slicing_is_by_code_point() {
        assert_eq!(head("çğış", 2), "çğ");
        assert_eq!(tail("çğış", 2), "ış");
        assert_eq!(skip("ab", 5), "");
        assert_eq!(head("", 3), "");
    }

    #[test]
    fn strip_and_split_include_separator_controls() {
        assert_eq!(strip("\u{1c} a \u{a0}"), "a");
        assert_eq!(collapse_ws(" a\t\n b "), "a b");
        assert_eq!(round(2.5), 2);
        assert_eq!(round(3.5), 4);
    }

    #[test]
    fn char_classes_follow_python() {
        assert!(is_alpha('ç') && !is_alpha('\u{307}') && !is_alpha('1'));
        assert!(is_alnum('½') && !is_alnum('_') && !is_alnum('\u{93e}'));
        assert!(contains_word("x KARAR: y", "KARAR") && contains_word("KARAR\u{307}", "KARAR"));
        assert!(
            !contains_word("KARARI", "KARAR")
                && !contains_word("_KARAR", "KARAR")
                && contains_word("KARARKARAR KARAR", "KARAR")
        );
    }

    #[test]
    fn value_conversions_follow_python() {
        use serde_json::json;
        assert_eq!(
            str_of(&json!([1, 2.0, "a'b", null, true, {"k": 1e20}])),
            "[1, 2.0, \"a'b\", None, True, {'k': 1e+20}]"
        );
        assert_eq!(str_of(&json!(1.5e-7)), "1.5e-07");
        assert_eq!(repr_str("a\u{1}\u{a0}ç\n"), "'a\\x01\\xa0ç\\n'");
        assert_eq!(to_float(&json!(" 1_000.5 ")), Some(1000.5));
        assert_eq!(to_float(&json!("1__0")), None);
        assert_eq!(to_float(&json!([1])), None);
        assert!(!truthy(&json!(0.0)) && !truthy(&json!({})) && truthy(&json!("0")));
        assert_eq!(path_join("/a/", "b"), "/a/b");
        assert_eq!(path_join("/a", "/b"), "/b");
    }
}
