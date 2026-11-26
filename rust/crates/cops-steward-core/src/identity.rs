//! Kimlik, yol ve sahiplik (grup A): `steward.py` baş kısmının SAF öğeleri. Kök dizin (`STEWARD_DIR`) parametredir;
//! ayar ve dosya okuması çağırandadır.

use crate::consts_gen::{BRAIN_PREFIX, DERIVED_TAIL_RE, P_NAME_RE, P_SID_RE, RESERVED_IDS, STEWARD_ID_RE};
use crate::pyc;
use crate::types::{Idea, Project, Question};
use indexmap::IndexMap;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::fmt;

/// `hosts.LOCAL_HOST_NAME`
pub const LOCAL_HOST_NAME: &str = "local";

// ── yollar ────────────────────────────────────────────────────────────────────

/// Bir değnekçi kimliğinin dosya yolları. `cards`/`oneshot` kimlikler arasında ORTAKTIR.
///
/// py: StewardPaths
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct StewardPaths {
    pub sid: String,
    pub root: String,
    pub projects: String,
    pub ideas: String,
    pub questions: String,
    pub state: String,
    pub log: String,
    pub jobs: String,
    pub workspace: String,
    pub daily: String,
    pub lock: String,
    pub cards: String,
    pub oneshot: String,
    pub reviews: String,
    pub review_pool: String,
    pub review_history: String,
    pub findings: String,
}

/// `paths_for`ın `ValueError`ı.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvalidStewardId(pub String);

impl fmt::Display for InvalidStewardId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid steward id: {}", pyc::repr_str(&self.0))
    }
}

impl std::error::Error for InvalidStewardId {}

fn full_match(re: &regex::Regex, s: &str) -> bool {
    re.find(s).is_some_and(|m| m.start() == 0 && m.end() == s.len())
}

/// `base` = `STEWARD_DIR`.
///
/// py: paths_for
pub fn paths_for(base: &str, sid: Option<&str>) -> Result<StewardPaths, InvalidStewardId> {
    let sid = sid.unwrap_or("default");
    if !full_match(&P_SID_RE, sid) {
        return Err(InvalidStewardId(sid.to_string()));
    }
    let j = pyc::path_join;
    let root = if sid == "default" { base.to_string() } else { j(&j(base, "stewards"), sid) };
    Ok(StewardPaths {
        sid: sid.to_string(),
        projects: j(&root, "projects.json"),
        ideas: j(&root, "ideas.json"),
        questions: j(&root, "questions.json"),
        state: j(&root, "state.json"),
        log: j(&root, "log.jsonl"),
        jobs: j(&root, "jobs.json"),
        workspace: j(&root, "workspace"),
        daily: j(&root, "daily"),
        lock: j(&root, ".lock"),
        cards: j(base, "cards"),
        oneshot: j(base, "oneshot"),
        reviews: j(&root, "reviews"),
        review_pool: j(&root, "review_pool.json"),
        review_history: j(&root, "review_history.json"),
        findings: j(&root, "findings.json"),
        root,
    })
}

