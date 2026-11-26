//! Hedefler (mod, model, effort, mercek), yuva ayarı, kapasite hatası sınıflaması ve ilgili sabitler.
use crate::py;
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::{BTreeSet, HashSet};
use std::sync::LazyLock;

pub const WINDOW_SECONDS: i64 = 15 * 86400;
pub const HISTORY_VERSION: i64 = 1;
pub const HISTORY_RUNS_MAX: usize = 200;
pub const MAX_ATTEMPTS: i64 = 3;
pub const MODE_MAX_ATTEMPTS: [(&str, i64); 2] = [("evren", 1), ("anthropic", 1)];
pub const CAPACITY_ERROR_PREFIX: &str = "capacity:";
pub const CAPACITY_RETRY_MIN: f64 = 300.0;
pub const CAPACITY_RETRY_MAX: f64 = 1800.0;
pub const CAPACITY_MAX_TRIES: i64 = 6;
pub const UNCOUNTED_ERRORS: [&str; 4] = [
    "cancelled",
    "spawn:",
    "yeniden başlatma",
    CAPACITY_ERROR_PREFIX,
];
pub const MODES: [&str; 6] = ["agy", "evren", "claude", "codex", "copilot", "anthropic"];
pub const UCLI_MODES: [&str; 2] = ["evren", "anthropic"];
pub const ANTHROPIC_ENDPOINT: &str = "https://api.anthropic.com/v1";
/// `$ / 1M token`: (girdi, çıktı, önbellek okuma, önbellek yazma). Sıra Python sözlüğüyle aynı (ilk eşleşen kazanır).
pub const ANTHROPIC_PRICES: [(&str, [f64; 4]); 4] = [
    ("haiku-5-5", [0.10, 0.50, 0.01, 0.125]),
    ("sonnet-5-5", [2.0, 10.0, 0.10, 2.5]),
    ("opus-5-5", [4.0, 20.0, 0.20, 5.0]),
    ("fable-5-1", [10.0, 50.0, 0.25, 12.5]),
];
pub const PAIR_STATUSES: [&str; 6] = [
    "running",
    "done",
    "partial",
    "error",
    "model_fallback",
    "limit",
];
pub const SEVERITIES: [&str; 3] = ["P1", "P2", "P3"];
pub const FINDING_STATES: [&str; 9] = [
    "new",
    "verify_sent",
    "verified",
    "refuted",
    "unclear",
    "approved",
    "rejected",
    "exported",
    "dup",
];
pub const FORBIDDEN_PATHS: [&str; 6] = [
    "CLAUDE.md",
    ".env*",
    "*token*",
    "*credential*",
    "*.pem",
    "settings*.json",
];
pub const SUBSCRIPTION_FABLE_EFFORTS: [&str; 3] = ["low", "medium", "high"];

static CAPACITY_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)model_capacity_exhausted|\b429\b|\b503\b|rate.?limit|too many requests|serv[iİı]ce unava[iİı]lable").unwrap()
});
static RETRY_AFTER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)retry[- ]?after\W{0,3}(\d+)").unwrap());

pub fn is_capacity_error(texts: &[&str]) -> bool {
    texts
        .iter()
        .any(|t| CAPACITY_RE.is_match(&ci(py::tail(t, 20000))))
}

/// Python `re.I` İ/ı/i/I'yı eşit sayar, Rust saymaz: büyük/küçük harf duyarsız aramadan önce İ ve ı `i`ye indirilir
/// (yalnız evet/hayır ya da rakam yakalayan aramalarda kullanılır; metin çıktıya gitmez).
pub(crate) fn ci(s: &str) -> std::borrow::Cow<'_, str> {
    if s.contains(['İ', 'ı']) {
        s.replace(['İ', 'ı'], "i").into()
    } else {
        s.into()
    }
}

pub fn capacity_retry_seconds(texts: &[&str]) -> f64 {
    for t in texts {
        if let Some(c) = RETRY_AFTER_RE.captures(&ci(py::tail(t, 20000))) {
            let v = decimal(&c[1]);
            return v.clamp(CAPACITY_RETRY_MIN, CAPACITY_RETRY_MAX);
        }
    }
    CAPACITY_RETRY_MIN
}

