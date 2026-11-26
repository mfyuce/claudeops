//! Maliyet defteri (`ucli_cost.py`): oturum başına `--usage-log` dosyalarının taranması, günlük tavan ve başlatma payı.
//!
//! **Defterin yazarı claudeops DEĞİL**: dosyalara yalnız `ucli` ekler (satır satır), iki dil de yalnız OKUR. Bu yüzden
//! paylaşılan bir yazım ya da dosya kilidi yoktur; yarım yazılmış son satır atlanır. Başlatma payı (rezervasyon) Python'da
//! da burada da SÜREÇ İÇİDİR: aynı anda hem Python hem Rust süreci Claude oturumu açarsa birbirlerinin payını görmez
//! (Python'da panel ile CLI arasında da öyle). Birleşimde spawn tek süreçte kalmalı ve [`CostLedger`] süreç başına TEK
//! örnek olmalı.
//!
//! Para sınırı kapalı yöne düşer: tavan açıkken okunamayan dizin/dosya, normal olmayan dosya ya da geçersiz sayaç
//! başlatmayı reddeder; ayar belgesi okunamıyorsa tavan bilinemediğinden yine reddedilir.

use crate::cost::{
    credit_window, py_round, write_mult, CostRefusal, UsageScan, BY_SESSION_TOP, RESERVE_TTL, RESERVE_USD, TTL,
};
use crate::pyfmt::parse_int;
use crate::pyjson::Py;
use crate::real::{docs::DOC_MAX_BYTES, fsio};
use crate::settings::{Settings, UcliCostConfig};
use serde_json::{json, Map, Value};
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, Read};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

/// Tek günlük satırının sınırı (Python sınırsız); aşan satır sayılamaz (sorun).
pub const LINE_MAX_BYTES: usize = 16 << 20;

/// `time.time()`.
pub type WallClock = Arc<dyn Fn() -> f64 + Send + Sync>;
/// `ucli_cost_config()`: HER çağrıda güncel ayar. `Err` = ayar okunamadı (tavan bilinemiyor).
pub type CostSettings = Arc<dyn Fn() -> Result<UcliCostConfig, String> + Send + Sync>;

pub fn system_clock() -> WallClock {
    Arc::new(|| SystemTime::now().duration_since(UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64()))
}

/// `settings.json` dosyasından ayar: dosya yoksa varsayılan (tavan yok). Var ama okunamıyor ya da ayrıştırılamıyorsa
/// `Err` (Python varsayılana düşer, yani tavanı kapatır). `db` kipi ve birleştirme için rs/state yükleyicisi bağlanır.
pub fn file_cost_settings(path: impl Into<String>) -> CostSettings {
    let path = path.into();
    Arc::new(move || {
        match fs::metadata(&path) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Settings::default().ucli_cost_config()),
            _ => {}
        }
        let parsed = fsio::read_bytes(&path, DOC_MAX_BYTES)
            .and_then(|b| Py::parse(std::str::from_utf8(&b).ok()?))
            .ok_or_else(|| "settings.json okunamadı".to_string())?;
        Ok(Settings::from_json(&parsed.to_value().to_string()).ucli_cost_config())
    })
}

fn local_tm(now: f64) -> Option<libc::tm> {
    let secs = now.floor() as libc::time_t;
    // SAFETY: `tm` yalnız tam sayı ve işaretçi alanlıdır; sıfır geçerli başlangıçtır.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    // SAFETY: iki işaretçi de geçerli ve bu çağrıya özel; `localtime_r` yeniden girilebilir.
    (!unsafe { libc::localtime_r(&secs, &mut tm) }.is_null()).then_some(tm)
}

