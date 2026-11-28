//! Kullanım/maliyet/sağlık özetleri ve rapor nitelik denetimleri.
use crate::badrec;
use crate::error::Result;
use crate::py::{self, S};
use crate::store::round_to;
use crate::targets::{ci, ANTHROPIC_PRICES};
use crate::usage::{self, Line, Raw};
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::ffi::OsStr;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::sync::LazyLock;

pub const HEALTH_DAYS: f64 = 7.0;
pub const HEALTH_MIN_RUNS: i64 = 5;
pub const HEALTH_MAX_RATE: f64 = 0.25;

/// `os.walk` (yukarıdan aşağı, bağlantı dizinlerine girmez): `(dizin, dosya adları)`; okunamayan dizin atlanır.
pub(crate) fn walk(root: &str, visit: &mut dyn FnMut(&str, &[String]) -> Result<()>) -> Result<()> {
    let mut stack = vec![root.to_string()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&dir) else {
            continue;
        };
        let (mut files, mut dirs) = (Vec::new(), Vec::new());
        for e in rd {
            let Ok(e) = e else { break };
            let name = e.file_name().to_string_lossy().into_owned();
            let path = e.path();
            if path.is_dir() {
                if !e.file_type().is_ok_and(|t| t.is_symlink()) {
                    dirs.push(py::path_join(&dir, &[&name]));
                }
            } else {
                files.push(name);
            }
        }
        visit(&dir, &files)?;
        stack.extend(dirs.into_iter().rev());
    }
    Ok(())
}

