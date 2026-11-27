//! Bir `.usage.jsonl` satırının TEK değerlendirmesi (Python `review._scan_usage_windows` döngü gövdesi). İki tüketicisi
//! var: `report::usage_cost_usd` (yalnız toplam) ve `cops-providers` `cost::UsageScan` (toplam + güvenilirlik). Dosya
//! açma, zaman penceresi ve günlük kaydı çağırandadır; satır sınırı ([`next_line`]), fiyat, sayaç ve sınır kuralları
//! yalnız burada.

use crate::py;
use crate::report::anthropic_price;
use crate::targets::{ANTHROPIC_PRICES, HAIKU_LONG_PRICE, HAIKU_LONG_PROMPT};
use cops_state::json::{Json, Map};
use std::io::{self, BufRead, Read};

/// Python `_MAX_USAGE_TOKENS`: tek istek sayacı için akla yatkın üst sınır (üstü bozuk kayıt).
pub const MAX_USAGE_TOKENS: f64 = 1e15;

/// Python `_MAX_LINE_DEPTH`: bir kullanım satırında iç içe dizi/nesne sınırı (gerçek kayıt 2-3 katlı).
pub const MAX_LINE_DEPTH: usize = 512;

/// Python `_MAX_LINE_BYTES`: tek kullanım satırının (satır sonu hariç) bayt sınırı.
pub const MAX_LINE_BYTES: usize = 16 << 20;

/// [`next_line`]ın sonucu.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Raw {
    End,
    /// Satır tamponda (varsa satır sonuyla).
    Line,
    /// [`MAX_LINE_BYTES`]i aşan satır: atlandı; anlamı [`too_long`].
    TooLong,
}

/// Python `_usage_lines`: sıradaki satırı `buf`a okur (yalnız `\n` ayırır). Sınırı aşan satır belleğe alınmaz: tampon en
/// çok sınır + 1 bayt olur, kalanı satır sonuna (ya da dosya sonuna) dek atılır. Atlarken çıkan okuma hatası
/// yutulur (satır yine sayılamadı); kalıcıysa sonraki çağrı bildirir.
pub fn next_line(reader: &mut impl BufRead, buf: &mut Vec<u8>) -> io::Result<Raw> {
    buf.clear();
    let limit = MAX_LINE_BYTES as u64 + 1;
    if reader.by_ref().take(limit).read_until(b'\n', buf)? == 0 {
        return Ok(Raw::End);
    }
    if buf.len() <= MAX_LINE_BYTES || buf.ends_with(b"\n") {
        return Ok(Raw::Line);
    }
    buf.clear();
    let _ = reader.skip_until(b'\n');
    Ok(Raw::TooLong)
}

/// [`Raw::TooLong`] satırının anlamı.
pub fn too_long() -> Line {
    Line::Uncountable {
        problem: "çok uzun satır",
        kind: "usage.length",
    }
}

/// Python'un tam sayı basamak sınırı: daha uzununu `json.loads` ayrıştırmaz.
const MAX_INT_DIGITS: usize = 4300;

/// Python `_USAGE_COUNT_KEYS`.
const COUNT_KEYS: [&str; 9] = [
    "cache_read_input_tokens",
    "cached_tokens",
    "cache_read_tokens",
    "cache_creation_input_tokens",
    "cache_write_tokens",
    "input_tokens",
    "prompt_tokens",
    "output_tokens",
    "completion_tokens",
];

