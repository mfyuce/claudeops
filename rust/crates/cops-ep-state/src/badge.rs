//! Geçmiş (History) rozeti: Python `steward.ownership_index()` (yalnız rozetin kullandığı `owners` bölümü) +
//! `steward.steward_badge`. Yalnız OKUR ([`StateDocs`] salt okuma kipinde): Python'un okuma yan etkileri (bozuk
//! `projects.json` kanıt yedeği, `db` kipinde tembel içe aktarma) burada YOK.
//!
//! `brains` haritası rozet için ek bilgi taşımaz: `ownership_index()` `brains=None` ile çağrılır, harita yalnız keşfedilen
//! kimliklerin `brain_name_for(sid)` adlarıdır (`degnekci`, `degnekci_<sid>`) ve `steward_badge` aynı adları önek kuralıyla
//! zaten tanır. `services` ve `hosts` rozette kullanılmaz; `services.json` yalnız `files` kipindeki UTF-8 hatası (Python'da
//! tüm indeksi düşüren istisna) için okunur.
use cops_state::pycompat::{is_re_digit, strip};
use cops_state::statedocs::Read;
use cops_state::{Backend, Json, Map, StateDocs};
use indexmap::IndexMap;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

/// Python `steward.BRAIN_PREFIX`.
pub const BRAIN_PREFIX: &str = "degnekci";
/// Python `steward.RESERVED_IDS`.
const RESERVED_IDS: [&str; 6] = [
    "default", "all", "services", "service", "steward", "stewards",
];

/// Python'da `ownership_index()` istisna verirdi (yalnız `files` kipinde UTF-8 olmayan `projects.json`/`services.json`):
/// `_instances_list` bunu yutar ve HİÇBİR satıra rozet koymaz.
#[derive(Debug, PartialEq, Eq)]
pub struct IndexFailed;

/// {proje: değnekçi kimliği}; yalnız TEK kimlikte görünen adlar (çakışanlar yok).
pub type Owners = IndexMap<String, String>;

/// `_SID_RE.fullmatch`: `[a-z]+` (ASCII).
fn sid_like(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_lowercase())
}

/// `valid_custom_id`: `^[a-z]{2,16}$`, rezerve değil, `degnekci` ile başlamıyor.
pub fn valid_custom_id(sid: &str) -> bool {
    (2..=16).contains(&sid.len())
        && sid_like(sid)
        && !RESERVED_IDS.contains(&sid)
        && !sid.starts_with(BRAIN_PREFIX)
}

/// `valid_name`: `^[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*$` ve en çok 48 karakter.
pub fn valid_name(name: &str) -> bool {
    let b = name.as_bytes();
    if b.is_empty() || b.len() > 48 || !b[0].is_ascii_lowercase() {
        return false;
    }
    let word = |c: u8| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_';
    let mut prev_dash = false;
    for &c in &b[1..] {
        if c == b'-' {
            if prev_dash {
                return false;
            }
            prev_dash = true;
        } else if word(c) {
            prev_dash = false;
        } else {
            return false;
        }
    }
    !prev_dash
}

/// `DERIVED_TAIL_RE.fullmatch`: `(?:20\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))?(?:_\d+)?` (`\d` Unicode ondalık).
fn derived_tail(t: &str) -> bool {
    let underscore_digits = |r: &str| {
        r.is_empty()
            || r.strip_prefix('_')
                .is_some_and(|d| !d.is_empty() && d.chars().all(is_re_digit))
    };
    let c: Vec<char> = t.chars().collect();
    let date = c.len() >= 8
        && c[0] == '2'
        && c[1] == '0'
        && is_re_digit(c[2])
        && is_re_digit(c[3])
        && matches!((c[4], c[5]), ('0', '1'..='9') | ('1', '0'..='2'))
        && match (c[6], c[7]) {
            ('0', d) => ('1'..='9').contains(&d),
            ('1' | '2', d) => is_re_digit(d),
            ('3', d) => d == '0' || d == '1',
            _ => false,
        };
    if date {
        let rest: String = c[8..].iter().collect();
        if underscore_digits(&rest) {
            return true;
        }
    }
    underscore_digits(t)
}

