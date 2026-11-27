//! tmux'suz saf metin işlevleri (ANSI temizleme, Claude giriş kutusu ayrıştırma).

use std::sync::LazyLock;

use regex::Regex;

macro_rules! regex {
    ($name:ident, $pat:expr) => {
        static $name: LazyLock<Regex> = LazyLock::new(|| Regex::new($pat).expect("sabit desen"));
    };
}

regex!(ANSI_SGR_RE, r"\x1b\[[0-9;]*[a-zA-Z]");
// Bitiş BEL ya da ST (`ESC \`).
regex!(ANSI_OSC_RE, r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)");
regex!(SGR_RE, r"\x1b\[([0-9;]*)m");
regex!(ANSI_ANY_RE, r"\x1b\[[0-9;?]*[A-Za-z]");

/// Python `_BOX_RULE_CHARS` (kutu çizgisi bundan en az [`BOX_RULE_RUN`] tane içerir).
pub const BOX_RULE_CHAR: char = '─';
const BOX_RULE: &str = "────";
/// Python `_PROMPT_CHAR`.
pub const PROMPT: char = '❯';

/// Parite testlerinin Python desenleriyle karşılaştırdığı regex kaynakları (Python adı, desen).
pub fn patterns() -> [(&'static str, &'static str); 4] {
    [
        ("ANSI_SGR_RE", ANSI_SGR_RE.as_str()),
        ("ANSI_OSC_RE", ANSI_OSC_RE.as_str()),
        ("_SGR_RE", SGR_RE.as_str()),
        ("_ANSI_ANY_RE", ANSI_ANY_RE.as_str()),
    ]
}

/// CSI ve OSC dizilerini atar. `capture-pane -e` çıktısında kelimeler tek tek renklendirildiği için eşleştirmeden
/// ÖNCE şarttır.
pub fn strip_ansi(text: &str) -> String {
    ANSI_OSC_RE
        .replace_all(&ANSI_SGR_RE.replace_all(text, ""), "")
        .into_owned()
}

/// Python `str.isspace` (Rust'ınkinden farkı: U+001C..U+001F de boşluktur).
pub(crate) fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// Python `str.strip()`.
pub(crate) fn py_strip(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// Python `str.split()` (ayraçsız): boşluk dizileriyle böler, boş parça yok.
pub(crate) fn py_split(s: &str) -> impl Iterator<Item = &str> {
    s.split(py_isspace).filter(|w| !w.is_empty())
}

/// Python `str.splitlines()`: `\n`, `\r`, `\r\n`, `\v`, `\f`, `\x1c`-`\x1e`, `\x85`, U+2028, U+2029 satır sonudur;
/// metin satır sonuyla bitiyorsa sonda boş satır yoktur.
pub(crate) fn py_splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        let mut end = i + c.len_utf8();
        match c {
            '\r' => {
                if let Some(&(j, '\n')) = chars.peek() {
                    chars.next();
                    end = j + 1;
                }
            }
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}'
            | '\u{2029}' => {}
            _ => continue,
        }
        out.push(&s[start..i]);
        start = end;
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

fn plain(line: &str) -> String {
    ANSI_ANY_RE.replace_all(line, "").into_owned()
}

fn starts_with_prompt(line: &str) -> bool {
    line.trim_start_matches(py_isspace).starts_with(PROMPT)
}

fn sgr_params(group: &str) -> Vec<u64> {
    group
        .split(';')
        .filter(|x| !x.is_empty())
        .map(|x| x.parse().unwrap_or(u64::MAX))
        .collect()
}