/// Python `_too_deep`: satır [`MAX_LINE_DEPTH`]ten derin mi. Dize (yarım da olsa) içindeki ayraç sayılmaz; ayrıştırmadan
/// önce bakılır, sonuç ayrıştırıcıya bağlı değildir.
pub fn too_deep(line: &str) -> bool {
    let opens = line.bytes().filter(|b| matches!(b, b'[' | b'{')).count();
    if opens <= MAX_LINE_DEPTH {
        return false;
    }
    let (mut depth, mut in_string, mut escaped) = (0usize, false, false);
    for b in line.bytes() {
        if in_string {
            match b {
                _ if escaped => escaped = false,
                b'\\' => escaped = true,
                b'"' => in_string = false,
                _ => {}
            }
            continue;
        }
        match b {
            b'"' => in_string = true,
            b'[' | b'{' => {
                depth += 1;
                if depth > MAX_LINE_DEPTH {
                    return true;
                }
            }
            b']' | b'}' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }
    false
}

/// Satırda [`MAX_INT_DIGITS`]ten uzun bir tam sayı değişmezi var mı (ondalıklı/üslü sayı ve dize içi sayılmaz). Python
/// bunu ayrıştırma hatasından anlar; burada ayrıştırıcıdan önce bakılır.
pub fn long_integer(line: &str) -> bool {
    let bytes = line.as_bytes();
    if bytes.len() <= MAX_INT_DIGITS {
        return false;
    }
    let (mut i, mut in_string) = (0usize, false);
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if in_string => i += 1,
            b'"' => in_string = !in_string,
            b'0'..=b'9' if !in_string => {
                let start = i;
                while bytes.get(i).is_some_and(u8::is_ascii_digit) {
                    i += 1;
                }
                let before = &bytes[..start];
                let tail_of_float = matches!(before.last(), Some(b'.' | b'e' | b'E' | b'+'))
                    || before.ends_with(b"e-")
                    || before.ends_with(b"E-");
                let head_of_float = matches!(bytes.get(i), Some(b'.' | b'e' | b'E'));
                if i - start > MAX_INT_DIGITS && !tail_of_float && !head_of_float {
                    return true;
                }
                continue;
            }
            _ => {}
        }
        i += 1;
    }
    false
}

/// Bir satırın anlamı.
#[derive(Debug)]
pub enum Line {
    /// Kayıt değil: ayrıştırılamayan (yarım yazılmış) satır ya da nesne olmayan değer.
    Ignored,
    /// Harcaması bilinemeyen satır: toplama güvenilmez (`problem`), günlük türü `kind`.
    Uncountable {
        problem: &'static str,
        kind: &'static str,
    },
    /// `task_start`: sonraki isteklerin modelinin fiyatı (yalnız `follow_model` iken).
    Model([f64; 4]),
    Record(Record),
}

/// Ayrıştırılmış kullanım kaydı.
#[derive(Debug)]
pub struct Record {
    fields: Map,
    /// `float(rec.get("t") or 0)`; sonlu değilse kayıt toplama girmez.
    pub time: f64,
    /// `usage` taşıyan kaydın zaman damgası sayı değil ya da sonlu değil: toplama güvenilmez.
    pub bad_time: bool,
}

/// Bir isteğin ücreti.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Charge {
    /// Geçersiz sayaç var (negatif, sayı değil, sınır üstü): toplama güvenilmez; o sayaç 0 sayılır.
    pub bad_count: bool,
    /// USD; None = sonlu olmayan sayı taşıyan istek bütünüyle atlanır.
    pub usd: Option<f64>,
}

/// `follow_model`: model çağırandan verilmedi, `task_start` kayıtlarından izlenir.
pub fn read_line(line: &str, follow_model: bool) -> Line {
    if too_deep(line) {
        return Line::Uncountable {
            problem: "çok derin satır",
            kind: "usage.depth",
        };
    }
    if long_integer(line) {
        return Line::Uncountable {
            problem: "çok uzun sayı",
            kind: "usage.number",
        };
    }
    // Python `json.loads` eşlenmemiş vekili kabul eder: satır sayımdan düşmez.
    let Ok((Json::Object(fields), _)) = Json::parse_lossy(line) else {
        return Line::Ignored;
    };
    if follow_model
        && py::is_str(fields.get("event"), "task_start")
        && py::truthy(fields.get("model"))
    {
        return Line::Model(anthropic_price(&py::str_or_empty(fields.get("model"))));
    }
    let (time, valid) = timestamp(fields.get("t"));
    let bad_time = !valid && fields.get("usage").and_then(Json::as_object).is_some();
    Line::Record(Record {
        fields,
        time,
        bad_time,
    })
}

