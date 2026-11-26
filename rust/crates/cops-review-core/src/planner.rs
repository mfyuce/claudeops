//! Planlayıcı ve havuz (saf).
use crate::error::Result;
use crate::limits::blocked_modes;
use crate::py;
use crate::targets::*;
use cops_state::json::{Json, Map};
use regex::Regex;
use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::LazyLock;

/// `history["pairs"]` (nesne değilse yok).
pub fn pairs(history: &Json) -> Option<&Map> {
    history.get("pairs").and_then(Json::as_object)
}

pub fn pair_key(proj: &str, t: &ReviewTarget) -> String {
    format!("{proj}|{}/{}", t.mode, t.pslug())
}

/// `review_window_hours` -> saniye.
pub fn window_seconds(hours: Option<&Json>) -> f64 {
    match hours.and_then(py::float) {
        Some(h) if h > 0.0 => h * 3600.0,
        _ => WINDOW_SECONDS as f64,
    }
}

fn fresh(rec: Option<&Json>, now: f64, window: f64) -> bool {
    rec.and_then(Json::as_object)
        .is_some_and(|r| py::is_str(r.get("status"), "done") && now - py::num(r.get("finished_at")) < window)
}

pub fn project_complete(history: &Json, proj: &str, targets: &[ReviewTarget], now: f64, window: f64) -> bool {
    let p = pairs(history);
    !targets.is_empty()
        && targets
            .iter()
            .all(|t| fresh(p.and_then(|p| p.get(&pair_key(proj, t))), now, window))
}

fn pool_names(pool: &Json, keep: impl Fn(&Map) -> bool) -> Vec<String> {
    let Some(pr) = pool.get("projects").and_then(Json::as_object) else { return Vec::new() };
    let set: BTreeSet<&String> = pr
        .iter()
        .filter(|(_, e)| e.as_object().is_some_and(&keep))
        .map(|(n, _)| n)
        .collect();
    set.into_iter().cloned().collect()
}

fn is_enabled(e: &Map) -> bool {
    py::truthy(e.get("enabled")) && !py::truthy(e.get("removed_at"))
}

/// Havuzda etkin proje adları, sıralı.
pub fn pool_enabled(pool: &Json) -> Vec<String> {
    pool_names(pool, is_enabled)
}

/// Havuzda ★ odak işaretli etkin projeler.
pub fn pool_focus(pool: &Json) -> Vec<String> {
    pool_names(pool, |e| py::truthy(e.get("focus")) && is_enabled(e))
}

pub fn agy_pool(model: &str) -> String {
    let m = model.to_lowercase();
    if m.contains("argon") {
        "argon".into()
    } else if m.starts_with("gemini") {
        "gemini".into()
    } else if m.starts_with("claude") || m.starts_with("gpt") {
        "claude_gpt".into()
    } else {
        m
    }
}

pub fn model_family(t: &ReviewTarget) -> String {
    if t.mode == "agy" {
        return format!("agy:{}", agy_pool(&t.model));
    }
    let lower = t.model.to_lowercase();
    let name = lower.rsplit('/').next().unwrap_or("");
    let alpha: String = name.chars().take_while(char::is_ascii_lowercase).collect();
    format!("{}:{}", t.mode, if alpha.is_empty() { name } else { &alpha })
}

/// `mode/model[@effort][~lens]` anahtarındaki model.
pub(crate) fn key_model(key: &str) -> &str {
    let m = key.split_once('/').map_or("", |(_, m)| m);
    let m = m.split('@').next().unwrap_or("");
    m.split('~').next().unwrap_or("")
}

fn blocked_targets<'a>(targets: &'a [ReviewTarget], skip: &[String]) -> Vec<&'a ReviewTarget> {
    let skip: HashSet<&str> = skip.iter().map(String::as_str).collect();
    let pools: HashSet<String> = skip.iter().filter(|k| k.starts_with("agy/")).map(|k| agy_pool(key_model(k))).collect();
    targets
        .iter()
        .filter(|t| {
            !skip.contains(t.mode.as_str())
                && !skip.contains(t.key().as_str())
                && !(t.mode == "agy" && pools.contains(&agy_pool(&t.model)))
        })
        .collect()
}