/// `time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))`; gösterilemeyen tarih None.
fn local_midnight(year: i64, month: i64, day: i64) -> Option<f64> {
    // SAFETY: bkz. `local_tm`.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    tm.tm_year = i32::try_from(year.checked_sub(1900)?).ok()?;
    tm.tm_mon = i32::try_from(month.checked_sub(1)?).ok()?;
    tm.tm_mday = i32::try_from(day).ok()?;
    tm.tm_isdst = -1;
    tm.tm_wday = -1;
    // SAFETY: geçerli, bu çağrıya özel yapı.
    let t = unsafe { libc::mktime(&mut tm) };
    (t != -1 || tm.tm_wday != -1).then_some(t as f64)
}

/// `_day_start_ms`: yerel gün başı (epoch ms).
pub fn day_start_ms(now: f64) -> f64 {
    local_tm(now)
        .and_then(|t| local_midnight(i64::from(t.tm_year) + 1900, i64::from(t.tm_mon) + 1, i64::from(t.tm_mday)))
        .map_or(0.0, |s| s * 1000.0)
}

/// `time.strftime("%Y-%m-%d", time.localtime(now))`.
fn day_key(now: f64) -> String {
    local_tm(now)
        .map(|t| format!("{:04}-{:02}-{:02}", i64::from(t.tm_year) + 1900, t.tm_mon + 1, t.tm_mday))
        .unwrap_or_default()
}

/// `_date_ms`: `YYYY-MM-DD` -> yerel gün başı (`end`: ertesi gün başı) epoch ms; bozuksa 0.
pub fn date_ms(day: &str, end: bool) -> f64 {
    let parts: Vec<Option<i64>> = day.split('-').map(parse_int).collect();
    let [Some(y), Some(m), Some(d)] = parts.as_slice() else { return 0.0 };
    local_midnight(*y, *m, *d).map_or(0.0, |t| (t + if end { 86400.0 } else { 0.0 }) * 1000.0)
}

/// `review._scan_usage(path, ..)`: dosyayı satır satır toplar (evrensel satır sonu, bozuk bayt U+FFFD). Olmayan dosya
/// sorunsuz 0. FIFO/aygıt açılışta bloklamaz.
pub fn scan_usage(path: impl AsRef<Path>, model: &str, since_ms: f64, mult: f64) -> UsageScan {
    let mut scan = UsageScan::new(model, since_ms, mult);
    let opened = OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY).open(path);
    let file = match opened {
        Ok(f) => f,
        Err(e) => {
            if e.kind() != io::ErrorKind::NotFound {
                scan.problem = Some("okunamadı");
            }
            return scan;
        }
    };
    match file.metadata() {
        Ok(m) if m.is_file() => {}
        Ok(_) => {
            scan.problem = Some("normal dosya değil");
            return scan;
        }
        Err(_) => {
            scan.problem = Some("okunamadı");
            return scan;
        }
    }
    let mut reader = BufReader::new(file);
    let mut line = Vec::new();
    loop {
        line.clear();
        let read = (&mut reader).take(LINE_MAX_BYTES as u64 + 1).read_until(b'\n', &mut line);
        match read {
            Ok(0) => break,
            Ok(_) => {}
            Err(_) => {
                scan.problem = Some("okunamadı");
                break;
            }
        }
        if line.len() > LINE_MAX_BYTES && !line.ends_with(b"\n") {
            scan.problem = Some("çok uzun satır");
            if reader.skip_until(b'\n').is_err() {
                break;
            }
            continue;
        }
        for part in line.split(|b| *b == b'\r') {
            if !part.is_empty() {
                scan.feed(&String::from_utf8_lossy(part));
            }
        }
    }
    scan
}

/// Bir kullanım günlüğü adayı. `stem` gösterim içindir; yol dosya adının ham baytlarını taşır (UTF-8 olmayan adlı
/// dosya sayımdan düşmesin).
struct Log {
    stem: String,
    path: PathBuf,
}

/// `.jsonl` adlı girdiler, okuma sırasıyla (`os.listdir`).
fn entries(base: &str) -> io::Result<Vec<Log>> {
    let mut out = Vec::new();
    for entry in fs::read_dir(base)? {
        let entry = entry?;
        let name = entry.file_name();
        if let Some(stem) = name.to_string_lossy().strip_suffix(".jsonl") {
            out.push(Log { stem: stem.to_string(), path: entry.path() });
        }
    }
    Ok(out)
}

