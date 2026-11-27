//! Kota (`/usage`) ve bağlam (`/context`) komutları ile ekran/metin ayrıştırıcıları (`CliProvider.usage_*`,
//! `context_*`, `parse_*`; claude, agy, copilot karşılıkları). Ekranı okumak ve komutu göndermek çağıranın işi; burada
//! yalnız komut adları, oturumsuz okuma argv'si ve ANSI'siz metnin yorumu var.
//!
//! Python `re` (3.10, `str` deseni) anlamı korunur: `\s` = `str.isspace()` (`\x1c-\x1f` dahil), `\d` = Unicode 13
//! ondalık rakamları (regex crate'in daha yeni Unicode `\d`i DEĞİL), `$` yalnız kırpılmış satırda kullanıldığından `\z`,
//! `pos`/`endpos` kod noktası konumudur. `str.strip()`/`splitlines()` için [`crate::pyfmt`].

use crate::provider::{Cli, Providers};
use crate::pyfmt::{decimal_value, splitlines, strip};
use regex::Regex;
use std::sync::LazyLock;

/// Bir kota/bağlam satırı (`{"label", "percent", "detail"}`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UsageEntry {
    pub label: String,
    /// Rakam metni olduğu gibi (`"48"`, bağlamda `"0.4"`).
    pub percent: String,
    pub detail: String,
}

fn entry(
    label: impl Into<String>,
    percent: impl Into<String>,
    detail: impl Into<String>,
) -> UsageEntry {
    UsageEntry {
        label: label.into(),
        percent: percent.into(),
        detail: detail.into(),
    }
}

/// Python `\s` sınıfının içi.
const S_IN: &str = r"\s\x1C-\x1F";

/// Python `\d` sınıfının içi (Unicode 13 `Nd` blokları; [`crate::pyfmt::decimal_value`] ile aynı tablo).
pub(crate) fn d_in() -> String {
    let mut out = String::new();
    let mut cp = 0u32;
    while cp < 0x20000 {
        if let Some(c) = char::from_u32(cp) {
            if decimal_value(c) == Some(0) {
                out.push_str(&format!("\\x{{{cp:X}}}-\\x{{{:X}}}", cp + 9));
                cp += 10;
                continue;
            }
        }
        cp += 1;
    }
    out
}

/// Python deseninden çeviri: `{S}` -> `[\s\x1C-\x1F]`, `{NS}` -> değili, `{D}` -> `[<Nd>]`, `{DI}` -> sınıf içi.
fn rx(pat: &str) -> Regex {
    let di = d_in();
    let p = pat
        .replace("{NS}", &format!("[^{S_IN}]"))
        .replace("{S}", &format!("[{S_IN}]"))
        .replace("{DI}", &di)
        .replace("{D}", &format!("[{di}]"));
    Regex::new(&p).expect("sabit desen")
}

// claude_provider.py `_USAGE_HEADER_RE`, `_USAGE_PERCENT_RE`, `_USAGE_RESETS_RE`, `_USAGE_FRESH_RE`.
static USAGE_HEADER: LazyLock<Regex> =
    LazyLock::new(|| rx(r"^(Current (?:session|week(?:{S}*\([^)]+\))?))\z"));
static USAGE_PERCENT: LazyLock<Regex> = LazyLock::new(|| rx(r"({D}+)%{S}*used"));
static USAGE_RESETS: LazyLock<Regex> = LazyLock::new(|| rx(r"^(Resets{S}.+)\z"));
static USAGE_FRESH: LazyLock<Regex> = LazyLock::new(|| {
    rx(
        r"^(Current (?:session|week(?:{S}*\([^)]+\))?)):{S}*({D}+)%{S}*used(?:{S}*[·•]{S}*(?:[Rr]esets?{S}+)?(.+))?\z",
    )
});
// claude_provider.py `_CONTEXT_TOTAL_RE`, `_CONTEXT_CATEGORY_RE` (satır içinde `search`).
static CONTEXT_TOTAL: LazyLock<Regex> = LazyLock::new(|| {
    rx(r"([{DI}.]+[kKmM]?){S}*/{S}*([{DI}.]+[kKmM]?){S}*tokens{S}*\(({D}+(?:\.{D}+)?)%\)")
});
static CONTEXT_CATEGORY: LazyLock<Regex> = LazyLock::new(|| {
    rx(r"([A-Za-z][A-Za-z ]*?):{S}*([{DI}.]+[kKmM]?){S}*(?:tokens?)?{S}*\(({D}+(?:\.{D}+)?)%\)")
});
// copilot_provider.py `_USAGE_PLAN_RE`, `_USAGE_FRACTION_RE`, `_USAGE_RESET_RE`. Sonuncusunda Python `$` (dizge sonu ya
// da sondaki `\n`in önü) `\z` oldu: önündeki `{S}*` sondaki `\n`i de yuttuğundan ilk başarılı eşleşme aynıdır.
static PLAN: LazyLock<Regex> = LazyLock::new(|| rx(r"Plan{S}+{NS}*{S}*({D}+)%{S}*used"));
static FRACTION: LazyLock<Regex> = LazyLock::new(|| rx(r"([{DI},]+{S}*/{S}*[{DI},]+{S}*AIC)"));
static RESET_IN: LazyLock<Regex> = LazyLock::new(|| rx(r"resets{S}+in{S}+([^\n•]+?){S}*(?:\n|\z)"));