/// `next_review` isteğe bağlı girdileri.
pub struct PlanOpts<'a> {
    pub busy_projects: &'a [String],
    pub window: f64,
    /// Projenin git HEAD'i ("" = bilinmiyor; hata da "" döndürmeli).
    pub head_of: Option<&'a dyn Fn(&str) -> String>,
    pub skip_pairs: &'a [String],
}

impl Default for PlanOpts<'_> {
    fn default() -> Self {
        PlanOpts { busy_projects: &[], window: WINDOW_SECONDS as f64, head_of: None, skip_pairs: &[] }
    }
}

/// Sıradaki (proje, hedef) ya da `None`.
pub fn next_review(
    pool: &Json,
    history: &Json,
    targets: &[ReviewTarget],
    now: f64,
    opts: &PlanOpts<'_>,
) -> Result<Option<(String, ReviewTarget)>> {
    let targets = blocked_targets(targets, &blocked_modes(history, now)?);
    if targets.is_empty() {
        return Ok(None);
    }
    let all_pairs = pairs(history);
    let busy: HashSet<&str> = opts.busy_projects.iter().map(String::as_str).collect();
    let sp: HashSet<&str> = opts.skip_pairs.iter().map(String::as_str).collect();
    let mut cands: Vec<(i32, f64, String, ReviewTarget)> = Vec::new();
    for proj in pool_enabled(pool) {
        if busy.contains(proj.as_str()) {
            continue;
        }
        let tgs: Vec<&ReviewTarget> =
            targets.iter().copied().filter(|t| !sp.contains(pair_key(&proj, t).as_str())).collect();
        if tgs.is_empty() {
            continue;
        }
        let recs: Vec<Option<&Map>> = tgs
            .iter()
            .map(|t| all_pairs.and_then(|p| p.get(&pair_key(&proj, t))).and_then(Json::as_object))
            .collect();
        let raw: Vec<Option<&Json>> =
            tgs.iter().map(|t| all_pairs.and_then(|p| p.get(&pair_key(&proj, t)))).collect();
        if recs.iter().flatten().any(|r| py::is_str(r.get("status"), "running")) {
            continue;
        }
        let mut head_cache: HashMap<(), String> = HashMap::new();
        let mut fresh_or_same = |i: usize| -> bool {
            if fresh(raw[i], now, opts.window) {
                return true;
            }
            let Some(head_of) = opts.head_of else { return false };
            let Some(r) = recs[i] else { return false };
            if !py::is_str(r.get("status"), "done") || !py::truthy(r.get("head")) {
                return false;
            }
            let hd = head_cache.entry(()).or_insert_with(|| head_of(&proj));
            !hd.is_empty() && py::is_str(r.get("head"), hd)
        };
        let flags: Vec<bool> = (0..tgs.len()).map(&mut fresh_or_same).collect();
        let covered: HashSet<String> =
            tgs.iter().zip(&flags).filter(|(_, f)| **f).map(|(t, _)| model_family(t)).collect();
        let mut pick: Option<&ReviewTarget> = None;
        for (i, t) in tgs.iter().enumerate() {
            if flags[i] {
                continue;
            }
            if let Some(r) = recs[i] {
                if py::str_in(r.get("status"), &["error", "model_fallback", "partial"])
                    && py::num(r.get("attempts")).trunc() >= max_attempts(&t.mode) as f64
                    && counts_as_attempt(raw[i])
                    && now - py::num(r.get("started_at")) < opts.window
                {
                    continue;
                }
                if py::is_str(r.get("status"), "error")
                    && py::str_or_empty(r.get("error")).starts_with(CAPACITY_ERROR_PREFIX)
                    && now < py::num(r.get("retry_at"))
                {
                    continue;
                }
            }
            if !covered.contains(&model_family(t)) {
                pick = Some(t);
                break;
            }
            if pick.is_none() {
                pick = Some(t);
            }
        }
        let Some(pick) = pick else { continue };
        let nfresh = flags.iter().filter(|f| **f).count();
        let known: Vec<f64> = recs
            .iter()
            .flatten()
            .map(|r| {
                let f = r.get("finished_at");
                py::num(if py::truthy(f) { f } else { r.get("started_at") })
            })
            .collect();
        if nfresh > 0 {
            cands.push((0, -(nfresh as f64), proj, pick.clone()));
        } else if known.is_empty() {
            cands.push((1, 0.0, proj, pick.clone()));
        } else {
            // Python `max`: ilk en büyük (NaN karşılaştırmaları False).
            let mx = known[1..].iter().fold(known[0], |a, &b| if b > a { b } else { a });
            cands.push((2, mx, proj, pick.clone()));
        }
    }
    let focus: HashSet<String> = pool_focus(pool).into_iter().collect();
    let rank = |c: &(i32, f64, String, ReviewTarget)| i32::from(!focus.contains(&c.2));
    cands.sort_by(|a, b| {
        rank(a)
            .cmp(&rank(b))
            .then(a.0.cmp(&b.0))
            .then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
            .then_with(|| a.2.cmp(&b.2))
    });
    Ok(cands.into_iter().next().map(|c| (c.2, c.3)))
}

