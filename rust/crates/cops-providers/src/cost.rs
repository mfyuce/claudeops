//! `ucli_cost.py` + `review.usage_cost_usd`in SAF yarısı: fiyat tablosu, kullanım günlüğü satırlarının toplanması, kredi
//! dönemi özeti, tavan reddi. Dosya, saat ve rezervasyon [`crate::real::ledger`]de.
//!
//! `rs/rev` (`cops-review-core`) fiyat tablosunu ve `usage_cost_usd`i de taşır; o dal birleşince tek kopya kalmalı.

use crate::pyfmt::parse_float;
use crate::pyjson::{Py, MAX_DEPTH};
use crate::settings::UcliCostConfig;
use serde_json::{json, Map, Value};
use std::fmt;

/// Başlatma sonucundaki `code` alanı: arayüz "tavanı yükselt ve tekrar dene" sunar.
pub const CAP_CODE: &str = "ucli_daily_cap";
/// 1 saatlik önbellek yazması 5 dakikalıktan pahalı.
pub const CACHE_1H_WRITE_MULT: f64 = 1.6;
/// Durum özetinin önbellek süresi (sn).
pub const TTL: f64 = 30.0;
/// Durum yanıtında en çok harcayan oturum sayısı.
pub const BY_SESSION_TOP: usize = 10;
/// Eşanlı başlatmada her oturum için ayrılan pay (USD).
pub const RESERVE_USD: f64 = 1.0;
/// Payın ömrü (sn).
pub const RESERVE_TTL: f64 = 120.0;
/// Tek istek sayacının üst sınırı (üstü bozuk kayıt).
pub const MAX_USAGE_TOKENS: f64 = 1e15;

/// `review.ANTHROPIC_PRICES` (sıra anlamlı: ilk alt dize eşleşmesi): girdi, çıktı, önbellek okuma, yazma ($/M).
const PRICES: [(&str, [f64; 4]); 4] = [
    ("haiku-5-5", [0.10, 0.50, 0.01, 0.125]),
    ("sonnet-5-5", [2.0, 10.0, 0.10, 2.5]),
    ("opus-5-5", [4.0, 20.0, 0.20, 5.0]),
    ("fable-5-1", [10.0, 50.0, 0.25, 12.5]),
];

/// `review.anthropic_price`: bilinmeyen model en pahalı varsayımla (opus).
pub fn anthropic_price(model: &str) -> [f64; 4] {
    PRICES
        .iter()
        .find(|(k, _)| model.contains(k))
        .map_or(PRICES[2].1, |(_, v)| *v)
}

/// `ucli_cost.write_mult`.
pub fn write_mult(cfg: &UcliCostConfig) -> f64 {
    if cfg.cache_ttl == "1h" {
        CACHE_1H_WRITE_MULT
    } else {
        1.0
    }
}

/// `round(x, digits)` (en yakın, eşitlikte çifte; ondalık gösterim üzerinden). Sonlu olmayan değer aynen döner.
pub fn py_round(x: f64, digits: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.digits$}").parse().unwrap_or(x)
}

/// Başlatma reddinin nedeni.
#[derive(Debug, Clone, PartialEq)]
pub enum CostRefusal {
    /// `DailyCapExceeded`.
    CapExceeded { today_usd: f64, cap_usd: f64 },
    /// Tavan açık (ya da bilinemiyor) ama harcama güvenilir biçimde sayılamıyor.
    Unverifiable(String),
    /// Tavanın kendisi okunamıyor: `settings.json` bozuk ya da değer geçersiz.
    BadSettings(String),
}

impl fmt::Display for CostRefusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let num = |v: f64| {
            if v.is_nan() {
                "nan".to_string()
            } else {
                format!("{v:.2}")
            }
        };
        match self {
            CostRefusal::CapExceeded { today_usd, cap_usd } => write!(
                f,
                "claude: günlük USD tavanı aşıldı ({} / {}); Ayarlar'dan ucli_cost.daily_cap_usd yükselt ya da yarın dene",
                num(*today_usd),
                num(*cap_usd)
            ),
            CostRefusal::Unverifiable(why) => write!(
                f,
                "claude: günlük USD tavanı denetlenemiyor ({why}); ucli_usage günlüklerini düzelt ya da Ayarlar'dan \
                 ucli_cost.daily_cap_usd'yi kapat"
            ),
            CostRefusal::BadSettings(why) => write!(
                f,
                "claude: günlük USD tavanı denetlenemiyor ({why}); settings.json'ı düzelt \
                 (ucli_cost.daily_cap_usd: 0 = tavan yok ya da pozitif sayı)"
            ),
        }
    }
}

