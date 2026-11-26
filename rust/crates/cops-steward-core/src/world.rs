//! Kimlik görünümü (`World`), değnekçinin izlediği oturumlar, durum satırı seçimi ve teslim oturumu (grup 2). Hepsi SAF:
//! sahiplik indeksi, görünümler ve günlük olayları çağırandan gelir.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::identity::{self, OwnershipIndex};
use crate::prompts::object_of;
use crate::pyc;
use crate::types::{Action, Config, Project, SessionView, World};
use chrono::{Datelike, Local, NaiveDate, TimeZone};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;

/// `time.strptime(s, "%Y-%m-%dT%H:%M:%S")` deseni (`_strptime`: büyük/küçük harf duyarsız, tek haneli alanlar geçerli).
static STAMP_RE: Fancy = LazyLock::new(|| {
    pyc::py_regex(concat!(
        r"(?i)^(\d\d\d\d)-(1[0-2]|0[1-9]|[1-9])-(3[01]|[12]\d|0[1-9]|[1-9]| [1-9])",
        r"T(2[0-3]|[0-1]\d|\d):([0-5]\d|\d):(6[01]|[0-5]\d|\d)$"
    ))
});

impl World {
    /// Proje bu tick'te başlatılamaz mı (host erişilemez ya da kota tutuyor).
    ///
    /// py: World.start_held
    pub fn start_held(&self, project: &str) -> bool {
        self.unavailable.contains(project) || self.quota_held.contains(project)
    }

    /// Projenin host'u ("" = yerel).
    ///
    /// py: World.host_of
    pub fn host_of(&self, project: &str) -> &str {
        self.hosts.get(project).map_or("", String::as_str)
    }

    /// Projenin sahibi ("" = sahipsiz ya da çakışmalı).
    ///
    /// py: World.owner_of
    pub fn owner_of(&self, project: &str) -> &str {
        if self.conflicts.contains(project) {
            return "";
        }
        self.owners.get(project).map_or("", String::as_str)
    }

    /// py: World.owns
    pub fn owns(&self, project: &str) -> bool {
        !project.is_empty() && self.owner_of(project) == self.sid
    }

    /// Yalnız bu kimliğin (çakışmasız) projeleri.
    ///
    /// py: World.own_projects
    pub fn own_projects(&self, projects: &IndexMap<String, Project>) -> IndexMap<String, Project> {
        projects.iter().filter(|(n, _)| self.owns(n)).map(|(n, p)| (n.clone(), p.clone())).collect()
    }

    /// py: World._owner_tag
    pub fn owner_tag(&self, project: &str) -> &str {
        if self.conflicts.contains(project) {
            return "!conflict";
        }
        self.owners.get(project).map_or("", String::as_str)
    }

    /// Oturum adı -> (tür, anahtar): tür `brain` | `service` | `project` | "".
    ///
    /// py: World.resolve
    pub fn resolve(&self, name: &str) -> (&'static str, String) {
        if name.is_empty() {
            return ("", String::new());
        }
        if self.brains.contains_key(name) || name.starts_with(BRAIN_PREFIX) {
            return ("brain", name.to_string());
        }
        for (s, rec) in &self.services {
            let exact = rec.get("match").and_then(Value::as_str) == Some("exact");
            if name == s || (!exact && name.starts_with(s.as_str())) {
                return ("service", s.clone());
            }
        }
        let names = self.owners.keys().chain(self.conflicts.iter()).map(String::as_str);
        match identity::project_key(name, names) {
            "" => ("", String::new()),
            key => ("project", key.to_string()),
        }
    }