pub const BACKLOG_FILES: [&str; 2] = ["TODO.md", "RTODO.md"];

/// Açık review satırı sayısı: `- [ ] (review ...`.
pub fn open_review_lines(text: &str) -> usize {
    static RE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r"(?m)^[{}]*- \[ \] \(review ", py::S)).unwrap());
    RE.find_iter(text).count()
}

/// Açık review satırı `limit`e ulaşmış etkin projeler (`count_of` `None` = sayılamadı, atlanır).
pub fn backlogged_projects(pool: &Json, count_of: impl Fn(&str) -> Option<i64>, limit: i64) -> Vec<String> {
    if limit <= 0 {
        return Vec::new();
    }
    let focus: HashSet<String> = pool_focus(pool).into_iter().collect();
    pool_enabled(pool)
        .into_iter()
        .filter(|p| !focus.contains(p) && count_of(p).is_some_and(|n| n >= limit))
        .collect()
}

/// Havuzu sahip olunan proje adlarıyla eşler. (yeni havuz, değişti mi).
pub fn pool_sync(pool: &Json, owner_names: &[String], now: f64) -> (Json, bool) {
    let mut projects: Map = pool
        .get("projects")
        .and_then(Json::as_object)
        .map(|src| src.iter().filter(|(_, v)| v.as_object().is_some()).map(|(k, v)| (k.clone(), v.clone())).collect())
        .unwrap_or_default();
    let owners: BTreeSet<&str> = owner_names.iter().map(String::as_str).filter(|n| !n.is_empty()).collect();
    let mut changed = false;
    for n in &owners {
        match projects.get_mut(*n).and_then(Json::as_object_mut) {
            None => {
                let mut e = Map::new();
                e.insert("enabled".into(), Json::Bool(true));
                e.insert("source".into(), "auto".into());
                e.insert("added_at".into(), Json::Float(now));
                e.insert("removed_at".into(), Json::Null);
                projects.insert((*n).to_string(), Json::Object(e));
                changed = true;
            }
            Some(e) => {
                if py::is_str(e.get("source"), "auto") && py::truthy(e.get("removed_at")) {
                    e.insert("enabled".into(), Json::Bool(true));
                    e.insert("removed_at".into(), Json::Null);
                    changed = true;
                }
            }
        }
    }
    for (n, e) in projects.iter_mut() {
        let Some(e) = e.as_object_mut() else { continue };
        if !owners.contains(n.as_str()) && py::is_str(e.get("source"), "auto") && !py::truthy(e.get("removed_at")) {
            e.insert("enabled".into(), Json::Bool(false));
            e.insert("removed_at".into(), Json::Float(now));
            changed = true;
        }
    }
    let mut out = Map::new();
    out.insert("projects".into(), Json::Object(projects));
    (Json::Object(out), changed)
}