/// `\d+` yakalamasının sayısı; Python `\d` ASCII dışı rakamları da kabul eder.
pub(crate) fn decimal(s: &str) -> f64 {
    s.chars()
        .fold(0.0, |acc, c| acc * 10.0 + f64::from(digit_value(c)))
}

pub(crate) fn digit_value(c: char) -> u32 {
    if let Some(d) = c.to_digit(10) {
        return d;
    }
    // Nd blokları 10'ar ardışıktır: bloğun başından uzaklık.
    let u = c as u32;
    let mut start = u;
    while start > 0 && u - start < 9 && char::from_u32(start - 1).is_some_and(is_decimal_digit) {
        start -= 1;
    }
    u - start
}

fn is_decimal_digit(c: char) -> bool {
    static ND: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\d$").unwrap());
    ND.is_match(c.encode_utf8(&mut [0; 4]))
}

/// Bu çift kaydının hatası deneme hakkını TÜKETİR mi.
/// Dolu ama nesne olmayan kayıt deneme SAYILMAZ (loglanır).
pub fn counts_as_attempt(rec: Option<&Json>) -> bool {
    let m = match rec.filter(|r| r.truthy()) {
        Some(r) => match r.as_object() {
            Some(m) => Some(m),
            None => {
                let kind = match r {
                    Json::Str(_) => "str",
                    Json::Array(_) => "list",
                    Json::Float(_) => "float",
                    Json::Bool(_) => "bool",
                    _ => "int",
                };
                crate::badrec::log_bad("pairs.record", kind);
                return false;
            }
        },
        None => None,
    };
    let err = py::str_or_empty(m.and_then(|m| m.get("error")));
    if err.starts_with(CAPACITY_ERROR_PREFIX)
        && py::num(m.and_then(|m| m.get("attempts"))).trunc() > CAPACITY_MAX_TRIES as f64
    {
        return true;
    }
    !UNCOUNTED_ERRORS.iter().any(|p| err.starts_with(p))
}

pub fn max_attempts(mode: &str) -> i64 {
    MODE_MAX_ATTEMPTS
        .iter()
        .find(|(m, _)| *m == mode)
        .map_or(MAX_ATTEMPTS, |(_, n)| *n)
}

/// `review_slots` ayarı -> [(mod, yuva)] (`MODES` sırasında); ""/`off`/hiç geçerli parça yok = boş.
pub fn parse_slots(spec: &str) -> Vec<(&'static str, u64)> {
    let t = py::strip(spec).to_lowercase();
    if t.is_empty() || t == "off" {
        return Vec::new();
    }
    let mut out: Vec<(&'static str, u64)> = MODES.iter().map(|m| (*m, 1)).collect();
    let mut seen = false;
    for part in t.split(',') {
        let Some((k, v)) = part.split_once('=') else {
            continue;
        };
        let (k, v) = (py::strip(k), py::strip(v));
        // Python `isdigit()`: ASCII dışı rakamlar da (`int()` kabul ettikleri) sayılır; u64 taşarsa en büyük değer.
        let digits = !v.is_empty() && v.chars().all(is_decimal_digit);
        if !digits {
            continue;
        }
        if let Some(slot) = out.iter_mut().find(|(m, _)| *m == k) {
            slot.1 = v.chars().fold(0u64, |a, c| {
                a.saturating_mul(10)
                    .saturating_add(u64::from(digit_value(c)))
            });
            seen = true;
        }
    }
    if seen {
        out
    } else {
        Vec::new()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Default)]
pub struct ReviewTarget {
    pub mode: String,
    pub model: String,
    pub slug: String,
    pub effort: String,
    pub lens: String,
}

impl ReviewTarget {
    pub fn new(mode: &str, model: &str, slug: &str) -> Self {
        ReviewTarget {
            mode: mode.into(),
            model: model.into(),
            slug: slug.into(),
            ..Default::default()
        }
    }
    pub fn pslug(&self) -> String {
        let base = if self.effort.is_empty() {
            self.slug.clone()
        } else {
            format!("{}@{}", self.slug, slug_model(&self.effort))
        };
        if self.lens.is_empty() {
            base
        } else {
            format!("{base}~{}", slug_model(&self.lens))
        }
    }
    pub fn key(&self) -> String {
        format!("{}/{}", self.mode, self.pslug())
    }
    pub fn spec(&self) -> String {
        if self.effort.is_empty() {
            self.model.clone()
        } else {
            format!("{}@{}", self.model, self.effort)
        }
    }
}

/// Yol güvenli ad.
pub fn slug_model(model: &str) -> String {
    static UNSAFE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^A-Za-z0-9._-]+").unwrap());
    static DASHES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"-{2,}").unwrap());
    let s = UNSAFE.replace_all(py::strip(model), "-");
    let s = DASHES
        .replace_all(s.trim_matches(['-', '.']), "-")
        .into_owned();
    if s.is_empty() {
        "model".into()
    } else {
        s
    }
}