    /// py: World._class
    pub fn class(&self, kind: &str, key: &str) -> &'static str {
        match kind {
            "brain" if self.brains.get(key) == Some(&self.sid) => "brain_own",
            "brain" => "brain_other",
            "service" => "service",
            "project" if self.conflicts.contains(key) => "conflict",
            "project" => match self.owners.get(key).map_or("", String::as_str) {
                owner if owner == self.sid => "own",
                "" => "adhoc",
                _ => "other",
            },
            _ => "adhoc",
        }
    }

    /// Yalnız ada göre sınıf.
    ///
    /// py: World.name_class
    pub fn name_class(&self, name: &str) -> &'static str {
        let (kind, key) = self.resolve(name);
        self.class(kind, &key)
    }

    /// Ad + (varsa) instance blueprint'i: `own` | `manual` | `other` | `conflict` | `adhoc` | `brain_own` |
    /// `brain_other` | `service`.
    ///
    /// py: World.session_class
    pub fn session_class(&self, name: &str, blueprint: Option<&str>) -> &'static str {
        let c = self.name_class(name);
        if matches!(c, "brain_own" | "brain_other" | "service") {
            return c;
        }
        let mut b = "adhoc";
        if let Some(bp) = blueprint.filter(|bp| !bp.is_empty() && *bp != name) {
            if self.brains.contains_key(bp) {
                b = "brain_other";
            } else if self.services.contains_key(bp) {
                b = "service";
            } else if self.owners.contains_key(bp) || self.conflicts.contains(bp) {
                b = self.class("project", bp);
            }
        }
        if P_DENY.contains(&c) {
            return c;
        }
        if P_DENY.contains(&b) {
            return b;
        }
        if c != "own" && b != "own" {
            return "adhoc";
        }
        if self.is_manual(name, blueprint) {
            "manual"
        } else {
            "own"
        }
    }

    /// Oturumun ait olduğu (bu kimliğin) proje adı: blueprint öncelikli; yoksa "".
    ///
    /// py: World.owned_key
    pub fn owned_key(&self, name: &str, blueprint: Option<&str>) -> String {
        match blueprint {
            Some(bp) if bp != name && self.owns(bp) => bp.to_string(),
            _ => self.project_key(name),
        }
    }

    /// Projenin sahiplik kaydı var ve bu oturum kayıttaki ad değil: sahibin elle açtığı oturum.
    ///
    /// py: World.is_manual
    pub fn is_manual(&self, name: &str, blueprint: Option<&str>) -> bool {
        let key = self.owned_key(name, blueprint);
        !key.is_empty() && self.owned.get(&key).is_some_and(|o| o != name)
    }

    /// Ad bu kimliğin projesine çözülüyorsa proje adı, değilse "".
    ///
    /// py: World.project_key
    pub fn project_key(&self, name: &str) -> String {
        match self.resolve(name) {
            ("project", key) if self.owns(&key) => key,
            _ => String::new(),
        }
    }
}

/// `ownership_index()` çıktısından kimliğin görünümü. `owned`: `state.owned` (boş değer -> "").
///
/// py: world_for
pub fn world_for(
    sid: &str,
    index: &OwnershipIndex,
    brain_name: &str,
    starts_left: Option<i64>,
    owned: Option<&Map<String, Value>>,
) -> World {
    let mut brains: IndexMap<String, String> =
        index.brains.iter().filter(|(_, s)| *s != sid).map(|(n, s)| (n.clone(), s.clone())).collect();
    let mine = if brain_name.is_empty() { identity::brain_name_for(sid) } else { brain_name.to_string() };
    brains.insert(mine, sid.to_string());
    World {
        sid: sid.to_string(),
        owners: index.owners.clone(),
        conflicts: index.conflicts.keys().cloned().collect(),
        brains,
        services: index.services.clone(),
        is_adhoc_owner: sid == "default",
        starts_left,
        hosts: index.hosts.clone(),
        owned: owned
            .into_iter()
            .flatten()
            .map(|(k, v)| (k.clone(), if pyc::truthy(v) { pyc::str_of(v) } else { String::new() }))
            .collect(),
        unavailable: BTreeSet::new(),
        quota_held: BTreeSet::new(),
    }
}

// ── değnekçinin izlediği oturumlar ────────────────────────────────────────────

/// `str(d.get(key) or "")`
fn text_of(d: &Map<String, Value>, key: &str) -> String {
    d.get(key).filter(|v| pyc::truthy(v)).map(pyc::str_of).unwrap_or_default()
}

/// Yerel saatli olay damgasının epoch karşılığı (`time.mktime(time.strptime(..))`); biçim bozuksa `None`.
fn local_epoch(stamp: &str) -> Option<f64> {
    let caps = STAMP_RE.as_ref()?.captures(stamp).ok()??;
    let field = |i: usize| caps.get(i).and_then(|m| pyc::to_int(&Value::from(m.as_str())));
    let small = |i: usize| field(i).and_then(|v| u32::try_from(v).ok());
    let date = NaiveDate::from_ymd_opt(i32::try_from(field(1)?).ok()?, small(2)?, small(3)?)?;
    if date.year() < 1 {
        return None;
    }
    let second = field(6)?;
    let extra = (second - 59).max(0);
    let naive = date.and_hms_opt(small(4)?, small(5)?, u32::try_from(second - extra).ok()?)?;
    let local = Local.from_local_datetime(&naive).earliest().map(|t| t.timestamp()).or_else(|| {
        // yaz saati boşluğu: bir saat sonrasından geri hesapla
        let later = naive.checked_add_signed(chrono::TimeDelta::hours(1))?;
        Local.from_local_datetime(&later).earliest().map(|t| t.timestamp() - 3600)
    })?;
    Some((local + extra) as f64)
}