/// `os.path.getmtime(p) * 1000.0`.
fn mtime_ms(path: &Path) -> io::Result<f64> {
    let m = fs::metadata(path)?;
    Ok((m.mtime() as f64 + m.mtime_nsec() as f64 * 1e-9) * 1000.0)
}

/// Günlükler; `since_ms` verilirse son yazımı ondan eski ya da `stat`ı alınamayan atlanır. Okunamayan dizin boş.
fn logs(base: &str, since_ms: Option<f64>) -> Vec<Log> {
    let mut all = entries(base).unwrap_or_default();
    if let Some(since) = since_ms {
        all.retain(|l| mtime_ms(&l.path).is_ok_and(|t| t >= since));
    }
    all
}

/// `per_session_usd`: bugünkü $, oturum başına.
pub fn per_session_usd(now: f64, base: &str, mult: f64) -> Vec<(String, f64)> {
    let since = day_start_ms(now);
    logs(base, Some(since)).into_iter().map(|l| (l.stem, scan_usage(&l.path, "", since, mult).total)).collect()
}

/// `today_usd`.
pub fn today_usd(now: f64, base: &str, mult: f64) -> f64 {
    per_session_usd(now, base, mult).iter().fold(0.0, |a, (_, v)| a + v)
}

/// `rate_by_session`: son `window_min` dakikanın hızı (USD/saat), yalnız > 0 olanlar.
pub fn rate_by_session(now: f64, window_min: f64, base: &str, mult: f64) -> Vec<(String, f64)> {
    if window_min <= 0.0 {
        return Vec::new();
    }
    let since = now * 1000.0 - window_min * 60_000.0;
    logs(base, Some(since))
        .into_iter()
        .filter_map(|l| {
            let usd = scan_usage(&l.path, "", since, mult).total;
            (usd > 0.0).then(|| (l.stem, usd * 60.0 / window_min))
        })
        .collect()
}

/// `rate_usd_per_hour`.
pub fn rate_usd_per_hour(now: f64, window_min: f64, base: &str, mult: f64) -> f64 {
    rate_by_session(now, window_min, base, mult).iter().fold(0.0, |a, (_, v)| a + v)
}

/// `total_usd`: birikmiş toplam; `since_ms` > 0 ise yalnız o andan sonrası.
pub fn total_usd(base: &str, mult: f64, since_ms: f64) -> f64 {
    let filter = (since_ms > 0.0).then_some(since_ms);
    logs(base, filter).into_iter().fold(0.0, |a, l| a + scan_usage(&l.path, "", since_ms, mult).total)
}

/// `_ledger_problem`: bugünün harcaması sayılamıyorsa nedeni (yalnız dosya adı; içerik yok).
pub fn ledger_problem(now: f64, base: &str, mult: f64) -> Option<String> {
    let since = day_start_ms(now);
    let all = match entries(base) {
        Ok(n) => n,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return None,
        Err(_) => return Some("günlük dizini okunamadı".into()),
    };
    for log in all {
        let why = match mtime_ms(&log.path) {
            Ok(t) if t < since => continue,
            Ok(_) => scan_usage(&log.path, "", since, mult).problem,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(_) => Some("okunamadı"),
        };
        if let Some(why) = why {
            return Some(format!("{}.jsonl: {why}", log.stem));
        }
    }
    None
}

/// Bir taramanın sonucu (`_CACHE`).
#[derive(Debug, Clone, Default)]
struct Snapshot {
    at: f64,
    day: String,
    usd: f64,
    total: f64,
    by: Vec<(String, f64)>,
    rate_1h: Vec<(String, f64)>,
    rate_15m: Vec<(String, f64)>,
}