/// Python `str.isdigit()` olup ondalık OLMAYAN karakterler (Unicode 13: üst/alt simge, daire içi rakamlar ...).
const DIGIT_NOT_DECIMAL: [(u32, u32); 20] = [
    (0xB2, 0xB3),
    (0xB9, 0xB9),
    (0x1369, 0x1371),
    (0x19DA, 0x19DA),
    (0x2070, 0x2070),
    (0x2074, 0x2079),
    (0x2080, 0x2089),
    (0x2460, 0x2468),
    (0x2474, 0x247C),
    (0x2488, 0x2490),
    (0x24EA, 0x24EA),
    (0x24F5, 0x24FD),
    (0x24FF, 0x24FF),
    (0x2776, 0x277E),
    (0x2780, 0x2788),
    (0x278A, 0x2792),
    (0x10A40, 0x10A43),
    (0x10E60, 0x10E68),
    (0x11052, 0x1105A),
    (0x1F100, 0x1F10A),
];

/// `str.isdigit()` (boş dizge False).
fn py_isdigit(s: &str) -> bool {
    !s.is_empty()
        && s.chars().all(|c| {
            decimal_value(c).is_some()
                || DIGIT_NOT_DECIMAL
                    .iter()
                    .any(|(a, b)| (*a..=*b).contains(&(c as u32)))
        })
}

/// Kod noktası konumu -> bayt konumu (dizge sonunda kırpılır).
fn byte_at(s: &str, chars: usize) -> usize {
    s.char_indices().nth(chars).map_or(s.len(), |(i, _)| i)
}

/// claude `/usage` (TUI): her `Current ...` başlığından sonraki en çok 3 satırda ilk `NN% used` ve ilk `Resets ...`.
/// Yüzdesi bulunamayan başlık atılır; hiç girdi yoksa None.
pub fn claude_usage(text: &str) -> Option<Vec<UsageEntry>> {
    let lines: Vec<&str> = splitlines(text).into_iter().map(strip).collect();
    let mut entries = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if !USAGE_HEADER.is_match(line) {
            continue;
        }
        let mut percent: Option<&str> = None;
        let mut resets = "";
        for next in lines.iter().take((i + 4).min(lines.len())).skip(i + 1) {
            if percent.is_none() {
                if let Some(c) = USAGE_PERCENT.captures(next) {
                    percent = c.get(1).map(|m| m.as_str());
                    continue;
                }
            }
            if let Some(c) = USAGE_RESETS.captures(next) {
                resets = c.get(1).map_or("", |m| m.as_str());
                break;
            }
        }
        if let Some(p) = percent {
            entries.push(entry(*line, p, resets));
        }
    }
    (!entries.is_empty()).then_some(entries)
}

/// claude `claude -p /usage` (oturumsuz, tek satır biçimi); hiç satır tanınmazsa TUI ayrıştırıcısına düşer.
pub fn claude_fresh_usage(text: &str) -> Option<Vec<UsageEntry>> {
    let mut entries = Vec::new();
    for ln in splitlines(text) {
        if let Some(c) = USAGE_FRESH.captures(strip(ln)) {
            let rs = strip(c.get(3).map_or("", |m| m.as_str()));
            let detail = if rs.is_empty() {
                String::new()
            } else {
                format!("Resets {rs}")
            };
            entries.push(entry(&c[1], &c[2], detail));
        }
    }
    if entries.is_empty() {
        claude_usage(text)
    } else {
        Some(entries)
    }
}

/// claude `/context`: son görülen `X/Y tokens (Z%)` toplam satırı listeyi SIFIRLAR (eski çıktı atılır), ardından gelen
/// `Ad: N tokens (Z%)` kategori satırları eklenir.
pub fn claude_context(text: &str) -> Option<Vec<UsageEntry>> {
    let mut entries: Vec<UsageEntry> = Vec::new();
    for line in splitlines(text).into_iter().map(strip) {
        if let Some(t) = CONTEXT_TOTAL.captures(line) {
            entries = vec![entry(
                "Context",
                &t[3],
                format!("{}/{} tokens", &t[1], &t[2]),
            )];
            continue;
        }
        if let Some(c) = CONTEXT_CATEGORY.captures(line) {
            let label = strip(&c[1]);
            if !label.is_empty() {
                entries.push(entry(label, &c[3], format!("{} tokens", &c[2])));
            }
        }
    }
    (!entries.is_empty()).then_some(entries)
}

/// agy `/usage` (TSV): `<grup>\t<metrik>\t<NN%>\t<ISO sıfırlanma>`; tam 4 alan ve `%`siz kısmı `isdigit()` olan satırlar.
pub fn agy_usage(text: &str) -> Option<Vec<UsageEntry>> {
    let mut rows = Vec::new();
    for line in splitlines(text) {
        let parts: Vec<&str> = line.split('\t').map(strip).collect();
        let [group, metric, percent, reset_at] = parts.as_slice() else {
            continue;
        };
        let pct = percent.trim_end_matches('%');
        if !py_isdigit(pct) {
            continue;
        }
        rows.push(entry(
            format!("{group} \u{2014} {metric}"),
            pct,
            format!("Resets {reset_at}"),
        ));
    }
    (!rows.is_empty()).then_some(rows)
}