pub fn split_spec(spec: &str) -> (String, String) {
    let t = py::strip(spec);
    let (m, e) = t.split_once('@').unwrap_or((t, ""));
    (py::strip(m).to_string(), py::strip(e).to_string())
}

pub fn split_models(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for part in text.split(',') {
        let part = py::strip(part);
        if !part.is_empty() && !out.iter().any(|o| o == part) {
            out.push(part.to_string());
        }
    }
    out
}

/// `steward.Config`in bu çekirdeğin okuduğu alanları (varsayılanlar Python ile aynı).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewConfig {
    pub review_agy_models: String,
    pub review_evren_models: String,
    pub review_claude_models: String,
    pub review_codex_models: String,
    pub review_copilot_models: String,
    pub review_anthropic_models: String,
    pub review_excluded: String,
    pub review_claude_auth: String,
    pub review_claude_effort: String,
    pub review_codex_effort: String,
    pub review_copilot_effort: String,
}

impl Default for ReviewConfig {
    fn default() -> Self {
        ReviewConfig {
            review_agy_models: String::new(),
            review_evren_models: String::new(),
            review_claude_models: String::new(),
            review_codex_models: String::new(),
            review_copilot_models: String::new(),
            review_anthropic_models: String::new(),
            review_excluded: String::new(),
            review_claude_auth: "api".into(),
            review_claude_effort: "low".into(),
            review_codex_effort: "low".into(),
            review_copilot_effort: "low".into(),
        }
    }
}

pub fn excluded_keys(cfg: &ReviewConfig) -> HashSet<String> {
    split_models(&cfg.review_excluded).into_iter().collect()
}

pub fn toggle_excluded(text: &str, key: &str, exclude: bool) -> String {
    let mut cur = split_models(text);
    if exclude && !cur.iter().any(|c| c == key) {
        cur.push(key.to_string());
    }
    if !exclude {
        cur.retain(|c| c != key);
    }
    cur.join(",")
}

/// `claude_models.json` içeriği (`statedocs` belgesi `claude_models`) -> model -> durum. Bozuk biçim -> boş.
pub fn claude_catalog_from(state: Option<&Json>) -> Map {
    let empty = Map::new();
    let Some(state) = state.and_then(Json::as_object) else {
        return empty;
    };
    match state.get("models") {
        Some(v) if v.truthy() => match v.as_object() {
            Some(m) => m
                .iter()
                .map(|(k, v)| (k.clone(), Json::Str(py::to_str(v))))
                .collect(),
            None => empty,
        },
        _ => empty,
    }
}

fn catalog_is(cat: &Map, model: &str, state: &str) -> bool {
    py::is_str(cat.get(model), state)
}

pub fn claude_is_subscription(cfg: &ReviewConfig) -> bool {
    let v = if cfg.review_claude_auth.is_empty() {
        "api"
    } else {
        &cfg.review_claude_auth
    };
    py::strip(v).to_lowercase() == "subscription"
}