/// `float(t or 0)` + geçerli mi. Sayıya çevrilemeyen = (0, geçersiz); float'a sığmayan tam sayı sonsuz.
fn timestamp(v: Option<&Json>) -> (f64, bool) {
    let Some(v) = v.filter(|v| v.truthy()) else {
        return (0.0, true);
    };
    let parsed = match v {
        Json::BigInt(_) => Some(py::float(v).unwrap_or(f64::INFINITY)),
        _ => py::float(v),
    };
    parsed.map_or((0.0, false), |t| (t, t.is_finite()))
}

/// `review._usage_number`: negatif olmayan, sınır içinde sayı (bool, NaN, metin değil).
fn usage_number(v: &Json) -> Option<f64> {
    matches!(v, Json::Int(_) | Json::Float(_) | Json::BigInt(_))
        .then(|| py::float(v))
        .flatten()
        .filter(|x| (0.0..=MAX_USAGE_TOKENS).contains(x))
}

/// `review._finite`: sayısal değer sonlu mu (float'a sığmayan tam sayı sonlu değil).
fn finite(v: &Json) -> bool {
    !matches!(v, Json::Float(_) | Json::BigInt(_)) || py::float(v).is_some_and(f64::is_finite)
}

impl Record {
    /// İstek kaydının ücreti; None = ücretlenecek kayıt değil (`usage` yok ya da `task_end`).
    pub fn charge(&self, price: [f64; 4], write_mult: f64) -> Option<Charge> {
        let u = self.fields.get("usage").and_then(Json::as_object)?;
        if py::is_str(self.fields.get("event"), "task_end") {
            return None; // görevin toplamı: istek satırları zaten sayıldı
        }
        // kaydın alanları bir kez gezilir (anahtar başına arama sıcak yolda ölçülür maliyetti)
        let bad_count = u.iter().any(|(k, v)| {
            *v != Json::Null && usage_number(v).is_none() && COUNT_KEYS.contains(&k.as_str())
        });
        let usd = u
            .values()
            .all(finite)
            .then(|| request_usd(u, price, write_mult));
        Some(Charge { bad_count, usd })
    }
}

fn request_usd(u: &Map, price: [f64; 4], write_mult: f64) -> f64 {
    let numeric = |k: &str| u.get(k).and_then(usage_number);
    let g = |names: &[&str]| names.iter().find_map(|n| numeric(n)).unwrap_or(0.0);
    let cr = g(&[
        "cache_read_input_tokens",
        "cached_tokens",
        "cache_read_tokens",
    ]);
    let cw = g(&["cache_creation_input_tokens", "cache_write_tokens"]);
    let [pi, po, pr, pw] = price;
    // `input_tokens` (Anthropic yerli) önbelleği içermez; ucli'nin `prompt_tokens`ı okuma+yazmayı içerir.
    let inp = match numeric("input_tokens") {
        Some(i) => {
            let read = if u.contains_key("cache_read_input_tokens") {
                0.0
            } else {
                cr
            };
            let written = if u.contains_key("cache_creation_input_tokens") {
                0.0
            } else {
                cw
            };
            f64::max(0.0, i - read - written)
        }
        None => f64::max(0.0, g(&["prompt_tokens"]) - cr - cw),
    };
    // ucli normalleştirilmiş sayaç yazmayı ayrı bildirmez: yeni girdi yazma fiyatından (güvenli üst sınır)
    let normalized =
        u.contains_key("cached_tokens") && !u.contains_key("cache_creation_input_tokens");
    let mut inp_price = if normalized { pw } else { pi };
    let (mut out_price, mut read_price, mut write_price) = (po, pr, pw);
    if price == ANTHROPIC_PRICES[0].1 && inp + cr + cw > HAIKU_LONG_PROMPT {
        let long_in;
        [long_in, out_price, read_price, write_price] = HAIKU_LONG_PRICE;
        inp_price = if inp_price == pi {
            long_in
        } else {
            write_price
        };
    }
    (inp * inp_price
        + g(&["output_tokens", "completion_tokens"]) * out_price
        + cr * read_price
        + cw * write_price * write_mult)
        / 1e6
}