/// `sum(dict.values())` -> `round(.., 4)`: boş sözlükte Python tam sayı 0 döner.
fn rounded_sum(rates: &[(String, f64)]) -> Value {
    if rates.is_empty() {
        json!(0)
    } else {
        json!(py_round(rates.iter().fold(0.0, |a, (_, v)| a + v), 4))
    }
}

/// `ucli_cost` modül durumu: önbellek (`_CACHE`) + başlatma payları (`_RESERVED`, `_RESERVE_LOCK`).
pub struct CostLedger {
    base: String,
    settings: CostSettings,
    clock: WallClock,
    cache: Mutex<Option<Snapshot>>,
    /// oturum -> (usd, bitiş anı)
    reserved: Mutex<Vec<(String, f64, f64)>>,
}

impl CostLedger {
    /// `base` = [`crate::Paths::ucli_usage_dir`].
    pub fn new(base: impl Into<String>, settings: CostSettings) -> CostLedger {
        CostLedger {
            base: base.into(),
            settings,
            clock: system_clock(),
            cache: Mutex::new(None),
            reserved: Mutex::new(Vec::new()),
        }
    }

    pub fn with_clock(mut self, clock: WallClock) -> CostLedger {
        self.clock = clock;
        self
    }

    /// `state`: panel özeti. Ayar okunamıyorsa varsayılanla gösterilir (kapı ayrıca reddeder).
    pub fn state(&self, now: f64, use_cache: bool) -> Value {
        let cfg = (self.settings)().unwrap_or_else(|_| Settings::default().ucli_cost_config());
        self.state_with(&cfg, now, use_cache)
    }

    fn state_with(&self, cfg: &UcliCostConfig, now: f64, use_cache: bool) -> Value {
        let cached = self.cache.lock().unwrap_or_else(PoisonError::into_inner).clone();
        let snap = match cached.filter(|s| use_cache && now - s.at <= TTL && s.day == day_key(now)) {
            Some(s) => s,
            None => {
                let mult = write_mult(cfg);
                let by = per_session_usd(now, &self.base, mult);
                let fresh = Snapshot {
                    at: now,
                    day: day_key(now),
                    total: total_usd(&self.base, mult, date_ms(&cfg.credit_since, false)),
                    usd: by.iter().fold(0.0, |a, (_, v)| a + v),
                    by,
                    rate_1h: rate_by_session(now, 60.0, &self.base, mult),
                    rate_15m: rate_by_session(now, 15.0, &self.base, mult),
                };
                *self.cache.lock().unwrap_or_else(PoisonError::into_inner) = Some(fresh.clone());
                fresh
            }
        };
        let (cap, usd) = (cfg.daily_cap_usd, snap.usd);
        let mut top = snap.by.clone();
        top.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        top.truncate(BY_SESSION_TOP);
        let by_session: Vec<Value> = top
            .iter()
            .filter(|(_, v)| *v > 0.0)
            .map(|(n, v)| json!({"session": n, "usd": py_round(*v, 4)}))
            .collect();
        let mut out = Map::new();
        let mut put = |k: &str, v: Value| out.insert(k.to_string(), v);
        put("today_usd", json!(py_round(usd, 4)));
        put("cap_usd", json!(cap));
        put("pct", if cap > 0.0 { json!(py_round(100.0 * usd / cap, 1)) } else { Value::Null });
        put("cache_ttl", json!(cfg.cache_ttl));
        put("by_session", Value::Array(by_session));
        put("rate_1h_usd", rounded_sum(&snap.rate_1h));
        put("rate_15m_usd", rounded_sum(&snap.rate_15m));
        let credit = cfg.credit_total_usd;
        if credit > 0.0 {
            let spent = snap.total;
            put("credit_total_usd", json!(credit));
            put("spent_total_usd", json!(py_round(spent, 4)));
            put("credit_left_usd", json!(py_round((credit - spent).max(0.0), 4)));
            out.extend(credit_window(cfg, spent, now, &|d| date_ms(d, true)));
        }
        for (k, v) in [("credit_since", &cfg.credit_since), ("credit_until", &cfg.credit_until)] {
            if !v.is_empty() {
                out.insert(k.to_string(), json!(v));
            }
        }
        Value::Object(out)
    }