/// SGR parametrelerinden "soluk/gri" ön plan: `Some(true)` gri, `Some(false)` varsayılan/renkli, `None` değişmedi.
pub fn dim_fg(params: &[u64]) -> Option<bool> {
    if params.is_empty() {
        return Some(false);
    }
    let mut state = None;
    let mut i = 0;
    while i < params.len() {
        let p = params[i];
        let kind = params.get(i + 1).copied();
        if matches!(p, 0 | 22 | 39) {
            state = Some(false);
        } else if matches!(p, 2 | 90) {
            state = Some(true);
        } else if matches!(p, 38 | 48) && i + 2 < params.len() && kind == Some(5) {
            if p == 38 {
                let v = params[i + 2];
                state = Some((232..=252).contains(&v) || matches!(v, 8 | 59 | 102 | 145));
            }
            i += 2;
        } else if matches!(p, 38 | 48) && i + 4 < params.len() && kind == Some(2) {
            // truecolor: içindeki `2` "soluk" değildir
            if p == 38 {
                let rgb = &params[i + 2..i + 5];
                let max = rgb.iter().copied().max().unwrap_or(0);
                let min = rgb.iter().copied().min().unwrap_or(0);
                state = Some(max - min <= 8 && (60..=200).contains(&rgb[0]));
            }
            i += 4;
        } else if (30..=37).contains(&p) || (91..=97).contains(&p) {
            state = Some(false);
        }
        i += 1;
    }
    state
}

/// Bir renk parçasında istemden SONRA, gri olmayan görünür karakter var mı.
pub fn segment_typed(seg: &str, dim: bool, seen_prompt: bool) -> bool {
    if dim || seg.is_empty() {
        return false;
    }
    let seg = if seen_prompt {
        seg
    } else {
        match seg.split_once(PROMPT) {
            Some((_, rest)) => rest,
            None => return false,
        }
    };
    seg.chars().any(|c| !py_isspace(c) && c != '\u{2502}')
}

