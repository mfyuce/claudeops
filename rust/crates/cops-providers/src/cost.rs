//! `ucli_cost.py` + `review.usage_cost_usd`in SAF yarısı: fiyat tablosu, kullanım günlüğü satırlarının toplanması, kredi
//! dönemi özeti, tavan reddi. Dosya, saat ve rezervasyon [`crate::real::ledger`]de.
//!
//! Fiyat tablosu ve satır kuralları tek kaynaktan: `cops-review-core` (`usage.rs`). Oradaki `usage_cost_usd` yalnız
//! toplamı verir; buradaki [`UsageScan`] aynı satır değerlendirmesinden toplamın güvenilirliğini (`problem`) de bildirir.

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

/// Fiyat tablosu ve `review.anthropic_price` tek kaynaktan (`cops-review-core`); burada ikinci kopya YOK.
pub use cops_review_core::report::anthropic_price;
/// Tek istek sayacının üst sınırı (üstü bozuk kayıt).
pub use cops_review_core::usage::MAX_USAGE_TOKENS;
use cops_review_core::usage::{self, Line};

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
    /// Atlanan bozuk kayıtların türü (`usage.record`, `usage.depth`, `usage.number`, `usage.length`), görülme
    /// sırasıyla.
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

    /// Pencerenin başı (epoch ms; 0 = süzme yok).
    pub(crate) fn since_ms(&self) -> f64 {
        self.since_ms
    }

    /// Tek satır (satır sonu olsa da olur). Ayrıştırılamayan (yarım yazılmış) satır atlanır.
    pub fn feed(&mut self, line: &str) {
        UsageScan::feed_all(std::slice::from_mut(self), line)
    }

    /// Satırı BİR kez ayrıştırıp yalnız zaman penceresi (`since_ms`) farklı toplayıcılara besler; her birinin sonucu tek
    /// başına [`UsageScan::feed`] ile aynıdır. Model ve yazma çarpanı hepsinde aynı olmalı.
    pub(crate) fn feed_all(scans: &mut [UsageScan], line: &str) {
        let Some(fixed_model) = scans.first().map(|s| s.fixed_model) else {
            return;
        };
        UsageScan::apply(scans, usage::read_line(line, !fixed_model));
    }

    /// Anlamı bilinen satırı (ya da okunmadan atlananı, [`usage::too_long`]) toplayıcılara işler.
    pub(crate) fn apply(scans: &mut [UsageScan], line: Line) {
        let Some((price, write_mult)) = scans.first().map(|s| (s.price, s.write_mult)) else {
            return;
        };
        match line {
            Line::Ignored => {}
            // sayılamayan kayıt sessizce 0 olmasın: pencere bilinmediği için hepsi güvenilmez
            Line::Uncountable { problem, kind } => {
                for scan in scans {
                    scan.problem = Some(problem);
                    scan.skipped.push(kind);
                }
            }
            Line::Model(price) => {
                for scan in scans {
                    scan.price = price;
                }
            }
            Line::Record(record) => UsageScan::add(scans, &record, price, write_mult),
        }
    }

    /// Ayrıştırılmış kaydı onu sayan pencerelere işler.
    fn add(scans: &mut [UsageScan], record: &usage::Record, price: [f64; 4], write_mult: f64) {
        if record.bad_time {
            for scan in scans.iter_mut() {
                scan.problem = Some("geçersiz zaman damgası");
            }
        }
        let t = record.time;
        if !t.is_finite() {
            // sonlu olmayan damgalı kayıt toplama girmez (TBD#375)
            for scan in scans {
                scan.skipped.push("usage.record");
            }
            return;
        }
        // kaydı sayan pencereler
        let counts = |s: &UsageScan| !(s.since_ms != 0.0 && t < s.since_ms);
        if !scans.iter().any(counts) {
            return;
        }
        let Some(charge) = record.charge(price, write_mult) else {
            return;
        };
        for scan in scans.iter_mut().filter(|s| counts(s)) {
            if charge.bad_count {
                scan.problem = Some("geçersiz sayaç");
            }
            match charge.usd {
                Some(usd) => scan.total += usd,
                // sonlu olmayan sayaçlı istek bütünüyle atlanır
                None => scan.skipped.push("usage.record"),
            }
        }
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