/// Metin kipi satırları (`\n`, `\r\n`, `\r`).
fn text_lines(s: &str) -> impl Iterator<Item = &str> {
    s.split('\n')
        .flat_map(|l| l.strip_suffix('\r').unwrap_or(l).split('\r'))
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct UsageRow {
    pub project: String,
    pub target: String,
    pub runs: i64,
    pub requests: i64,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub reasoning_tokens: i64,
    pub cached_tokens: i64,
    pub total_tokens: i64,
    pub seconds: f64,
}

impl UsageRow {
    pub fn to_json(&self) -> Json {
        let mut m = Map::new();
        m.insert("project".into(), self.project.as_str().into());
        m.insert("target".into(), self.target.as_str().into());
        for (k, v) in [
            ("runs", self.runs),
            ("requests", self.requests),
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("reasoning_tokens", self.reasoning_tokens),
            ("cached_tokens", self.cached_tokens),
            ("total_tokens", self.total_tokens),
        ] {
            m.insert(k.into(), Json::Int(v));
        }
        m.insert("seconds".into(), Json::Float(self.seconds));
        Json::Object(m)
    }
}

/// Python `usage_summary` iç döngüsü: tek kullanım satırını `a`ya ekler.
fn add_usage_line(a: &mut UsageRow, line: &str, path: &str) {
    let Ok(Json::Object(e)) = Json::parse(line) else {
        return;
    };
    if !py::is_str(e.get("event"), "request") {
        return;
    }
    let usage = e.get("usage").and_then(Json::as_object);
    let Some(sec) = badrec::field(&e, "seconds", "usage.record", path) else {
        return;
    };
    let non_finite = |v: &Json| matches!(v, Json::Float(f) if !f.is_finite());
    if usage.is_some_and(|u| u.values().any(non_finite)) {
        badrec::log_bad("usage.record", path);
        return;
    }
    a.requests += 1;
    a.seconds += sec;
    let Some(u) = usage else { return };
    for (key, slot) in [
        ("prompt_tokens", &mut a.prompt_tokens),
        ("completion_tokens", &mut a.completion_tokens),
        ("reasoning_tokens", &mut a.reasoning_tokens),
        ("cached_tokens", &mut a.cached_tokens),
        ("total_tokens", &mut a.total_tokens),
    ] {
        let n = match u.get(key) {
            Some(Json::Int(i)) => *i,
            Some(Json::Float(f)) => f.trunc() as i64,
            // Python keyfi büyüklükte toplar; burada sınıra kırpılır.
            Some(Json::BigInt(s)) if s.starts_with('-') => i64::MIN,
            Some(Json::BigInt(_)) => i64::MAX,
            _ => continue,
        };
        *slot = slot.saturating_add(n);
    }
}

/// `<ts>.usage.jsonl` dosyalarını (proje, mod/model) başına toplar.
pub fn usage_summary(reviews_root: &str, project: &str) -> Result<Vec<UsageRow>> {
    let root = py::abspath(reviews_root);
    let mut index: HashMap<(String, String), usize> = HashMap::new();
    let mut rows: Vec<UsageRow> = Vec::new();
    walk(&root, &mut |dir, files| {
        for name in files {
            if !name.ends_with(".usage.jsonl") {
                continue;
            }
            let path = py::path_join(dir, &[name]);
            let rel = py::relpath(&path, &root);
            let parts: Vec<&str> = rel.split('/').collect();
            if parts.len() < 4 {
                continue;
            }
            let (proj, tgt) = (parts[0].to_string(), format!("{}/{}", parts[1], parts[2]));
            if !project.is_empty() && proj != project {
                continue;
            }
            let i = *index.entry((proj.clone(), tgt.clone())).or_insert_with(|| {
                rows.push(UsageRow {
                    project: proj,
                    target: tgt,
                    ..Default::default()
                });
                rows.len() - 1
            });
            let a = &mut rows[i];
            // Python `_open_regular_rb`: yalnız normal dosya, FIFO açılışta bloklamaz (koşu sayılmaz)
            let Ok(file) = open_regular_nonblocking(Path::new(&path)) else {
                continue;
            };
            a.runs += 1;
            let mut reader = io::BufReader::new(file);
            let mut raw = Vec::new();
            loop {
                match usage::next_line(&mut reader, &mut raw) {
                    // yarıda okuma hatası: kalan satırlar atlanır, sayılanlar kalır (Python `except OSError`)
                    Ok(Raw::End) | Err(_) => break,
                    Ok(Raw::TooLong) => {
                        badrec::log_bad("usage.length", &path);
                        continue;
                    }
                    Ok(Raw::Line) => {}
                }
                let text = String::from_utf8_lossy(&raw);
                for line in text_lines(text.strip_suffix('\n').unwrap_or(&text)) {
                    if usage::too_deep(line) {
                        badrec::log_bad("usage.depth", &path);
                        continue;
                    }
                    add_usage_line(a, line, &path);
                }
            }
        }
        Ok(())
    })?;
    let weight = |r: &UsageRow| {
        if r.prompt_tokens != 0 {
            r.prompt_tokens
        } else {
            r.total_tokens
        }
    };
    rows.sort_by(|a, b| {
        weight(b)
            .cmp(&weight(a))
            .then_with(|| a.project.cmp(&b.project))
            .then_with(|| a.target.cmp(&b.target))
    });
    Ok(rows)
}

#[derive(Debug, Clone, PartialEq)]
pub struct HealthRow {
    pub target: String,
    pub runs: i64,
    pub ok: i64,
    pub error: i64,
    pub rate: f64,
    pub candidate: bool,
}

impl HealthRow {
    pub fn to_json(&self) -> Json {
        let mut m = Map::new();
        m.insert("target".into(), self.target.as_str().into());
        m.insert("runs".into(), Json::Int(self.runs));
        m.insert("ok".into(), Json::Int(self.ok));
        m.insert("error".into(), Json::Int(self.error));
        m.insert("rate".into(), Json::Float(self.rate));
        m.insert("candidate".into(), Json::Bool(self.candidate));
        Json::Object(m)
    }
}

/// `runs` kayıtlarından `|` içeren çift anahtarı olanlar: (kayıt, proje, hedef).
fn run_records(history: &Json) -> impl Iterator<Item = (&Map, String, String)> {
    history
        .get("runs")
        .and_then(Json::as_array)
        .unwrap_or(&[])
        .iter()
        .filter_map(|r| {
            let r = r.as_object()?;
            let pair = py::str_or_empty(r.get("pair"));
            let (p, t) = pair.split_once('|')?;
            Some((r, p.to_string(), t.to_string()))
        })
}

/// Son `days` günde (mod/model) başına başarı oranı; en kötü oran önce.
pub fn model_health(
    history: &Json,
    now: f64,
    days: f64,
    min_runs: i64,
    max_rate: f64,
) -> Vec<HealthRow> {
    let cutoff = now - days * 86400.0;
    let mut agg: Vec<HealthRow> = Vec::new();
    for (r, _, target) in run_records(history) {
        let status = r
            .get("status")
            .map_or_else(|| "None".to_string(), py::to_str);
        if py::num(r.get("at")) < cutoff || status == "limit" {
            continue;
        }
        let i = match agg.iter().position(|a| a.target == target) {
            Some(i) => i,
            None => {
                agg.push(HealthRow {
                    target,
                    runs: 0,
                    ok: 0,
                    error: 0,
                    rate: 0.0,
                    candidate: false,
                });
                agg.len() - 1
            }
        };
        let a = &mut agg[i];
        a.runs += 1;
        if status == "done" || status == "partial" {
            a.ok += 1;
        } else {
            a.error += 1;
        }
    }
    for a in &mut agg {
        a.rate = if a.runs != 0 {
            round_to(a.ok as f64 / a.runs as f64, 3)
        } else {
            0.0
        };
        a.candidate = a.runs >= min_runs && a.rate <= max_rate;
    }
    agg.sort_by(|a, b| {
        a.rate
            .partial_cmp(&b.rate)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(b.runs.cmp(&a.runs))
            .then_with(|| a.target.cmp(&b.target))
    });
    agg
}

/// Haftalık özet metni; aday yoksa "".
pub fn health_digest(rows: &[HealthRow], excluded: &[String], days: f64, lang: &str) -> String {
    let skip: HashSet<&str> = excluded.iter().map(String::as_str).collect();
    let cands: Vec<&HealthRow> = rows
        .iter()
        .filter(|r| r.candidate && !skip.contains(r.target.as_str()))
        .collect();
    if cands.is_empty() {
        return String::new();
    }
    let d = crate::limits::fmt_g(days);
    let tr = lang == "tr";
    let mut lines = vec![if tr {
        format!("Reviewer: son {d} günde başarısız model/mod adayları (sahip onaylarsa havuzdan çıkar; `limit` koşuları sayılmaz):")
    } else {
        format!("Reviewer: low-success model/mode candidates over the last {d} days (excluded on owner approval; `limit` runs not counted):")
    }];
    for r in cands {
        let pct = (100.0 * r.rate).round_ties_even() as i64;
        lines.push(format!(
            "- {}: {}/{} başarılı (%{pct})",
            r.target, r.ok, r.runs
        ));
    }
    lines.push(
        if tr {
            "Çıkarmak için: `py/cops steward -s reviewer review exclude <mod/model>`"
        } else {
            "To exclude: `py/cops steward -s reviewer review exclude <mode/model>`"
        }
        .to_string(),
    );
    lines.join("\n")
}

#[derive(Debug, Clone, PartialEq)]
pub struct DurationRow {
    pub project: String,
    pub target: String,
    pub runs: i64,
    pub timed: i64,
    pub unknown: i64,
    pub seconds: f64,
}

impl DurationRow {
    pub fn to_json(&self) -> Json {
        let mut m = Map::new();
        m.insert("project".into(), self.project.as_str().into());
        m.insert("target".into(), self.target.as_str().into());
        m.insert("runs".into(), Json::Int(self.runs));
        m.insert("timed".into(), Json::Int(self.timed));
        m.insert("unknown".into(), Json::Int(self.unknown));
        m.insert("seconds".into(), Json::Float(self.seconds));
        Json::Object(m)
    }
}

/// (proje, mod/model) başına koşu sayısı ve duvar süresi; en çok süre önce.
pub fn duration_summary(history: &Json, project: &str) -> Vec<DurationRow> {
    let mut agg: BTreeMap<(String, String), DurationRow> = BTreeMap::new();
    for (r, proj, tgt) in run_records(history) {
        if !project.is_empty() && proj != project {
            continue;
        }
        let a = agg
            .entry((proj.clone(), tgt.clone()))
            .or_insert_with(|| DurationRow {
                project: proj,
                target: tgt,
                runs: 0,
                timed: 0,
                unknown: 0,
                seconds: 0.0,
            });
        a.runs += 1;
        let seconds = match r.get("seconds") {
            Some(Json::Int(_) | Json::Float(_) | Json::BigInt(_)) => {
                badrec::field(r, "seconds", "runs", &py::str_or_empty(r.get("pair")))
            }
            _ => None,
        };
        match seconds {
            Some(s) if s >= 0.0 => {
                a.timed += 1;
                a.seconds += s;
            }
            _ => a.unknown += 1,
        }
    }
    let mut out: Vec<DurationRow> = agg.into_values().collect();
    out.sort_by(|a, b| {
        b.seconds
            .partial_cmp(&a.seconds)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.project.cmp(&b.project))
            .then_with(|| a.target.cmp(&b.target))
    });
    out
}

