//! `py/claudeops/effort.py`: sağlayıcıdan bağımsız effort yardımcıları.

/// Düşükten yükseğe bilinen seviye adları.
pub const EFFORT_LADDER: [&str; 8] = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
const ID_TIERS: [&str; 6] = ["minimal", "low", "medium", "high", "xhigh", "max"];

pub fn effort_rank(level: &str) -> Option<usize> {
    EFFORT_LADDER.iter().position(|l| *l == level)
}

/// `gemini-3.8-flash-high` -> (`gemini-3.8-flash`, `high`).
pub fn split_tier(model_id: &str) -> (&str, Option<&str>) {
    match model_id.rsplit_once('-') {
        Some((head, tail)) if !head.is_empty() && ID_TIERS.contains(&tail) => (head, Some(tail)),
        _ => (model_id, None),
    }
}

/// Merdivene göre sıralı, tekrarsız; bilinmeyen adlar girdi sırasıyla sonda.
pub fn sort_levels<I: IntoIterator<Item = String>>(levels: I) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();
    for l in levels {
        if !l.is_empty() && !seen.contains(&l) {
            seen.push(l);
        }
    }
    let (mut known, unknown): (Vec<_>, Vec<_>) = seen.into_iter().partition(|l| effort_rank(l).is_some());
    known.sort_by_key(|l| effort_rank(l));
    known.extend(unknown);
    known
}

/// `levels` içinden `requested`e uygun seviye (asla gereksiz yükseltmez). `default` = "medium".
pub fn nearest_effort(requested: &str, levels: &[String]) -> Option<String> {
    if levels.is_empty() {
        return None;
    }
    if levels.iter().any(|l| l == requested) {
        return Some(requested.into());
    }
    let ranked: Vec<(usize, &String)> = levels.iter().filter_map(|l| effort_rank(l).map(|r| (r, l))).collect();
    if ranked.is_empty() {
        return Some(levels[0].clone());
    }
    let wanted = effort_rank(requested).or_else(|| effort_rank("medium")).unwrap_or(0);
    ranked.iter().filter(|(r, _)| *r <= wanted).max().or_else(|| ranked.iter().min()).map(|(_, l)| (*l).clone())
}
