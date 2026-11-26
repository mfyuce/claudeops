//! Python davranışıyla eşleşme yardımcıları (`json`, `str.strip`, `splitlines`, doğruluk değeri, `int`).

use serde_json::Value;

/// `str.isspace` (Rust'tan farkı: 0x1C..0x1F de boşluktur).
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `str.splitlines` satırları.
pub fn splitlines(s: &str) -> impl Iterator<Item = &str> {
    let brk = |c: char| {
        matches!(
            c,
            '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}'..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
        )
    };
    let mut rest = s;
    std::iter::from_fn(move || {
        if rest.is_empty() {
            return None;
        }
        let Some(i) = rest.find(brk) else {
            return Some(std::mem::take(&mut rest));
        };
        let line = &rest[..i];
        let mut tail = rest[i..].chars();
        if tail.next() == Some('\r') && tail.as_str().starts_with('\n') {
            tail.next();
        }
        rest = tail.as_str();
        Some(line)
    })
}

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

/// Skalerler için `str()`; dizi/nesne json yazımıyla döner (yalnız eşitlik denetiminde kullanılır).
pub fn to_str(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// `str(v) if v else None`.
pub fn truthy_str(v: Option<&Value>) -> Option<String> {
    v.filter(|v| truthy(v)).map(to_str)
}

/// `int("...")`: baştaki/sondaki boşluk, işaret ve rakamlar arası tek `_`. i64'e sığmayan değer `None`
/// (taşmayı ayırmak için [`int_saturating`]).
pub fn int(s: &str) -> Option<i64> {
    int_saturating(s).and_then(|n| i64::try_from(n).ok())
}

/// [`int`] ama sözdizimi geçerli her sayı döner: i128'e sığmayan değer `i128::MIN`/`MAX`e doyurulur
/// (Python `int` sınırsızdır; çağıran taşmayı "geçersiz"den ayırabilsin).
pub fn int_saturating(s: &str) -> Option<i128> {
    let s = strip(s);
    let digits = s.strip_prefix(['+', '-']).unwrap_or(s);
    if digits.is_empty()
        || digits
            .split('_')
            .any(|p| p.is_empty() || !p.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    let neg = s.starts_with('-');
    Some(s.replace('_', "").parse().unwrap_or(if neg { i128::MIN } else { i128::MAX }))
}

/// `float("...")` (ASCII): baştaki/sondaki boşluk, rakamlar arası tek `_` (PEP 515), `inf`/`nan` yazımları.
/// Unicode rakamlar (`float("١")`) desteklenmez (bilinen sapma).
pub fn float(s: &str) -> Option<f64> {
    let s = strip(s);
    if s.contains('_') {
        let b = s.as_bytes();
        let ok = b
            .iter()
            .enumerate()
            .filter(|(_, c)| **c == b'_')
            .all(|(i, _)| i > 0 && b[i - 1].is_ascii_digit() && b.get(i + 1).is_some_and(u8::is_ascii_digit));
        if !ok {
            return None;
        }
        return s.replace('_', "").parse().ok();
    }
    s.parse().ok()
}

/// Eşsiz vekil `\uD8xx` kaçışlarını `�` yapar (Python kabul eder, serde_json reddeder).
pub(crate) fn mask_lone_surrogates(s: &str) -> String {
    let b = s.as_bytes();
    let unit = |i: usize| -> Option<u32> {
        if b.get(i) != Some(&b'\\') || b.get(i + 1) != Some(&b'u') {
            return None;
        }
        u32::from_str_radix(s.get(i + 2..i + 6)?, 16).ok()
    };
    let mut out = String::with_capacity(s.len());
    let (mut copied, mut i) = (0, 0);
    while i < b.len() {
        if b[i] != b'\\' {
            i += 1;
        } else if let Some(u @ 0xD800..=0xDFFF) = unit(i) {
            if u < 0xDC00 && matches!(unit(i + 6), Some(0xDC00..=0xDFFF)) {
                i += 12;
            } else {
                out.push_str(&s[copied..i]);
                out.push_str("\\ufffd");
                i += 6;
                copied = i;
            }
        } else {
            i += 2; // `\\` dahil her kaçış iki bayt tüketir
        }
    }
    out.push_str(&s[copied..]);
    out
}

/// `json.loads`: geçersizse `None`.
pub fn json(raw: &[u8]) -> Option<Value> {
    let text = std::str::from_utf8(raw).ok()?;
    serde_json::from_str(text)
        .ok()
        .or_else(|| serde_json::from_str(&mask_lone_surrogates(text)).ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_string_rules() {
        assert_eq!(strip("\u{1c} a \u{2028}"), "a");
        assert_eq!(splitlines("a\r\nb\rc\u{2028}d\n").collect::<Vec<_>>(), ["a", "b", "c", "d"]);
        assert_eq!(splitlines("a\n\nb").collect::<Vec<_>>(), ["a", "", "b"]);
        assert_eq!(
            (int(" +1_000 "), int("1__0"), int("_1"), int("1.5"), int("-3")),
            (Some(1000), None, None, None, Some(-3))
        );
        assert_eq!(int("99999999999999999999"), None);
        assert_eq!(int_saturating("99999999999999999999"), Some(99_999_999_999_999_999_999));
        assert_eq!(int_saturating(&"9".repeat(60)), Some(i128::MAX));
        assert_eq!(int_saturating(&format!("-{}", "9".repeat(60))), Some(i128::MIN));
        assert_eq!(int_saturating("1x"), None);
        assert_eq!(to_str(&Value::Null), "None");
        for (v, want) in [
            ("1_0", Some(10.0)),
            ("1__0", None),
            ("_1", None),
            ("1_", None),
            ("1_0.5_0", Some(10.5)),
            ("1e1_0", Some(1e10)),
            ("1_e10", None),
            (" 2.5\n", Some(2.5)),
            ("+.5", Some(0.5)),
            ("5.", Some(5.0)),
            ("0x10", None),
            ("1,5", None),
            ("-Infinity", Some(f64::NEG_INFINITY)),
        ] {
            assert_eq!(float(v), want, "{v:?}");
        }
        assert!(float("nan").is_some_and(f64::is_nan));
    }

    #[test]
    fn lone_surrogates_parse() {
        let pair = ["d83d", "de00"].map(|h| format!("\\u{h}")).concat();
        let v = json(format!(r#"{{"a":"\ud800x\udc00","b":"{pair}","c":"\\ud800"}}"#).as_bytes()).unwrap();
        assert_eq!(v["a"], "\u{fffd}x\u{fffd}");
        assert_eq!(v["b"], "\u{1f600}");
        assert_eq!(v["c"], "\\ud800");
        assert!(json(b"{").is_none() && json(b"\xff").is_none() && json(b"").is_none());
    }
}