/// Değnekçi bu oturumu kendisi açtı ya da sürdü mü (olay günlüğünde kanıt)?
///
/// py: owned_evidence
pub fn owned_evidence(events: &[Map<String, Value>], name: &str, project: &str, started_at: f64) -> bool {
    for e in events {
        let Some(ev) = e.get("event").and_then(Value::as_str).filter(|ev| OWNED_EVIDENCE_EVENTS.contains(ev)) else {
            continue;
        };
        if e.get("ok") == Some(&Value::Bool(false)) {
            continue;
        }
        let kind_ok = e.get("kind").and_then(Value::as_str).is_some_and(|k| P_OWNED_EVIDENCE_KINDS.contains(&k));
        if ev == "action" && !kind_ok {
            continue;
        }
        if ev == "outcome" && e.get("result").and_then(Value::as_str) != Some("changed") {
            continue;
        }
        let n = text_of(e, "name");
        if n == name {
            return true;
        }
        if n == project && started_at != 0.0 {
            let ts = text_of(e, "ts");
            if local_epoch(pyc::head(&ts, 19)).is_some_and(|ts| ts >= started_at) {
                return true;
            }
        }
    }
    false
}

/// `update_owned` değişiklik satırı.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnedChange {
    pub project: String,
    pub name: String,
    /// `adopt` | `none` | `ambiguous` | `seed` | `seed_none` | `seed_manual`
    pub how: String,
    pub sessions: Vec<String>,
}

/// `(oturum adı, proje, açılış zamanı) -> değnekçinin sürdüğüne kanıt var mı`.
pub type Evidence<'a> = &'a dyn Fn(&str, &str, f64) -> bool;

/// Kaydı olmayan bu kimliğin projelerine sahiplik kaydı yazar. `evidence(ad, proje, açılış)` yalnız `seeding`de sorulur.
///
/// py: update_owned
pub fn update_owned(
    owned: &IndexMap<String, String>,
    views: &[SessionView],
    world: &World,
    projects: &IndexMap<String, Project>,
    seeding: bool,
    evidence: Option<Evidence<'_>>,
) -> (IndexMap<String, String>, Vec<OwnedChange>) {
    let mut out = owned.clone();
    let mut changes = Vec::new();
    let mut live: IndexMap<String, Vec<&SessionView>> = IndexMap::new();
    for v in views.iter().filter(|v| v.running) {
        let key = world.owned_key(&v.name, v.blueprint.as_deref());
        if !key.is_empty() {
            live.entry(key).or_default().push(v);
        }
    }
    for p in world.own_projects(projects).keys() {
        if out.contains_key(p) || world.unavailable.contains(p) {
            continue;
        }
        let vs: &[&SessionView] = live.get(p).map_or(&[], Vec::as_slice);
        let (pick, how) = match evidence.filter(|_| seeding) {
            Some(evidence) => {
                let ev: Vec<&&SessionView> = vs.iter().filter(|v| evidence(&v.name, p, v.started_at)).collect();
                let pick = match ev.as_slice() {
                    [only] => only.name.clone(),
                    _ => String::new(),
                };
                let how = if !pick.is_empty() {
                    "seed"
                } else if vs.is_empty() {
                    "seed_none"
                } else {
                    "seed_manual"
                };
                (pick, how)
            }
            None => {
                let pick = match vs {
                    [only] => only.name.clone(),
                    _ => String::new(),
                };
                let how = if !pick.is_empty() {
                    "adopt"
                } else if vs.is_empty() {
                    "none"
                } else {
                    "ambiguous"
                };
                (pick, how)
            }
        };
        out.insert(p.clone(), pick.clone());
        changes.push(OwnedChange {
            project: p.clone(),
            name: pick,
            how: how.to_string(),
            sessions: vs.iter().map(|v| v.name.clone()).collect(),
        });
    }
    (out, changes)
}