/// İsteğe bağlı `paths` argümanının Python'daki üç biçimi.
#[derive(Debug, Clone, Copy)]
pub enum PathsArg<'a> {
    /// `None` = `default`
    Default,
    /// kimlik
    Sid(&'a str),
    Paths(&'a StewardPaths),
}

/// py: _pp
pub fn pp(base: &str, paths: PathsArg<'_>) -> Result<StewardPaths, InvalidStewardId> {
    match paths {
        PathsArg::Default => paths_for(base, None),
        PathsArg::Sid(s) => paths_for(base, Some(s)),
        PathsArg::Paths(p) => Ok(p.clone()),
    }
}

/// Pasif servis kaydının yolu; `base` = `STEWARD_DIR`.
///
/// py: services_path
pub fn services_path(base: &str) -> String {
    pyc::path_join(base, "services.json")
}

/// Proje/istek host alanı: boşluk kırpılır, `local` ve boş (ya da Python'da "yanlış" değer) = "".
///
/// py: normalize_host
pub fn normalize_host(host: &Value) -> String {
    if !pyc::truthy(host) {
        return String::new();
    }
    let s = pyc::str_of(host);
    let h = pyc::strip(&s);
    if h.is_empty() || h == LOCAL_HOST_NAME {
        String::new()
    } else {
        h.to_string()
    }
}

// ── kimlik kuralları ──────────────────────────────────────────────────────────

/// `default` DIŞI bir kimlik için geçerli mi.
///
/// py: valid_custom_id
pub fn valid_custom_id(sid: &str) -> bool {
    pyc::match_dollar(&STEWARD_ID_RE, sid) && !RESERVED_IDS.contains(&sid) && !sid.starts_with(BRAIN_PREFIX)
}

/// `default` (özel kimlik) ya da geçerli özel kimlik.
///
/// py: valid_steward_id
pub fn valid_steward_id(sid: &str) -> bool {
    sid == "default" || valid_custom_id(sid)
}

/// py: valid_name
pub fn valid_name(name: &str) -> bool {
    !name.is_empty() && pyc::match_dollar(&P_NAME_RE, name) && pyc::len(name) <= 48
}

/// Ayarda `stewards.<sid>.role == "reviewer"` olan kimlikler. `stewards` = ayarın `stewards` değeri
/// (ayar okunamadıysa `None` -> boş küme).
///
/// py: reviewer_ids
pub fn reviewer_ids(stewards: Option<&Value>) -> BTreeSet<String> {
    let Some(map) = stewards.and_then(Value::as_object) else {
        return BTreeSet::new();
    };
    map.iter()
        .filter(|(k, v)| {
            v.as_object().is_some_and(|o| {
                let role = o.get("role").filter(|r| pyc::truthy(r)).map(pyc::str_of).unwrap_or_default();
                valid_custom_id(k) && pyc::strip(&role) == "reviewer"
            })
        })
        .map(|(k, _)| k.clone())
        .collect()
}

/// `sid` reviewer rolünde mi? `StewardPaths` için çağıran `Some(&paths.sid)` verir; `None` = `default`.
///
/// py: is_reviewer
pub fn is_reviewer(sid: Option<&str>, reviewers: &BTreeSet<String>) -> bool {
    let s = sid.unwrap_or("default");
    s != "default" && reviewers.contains(s)
}

/// Beyin oturumunun adı: `default` -> `degnekci`, diğerleri `degnekci_<sid>`.
///
/// py: brain_name_for
pub fn brain_name_for(sid: &str) -> String {
    if sid == "default" {
        BRAIN_PREFIX.to_string()
    } else {
        format!("{BRAIN_PREFIX}_{sid}")
    }
}

/// History başlığı (TEK kaynak).
///
/// py: steward_title
pub fn steward_title(sid: &str, role: &str, session: &str) -> String {
    if role == "brain" {
        format!("değnekçi · {sid} · beyin")
    } else {
        format!("{session} (değnekçi: {sid})")
    }
}

/// History rozeti.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StewardBadge {
    pub kind: String,
    pub role: String,
    pub sid: String,
    pub title: String,
}

fn badge(role: &str, sid: &str, session: &str) -> StewardBadge {
    StewardBadge {
        kind: "steward".into(),
        role: role.into(),
        sid: sid.into(),
        title: steward_title(sid, role, session),
    }
}

/// Oturum adı `key` projesinin oturumu mu: tam ad ya da `key` + [tarih soneki] + [`_N`].
///
/// py: derived_of
pub fn derived_of(name: &str, key: &str) -> bool {
    !key.is_empty() && name.strip_prefix(key).is_some_and(|tail| full_match(&DERIVED_TAIL_RE, tail))
}

/// Oturum adı -> kayıtlı proje adı (`derived_of`; birden çok aday tutarsa en uzunu); yoksa "".
///
/// py: _project_key
pub fn project_key<'a>(name: &str, projects: impl IntoIterator<Item = &'a str>) -> &'a str {
    let mut best = "";
    for p in projects {
        if derived_of(name, p) && pyc::len(p) > pyc::len(best) {
            best = p;
        }
    }
    best
}

