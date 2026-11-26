//! Python davranış uyumu: `str.strip/split/splitlines`, kod noktası dilimleme, yuvarlama, yerel zaman.
//! Rust'ın karşılıkları (`trim`, `lines`, bayt dilimi) Python'dan farklıdır; taşınan kod bunları kullanır.

use crate::unicode_gen::{CASEFOLD, DIGIT_ONLY};
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
static DECIMAL_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^\p{Nd}$").ok());

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

/// `c.isdecimal()`
pub fn is_decimal(c: char) -> bool {
    char_matches(&DECIMAL_RE, c)
}

/// `c.isdigit()`: onluk rakamlar + üst simge, daire içi vb.
pub fn is_digit(c: char) -> bool {
    let n = u32::from(c);
    is_decimal(c) || DIGIT_ONLY.iter().any(|&(a, b)| (a..=b).contains(&n))
}

/// `s.isdigit()` (boş dizge yanlış)
pub fn str_is_digit(s: &str) -> bool {
    !s.is_empty() && s.chars().all(is_digit)
}

/// `int(c)`, tek Unicode onluk rakam (`is_decimal`) için: bloklar 10'ar ardışık kod noktasıdır ve sıfırla başlar.
pub fn decimal_value(c: char) -> i64 {
    let before =
        (1..u32::from(c)).map_while(|back| char::from_u32(u32::from(c) - back).filter(|p| is_decimal(*p))).count();
    (before % 10) as i64
}

/// `s.casefold()` (tam büyük/küçük harf katlama; Python tablosu `unicode_gen`).
pub fn casefold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match CASEFOLD.binary_search_by_key(&c, |&(k, _)| k) {
            Ok(i) => out.push_str(CASEFOLD.get(i).map_or("", |&(_, v)| v)),
            Err(_) => out.extend(c.to_lowercase()),
        }
    }
    out
}

/// Python `re.I` eşleşmesi için girdi hazırlığı: Python'da `i`, `I`, `İ`, `ı` birbirine denktir, Rust `(?i)`de `İ`/`ı` değil.
/// Karakter sayısı korunur (bayt konumları DEĞİŞİR).
pub fn ci_input(s: &str) -> String {
    s.replace(['İ', 'ı'], "i")
}

const WORD_CLASS: &str = r"\p{L}\p{N}_";
const SPACE_CLASS: &str = r"\s\x1c-\x1f";

/// Python `re` desenini aynı anlama gelen `fancy_regex` desenine çevirir: `\w \W \s \S \b` Python tanımıyla (birleşen
/// işaret sözcük değil, U+001C..U+001F boşluk). `(?i)` ile başlayan desende `ı` -> `i`; girdiyi `ci_input`tan geçirin.
/// Yalnız bu crate'in taşıdığı desenlerin kullandığı sözdizimi desteklenir (sınıf içinde `\W`/`\S`/`\b` yok).
pub fn py_pattern(pattern: &str) -> String {
    let ci = pattern.starts_with("(?i)");
    let word = format!("(?-i:[{WORD_CLASS}])");
    let mut out = String::new();
    let mut in_class = false;
    let mut it = pattern.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            let Some(e) = it.next() else {
                out.push(c);
                break;
            };
            match (e, in_class) {
                ('w', true) => out.push_str(WORD_CLASS),
                ('w', false) => out.push_str(&word),
                ('W', false) => out.push_str(&format!("(?-i:[^{WORD_CLASS}])")),
                ('s', true) => out.push_str(SPACE_CLASS),
                ('s', false) => out.push_str(&format!("[{SPACE_CLASS}]")),
                ('S', false) => out.push_str(&format!("[^{SPACE_CLASS}]")),
                ('b', false) => out.push_str(&format!("(?:(?<={word})(?!{word})|(?<!{word})(?={word}))")),
                _ => {
                    out.push('\\');
                    out.push(e);
                }
            }
            continue;
        }
        match c {
            '[' => in_class = true,
            ']' => in_class = false,
            _ => {}
        }
        out.push(if ci && c == 'ı' { 'i' } else { c });
    }
    out
}

/// `py_pattern` + derleme. Hata yalnız desteklenmeyen desende olur (testler her kullanılan deseni derler).
pub fn py_regex(pattern: &str) -> Option<fancy_regex::Regex> {
    fancy_regex::Regex::new(&py_pattern(pattern)).ok()
}