    /// `invalidate` (ayar kaydedilince).
    pub fn invalidate(&self) {
        *self.cache.lock().unwrap_or_else(PoisonError::into_inner) = None;
    }

    fn config(&self) -> Result<UcliCostConfig, CostRefusal> {
        (self.settings)().map_err(CostRefusal::Unverifiable)
    }

    /// (yuvarlanmış bugünkü harcama, tavan) — taze tarama.
    fn fresh_totals(&self, cfg: &UcliCostConfig, now: f64) -> (f64, f64) {
        let state = self.state_with(cfg, now, false);
        // sonlu olmayan sayı JSON'a giremez (`null`): sayaçlar sınırlı olduğundan beklenmez, olursa kapalı yön
        (state.get("today_usd").and_then(Value::as_f64).unwrap_or(f64::INFINITY), cfg.daily_cap_usd)
    }

    /// `cap_exceeded`. Ayar okunamıyorsa hata.
    pub fn cap_exceeded(&self, now: f64) -> Result<bool, CostRefusal> {
        let cfg = self.config()?;
        let (usd, cap) = self.fresh_totals(&cfg, now);
        Ok(cap > 0.0 && usd >= cap)
    }

    /// `reserve`: başlatma payı ayır. Tavan (bugün + başkalarının payı) doluysa ya da harcama sayılamıyorsa ret.
    pub fn reserve(&self, session: &str, now: f64) -> Result<(), CostRefusal> {
        let mut held = self.reserved.lock().unwrap_or_else(PoisonError::into_inner);
        held.retain(|(_, _, until)| *until > now);
        let cfg = self.config()?;
        let (usd, cap) = self.fresh_totals(&cfg, now);
        if cap <= 0.0 {
            held.retain(|(n, _, _)| n != session);
            return Ok(());
        }
        if let Some(why) = ledger_problem(now, &self.base, write_mult(&cfg)) {
            return Err(CostRefusal::Unverifiable(why));
        }
        let others = held.iter().filter(|(n, _, _)| n != session).fold(0.0, |a, (_, u, _)| a + u);
        if usd + others >= cap {
            return Err(CostRefusal::CapExceeded { today_usd: usd + others, cap_usd: cap });
        }
        let share = (session.to_string(), RESERVE_USD, now + RESERVE_TTL);
        match held.iter_mut().find(|(n, _, _)| n == session) {
            Some(slot) => *slot = share,
            None => held.push(share),
        }
        Ok(())
    }

    /// `release`: başlatma başarısız oldu, payı hemen geri ver.
    pub fn release(&self, session: &str) {
        self.reserved.lock().unwrap_or_else(PoisonError::into_inner).retain(|(n, _, _)| n != session);
    }

    /// Payı duran oturumlar (süre dolumu uygulanmadan).
    pub fn reserved_sessions(&self) -> Vec<String> {
        self.reserved.lock().unwrap_or_else(PoisonError::into_inner).iter().map(|(n, _, _)| n.clone()).collect()
    }

    /// `_claude_service_flags`in kapısı: `cap_exceeded` + `reserve`.
    pub fn check_and_reserve_at(&self, session: &str, now: f64) -> Result<(), CostRefusal> {
        let cfg = self.config()?;
        let (usd, cap) = self.fresh_totals(&cfg, now);
        if cap > 0.0 && usd >= cap {
            return Err(CostRefusal::CapExceeded { today_usd: usd, cap_usd: cap });
        }
        self.reserve(session, now)
    }
}

impl crate::real::probe::CostGate for CostLedger {
    fn check_and_reserve(&self, session: &str) -> Result<(), CostRefusal> {
        self.check_and_reserve_at(session, (self.clock)())
    }

    fn release(&self, session: &str) {
        CostLedger::release(self, session)
    }
}