/// Oturum/instance adı için History rozeti: beyin ya da bir değnekçinin sahip olduğu proje oturumu; değilse `None`.
///
/// py: steward_badge
pub fn steward_badge(name: &str, index: &OwnershipIndex) -> Option<StewardBadge> {
    let sid: &str = if let Some(s) = index.brains.get(name) {
        s
    } else if name == BRAIN_PREFIX {
        "default"
    } else {
        name.strip_prefix(BRAIN_PREFIX).and_then(|r| r.strip_prefix('_')).unwrap_or("")
    };
    if !sid.is_empty() {
        return Some(badge("brain", sid, ""));
    }
    let owner = index.owners.get(project_key(name, index.owners.keys().map(String::as_str)))?;
    (!owner.is_empty()).then(|| badge("project", owner, name))
}

// ── hata türleri ──────────────────────────────────────────────────────────────

/// reviewer rolündeki kimlik projects.json'a yazamaz / proje devralamaz / devredemez.
///
/// py: ReviewerRefused
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewerRefused(pub String);

impl fmt::Display for ReviewerRefused {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ReviewerRefused {}

/// `flock` zaman aşımında alınamadı: yazım yapılmadı, çağıran hatayı görür.
///
/// py: LockTimeout
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LockTimeout(pub String);

impl fmt::Display for LockTimeout {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for LockTimeout {}

/// Proje adı başka bir değnekçi kimliğinin `projects.json`'unda zaten var.
///
/// py: OwnedElsewhere
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnedElsewhere {
    pub name: String,
    pub owner: String,
}

impl OwnedElsewhere {
    /// py: OwnedElsewhere.__init__
    pub fn new(name: impl Into<String>, owner: impl Into<String>) -> Self {
        OwnedElsewhere { name: name.into(), owner: owner.into() }
    }
}

impl fmt::Display for OwnedElsewhere {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "project {} is owned by steward {}", pyc::repr_str(&self.name), pyc::repr_str(&self.owner))
    }
}

impl std::error::Error for OwnedElsewhere {}

/// Ad proje olarak talep edilemez.
///
/// py: ReservedName
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReservedName {
    pub name: String,
    pub reason: String,
}

impl ReservedName {
    /// py: ReservedName.__init__
    pub fn new(name: impl Into<String>, reason: impl Into<String>) -> Self {
        ReservedName { name: name.into(), reason: reason.into() }
    }
}

impl fmt::Display for ReservedName {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "project name {} is reserved ({})", pyc::repr_str(&self.name), self.reason)
    }
}

impl std::error::Error for ReservedName {}

// ── sahiplik indeksi ──────────────────────────────────────────────────────────

/// `build_ownership_index` sonucu (sözlük sırası Python'daki gibi).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct OwnershipIndex {
    /// proje -> kimlik (çakışanlar hariç)
    pub owners: IndexMap<String, String>,
    /// proje -> onu gösteren kimlikler
    pub conflicts: IndexMap<String, Vec<String>>,
    /// beyin oturumu adı -> kimlik
    pub brains: IndexMap<String, String>,
    /// servis adı -> kayıt (sözlük değilse boş sözlük)
    pub services: IndexMap<String, Value>,
    /// proje -> host (yalnız uzak)
    pub hosts: IndexMap<String, String>,
}