static HAS_FINDING: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!(r"(?m)^#{{2,4}}[{S}]*R-\d+[{S}]*\|")).unwrap());

/// Rapor "tamamlanmadı" diyor ve hiç bulgu başlığı yok: `partial` sayılır.
pub fn report_incomplete(text: &str) -> bool {
    static INCOMPLETE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(
            r"(?i)tool[- ]call budget (?:was )?exhausted|budget exhausted|araç (?:çağrisi )?bütçesi[{S}]+(?:\(\d+ çağri\)[{S}]+)?tükendi|inceleme(?:nin)? (?:durumu: )?tamamlanmadi"
        ))
        .unwrap()
    });
    INCOMPLETE.is_match(&ci(text)) && !HAS_FINDING.is_match(text)
}

/// Bulgu başlığı var ama gövdede içerik yok.
pub fn report_bodyless(text: &str) -> bool {
    if !HAS_FINDING.is_match(text) {
        return false;
    }
    let body: String = py::splitlines(text)
        .into_iter()
        .filter(|l| !py::lstrip(l).starts_with('#'))
        .collect();
    let chars: Vec<char> = py::casefold(&body)
        .chars()
        .filter(|c| c.is_alphanumeric())
        .collect();
    chars.is_empty() || (chars.len() >= 3 && chars.iter().all(|c| *c == chars[0]))
}