/// Claude TUI giriş kutusunda kullanıcının yazdığı (gönderilmemiş) metin var mı; girdi `capture-pane -e` ekranı.
/// Gri öneri/yer tutucu sayılmaz. Kutu bulunamazsa `None`.
pub fn typed_input_in_box(ansi_text: &str) -> Option<bool> {
    let lines: Vec<&str> = ansi_text.split('\n').collect();
    let plain: Vec<String> = lines.iter().map(|l| plain(l)).collect();
    let i = (0..lines.len())
        .rev()
        .find(|&i| starts_with_prompt(&plain[i]) && (i == 0 || plain[i - 1].contains(BOX_RULE)))?;
    let raw = lines[i];
    let (mut dim, mut seen_prompt, mut typed, mut pos) = (false, false, false, 0);
    for m in SGR_RE.captures_iter(raw) {
        let (Some(all), Some(group)) = (m.get(0), m.get(1)) else {
            continue;
        };
        let seg = &raw[pos..all.start()];
        typed |= segment_typed(seg, dim, seen_prompt);
        seen_prompt |= seg.contains(PROMPT);
        dim = dim_fg(&sgr_params(group.as_str())).unwrap_or(dim);
        pos = all.end();
    }
    typed |= segment_typed(&raw[pos..], dim, seen_prompt);
    Some(typed)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputBox {
    /// Kutunun düz metni.
    pub plain: String,
    /// Gri/soluk (öneri) parçalar atılmış kutu metni.
    pub typed: String,
    /// Kutu dışındaki satırlar (ANSI korunur).
    pub outside: String,
}

/// Claude TUI giriş kutusunu ayırır: üstünde `────` olan SON `❯` satırından alttaki son çizgiye kadar.
pub fn input_box(ansi_text: &str) -> Option<InputBox> {
    let lines: Vec<&str> = ansi_text.split('\n').collect();
    let plain: Vec<String> = lines.iter().map(|l| plain(l)).collect();
    let last_rule = plain.iter().rposition(|l| l.contains(BOX_RULE))?;
    let i = (1..lines.len()).rev().find(|&i| {
        starts_with_prompt(&plain[i]) && plain[i - 1].contains(BOX_RULE) && last_rule > i
    })?;
    let body = lines[i..last_rule].join("\n");
    let mut typed = String::new();
    let (mut dim, mut pos) = (false, 0);
    for m in SGR_RE.captures_iter(&body) {
        let (Some(all), Some(group)) = (m.get(0), m.get(1)) else {
            continue;
        };
        if !dim {
            typed.push_str(&body[pos..all.start()]);
        }
        dim = dim_fg(&sgr_params(group.as_str())).unwrap_or(dim);
        pos = all.end();
    }
    if !dim {
        typed.push_str(&body[pos..]);
    }
    let outside: Vec<&str> = lines[..i]
        .iter()
        .chain(&lines[last_rule..])
        .copied()
        .collect();
    Some(InputBox {
        plain: plain[i..last_rule].join("\n"),
        typed: self::plain(&typed),
        outside: outside.join("\n"),
    })
}

/// Pencere şeridi bağlam etiketi (`ctx 120K/300K`). `%` ve `#` içermez (tmux status-right strftime'dan geçirir).
/// Yuvarlama Python `round` gibi yarımda çifte.
pub fn ctx_label(tokens: Option<i64>, warn: i64) -> String {
    let k = |v: i64| (v as f64 / 1000.0).round_ties_even() as i64;
    match tokens {
        Some(t) if t > 0 && warn > 0 => format!("ctx {}K/{}K", k(t), k(warn)),
        Some(t) if t > 0 => format!("ctx {}K", k(t)),
        _ => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_sgr_and_osc() {
        let raw = "\x1b[1m\x1b[38;5;220mSwitch\x1b[0m\x1b[39m \x1b]0;t\x07model?";
        assert_eq!(strip_ansi(raw), "Switch model?");
        // ST (`ESC \\`) ile biten OSC: yalnız dizi silinir, arasındaki metin kalır.
        let st = "\x1b]8;;http://x.invalid\x1b\\bag\x1b]8;;\x1b\\ son\x1b]0;t\x07!";
        assert_eq!(strip_ansi(st), "bag son!");
    }

    #[test]
    fn typed_vs_suggestion() {
        let rule = "────────";
        let screen = |body: &str| format!("{rule}\n❯\u{a0}{body}\n{rule}\n");
        assert_eq!(typed_input_in_box(&screen("merhaba")), Some(true));
        assert_eq!(
            typed_input_in_box(&screen("\x1b[2mdevam\x1b[0m")),
            Some(false)
        );
        assert_eq!(typed_input_in_box(&screen("")), Some(false));
        assert_eq!(typed_input_in_box("döküm"), None);
        let b = input_box(&format!("üst\n{}alt", screen("x \x1b[90mgri\x1b[39m y"))).unwrap();
        assert_eq!(b.typed, "❯\u{a0}x  y");
        assert_eq!(b.outside, format!("üst\n{rule}\n{rule}\nalt"));
    }

    /// Beklenen değerler Python 3.10 `str.splitlines/strip/split` çıktısı.
    #[test]
    fn str_helpers_match_python() {
        let cases: [(&str, &[&str], &str, &[&str]); 9] = [
            ("", &[], "", &[]),
            ("a", &["a"], "a", &["a"]),
            ("a\n", &["a"], "a", &["a"]),
            ("a\n\nb", &["a", "", "b"], "a\n\nb", &["a", "b"]),
            ("a\r\nb\rc", &["a", "b", "c"], "a\r\nb\rc", &["a", "b", "c"]),
            (
                "x\x0by\x0cz\x1cq\x1dr\x1es\x1ft",
                &["x", "y", "z", "q", "r", "s\x1ft"],
                "x\x0by\x0cz\x1cq\x1dr\x1es\x1ft",
                &["x", "y", "z", "q", "r", "s", "t"],
            ),
            (
                "u\u{85}v\u{2028}w\u{2029}",
                &["u", "v", "w"],
                "u\u{85}v\u{2028}w",
                &["u", "v", "w"],
            ),
            ("\r\n", &[""], "", &[]),
            ("\n\n", &["", ""], "", &[]),
        ];
        for (input, lines, stripped, words) in cases {
            assert_eq!(py_splitlines(input), lines, "{input:?}");
            assert_eq!(py_strip(input), stripped, "{input:?}");
            assert_eq!(py_split(input).collect::<Vec<_>>(), words, "{input:?}");
        }
    }

    #[test]
    fn ctx_label_rounds_like_python() {
        assert_eq!(ctx_label(Some(2500), 0), "ctx 2K");
        assert_eq!(ctx_label(Some(120_400), 300_000), "ctx 120K/300K");
        assert_eq!(ctx_label(Some(0), 10), "");
        assert_eq!(ctx_label(None, 0), "");
    }
}