/// `ucli_cost.refusal` (maliyet kısmı): başlatma reddi -> web sonucu. Çok kullanıcı kipinin `spawn_refused` dalı
/// (`authz.SpawnRefused`) kanca sahibi katmandadır (G9).
pub fn refusal(error: &str, cost: Option<&CostRefusal>) -> Value {
    let mut out = Map::new();
    out.insert("ok".into(), json!(false));
    out.insert("error".into(), json!(error));
    if let Some(CostRefusal::CapExceeded { today_usd, cap_usd }) = cost {
        out.insert("code".into(), json!(CAP_CODE));
        out.insert("today_usd".into(), json!(py_round(*today_usd, 2)));
        out.insert("cap_usd".into(), json!(py_round(*cap_usd, 2)));
    }
    Value::Object(out)
}

/// `review._usage_number`: negatif olmayan, sınır içinde sayı (bool, NaN, metin değil).
fn usage_number(v: Option<&Py>) -> Option<f64> {
    let n = match v? {
        Py::Int(i) => *i as f64,
        Py::Float(f) => *f,
        _ => return None,
    };
    (0.0..=MAX_USAGE_TOKENS).contains(&n).then_some(n)
}

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

/// `review._finite`: sayısal değer sonlu mu (float'a sığmayan tam sayı sonlu değil).
fn finite(v: &Py) -> bool {
    match v {
        Py::BigInt(s) => s.parse::<f64>().is_ok_and(f64::is_finite),
        Py::Float(f) => f.is_finite(),
        _ => true,
    }
}

/// `float(rec.get("t") or 0)` + geçerli mi. Sayıya çevrilemeyen = (0, geçersiz); sonlu olmayan değer aynen döner.
fn timestamp(v: Option<&Py>) -> (f64, bool) {
    let Some(v) = v.filter(|v| v.truthy()) else {
        return (0.0, true);
    };
    let parsed = match v {
        Py::Bool(_) => Some(1.0),
        Py::Int(i) => Some(*i as f64),
        // float'a sığmayan tam sayı (Python `OverflowError`) burada sonsuz olur
        Py::BigInt(s) => s.parse::<f64>().ok(),
        Py::Float(f) => Some(*f),
        Py::Str(s) => parse_float(s),
        _ => None,
    };
    parsed.map_or((0.0, false), |t| (t, t.is_finite()))
}

/// Metindeki toplam açılış ayracı [`MAX_DEPTH`]i aşıyor mu (ayrıştırılamayan satır derinlik yüzünden olabilir).
fn maybe_too_deep(line: &str) -> bool {
    line.bytes().filter(|b| matches!(b, b'[' | b'{')).count() > MAX_DEPTH
}

/// `review._scan_usage`: satır satır beslenen toplayıcı.
#[derive(Debug, Clone)]
pub struct UsageScan {
    price: [f64; 4],
    /// Model çağırandan: `task_start` kayıtları fiyatı değiştirmez.
    fixed_model: bool,
    since_ms: f64,
    write_mult: f64,
    /// Toplam USD.
    pub total: f64,
    /// Boş değilse toplama güvenilmez.
    pub problem: Option<&'static str>,
    /// Atlanan bozuk kayıtların türü (`usage.record`), görülme sırasıyla.
    pub skipped: Vec<&'static str>,
}

impl UsageScan {
    pub fn new(model: &str, since_ms: f64, write_mult: f64) -> UsageScan {
        let price = anthropic_price(if model.is_empty() { "opus-5-5" } else { model });
        UsageScan {
            price,
            fixed_model: !model.is_empty(),
            since_ms,
            write_mult,
            total: 0.0,
            problem: None,
            skipped: Vec::new(),
        }
    }