/// $/1M token fiyatı; bilinmeyen model en pahalı varsayım.
pub fn anthropic_price(model: &str) -> [f64; 4] {
    ANTHROPIC_PRICES
        .iter()
        .find(|(k, _)| model.contains(k))
        .map_or_else(|| ANTHROPIC_PRICES[2].1, |(_, v)| *v)
}

/// Python `_scan_usage_windows` açılışı: `O_NONBLOCK` (FIFO açılışta bloklamaz). Olmayan dosya `Err(None)` (sorun
/// değil); açılamayan ya da normal olmayan dosya `Err(Some(neden))`.
fn open_regular_nonblocking(
    path: &Path,
) -> std::result::Result<std::fs::File, Option<&'static str>> {
    use std::os::unix::fs::OpenOptionsExt;
    let f = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)
        .map_err(|e| (e.kind() != io::ErrorKind::NotFound).then_some(UNREADABLE))?;
    match f.metadata() {
        Ok(m) if m.is_file() => Ok(f),
        Ok(_) => Err(Some(NOT_REGULAR)),
        Err(_) => Err(Some(UNREADABLE)),
    }
}

const UNREADABLE: &str = "okunamadı";
const NOT_REGULAR: &str = "normal dosya değil";
const UNLISTED: &str = "dizin okunamadı";

/// Harcama sayılamıyorken [`anthropic_spent_usd`]in döndürdüğü değer (Python `_UNCOUNTABLE_SPENT_USD`).
pub const UNCOUNTABLE_SPENT_USD: f64 = 1e18;

