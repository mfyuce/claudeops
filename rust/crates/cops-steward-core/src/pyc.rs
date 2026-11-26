//! Python davranış uyumu: `str.strip/split/splitlines`, kod noktası dilimleme, yuvarlama, yerel zaman.
//! Rust'ın karşılıkları (`trim`, `lines`, bayt dilimi) Python'dan farklıdır; taşınan kod bunları kullanır.

use chrono::{DateTime, Local, TimeZone};

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
}