/// copilot `/usage`: tek `Plan ... NN% used` satırı; kesir (`530 / 1,500 AIC`) yüzdeden SONRA herhangi bir yerde,
/// `resets in ...` yüzde eşleşmesinin başından sonuna +120 kod noktasına dek aranır.
pub fn copilot_usage(text: &str) -> Option<Vec<UsageEntry>> {
    let m = PLAN.captures(text)?;
    let whole = m.get(0)?;
    let fm = FRACTION.captures_at(text, whole.end());
    let end_chars = text[..whole.end()].chars().count() + 120;
    let hay = &text[..byte_at(text, end_chars)];
    let rm = RESET_IN.captures_at(hay, whole.start());
    let mut detail = fm.map_or(String::new(), |f| f[1].to_string());
    if let Some(r) = rm {
        let sep = if detail.is_empty() { "" } else { " \u{b7} " };
        detail = format!("{detail}{sep}resets in {}", strip(&r[1]));
    }
    Some(vec![entry("Plan (AI Credits)", &m[1], detail)])
}

impl Cli {
    /// Hesap kota/kullanım slash komutu; None = bu CLI'da yok.
    pub fn usage_command(self) -> Option<&'static str> {
        matches!(self, Cli::Claude | Cli::Agy | Cli::Copilot).then_some("/usage")
    }

    /// `/usage` modal açar (Escape gerekir): claude ve agy evet, copilot (yan panel) ve diğerleri hayır.
    pub fn usage_needs_dismiss(self) -> bool {
        matches!(self, Cli::Claude | Cli::Agy)
    }

    /// Tek oturumun bağlam doluluğu komutu (yalnız claude `/context`).
    pub fn context_command(self) -> Option<&'static str> {
        (self == Cli::Claude).then_some("/context")
    }

    /// `/context` modal açmaz (claude dahil hiçbirinde).
    pub fn context_needs_dismiss(self) -> bool {
        false
    }

    /// Başarısız oturumsuz okuma çıktısı "giriş yapılmamış" mı (yalnız agy metni biliniyor).
    pub fn usage_auth_missing(self, output: &str) -> bool {
        if self != Cli::Agy {
            return false;
        }
        let low = output.to_lowercase();
        low.contains("waiting for authentication") || low.contains("authentication failed")
    }

    /// `usage_command()` ekranının ayrıştırılması; None = tanınmadı ya da bu CLI'da yok.
    pub fn parse_usage_text(self, text: &str) -> Option<Vec<UsageEntry>> {
        match self {
            Cli::Claude => claude_usage(text),
            Cli::Agy => agy_usage(text),
            Cli::Copilot => copilot_usage(text),
            _ => None,
        }
    }

    /// Oturumsuz okuma çıktısı (`usage_fresh_argv`/`usage_fresh_tui_argv`); claude dışında `parse_usage_text`.
    pub fn parse_fresh_usage(self, text: &str) -> Option<Vec<UsageEntry>> {
        match self {
            Cli::Claude => claude_fresh_usage(text),
            _ => self.parse_usage_text(text),
        }
    }

    /// `context_command()` ekranının ayrıştırılması (ilk öge toplam).
    pub fn parse_context_text(self, text: &str) -> Option<Vec<UsageEntry>> {
        match self {
            Cli::Claude => claude_context(text),
            _ => None,
        }
    }
}

impl Providers<'_> {
    /// Oturum açmadan kullanım okuması (model turu yakmayan kısa süreç): claude `-p /usage`, agy `--print=/usage`.
    pub fn usage_fresh_argv(&self, cli: Cli) -> Option<Vec<String>> {
        match cli {
            Cli::Claude => Some(vec![
                self.resolved_binary("claude"),
                "-p".into(),
                "/usage".into(),
            ]),
            Cli::Agy => Some(vec![self.resolved_binary("agy"), "--print=/usage".into()]),
            _ => None,
        }
    }

    /// Oturumsuz okuma, geçici TUI yolu (yalnız copilot: `-p /usage` kredi yakar, kullanılmaz).
    pub fn usage_fresh_tui_argv(&self, cli: Cli) -> Option<Vec<String>> {
        (cli == Cli::Copilot).then(|| vec![self.resolved_binary("copilot")])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_classes() {
        assert!(USAGE_PERCENT.is_match("\u{1d}5%\u{1c}used"));
        assert!(USAGE_PERCENT.is_match("٣%used"));
        // U+11F50 (Kawi rakamı, Unicode 15): Python 3.10 `\d` DEĞİL.
        assert!(!USAGE_PERCENT.is_match("\u{11F50}%used"));
        assert!(py_isdigit("²") && py_isdigit("٣") && !py_isdigit("") && !py_isdigit("½"));
    }
}