    /// Tek satır (satır sonu olsa da olur). Ayrıştırılamayan (yarım yazılmış) satır atlanır.
    pub fn feed(&mut self, line: &str) {
        let Some(rec) = Py::parse(line) else {
            // Python 512'den derin satırı da (~1000'e dek) okur: sayılamayan kayıt sessizce 0 olmasın
            if maybe_too_deep(line) {
                self.problem = Some("çok derin satır");
            }
            return;
        };
        if !rec.is_object() {
            return;
        }
        if !self.fixed_model && rec.get("event").and_then(Py::as_str) == Some("task_start") {
            if let Some(model) = rec.get("model").filter(|m| m.truthy()) {
                self.price = anthropic_price(&model.py_str());
                return;
            }
        }
        let (t, t_ok) = timestamp(rec.get("t"));
        let usage = rec.get("usage").filter(|u| u.is_object());
        if !t_ok && usage.is_some() {
            self.problem = Some("geçersiz zaman damgası");
        }
        if !t.is_finite() {
            self.skipped.push("usage.record"); // sonlu olmayan damgalı kayıt toplama girmez (TBD#375)
            return;
        }
        if self.since_ms != 0.0 && t < self.since_ms {
            return;
        }
        let Some(u) = usage else { return };
        if COUNT_KEYS.iter().any(|k| {
            u.get(k)
                .is_some_and(|v| *v != Py::Null && usage_number(Some(v)).is_none())
        }) {
            self.problem = Some("geçersiz sayaç");
        }
        if let Py::Object(fields) = u {
            if !fields.iter().all(|(_, v)| finite(v)) {
                self.skipped.push("usage.record"); // sonlu olmayan sayaçlı istek bütünüyle atlanır
                return;
            }
        }
        let g = |names: &[&str]| {
            names
                .iter()
                .find_map(|n| usage_number(u.get(n)))
                .unwrap_or(0.0)
        };
        let cr = g(&[
            "cache_read_input_tokens",
            "cached_tokens",
            "cache_read_tokens",
        ]);
        let cw = g(&["cache_creation_input_tokens", "cache_write_tokens"]);
        let [pi, po, pr, pw] = self.price;
        let inp = match usage_number(u.get("input_tokens")) {
            Some(i) => {
                let read = if u.get("cache_read_input_tokens").is_some() {
                    0.0
                } else {
                    cr
                };
                let written = if u.get("cache_creation_input_tokens").is_some() {
                    0.0
                } else {
                    cw
                };
                (i - read - written).max(0.0)
            }
            None => (g(&["prompt_tokens"]) - cr - cw).max(0.0),
        };
        let normalized =
            u.get("cached_tokens").is_some() && u.get("cache_creation_input_tokens").is_none();
        let inp_price = if normalized { pw } else { pi };
        let out = g(&["output_tokens", "completion_tokens"]);
        self.total += (inp * inp_price + out * po + cr * pr + cw * pw * self.write_mult) / 1e6;
    }
}

/// `ucli_cost.credit_window`: `end_of_day_ms` = `_date_ms(gün, end=True)` (bozuksa 0).
pub fn credit_window(
    cfg: &UcliCostConfig,
    spent: f64,
    now: f64,
    end_of_day_ms: &dyn Fn(&str) -> f64,
) -> Map<String, Value> {
    let mut out = Map::new();
    if !cfg.credit_since.is_empty() {
        out.insert("credit_since".into(), json!(cfg.credit_since));
    }
    if !cfg.credit_until.is_empty() {
        let end_ms = end_of_day_ms(&cfg.credit_until);
        if end_ms > 0.0 {
            let days = ((end_ms / 1000.0 - now) / 86400.0).max(0.0);
            out.insert("credit_until".into(), json!(cfg.credit_until));
            out.insert("days_left".into(), json!(py_round(days, 1)));
            let credit = cfg.credit_total_usd;
            if credit > 0.0 && days > 0.0 {
                let budget = (credit - spent).max(0.0) / days.max(1.0);
                out.insert("daily_budget_usd".into(), json!(py_round(budget, 2)));
            }
        }
    }
    out
}