/// `derived_of(name, key)`: tam ad ya da `key` + [tarih] + [`_N`].
pub fn derived_of(name: &str, key: &str) -> bool {
    !key.is_empty() && name.strip_prefix(key).is_some_and(derived_tail)
}

/// `_project_key`: `derived_of` tutan en uzun proje adı; yoksa `""`.
fn project_key<'a>(name: &str, owners: &'a Owners) -> &'a str {
    let mut best = "";
    for p in owners.keys() {
        if derived_of(name, p) && p.len() > best.len() {
            best = p;
        }
    }
    best
}

/// `steward_badge(name, index)`: `{kind: "steward", role: brain|project, sid, title}` ya da `None`.
pub fn badge(name: &str, owners: &Owners) -> Option<Json> {
    let brain = if name == BRAIN_PREFIX {
        "default"
    } else {
        name.strip_prefix("degnekci_").unwrap_or("")
    };
    let (role, sid, title) = if !brain.is_empty() {
        ("brain", brain, format!("değnekçi · {brain} · beyin"))
    } else {
        let key = project_key(name, owners);
        let sid = owners.get(key).map(String::as_str).unwrap_or("");
        if key.is_empty() || sid.is_empty() {
            return None;
        }
        ("project", sid, format!("{name} (değnekçi: {sid})"))
    };
    let mut m = Map::new();
    m.insert("kind".into(), "steward".into());
    m.insert("role".into(), role.into());
    m.insert("sid".into(), sid.into());
    m.insert("title".into(), title.into());
    Some(Json::Object(m))
}

/// `steward._load_json(path, {})`: `files` dışı kipte `statedocs.read_json` (bozuk/yok = `{}`); `files` kipinde doğrudan
/// `json.load`: yok/okunamaz/JSON değil = `{}`, ama UTF-8 olmayan içerik Python'da `UnicodeDecodeError` (yakalanmaz).
fn load_json(docs: &StateDocs, path: &Path) -> Result<Json, IndexFailed> {
    use cops_state::paths::realpath;
    // `statedocs._db_ok(path)`: yol (gerçek yoluyla) durum dizini altında mı
    let db_ok = realpath(path).starts_with(realpath(docs.dir().root()));
    if docs.backend() != Backend::Files && db_ok {
        return Ok(match docs.read(&docs.name_for(path), path) {
            Read::Value(v) | Read::Lossy(v) => v,
            Read::Missing | Read::Corrupt => Json::object(),
        });
    }
    let Ok(raw) = std::fs::read(path) else {
        return Ok(Json::object());
    };
    let text = std::str::from_utf8(&raw).map_err(|_| IndexFailed)?;
    Ok(Json::parse_lossy(text).map_or_else(|_| Json::object(), |(v, _)| v))
}

/// `_project_meta(path)[0]`: `projects.json` VARSA (`os.stat`) nesne değerli ve `valid_name` anahtarlar.
fn project_names(docs: &StateDocs, path: &Path) -> Result<Vec<String>, IndexFailed> {
    if std::fs::metadata(path).is_err() {
        return Ok(Vec::new());
    }
    let raw = load_json(docs, path)?;
    let Some(m) = raw.as_object() else {
        return Ok(Vec::new());
    };
    let mut names: Vec<String> = m
        .iter()
        .filter(|(n, d)| d.as_object().is_some() && valid_name(n))
        .map(|(n, _)| n.clone())
        .collect();
    names.sort();
    Ok(names)
}

/// `discover_steward_ids()`: `default` + `steward/stewards/` altındaki `[a-z]+` adlı DİZİNLER (sıralı).
fn discover_ids(steward_dir: &Path) -> Vec<String> {
    let mut ids: Vec<String> = std::fs::read_dir(steward_dir.join("stewards"))
        .map(|rd| {
            rd.filter_map(Result::ok)
                .filter_map(|e| e.file_name().to_str().map(String::from))
                .filter(|e| e != "default" && sid_like(e))
                .filter(|e| steward_dir.join("stewards").join(e).is_dir())
                .collect()
        })
        .unwrap_or_default();
    ids.sort();
    ids.insert(0, "default".into());
    ids
}