pub fn claude_specs(cfg: &ReviewConfig, catalog: &Map) -> Vec<String> {
    let specs = split_models(&cfg.review_claude_models);
    if !specs.is_empty() {
        return specs
            .into_iter()
            .filter(|s| !catalog_is(catalog, &split_spec(s).0, "disabled"))
            .collect();
    }
    if claude_is_subscription(cfg) {
        let sorted: BTreeSet<&String> = catalog.keys().collect();
        return sorted
            .into_iter()
            .filter(|m| m.contains("fable") && catalog_is(catalog, m, "enabled"))
            .flat_map(|m| {
                SUBSCRIPTION_FABLE_EFFORTS
                    .iter()
                    .map(move |e| format!("{m}@{e}"))
            })
            .collect();
    }
    Vec::new()
}

/// `catalog`: claude model kataloğu (yalnız claude modu okur).
pub fn targets_from_config(
    cfg: &ReviewConfig,
    agy_models: &[String],
    evren_models: &[String],
    catalog: &Map,
) -> Vec<ReviewTarget> {
    let mut out: Vec<ReviewTarget> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut push = |t: ReviewTarget, out: &mut Vec<ReviewTarget>| {
        if seen.insert(t.key()) {
            out.push(t);
        }
    };
    for (mode, avail, want) in [
        ("agy", agy_models, &cfg.review_agy_models),
        ("evren", evren_models, &cfg.review_evren_models),
    ] {
        let wanted = split_models(want);
        let list = if wanted.is_empty() {
            avail
        } else {
            &wanted[..]
        };
        for m in list {
            if !wanted.is_empty() && !avail.contains(m) {
                continue;
            }
            push(ReviewTarget::new(mode, m, &slug_model(m)), &mut out);
        }
    }
    for (mode, attr) in [
        ("claude", &cfg.review_claude_models),
        ("codex", &cfg.review_codex_models),
        ("copilot", &cfg.review_copilot_models),
        ("anthropic", &cfg.review_anthropic_models),
    ] {
        let specs = if mode == "claude" {
            claude_specs(cfg, catalog)
        } else {
            split_models(attr)
        };
        for spec in specs {
            let (m, effort) = split_spec(&spec);
            if m.is_empty() {
                continue;
            }
            let sub = mode == "claude" && claude_is_subscription(cfg);
            let slug = format!("{}{}", slug_model(&m), if sub { "-sub" } else { "" });
            push(
                ReviewTarget {
                    effort,
                    ..ReviewTarget::new(mode, &m, &slug)
                },
                &mut out,
            );
        }
    }
    let skip = excluded_keys(cfg);
    if !skip.is_empty() {
        out.retain(|t| !skip.contains(&t.key()));
    }
    out
}

/// History satırı/sohbet başlığı. `ts`: epoch (sayı) ya da 14 haneli damga dizesi.
pub fn review_title(project: &str, mode: &str, model: &str, ts: Option<&Json>) -> String {
    static STAMP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\d{14}$").unwrap());
    let when = match ts {
        Some(Json::Str(s)) if STAMP.is_match(s) => {
            let c: Vec<char> = s.chars().collect();
            let cut = |a: usize, b: usize| c[a..b].iter().collect::<String>();
            format!(
                "{}-{}-{} {}:{}",
                cut(0, 4),
                cut(4, 6),
                cut(6, 8),
                cut(8, 10),
                cut(10, 12)
            )
        }
        None | Some(Json::Null) => String::new(),
        Some(Json::Str(s)) if s.is_empty() => String::new(),
        Some(v) => py::float(v)
            .and_then(|f| crate::clock::format_local(f, "%Y-%m-%d %H:%M"))
            .unwrap_or_default(),
    };
    let mut parts = vec![
        "review".to_string(),
        project.to_string(),
        format!("{mode}/{model}"),
    ];
    if !when.is_empty() {
        parts.push(when);
    }
    parts.join(" · ")
}