/// `re.search(...)` var mı (derlenememiş desen ya da geri izleme sınırı = yok).
pub fn is_match(re: &Option<fancy_regex::Regex>, s: &str) -> bool {
    re.as_ref().is_some_and(|r| r.is_match(s).unwrap_or(false))
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

/// `int(v)`; Python'un istisna fırlattığı (ya da i64'e sığmayan) değerde `None`.
pub fn to_int(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(i64::from(*b)),
        Value::Number(n) => n.as_i64().or_else(|| {
            let f = n.as_f64().filter(|f| f.is_finite() && f.abs() < 9.2e18)?;
            Some(f.trunc() as i64)
        }),
        Value::String(s) => {
            let t = strip(s);
            let body = t.strip_prefix(['+', '-']).unwrap_or(t);
            let bad = body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__");
            if bad || !body.chars().all(|c| is_decimal(c) || c == '_') {
                return None;
            }
            let ascii: String = t
                .chars()
                .filter(|&c| c != '_')
                .map(|c| if is_decimal(c) { char::from(b'0' + decimal_value(c) as u8) } else { c })
                .collect();
            ascii.parse().ok()
        }
        _ => None,
    }
}

/// `json.dumps(s)` (str, `ensure_ascii=True`): tırnaklarıyla.
pub fn json_str_ascii(s: &str) -> String {
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
                for unit in c.encode_utf16(&mut [0u16; 2]) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

/// `hashlib.sha1(data).hexdigest()` (kimlik/değişim özeti; güvenlik amaçlı değil). Ayrı bağımlılık eklenmesin diye burada.
pub fn sha1_hex(data: &[u8]) -> String {
    let mut h: [u32; 5] = [0x6745_2301, 0xefcd_ab89, 0x98ba_dcfe, 0x1032_5476, 0xc3d2_e1f0];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&(data.len() as u64).wrapping_mul(8).to_be_bytes());
    for block in msg.as_chunks::<64>().0 {
        let mut w = [0u32; 80];
        for (slot, b) in w.iter_mut().zip(block.as_chunks::<4>().0) {
            *slot = b.iter().fold(0, |acc, &x| (acc << 8) | u32::from(x));
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = h;
        for (i, &word) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5a82_7999),
                20..=39 => (b ^ c ^ d, 0x6ed9_eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1b_bcdc),
                _ => (b ^ c ^ d, 0xca62_c1d6),
            };
            let t = a.rotate_left(5).wrapping_add(f).wrapping_add(e).wrapping_add(k).wrapping_add(word);
            (e, d, c, b, a) = (d, c, b.rotate_left(30), a, t);
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e]) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
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
    fn digits_and_casefold_follow_python() {
        use serde_json::json;
        assert!(is_digit('²') && !is_decimal('²') && is_decimal('٣') && !is_digit('½') && !str_is_digit(""));
        assert_eq!((decimal_value('7'), decimal_value('٣'), decimal_value('𝟗')), (7, 3, 9));
        assert_eq!(to_int(&json!("١_٢")), Some(12));
        assert_eq!(casefold("Straße İ ΣΣ ﬁ ſ"), "strasse i\u{307} σσ fi s");
        assert_eq!(ci_input("İı"), "ii");
    }

    #[test]
    fn python_regex_classes() {
        let re = py_regex(r"(?i)\bsonra\b|^\W*x\s\S[\w#]$");
        assert!(is_match(&re, "bir SONRA.") && !is_match(&re, "sonrası") && is_match(&re, "sonra\u{307}"));
        assert!(is_match(&re, "\u{307}x\u{1c}y#"));
        assert_eq!(py_pattern(r"(?i)ı[\s\w]"), r"(?i)i[\s\x1c-\x1f\p{L}\p{N}_]");
    }

    #[test]
    fn int_json_and_sha1_follow_python() {
        use serde_json::json;
        assert_eq!(to_int(&json!(" -1_000 ")), Some(-1000));
        assert_eq!(to_int(&json!(-2.9)), Some(-2));
        assert!(to_int(&json!("1.5")).is_none() && to_int(&json!("_1")).is_none() && to_int(&json!(null)).is_none());
        assert_eq!(json_str_ascii("a\"\\\n\u{7f}ç😀\u{1}"), r#""a\"\\\n\u007f\u00e7\ud83d\ude00\u0001""#);
        assert_eq!(sha1_hex(b""), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(sha1_hex(b"abc"), "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(sha1_hex(&[b'a'; 1000]), "291e9a6c66994949b57ba5e650361e98fc36b1ba");
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