/// `reviewer_ids()`: ayarda `stewards.<sid>.role` (kırpılmış) `reviewer` olan geçerli özel kimlikler.
fn reviewer_ids(docs: &StateDocs) -> BTreeSet<String> {
    let settings = cops_state::settings::load(docs.dir());
    let Some(st) = settings.get("stewards").and_then(Json::as_object) else {
        return BTreeSet::new();
    };
    st.iter()
        .filter(|(k, v)| {
            v.as_object().is_some()
                && valid_custom_id(k)
                && v.get("role")
                    .and_then(Json::as_str)
                    .is_some_and(|r| strip(r) == "reviewer")
        })
        .map(|(k, _)| k.clone())
        .collect()
}

/// `ownership_index()["owners"]`.
pub fn owners(docs: &StateDocs) -> Result<Owners, IndexFailed> {
    let steward_dir = docs.dir().join("steward");
    let ids = discover_ids(&steward_dir);
    let reviewers = reviewer_ids(docs);
    let mut by_sid: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for sid in &ids {
        let names = if reviewers.contains(sid) {
            Vec::new()
        } else if sid == "default" {
            project_names(docs, &steward_dir.join("projects.json"))?
        } else {
            project_names(
                docs,
                &steward_dir.join("stewards").join(sid).join("projects.json"),
            )?
        };
        by_sid.insert(sid.clone(), names);
    }
    load_json(docs, &steward_dir.join("services.json"))?;
    let mut seen: IndexMap<String, Vec<&str>> = IndexMap::new();
    for (sid, names) in &by_sid {
        for n in names {
            let l = seen.entry(n.clone()).or_default();
            if !l.contains(&sid.as_str()) {
                l.push(sid);
            }
        }
    }
    Ok(seen
        .into_iter()
        .filter(|(_, s)| s.len() == 1)
        .map(|(n, s)| (n, s[0].to_string()))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn name_rules() {
        assert!(valid_name("ancient-script-pipeline-fd"));
        assert!(!valid_name("a--b") && !valid_name("a-") && !valid_name("-a") && !valid_name("Ab"));
        assert!(!valid_name(&"a".repeat(49)) && valid_name(&"a".repeat(48)));
        assert!(valid_custom_id("rev") && !valid_custom_id("degnekcix") && !valid_custom_id("all"));
        assert!(!valid_custom_id("a") && !valid_custom_id(&"a".repeat(17)));
        for (n, k, want) in [
            ("ncs", "ncs", true),
            ("ncs20261019", "ncs", true),
            ("ncs20261019_1", "ncs", true),
            ("ncs_3", "ncs", true),
            ("ncschr20261017", "ncs", false),
            ("ncs20261019review", "ncs", false),
            ("ncs20261301", "ncs", false),
            ("ncs20261232", "ncs", false),
            ("ncs2026101", "ncs", false),
            ("ncs20261019_", "ncs", false),
            ("ncs20٢61019", "ncs", true), // \d Unicode ondalık
            ("x", "", false),
        ] {
            assert_eq!(derived_of(n, k), want, "{n} {k}");
        }
    }

    #[test]
    fn badges() {
        let mut o = Owners::new();
        o.insert("ncs".into(), "rev".into());
        o.insert("ncs2".into(), "default".into());
        let t = |n: &str| badge(n, &o).map(|b| b.to_compact());
        assert_eq!(
            t("degnekci").unwrap(),
            r#"{"kind": "steward", "role": "brain", "sid": "default", "title": "değnekçi · default · beyin"}"#
        );
        assert!(t("degnekci_iso").unwrap().contains(r#""sid": "iso""#));
        assert_eq!(t("degnekci_"), None);
        assert!(t("ncs2_4").unwrap().contains("ncs2_4 (değnekçi: default)"));
        assert!(t("ncs20261019").unwrap().contains(r#""sid": "rev""#));
        assert_eq!(t("başka"), None);
    }
}