/// SAF indeks kurucu. Çakışan ad `owners`'a da `hosts`'a da GİRMEZ.
///
/// py: build_ownership_index
pub fn build_ownership_index(
    names_by_sid: &IndexMap<String, Option<Vec<String>>>,
    brains: Option<&IndexMap<String, String>>,
    services: Option<&IndexMap<String, Value>>,
    hosts: Option<&IndexMap<String, IndexMap<String, Value>>>,
) -> OwnershipIndex {
    let mut sids: Vec<&String> = names_by_sid.keys().collect();
    sids.sort();
    let mut seen: IndexMap<&str, Vec<&str>> = IndexMap::new();
    for sid in sids {
        for n in names_by_sid.get(sid).and_then(Option::as_ref).into_iter().flatten() {
            let lst = seen.entry(n.as_str()).or_default();
            if !lst.contains(&sid.as_str()) {
                lst.push(sid);
            }
        }
    }
    let mut out = OwnershipIndex::default();
    for (n, s) in &seen {
        match s.as_slice() {
            [only] => {
                out.owners.insert(n.to_string(), only.to_string());
            }
            _ => {
                let mut v: Vec<String> = s.iter().map(|x| x.to_string()).collect();
                v.sort();
                out.conflicts.insert(n.to_string(), v);
            }
        }
    }
    let all: BTreeSet<&String> = names_by_sid.keys().chain(brains.into_iter().flat_map(IndexMap::keys)).collect();
    for sid in all {
        let brain =
            brains.and_then(|b| b.get(sid)).filter(|b| !b.is_empty()).cloned().unwrap_or_else(|| brain_name_for(sid));
        out.brains.insert(brain, sid.clone());
    }
    for (n, r) in services.into_iter().flatten() {
        if valid_name(n) {
            let rec = if r.is_object() { r.clone() } else { Value::Object(Map::new()) };
            out.services.insert(n.clone(), rec);
        }
    }
    for (p, s) in &out.owners {
        let host = hosts.and_then(|h| h.get(s)).and_then(|m| m.get(p)).map(normalize_host).unwrap_or_default();
        if !host.is_empty() {
            out.hosts.insert(p.clone(), host);
        }
    }
    out
}

/// Ad proje olarak talep edilemiyorsa nedeni, değilse "". Servis kaydı sözlük değilse `prefix` kipi sayılır.
///
/// py: reserved_reason
pub fn reserved_reason(name: &str, index: &OwnershipIndex) -> String {
    let mut brains: BTreeSet<&str> = index.brains.keys().map(String::as_str).collect();
    brains.insert(BRAIN_PREFIX);
    if let Some(b) = brains.into_iter().find(|b| name == *b || b.starts_with(name) || name.starts_with(*b)) {
        return format!("brain name {b}");
    }
    for (s, rec) in &index.services {
        let exact = rec.get("match").and_then(Value::as_str) == Some("exact");
        if name == s || (!exact && name.starts_with(s.as_str())) {
            return format!("service {s}");
        }
    }
    String::new()
}

// ── sözlükten veri sınıfı ─────────────────────────────────────────────────────

/// Python veri sınıfında varsayılanı OLMAYAN alanlar (eksikse `TypeError`).
pub trait FromDict: DeserializeOwned {
    const REQUIRED: &'static [&'static str];
}

impl FromDict for Project {
    const REQUIRED: &'static [&'static str] = &["name"];
}

impl FromDict for Idea {
    const REQUIRED: &'static [&'static str] = &["id", "text", "created_at"];
}

impl FromDict for Question {
    const REQUIRED: &'static [&'static str] = &["id", "project", "text", "created_at"];
}

/// `from_dict` hatası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FromDictError {
    /// zorunlu alan yok (Python: `TypeError`)
    Missing(&'static str),
    /// alan tipi uymuyor (Python bunu olduğu gibi saklar; burada hata)
    BadType(String),
}

impl fmt::Display for FromDictError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FromDictError::Missing(n) => write!(f, "missing required field: {n}"),
            FromDictError::BadType(e) => write!(f, "bad field type: {e}"),
        }
    }
}

impl std::error::Error for FromDictError {}

/// Bilinmeyen anahtarlar atılır, eksik alanlar varsayılanı alır.
///
/// py: _from_dict
pub fn from_dict<T: FromDict>(d: &Map<String, Value>) -> Result<T, FromDictError> {
    if let Some(missing) = T::REQUIRED.iter().find(|k| !d.contains_key(**k)) {
        return Err(FromDictError::Missing(missing));
    }
    serde_json::from_value(Value::Object(d.clone())).map_err(|e| FromDictError::BadType(e.to_string()))
}