/// `/api/status` satırlarından değnekçinin göreceği oturumlar. `fresh_hosts` = durumu taze uzak host'lar.
///
/// py: select_rows
pub fn select_rows(
    rows: &[Map<String, Value>],
    world: &World,
    fresh_hosts: &BTreeSet<String>,
) -> Vec<Map<String, Value>> {
    let mut out = Vec::new();
    for r in rows {
        if text_of(r, "cli") == "shell" {
            continue;
        }
        let host = identity::normalize_host(r.get("host").unwrap_or(&Value::Null));
        let name = text_of(r, "name");
        let (kind, key) = world.resolve(&name);
        let proj_host = if kind == "project" { world.host_of(&key) } else { "" };
        if host.is_empty() {
            let instance = r.get("instance").is_some_and(pyc::truthy);
            let bp = r.get("blueprint").filter(|_| instance).and_then(Value::as_str);
            let remote_bp = bp.is_some_and(|bp| !bp.is_empty() && bp != name && !world.host_of(bp).is_empty());
            if !proj_host.is_empty() || remote_bp {
                continue;
            }
            out.push(r.clone());
        } else if kind == "project" && proj_host == host && fresh_hosts.contains(&host) {
            out.push(r.clone());
        }
    }
    out
}

/// `name`in projesinin başka bir çalışan oturumu var mı (beyin sayılmaz).
///
/// py: _sibling_running
pub fn sibling_running(
    views: &[SessionView],
    name: &str,
    projects: &IndexMap<String, Project>,
    cfg: &Config,
    world: Option<&World>,
) -> bool {
    let other = |x: &&SessionView| x.running && x.name != name && x.name != cfg.brain_name;
    if let Some(world) = world {
        let key = world.project_key(name);
        return !key.is_empty()
            && views.iter().filter(other).any(|x| world.resolve(&x.name) == ("project", key.clone()));
    }
    let names = || projects.keys().map(String::as_str);
    let key = identity::project_key(name, names());
    !key.is_empty() && views.iter().filter(other).any(|x| identity::project_key(&x.name, names()) == key)
}

/// Cevabın/direktifin gideceği çalışan oturum: önce `source`, yoksa en kısa (eşitse sözlük sırasında ilk) ad.
///
/// py: pick_delivery_view
pub fn pick_delivery_view<'a>(views: &'a [SessionView], project: &str, source: &str) -> Option<&'a SessionView> {
    let mine = || views.iter().filter(|x| x.running && x.project() == project);
    mine()
        .find(|x| !source.is_empty() && x.name == source)
        .or_else(|| mine().min_by_key(|x| (pyc::len(&x.name), x.name.as_str())))
}

/// Direktif teslim döngüsü: her `(proje, make)` için teslim oturumunu seçer; meşgul / alt ajanlı / alınmış oturumu atlar.
/// `taken` yerinde güncellenir; dönüş: (eylemler, yeni state). Eylem yoksa state aynen döner.
///
/// py: plan_deliveries
pub fn plan_deliveries<P, F>(
    entries: impl IntoIterator<Item = (P, F)>,
    mine: &[SessionView],
    taken: &mut BTreeSet<String>,
    state: &Map<String, Value>,
    now: f64,
    limit: i64,
) -> Result<(Vec<Action>, Map<String, Value>), BadValue>
where
    P: AsRef<str>,
    F: Fn(&SessionView) -> Action,
{
    let mut out: Vec<Action> = Vec::new();
    let mut lda: Option<Map<String, Value>> = None;
    for (project, make) in entries {
        let Some(v) = pick_delivery_view(mine, project.as_ref(), "") else { continue };
        if v.busy == Some(true) || taken.contains(&v.name) || v.subagent_active || v.subagent_unknown {
            continue;
        }
        out.push(make(v));
        taken.insert(v.name.clone());
        if lda.is_none() {
            lda = Some(object_of(state.get("last_directive_at"))?.cloned().unwrap_or_default());
        }
        if let Some(map) = lda.as_mut() {
            map.insert(v.name.clone(), Value::from(now));
        }
        if i64::try_from(out.len()).unwrap_or(i64::MAX) >= limit {
            break;
        }
    }
    let mut st = state.clone();
    if let Some(map) = lda {
        st.insert("last_directive_at".to_string(), Value::Object(map));
    }
    Ok((out, st))
}

/// Oturum makine geneli (`max_active_total`) slotu yer mi: yalnız mesaj alan/meşgul oturum.
///
/// py: holds_total_slot
pub fn holds_total_slot(v: &SessionView, now: f64, last_directive_at: f64) -> bool {
    if !v.running {
        return false;
    }
    if v.busy != Some(false) || v.subagent_active || v.subagent_unknown {
        return true;
    }
    let mut last = v.last_activity;
    for x in [v.started_at, last_directive_at] {
        if x > last {
            last = x;
        }
    }
    last != 0.0 && (now - last) < SLOT_RECENT_SECONDS
}