/// Bir `.usage.jsonl` dosyasının $ maliyeti. `model` boşsa kayıttan izlenir; `since_ms > 0` yalnız sonrası. Toplamın
/// güvenilirliğini bildirmez.
pub fn usage_cost_usd(path: &str, model: &str, since_ms: f64, write_mult: f64) -> Result<f64> {
    Ok(scan_report(Path::new(path), model, since_ms, write_mult).0)
}

/// (toplam, sorun). `sorun` doluysa toplama güvenilmez (Python `_scan_usage`ın ikinci dönüşü; neden listesi aynı).
fn scan_report(
    path: &Path,
    model: &str,
    since_ms: f64,
    write_mult: f64,
) -> (f64, Option<&'static str>) {
    let file = match open_regular_nonblocking(path) {
        Ok(file) => file,
        Err(why) => return (0.0, why),
    };
    let key = path.to_string_lossy();
    scan_lines(
        &mut io::BufReader::new(file),
        &key,
        model,
        since_ms,
        write_mult,
    )
}

/// [`scan_report`]ın satır döngüsü (açılmış dosya).
fn scan_lines(
    reader: &mut impl io::BufRead,
    path: &str,
    model: &str,
    since_ms: f64,
    write_mult: f64,
) -> (f64, Option<&'static str>) {
    let mut price = anthropic_price(if model.is_empty() { "opus-5-5" } else { model });
    let mut total = 0.0;
    let mut problem = None;
    let mut raw = Vec::new();
    loop {
        let read = match usage::next_line(reader, &mut raw) {
            Ok(Raw::End) => break,
            Ok(Raw::TooLong) => usage::too_long(),
            Ok(Raw::Line) => {
                let Ok(line) = std::str::from_utf8(raw.strip_suffix(b"\n").unwrap_or(&raw)) else {
                    badrec::log_bad("usage.line", path); // yalnız bozuk satır atlanır; kalan istekler maliyete girer
                    continue;
                };
                usage::read_line(line, model.is_empty())
            }
            Err(_) => {
                // yarıda okunamadı: sayılanlar kalır, toplam güvenilmez (Python ve `cops-providers` ledger ile aynı)
                problem = Some(UNREADABLE);
                break;
            }
        };
        let record = match read {
            Line::Ignored => continue,
            Line::Uncountable { problem: why, kind } => {
                problem = Some(why);
                badrec::log_bad(kind, path);
                continue;
            }
            Line::Model(found) => {
                price = found;
                continue;
            }
            Line::Record(record) => record,
        };
        if record.bad_time {
            problem = Some("geçersiz zaman damgası");
        }
        if !record.time.is_finite() {
            badrec::log_bad("usage.record", path);
            continue;
        }
        if since_ms != 0.0 && record.time < since_ms {
            continue;
        }
        let Some(charge) = record.charge(price, write_mult) else {
            continue;
        };
        if charge.bad_count {
            problem = Some("geçersiz sayaç");
        }
        match charge.usd {
            Some(usd) => total += usd,
            None => badrec::log_bad("usage.record", path),
        }
    }
    (total, problem)
}

/// `ENOENT`.
fn absent(e: &io::Error) -> bool {
    e.kind() == io::ErrorKind::NotFound
}

