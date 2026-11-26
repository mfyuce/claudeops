//! Gizli değer ayıklama. Python'daki ileri/geri bakışlı iki kalıp burada elle uygulanır (`regex` desteklemez).
use crate::py::{self, S};
use regex::Regex;
use std::sync::LazyLock;

/// Öğrenilmiş (DSN) parolası bundan kısaysa düz metinde maskelenmez.
pub const LEARNED_MIN: usize = 4;
/// Bundan uzunsa her yerde düz değiştirilir; arası yalnız sözcük sınırında.
pub const LEARNED_PLAIN_MIN: usize = 8;
const MASK: &str = "[REDACTED]";

/// `scheme://kullanıcı:` öneki. `İ`/`ı`: Python `re.I`de `[a-z]`ye girer.
static DSN_PREFIX: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(r#"(?i)\b[a-zİı][a-z0-9+.\-İı]*://[^{S}:/@"']+:"#)).unwrap()
});

struct Dsn {
    prefix_end: usize,
    /// Parolayı kapatan `@`in konumu.
    at: usize,
    start: usize,
}

fn stops_password(c: char) -> bool {
    py::is_space(c) || c == '"' || c == '\''
}

/// `_DSN_RE` eşleşmeleri: parola açgözlü (boşluksuz parçada, ardında geçerli konak karakteri olan SON `@`), en az 3 karakter.
fn dsn_matches(text: &str) -> Vec<Dsn> {
    let mut out = Vec::new();
    let mut pos = 0;
    while pos <= text.len() {
        let Some(m) = DSN_PREFIX.find_at(text, pos) else {
            break;
        };
        let rest = &text[m.end()..];
        let run_len = rest.find(stops_password).unwrap_or(rest.len());
        let run = &rest[..run_len];
        let at = run
            .char_indices()
            .enumerate()
            .filter(|(n, (i, c))| {
                *n >= 3
                    && *c == '@'
                    && run[i + 1..]
                        .chars()
                        .next()
                        .is_some_and(|d| d != '@' && d != '/')
            })
            .map(|(_, (i, _))| i)
            .last();
        match at {
            Some(at) => {
                out.push(Dsn {
                    start: m.start(),
                    prefix_end: m.end(),
                    at: m.end() + at,
                });
                pos = m.end() + at + 1;
            }
            None => pos = m.start() + text[m.start()..].chars().next().map_or(1, char::len_utf8),
        }
    }
    out
}

/// Metindeki `scheme://user:PAROLA@host` parolaları.
pub fn dsn_passwords(text: &str) -> Vec<String> {
    dsn_matches(text)
        .iter()
        .map(|d| &text[d.prefix_end..d.at])
        .filter(|p| *p != MASK)
        .map(str::to_string)
        .collect()
}

fn mask_dsn(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    for d in dsn_matches(text) {
        debug_assert!(d.start >= last);
        out.push_str(&text[last..d.prefix_end]);
        out.push_str(MASK);
        last = d.at;
    }
    out.push_str(&text[last..]);
    out
}

fn word_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '/' | '-')
}

/// `(?<![A-Za-z0-9_./-])SIR(?![A-Za-z0-9_./-])` -> `[REDACTED]`.
fn mask_word(text: &str, secret: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let (mut last, mut pos) = (0, 0);
    while let Some(i) = text[pos..].find(secret).map(|i| i + pos) {
        let end = i + secret.len();
        let free = !text[..i].chars().next_back().is_some_and(word_char)
            && !text[end..].chars().next().is_some_and(word_char);
        if free {
            out.push_str(&text[last..i]);
            out.push_str(MASK);
            last = end;
            pos = end;
        } else {
            pos = i + text[i..].chars().next().map_or(1, char::len_utf8);
        }
    }
    out.push_str(&text[last..]);
    out
}

/// (kalıp, ilk grup korunur mu)
static SECRETS: LazyLock<Vec<(Regex, bool)>> = LazyLock::new(|| {
    let q = r#"\\\"'"#; // sınıf içinde: ters bölü, çift tırnak, tek tırnak
    [
        (r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----".to_string(), false),
        (r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}".to_string(), false),
        (r"\bgh[pousr]_[A-Za-z0-9]{20,}".to_string(), false),
        (r"\bhf_[A-Za-z0-9]{20,}".to_string(), false),
        (r"\bAKIA[0-9A-Z]{16}\b".to_string(), false),
        (r"\bxox[abprs]-[A-Za-z0-9-]{10,}".to_string(), false),
        (format!(r"(?i)\bBearer[{S}]+[A-Za-z0-9._~+/=\-İı]{{16,}}"), false),
        (r"\bAIza[0-9A-Za-z_-]{30,}".to_string(), false),
        (r"\bglpat-[A-Za-z0-9_-]{16,}".to_string(), false),
        (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}".to_string(), false),
        (r"\btk_[A-Za-z0-9]{16,}".to_string(), false),
        (
            format!(
                r"(?i)((?:ap[iİı][_-]?key|secret|token|pass(?:w(?:or)?d)?|author[iİı]zat[iİı]on)[\w-]*[{q}]{{0,2}}[{S}]*[:=][{S}]*[\\]?[\x22']?)[^{S}{q},;]{{8,}}"
            ),
            true,
        ),
        (
            format!(r"(?i)(--(?:password|passwd|token|ap[iİı]-key|secret)[ =])[^{S}\x22']{{4,}}"),
            true,
        ),
    ]
    .into_iter()
    .map(|(p, g)| (Regex::new(&p).unwrap(), g))
    .collect()
});

/// Bilinen gizli değer biçimlerini `[REDACTED]` yapar; `learned`: daha önce görülmüş sırlar.
pub fn redact_secrets(text: &str, learned: &[String]) -> String {
    let mut all: Vec<String> = learned.to_vec();
    all.extend(
        dsn_passwords(text)
            .into_iter()
            .filter(|p| !learned.contains(p)),
    );
    let mut out = mask_dsn(text);
    all.sort_by_key(|s| std::cmp::Reverse(s.chars().count()));
    for s in &all {
        let n = s.chars().count();
        if n >= LEARNED_PLAIN_MIN {
            out = out.replace(s.as_str(), MASK);
        } else if n >= LEARNED_MIN {
            out = mask_word(&out, s);
        }
    }
    for (re, keep_first) in SECRETS.iter() {
        if !re.is_match(&out) {
            continue;
        }
        out = if *keep_first {
            re.replace_all(&out, |c: &regex::Captures<'_>| format!("{}{MASK}", &c[1]))
                .into_owned()
        } else {
            re.replace_all(&out, regex::NoExpand(MASK)).into_owned()
        };
    }
    out
}
