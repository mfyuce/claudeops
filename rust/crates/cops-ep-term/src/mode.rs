//! web.py `_detect_mode_in_text(text, get_provider(cli))`: ekranın son 8 DOLU satırında (ANSI ayıklanmış) sağlayıcının
//! izin modu desenleri, sözlük sırasıyla; ilk eşleşen mod, yoksa `None`.
//!
//! Desenler (`providers/*_provider.py` `MODE_STATUS_PATTERNS`, `re.IGNORECASE`): yalnız `claude` ve `copilot` tanımlar;
//! `agy`, `codex`, `shell`, `ucli` boş sözlük (mod yok). `get_provider` tanınmayan cli için `claude` döner.
//!
//! Python `re.IGNORECASE` ile Rust `(?i)` AYNI DEĞİL (Python `i` için `İ`/`ı`, `s` için `ſ` de eşler; Rust basit katlama
//! `İ`/`ı`yı eşlemez) ve Python `\s` U+001C..U+001F'i de kapsar: desenler bu yüzden açık karakter sınıflarıyla yazılır
//! (sınıflar Python'dan tüm kod noktaları taranarak çıkarıldı; `tests/pure_parity.rs` yeniden denetler).
use cops_state::pycompat::strip;
use regex::Regex;
use std::sync::LazyLock;

/// Python `re` `\s` (str deseni) = `str.isspace`.
pub const PY_SPACE_CLASS: &str = r"[\s\x1c-\x1f]";

/// Python `re.IGNORECASE` altında bir ASCII harfin eşlediği karakterler (harf dışı karakter kaçırılmış hâliyle).
pub fn ci_class(c: char) -> String {
    match c {
        'i' | 'I' => "[iI\u{130}\u{131}]".into(),
        's' | 'S' => "[sS\u{17f}]".into(),
        c if c.is_ascii_alphabetic() => {
            format!("[{}{}]", c.to_ascii_lowercase(), c.to_ascii_uppercase())
        }
        c => regex::escape(&c.to_string()),
    }
}

/// Düz metin deseni (yalnız harf, boşluk, `·`) + Python `\s*` yer tutucusu `~`.
fn compile(src: &str) -> Regex {
    let pat: String = src
        .chars()
        .map(|c| match c {
            '~' => format!("{PY_SPACE_CLASS}*"),
            c => ci_class(c),
        })
        .collect();
    Regex::new(&pat).expect("sabit desen")
}

type Patterns = Vec<(&'static str, Regex)>;

static CLAUDE: LazyLock<Patterns> = LazyLock::new(|| {
    vec![
        ("plan", compile("plan mode on")),
        ("acceptEdits", compile("accept edits on")),
        ("auto", compile("auto mode on")),
        ("manual", compile("manual mode on")),
    ]
});

static COPILOT: LazyLock<Patterns> = LazyLock::new(|| {
    vec![
        ("plan", compile("·~plan~·")),
        ("autopilot", compile("·~autopilot~·")),
    ]
});

/// `get_provider(cli).mode_status_patterns()`.
pub fn patterns(cli: &str) -> &'static [(&'static str, Regex)] {
    match cli {
        "agy" | "codex" | "shell" | "ucli" => &[],
        "copilot" => &COPILOT,
        _ => &CLAUDE,
    }
}

/// Python `str.splitlines()` (sonda satır sonu varsa boş satır yok).
pub fn py_splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let mut end = i + c.len_utf8();
        match c {
            '\r' => {
                if let Some(&(j, '\n')) = it.peek() {
                    it.next();
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

/// `_detect_mode_in_text(text, get_provider(cli))`.
pub fn detect(text: &str, cli: &str) -> Option<&'static str> {
    let pats = patterns(cli);
    if pats.is_empty() {
        return None;
    }
    let clean = cops_tmux::strip_ansi(text);
    let full: Vec<&str> = py_splitlines(&clean)
        .into_iter()
        .filter(|l| !strip(l).is_empty())
        .collect();
    let tail = full[full.len().saturating_sub(8)..].join("\n");
    pats.iter()
        .find(|(_, re)| re.is_match(&tail))
        .map(|(m, _)| *m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_modes_and_python_case_rules() {
        assert_eq!(
            detect("x\n  ⏵⏵ plan mode on (shift)\n", "claude"),
            Some("plan")
        );
        assert_eq!(detect("AUTO MODE ON", "zzz"), Some("auto"));
        assert_eq!(detect("manual mode on", "agy"), None);
        assert_eq!(
            detect("accept ed\u{131}ts on", "claude"),
            Some("acceptEdits")
        );
        assert_eq!(detect("\u{130}gnore auto mode \u{17f}on", "claude"), None);
        assert_eq!(detect("plan mode on\n", "ucli"), None);
        // eski satır 8 dolu satırın gerisinde kaldı
        let old = format!("plan mode on\n{}", "x\n\n".repeat(8));
        assert_eq!(detect(&old, "claude"), None);
    }

    #[test]
    fn copilot_space_class_is_pythons() {
        assert_eq!(detect("· \u{1c}plan\t·", "copilot"), Some("plan"));
        assert_eq!(detect("·autopilot·", "copilot"), Some("autopilot"));
        assert_eq!(detect("plan mode on", "copilot"), None);
    }

    #[test]
    fn splitlines_like_python() {
        assert_eq!(py_splitlines("a\r\nb\rc\x1cd\n"), vec!["a", "b", "c", "d"]);
        assert_eq!(py_splitlines(""), Vec::<&str>::new());
        assert_eq!(py_splitlines("\n\n"), vec!["", ""]);
    }
}