/// Python `_anthropic_spend`: tüm `anthropic` koşularının (toplam $, sorun). `sorun` doluysa harcama SAYILAMIYOR
/// (`<köke göre yol>: <neden>`, ilk görülen): günlük dolar tavanıyla aynı kural (listelenemeyen dizin, okunamayan ya da
/// normal olmayan dosya, satır sorunları) + içine girilmeyen bağlantı dizini. Olmayan kök/dizin/dosya ve
/// ayrıştırılamayan satır sorun değildir. Yollar ham baytlarla gezilir (UTF-8 olmayan adlı günlük sayımdan düşmez).
pub fn anthropic_spend(reviews_root: &str) -> (f64, Option<String>) {
    let root = Path::new(if reviews_root.is_empty() {
        "."
    } else {
        reviews_root
    });
    let mut spend = Spend {
        root,
        total: 0.0,
        problem: None,
    };
    let entries = match std::fs::read_dir(root) {
        Ok(rd) => rd.collect::<io::Result<Vec<_>>>(),
        Err(e) if absent(&e) => return (0.0, None),
        Err(e) => Err(e),
    };
    let Ok(entries) = entries else {
        spend.note(root, UNLISTED);
        return (spend.total, spend.problem);
    };
    for entry in entries {
        let name = entry.file_name();
        if name.as_encoded_bytes().starts_with(b".") {
            continue;
        }
        let adir = root.join(&name).join("anthropic");
        match std::fs::symlink_metadata(&adir) {
            Ok(_) => spend.tree(&adir),
            // `anthropic` koşusu yok / kökte proje olmayan dosya
            Err(e) if absent(&e) || e.raw_os_error() == Some(libc::ENOTDIR) => {}
            Err(_) => spend.note(&adir, UNREADABLE),
        }
    }
    (spend.total, spend.problem)
}

struct Spend<'a> {
    root: &'a Path,
    total: f64,
    problem: Option<String>,
}

impl Spend<'_> {
    /// İlk görülen sorun kalır.
    fn note(&mut self, path: &Path, why: &str) {
        if self.problem.is_some() {
            return;
        }
        let rel = path.strip_prefix(self.root).unwrap_or(path);
        let rel = if rel.as_os_str().is_empty() {
            "reviews".into()
        } else {
            py_backslashed(rel.as_os_str().as_bytes())
        };
        self.problem = Some(format!("{rel}: {why}"));
    }

    /// Bir `anthropic/` ağacı (Python `os.walk`: yukarıdan aşağı, bağlantı dizinine girmez).
    fn tree(&mut self, adir: &Path) {
        let mut stack = vec![adir.to_path_buf()];
        while let Some(dir) = stack.pop() {
            let entries = match std::fs::read_dir(&dir) {
                Ok(rd) => rd.collect::<io::Result<Vec<_>>>(),
                Err(e) if absent(&e) => continue,
                Err(e) => Err(e),
            };
            let Ok(entries) = entries else {
                self.note(&dir, UNLISTED);
                continue;
            };
            // Python: önce dizinler denetlenir, sonra dosyalar okunur
            let (dirs, files): (Vec<_>, Vec<_>) =
                entries.into_iter().partition(|e| e.path().is_dir());
            let mut next = Vec::new();
            for entry in dirs {
                let path = entry.path();
                if entry.file_type().is_ok_and(|t| t.is_symlink()) {
                    self.note(&path, "bağlantı dizini sayılamıyor");
                    continue;
                }
                if is_usage_log(&entry.file_name()) {
                    self.note(&path, NOT_REGULAR);
                }
                next.push(path);
            }
            for entry in files {
                self.file(adir, &entry.path());
            }
            stack.extend(next.into_iter().rev());
        }
    }

    fn file(&mut self, adir: &Path, path: &Path) {
        if !path.file_name().is_some_and(is_usage_log) {
            // hedefine bakılamayan bağlantı bir dizin olabilir
            let looked = std::fs::symlink_metadata(path).and_then(|m| {
                if m.file_type().is_symlink() {
                    std::fs::metadata(path)?;
                }
                Ok(())
            });
            if looked.is_err_and(|e| !absent(&e) && e.raw_os_error() != Some(libc::ENOTDIR)) {
                self.note(path, UNREADABLE);
            }
            return;
        }
        let Ok(rel) = path.strip_prefix(adir) else {
            return;
        };
        let mut parts = rel.components();
        let (Some(model), Some(_)) = (parts.next(), parts.next()) else {
            return;
        };
        let (usd, why) = scan_report(path, &model.as_os_str().to_string_lossy(), 0.0, 1.0);
        self.total += usd;
        if let Some(why) = why {
            self.note(path, why);
        }
    }
}

fn is_usage_log(name: &OsStr) -> bool {
    name.as_encoded_bytes().ends_with(b".usage.jsonl")
}

