//! Kullanım/maliyet/sağlık özetleri ve rapor nitelik denetimleri.
use crate::badrec;
use crate::error::Result;
use crate::py::{self, S};
use crate::store::round_to;
use crate::targets::{ci, ANTHROPIC_PRICES};
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::{BTreeMap, HashMap, HashSet};
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
            let Ok(bytes) = std::fs::read(&path) else {
                continue;
            };
            a.runs += 1;
            for line in text_lines(&String::from_utf8_lossy(&bytes)) {
                let Ok(Json::Object(e)) = Json::parse(line) else {
                    continue;
                };
                if !py::is_str(e.get("event"), "request") {
                    continue;
                }
                let usage = e.get("usage").and_then(Json::as_object);
                let Some(sec) = badrec::field(&e, "seconds", "usage.record", &path) else {
                    continue;
                };
                let non_finite = |v: &Json| matches!(v, Json::Float(f) if !f.is_finite());
                if usage.is_some_and(|u| u.values().any(non_finite)) {
                    badrec::log_bad("usage.record", &path);
                    continue;
                }
                a.requests += 1;
                a.seconds += sec;
                let Some(u) = usage else { continue };
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

/// Bir `.usage.jsonl` dosyasının $ maliyeti. `model` boşsa kayıttan izlenir; `since_ms > 0` yalnız sonrası.
pub fn usage_cost_usd(path: &str, model: &str, since_ms: f64, write_mult: f64) -> Result<f64> {
    let [mut pi, mut po, mut pr, mut pw] =
        anthropic_price(if model.is_empty() { "opus-5-5" } else { model });
    let mut total = 0.0;
    let Ok(bytes) = std::fs::read(path) else {
        return Ok(0.0);
    };
    for raw in bytes.split(|b| *b == b'\n') {
        let Ok(line) = std::str::from_utf8(raw) else {
            badrec::log_bad("usage.line", path); // yalnız bozuk satır atlanır; kalan istekler maliyete girer
            continue;
        };
        let line = line.trim_end_matches('\r');
        let Ok(Json::Object(rec)) = Json::parse(line) else {
            continue;
        };
        if model.is_empty()
            && py::is_str(rec.get("event"), "task_start")
            && py::truthy(rec.get("model"))
        {
            [pi, po, pr, pw] = anthropic_price(&py::str_or_empty(rec.get("model")));
            continue;
        }
        // `float(t or 0)`: sayı olmayan 0; sonlu olmayan ya da sığmayan satır bozuktur.
        let t = match rec.get("t").filter(|v| v.truthy()) {
            Some(v @ Json::BigInt(_)) => py::float(v).unwrap_or(f64::INFINITY),
            Some(v) => py::float(v).unwrap_or(0.0),
            None => 0.0,
        };
        if !t.is_finite() {
            badrec::log_bad("usage.record", path);
            continue;
        }
        if since_ms != 0.0 && t < since_ms {
            continue;
        }
        let Some(u) = rec.get("usage").and_then(Json::as_object) else {
            continue;
        };
        let broken = |v: &Json| {
            matches!(v, Json::Int(_) | Json::Float(_) | Json::BigInt(_))
                && !py::float(v).is_some_and(f64::is_finite)
        };
        if u.values().any(broken) {
            badrec::log_bad("usage.record", path);
            continue;
        }
        // `isinstance(x, (int, float))`: bool de sayılır.
        let numeric = |k: &str| match u.get(k) {
            Some(Json::Str(_)) | None => None,
            Some(v) => py::float(v),
        };
        let g = |names: &[&str]| names.iter().find_map(|n| numeric(n)).unwrap_or(0.0);
        let cr = g(&[
            "cache_read_input_tokens",
            "cached_tokens",
            "cache_read_tokens",
        ]);
        let cw = g(&["cache_creation_input_tokens", "cache_write_tokens"]);
        let inp = match numeric("input_tokens") {
            Some(i) => f64::max(
                0.0,
                i - (if u.contains_key("cache_read_input_tokens") {
                    0.0
                } else {
                    cr
                }) - (if u.contains_key("cache_creation_input_tokens") {
                    0.0
                } else {
                    cw
                }),
            ),
            None => f64::max(0.0, g(&["prompt_tokens"]) - cr - cw),
        };
        let inp_price =
            if u.contains_key("cached_tokens") && !u.contains_key("cache_creation_input_tokens") {
                pw
            } else {
                pi
            };
        total += (inp * inp_price
            + g(&["output_tokens", "completion_tokens"]) * po
            + cr * pr
            + cw * pw * write_mult)
            / 1e6;
    }
    Ok(total)
}

/// Tüm `anthropic` koşularının toplam $.
pub fn anthropic_spent_usd(reviews_root: &str) -> Result<f64> {
    let mut total = 0.0;
    let Ok(rd) = std::fs::read_dir(if reviews_root.is_empty() {
        "."
    } else {
        reviews_root
    }) else {
        return Ok(0.0);
    };
    for e in rd.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }
        let adir = py::path_join(reviews_root, &[&name, "anthropic"]);
        if std::fs::symlink_metadata(&adir).is_err() {
            continue;
        }
        walk(&adir, &mut |dir, files| {
            for f in files {
                if !f.ends_with(".usage.jsonl") {
                    continue;
                }
                let path = py::path_join(dir, &[f]);
                let rel = py::relpath(&path, &adir);
                let parts: Vec<&str> = rel.split('/').collect();
                if parts.len() < 2 {
                    continue;
                }
                total += usage_cost_usd(&path, parts[0], 0.0, 1.0)?;
            }
            Ok(())
        })?;
    }
    Ok(total)
}
