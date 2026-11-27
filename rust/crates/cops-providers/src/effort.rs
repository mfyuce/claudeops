//! `py/claudeops/effort.py`: sağlayıcıdan bağımsız effort yardımcıları.

/// Düşükten yükseğe bilinen seviye adları.
pub const EFFORT_LADDER: [&str; 8] = [
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra",
];
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
    let (mut known, unknown): (Vec<_>, Vec<_>) =
        seen.into_iter().partition(|l| effort_rank(l).is_some());
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
    let ranked: Vec<(usize, &String)> = levels
        .iter()
        .filter_map(|l| effort_rank(l).map(|r| (r, l)))
        .collect();
    if ranked.is_empty() {
        return Some(levels[0].clone());
    }
    let wanted = effort_rank(requested)
        .or_else(|| effort_rank("medium"))
        .unwrap_or(0);
    ranked
        .iter()
        .filter(|(r, _)| *r <= wanted)
        .max()
        .or_else(|| ranked.iter().min())
        .map(|(_, l)| (*l).clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(l: &[&str]) -> Vec<String> {
        l.iter().map(|s| s.to_string()).collect()
    }

    /// Beklenenler Python `effort.py`nin aynı girdideki çıktısı (27 Kas elle koşuldu; geniş kapsam `parity_model_effort`).
    #[test]
    fn tiers_sorting_and_nearest_match_python() {
        assert_eq!(
            split_tier("gemini-3.8-flash-high"),
            ("gemini-3.8-flash", Some("high"))
        );
        assert_eq!(split_tier("-high"), ("-high", None));
        assert_eq!(split_tier("x-ultra"), ("x-ultra", None));
        assert_eq!(split_tier("abc"), ("abc", None));
        assert_eq!(
            sort_levels(v(&["max", "foo", "low", "", "low", "high"])),
            v(&["low", "high", "max", "foo"])
        );
        assert_eq!(
            nearest_effort("high", &v(&["low", "medium"])).as_deref(),
            Some("medium")
        );
        assert_eq!(
            nearest_effort("low", &v(&["medium", "max"])).as_deref(),
            Some("medium")
        );
        assert_eq!(
            nearest_effort("weird", &v(&["low", "high"])).as_deref(),
            Some("low")
        );
        assert_eq!(nearest_effort("x", &v(&["a", "b"])).as_deref(), Some("a"));
        assert_eq!(nearest_effort("x", &[]), None);
    }
}