/// Python `os.fsdecode(b).encode("utf-8", "backslashreplace")`: UTF-8 olmayan her bayt `\udcXX` yazılır.
fn py_backslashed(bytes: &[u8]) -> String {
    let mut out = String::new();
    for chunk in bytes.utf8_chunks() {
        out.push_str(chunk.valid());
        for b in chunk.invalid() {
            out.push_str(&format!("\\udc{b:02x}"));
        }
    }
    out
}

/// [`anthropic_spend`]in toplamı; harcama sayılamıyorsa [`UNCOUNTABLE_SPENT_USD`].
pub fn anthropic_spent_usd(reviews_root: &str) -> Result<f64> {
    let (total, problem) = anthropic_spend(reviews_root);
    Ok(if problem.is_some() {
        UNCOUNTABLE_SPENT_USD
    } else {
        total
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, Read};
    use std::os::unix::fs::OpenOptionsExt;

    /// `ok` baytını verir, sonra her okumada `EIO`.
    struct FailsAfter(io::Cursor<Vec<u8>>);

    impl Read for FailsAfter {
        fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
            match self.0.read(buf)? {
                0 => Err(io::Error::from_raw_os_error(libc::EIO)),
                n => Ok(n),
            }
        }
    }

    impl BufRead for FailsAfter {
        fn fill_buf(&mut self) -> io::Result<&[u8]> {
            if self.0.position() as usize >= self.0.get_ref().len() {
                return Err(io::Error::from_raw_os_error(libc::EIO));
            }
            self.0.fill_buf()
        }
        fn consume(&mut self, n: usize) {
            self.0.consume(n)
        }
    }

    /// Yarıda okunamayan dosya: sayılan istekler toplamda kalır, sorun "okunamadı" (Python `_scan_usage_windows` ve
    /// `cops-providers` `real/ledger.rs` ile aynı; rs-prov 28 Kas).
    #[test]
    fn a_read_error_mid_file_keeps_the_partial_total() {
        let line = b"{\"event\": \"request\", \"t\": 1, \"usage\": {\"input_tokens\": 1000000}}\n"
            .to_vec();
        let mut whole = io::Cursor::new(line.clone());
        let (full, ok) = scan_lines(&mut whole, "x", "claude-opus-5-5", 0.0, 1.0);
        assert!(full > 0.0 && ok.is_none(), "{full} {ok:?}");
        let mut broken = FailsAfter(io::Cursor::new(line));
        let (partial, why) = scan_lines(&mut broken, "x", "claude-opus-5-5", 0.0, 1.0);
        assert_eq!(why, Some(UNREADABLE));
        assert_eq!(partial, full);
    }

    /// Yazanı olmayan FIFO `usage_summary`yi bloklamaz: atlanır (koşu sayılmaz), öteki günlük sayılır.
    #[test]
    fn usage_summary_skips_a_fifo_without_blocking() {
        let dir = tempfile::tempdir().unwrap();
        let a = dir.path().join("p/m/model/a");
        let b = dir.path().join("p/m/model/b");
        std::fs::create_dir_all(&a).unwrap();
        std::fs::create_dir_all(&b).unwrap();
        let fifo = std::ffi::CString::new(a.join("a.usage.jsonl").as_os_str().as_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(fifo.as_ptr(), 0o600) }, 0);
        std::fs::write(
            b.join("b.usage.jsonl"),
            "{\"event\": \"request\", \"seconds\": 1}\n",
        )
        .unwrap();
        let root = dir.path().to_string_lossy().into_owned();
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = tx.send(usage_summary(&root, ""));
        });
        let got = rx.recv_timeout(std::time::Duration::from_secs(5));
        if got.is_err() {
            // bloklanan açılışı serbest bırak, sonra düş
            let _ = std::fs::OpenOptions::new()
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(a.join("a.usage.jsonl"));
            panic!("usage_summary FIFO açılışında bloklandı");
        }
        let rows = got.unwrap().unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!((rows[0].runs, rows[0].requests), (1, 1));
    }
}
