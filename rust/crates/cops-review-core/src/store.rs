//! `review_pool.json` / `review_history.json` / `findings.json` depoları. Yazım yolu `cops-state` (`statedocs`) üzerinden:
//! canlıda `store_backend=db`de doğruluk kaynağı DB, dosya ayna. Kilit Python ile AYNI dosyada (`<kök>/.lock`, flock).
use crate::clock;
use crate::error::{Error, Result};
use crate::flow::{sha1_hex, APPROVABLE_STATES, REJECTABLE_STATES, VERIFIABLE_STATES};
use crate::parse::Finding;
use crate::planner::pair_key;
use crate::py;
use crate::targets::*;
use crate::unicode13::unassigned;
use cops_state::json::{Json, Map};
use cops_state::statedocs::Read;
use cops_state::{Backend, StateDocs};
use regex::Regex;
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, LazyLock};
use std::time::{Duration, Instant};
use unicode_normalization::char::canonical_combining_class;
use unicode_normalization::UnicodeNormalization;

/// 2026-11-17T12:41:25+03:00: abonelik kipinin açıldığı an (R10 göçü).
pub const R10_SUB_SINCE: f64 = 1794908485.0;
pub const R10_MARK: &str = "r10_sub_migrated";
pub const LOCK_TIMEOUT: Duration = Duration::from_secs(10);
const FINISHED: [&str; 5] = ["done", "partial", "error", "model_fallback", "limit"];

/// `StewardPaths`in reviewer alanları.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewPaths {
    pub root: PathBuf,
    pub reviews: PathBuf,
    pub review_pool: PathBuf,
    pub review_history: PathBuf,
    pub findings: PathBuf,
    pub lock: PathBuf,
}

impl ReviewPaths {
    pub fn at(root: impl Into<PathBuf>) -> ReviewPaths {
        let root: PathBuf = root.into();
        ReviewPaths {
            reviews: root.join("reviews"),
            review_pool: root.join("review_pool.json"),
            review_history: root.join("review_history.json"),
            findings: root.join("findings.json"),
            lock: root.join(".lock"),
            root,
        }
    }

    /// `paths_for(sid)`: `default` kökü `<durum>/steward`, diğerleri `<durum>/steward/stewards/<sid>`.
    pub fn for_sid(state_dir: &Path, sid: &str) -> Result<ReviewPaths> {
        if sid.is_empty() || !sid.bytes().all(|b| b.is_ascii_lowercase()) {
            return Err(Error::Value(format!("invalid steward id: {sid:?}")));
        }
        let base = state_dir.join("steward");
        Ok(ReviewPaths::at(if sid == "default" { base } else { base.join("stewards").join(sid) }))
    }
}

/// Tutulan kimlik kilidi; düşünce bırakılır. İç içe alınmaz: kilit altındaki işlevler `&StewardLock` ister.
#[derive(Debug)]
pub struct StewardLock {
    _file: File,
}

/// `sw.steward_lock`: dışlayıcı `flock`, zaman aşımında [`Error::LockTimeout`].
pub fn steward_lock(path: &Path, timeout: Duration) -> Result<StewardLock> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    let f = OpenOptions::new().read(true).write(true).create(true).truncate(false).mode(0o600).open(path)?;
    let deadline = Instant::now() + timeout;
    loop {
        // SAFETY: açık ve bu işlev boyunca yaşayan bir tanıtıcı.
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
            return Ok(StewardLock { _file: f });
        }
        let e = std::io::Error::last_os_error();
        match e.kind() {
            std::io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    return Err(Error::LockTimeout(format!("{} within {}s", path.display(), timeout.as_secs_f64())));
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            std::io::ErrorKind::Interrupted => {}
            _ => return Err(e.into()),
        }
    }
}

/// `_corrupt_backup`: bozuk dosyanın kanıt kopyası (`<yol>.corrupt-<ts>`, değiştirilme zamanı korunur); hata yutulur.
fn corrupt_backup(path: &Path) {
    let mut dst = path.as_os_str().to_os_string();
    dst.push(format!(".corrupt-{}", clock::now() as i64));
    let dst = PathBuf::from(dst);
    if std::fs::copy(path, &dst).is_ok() {
        if let Ok(t) = std::fs::metadata(path).and_then(|m| m.modified()) {
            if let Ok(f) = OpenOptions::new().write(true).open(&dst) {
                let _ = f.set_modified(t);
            }
        }
    }
}

pub struct ReviewStore {
    docs: Arc<StateDocs>,
    pub paths: ReviewPaths,
    pub lock_timeout: Duration,
}

impl ReviewStore {
    pub fn new(docs: Arc<StateDocs>, paths: ReviewPaths) -> ReviewStore {
        ReviewStore { docs, paths, lock_timeout: LOCK_TIMEOUT }
    }

    pub fn lock(&self) -> Result<StewardLock> {
        steward_lock(&self.paths.lock, self.lock_timeout)
    }

    /// `sw._load_json`: yok ya da bozuk -> `None` (bozukta kanıt yedeği).
    fn load_json(&self, path: &Path) -> Result<Option<Json>> {
        let backend = self.docs.backend();
        let r = if backend == Backend::Files {
            // Python dosya kipinde UTF-8 olmayan içerikte istisna fırlatır (yalnız JSON hatasında yedek alır).
            match std::fs::read(path) {
                Ok(b) => match String::from_utf8(b) {
                    Ok(t) => Json::parse(&t).map(Read::Value).unwrap_or(Read::Corrupt),
                    Err(_) => return Err(Error::Value(format!("{}: utf-8 değil", path.display()))),
                },
                Err(_) => Read::Missing,
            }
        } else {
            let name = self.docs.name_for(path);
            let r = self.docs.read(&name, path);
            if backend == Backend::Dual
                && matches!(r, Read::Value(_))
                && cops_state::statedocs::read_file(path) == Read::Corrupt
            {
                corrupt_backup(path); // DB'den dönüldü ama dosya bozuk: Python da yedek alır
            }
            r
        };
        Ok(match r {
            Read::Value(v) => Some(v),
            Read::Missing => None,
            Read::Corrupt => {
                corrupt_backup(path);
                None
            }
        })
    }

    /// `sw._save_json` (0600).
    fn save_json(&self, path: &Path, obj: &Json) -> Result<()> {
        if let Some(d) = path.parent() {
            std::fs::create_dir_all(d)?;
        }
        let name = self.docs.name_for(path);
        self.docs.write(&name, path, obj, Some(0o600)).map(|_| ()).map_err(|e| Error::State(e.to_string()))
    }

    pub fn load_pool(&self) -> Result<Json> {
        let raw = self.load_json(&self.paths.review_pool)?;
        Ok(match raw {
            Some(v) if v.get("projects").and_then(Json::as_object).is_some() => v,
            _ => {
                let mut m = Map::new();
                m.insert("projects".into(), Json::object());
                Json::Object(m)
            }
        })
    }

    pub fn save_pool(&self, pool: &Json) -> Result<()> {
        self.save_json(&self.paths.review_pool, pool)
    }

    pub fn load_history(&self) -> Result<Map> {
        let mut raw = match self.load_json(&self.paths.review_history)? {
            Some(Json::Object(m)) => m,
            _ => Map::new(),
        };
        normalize_history(&mut raw)?;
        Ok(raw)
    }

    /// `runs` son [`HISTORY_RUNS_MAX`] kayda kırpılır.
    pub fn save_history(&self, hist: &Map) -> Result<()> {
        let mut h = hist.clone();
        let runs = match h.get("runs") {
            Some(Json::Array(a)) => a[a.len().saturating_sub(HISTORY_RUNS_MAX)..].to_vec(),
            Some(v) if v.truthy() => return Err(Error::Value("history[\"runs\"] liste değil".into())),
            _ => Vec::new(),
        };
        h.insert("runs".into(), Json::Array(runs));
        self.save_json(&self.paths.review_history, &Json::Object(h))
    }

    /// `set_block`: `key` mod ya da `mod/slug`.
    pub fn set_block(&self, key: &str, until: f64, reason: &str) -> Result<()> {
        let _g = self.lock()?;
        let mut hist = self.load_history()?;
        let mut e = Map::new();
        e.insert("until".into(), Json::Float(until));
        e.insert("reason".into(), reason.into());
        e.insert("set_at".into(), Json::Float(clock::now()));
        crate::limits::blocks_mut(&mut hist)?.insert(key.into(), Json::Object(e));
        self.save_history(&hist)
    }

    /// Çift kaydını kilit altında okuyup-değiştirip-yazar; güncel kaydı döner.
    pub fn update_pair(&self, proj: &str, t: &ReviewTarget, mut fields: Map) -> Result<Map> {
        let status = fields.get("status").filter(|v| **v != Json::Null);
        if let Some(s) = status {
            if !py::str_in(Some(s), &PAIR_STATUSES) {
                return Err(Error::Value(format!("invalid pair status: {}", py::repr(s))));
            }
        }
        let _g = self.lock()?;
        let mut hist = self.load_history()?;
        let key = pair_key(proj, t);
        let pairs = hist
            .get_mut("pairs")
            .and_then(Json::as_object_mut)
            .ok_or_else(|| Error::Value("history[\"pairs\"] nesne değil".into()))?;
        let mut rec = match pairs.get(&key) {
            Some(Json::Object(m)) => m.clone(),
            Some(v) if v.truthy() => return Err(Error::Value(format!("çift kaydı nesne değil: {key}"))),
            _ => Map::new(),
        };
        if py::is_str(fields.get("status"), "running") && !fields.contains_key("attempts") {
            let started = py::num(fields.get("started_at"));
            let started = if started != 0.0 { started } else { clock::now() };
            let stale = py::is_str(rec.get("status"), "done")
                || started - py::num(rec.get("started_at")) >= WINDOW_SECONDS as f64;
            let prev = if stale { 0 } else { py::num(rec.get("attempts")).trunc() as i64 };
            fields.insert("attempts".into(), Json::Int(prev.saturating_add(1)));
        }
        let finished = py::str_in(fields.get("status"), &FINISHED);
        for (k, v) in fields {
            rec.insert(k, v);
        }
        pairs.insert(key.clone(), Json::Object(rec.clone()));
        if finished {
            let get = |k: &str| rec.get(k).cloned().unwrap_or(Json::Null);
            let mut run = Map::new();
            run.insert("pair".into(), key.into());
            run.insert("status".into(), get("status"));
            run.insert("at".into(), get("finished_at"));
            run.insert("file".into(), get("file"));
            run.insert("io_file".into(), get("io_file"));
            run.insert("seconds".into(), run_seconds(&rec).map_or(Json::Null, Json::Float));
            match hist.get_mut("runs") {
                Some(Json::Array(a)) => a.push(Json::Object(run)),
                _ => return Err(Error::Value("history[\"runs\"] liste değil".into())),
            }
        }
        self.save_history(&hist)?;
        Ok(rec)
    }

    pub fn load_findings(&self) -> Result<Map> {
        Ok(match self.load_json(&self.paths.findings)? {
            Some(Json::Object(m)) => m,
            _ => Map::new(),
        })
    }

    pub fn save_findings(&self, findings: Map) -> Result<()> {
        self.save_json(&self.paths.findings, &Json::Object(findings))
    }

    /// Ayrıştırılmış bulguları `state=new` (ya da yinelenense `dup`) ekler; eklenen yeni fid'ler döner.
    pub fn add_findings(&self, proj: &str, review_file: &str, parsed: &[Finding]) -> Result<Vec<String>> {
        self.add_findings_at(proj, review_file, parsed, clock::now)
    }

    pub fn add_findings_at(
        &self,
        proj: &str,
        review_file: &str,
        parsed: &[Finding],
        now: impl Fn() -> f64,
    ) -> Result<Vec<String>> {
        static NON_ALNUM: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^A-Za-z0-9]+").unwrap());
        let reviews = self.paths.reviews.to_string_lossy().into_owned();
        let root = format!("{}/", reviews.trim_end_matches('/'));
        let rel = if review_file.starts_with(&root) {
            py::relpath(review_file, &reviews)
        } else {
            review_file.to_string()
        };
        let base = NON_ALNUM.replace_all(&rel, "").into_owned();
        let mut added = Vec::new();
        let _g = self.lock()?;
        let mut data = self.load_findings()?;
        let mut by_key: HashMap<String, String> = HashMap::new();
        for (ofid, orec) in &data {
            let Some(o) = orec.as_object() else { continue };
            if py::is_str(o.get("state"), "dup")
                || !py::is_str(o.get("project"), proj)
                || py::is_str(o.get("review_file"), review_file)
            {
                continue;
            }
            let okey = match o.get("key").filter(|k| k.truthy()) {
                Some(k) => py::to_str(k),
                None => finding_key(
                    proj,
                    &py::str_or_empty(o.get("where")),
                    &py::str_or_empty(o.get("title")),
                ),
            };
            let better = match by_key.get(&okey).and_then(|f| data.get(f)).and_then(Json::as_object) {
                Some(cur) => canon_rank(o) < canon_rank(cur),
                None => true,
            };
            if better {
                by_key.insert(okey, ofid.clone());
            }
        }
        let mut changed = false;
        for f in parsed {
            let mut fid = format!("{}:{base}:{}", slug_model(proj), f.r#ref);
            if let Some(old) = data.get(&fid) {
                let old = old.as_object().ok_or_else(|| Error::Value(format!("bulgu kaydı nesne değil: {fid}")))?;
                if py::is_str(old.get("review_file"), review_file) {
                    continue;
                }
                fid = format!("{fid}~{}", &sha1_hex(review_file.as_bytes())[..6]);
                if data.contains_key(&fid) {
                    continue;
                }
            }
            let key = finding_key(proj, &f.r#where, &f.title);
            let mut rec = Map::new();
            let mut put = |k: &str, v: Json| rec.insert(k.to_string(), v);
            put("project", proj.into());
            put("review_file", review_file.into());
            put("ref", f.r#ref.as_str().into());
            put("severity", f.severity.as_str().into());
            put("title", f.title.as_str().into());
            put("where", f.r#where.as_str().into());
            put("body", f.body.as_str().into());
            put("state", "new".into());
            put("verdict", "".into());
            put("verdict_at", Json::Null);
            put("decided_by", "".into());
            put("decided_at", Json::Null);
            put("exported_to", "".into());
            put("created_at", Json::Float(now()));
            put("key", key.as_str().into());
            if let Some(canon_id) = by_key.get(&key) {
                rec.insert("state".into(), "dup".into());
                rec.insert("dup_of".into(), canon_id.as_str().into());
                if let Some(canon) = data.get_mut(canon_id).and_then(Json::as_object_mut) {
                    let cur = canon.get("severity");
                    let cur = if py::truthy(cur) { py::str_or_empty(cur) } else { "P9".into() };
                    if py::str_in(canon.get("state"), &["new", "verify_sent", "unclear", "verified"]) && f.severity < cur {
                        canon.insert("severity".into(), f.severity.as_str().into());
                    }
                }
            } else {
                added.push(fid.clone());
            }
            data.insert(fid, Json::Object(rec));
            changed = true;
        }
        if changed {
            self.save_findings(data)?;
        }
        Ok(added)
    }

    /// Doğrulama direktifi gittikten sonra bulguları `verify_sent` yapar.
    pub fn mark_verify_sent(&self, fids: &[String], session: &str, baseline: &str, now: f64) -> Result<Vec<String>> {
        let mut done = Vec::new();
        let _g = self.lock()?;
        let mut data = self.load_findings()?;
        for fid in fids {
            let Some(rec) = data.get_mut(fid).and_then(Json::as_object_mut) else { continue };
            if py::str_in(rec.get("state"), &VERIFIABLE_STATES) {
                rec.insert("state".into(), "verify_sent".into());
                rec.insert("verify_sent_at".into(), Json::Float(now));
                rec.insert("verify_session".into(), session.into());
                rec.insert("verify_baseline".into(), baseline.into());
                done.push(fid.clone());
            }
        }
        if !done.is_empty() {
            self.save_findings(data)?;
        }
        Ok(done)
    }

    /// Sahibin bulgu kararı: `approve` | `reject` | `undup`. Python'un döndürdüğü sözlük.
    pub fn decide_finding(&self, fid: &str, action: &str, now: f64, by: &str) -> Result<Json> {
        let fail = |msg: String, state: Option<Json>| {
            let mut m = Map::new();
            m.insert("ok".into(), Json::Bool(false));
            m.insert("error".into(), msg.into());
            if let Some(s) = state {
                m.insert("state".into(), s);
            }
            Ok(Json::Object(m))
        };
        let ok = |state: &str| {
            let mut m = Map::new();
            m.insert("ok".into(), Json::Bool(true));
            m.insert("id".into(), fid.into());
            m.insert("state".into(), state.into());
            Ok(Json::Object(m))
        };
        if !["approve", "reject", "undup"].contains(&action) {
            return fail("action must be approve, reject or undup".into(), None);
        }
        let _g = self.lock()?;
        let mut data = self.load_findings()?;
        let Some(rec) = data.get_mut(fid).and_then(Json::as_object_mut) else {
            return fail(format!("unknown finding: {fid}"), None);
        };
        let st = rec.get("state").cloned().unwrap_or(Json::Null);
        let target = if action == "undup" {
            if !py::is_str(Some(&st), "dup") {
                return fail(
                    format!("cannot undup a finding in state {} (allowed: dup)", py::repr(&st)),
                    Some(st),
                );
            }
            rec.shift_remove("dup_of");
            "new"
        } else {
            let (allowed, target): (&[&str], &str) = if action == "approve" {
                (&APPROVABLE_STATES, "approved")
            } else {
                (&REJECTABLE_STATES, "rejected")
            };
            if !py::str_in(Some(&st), allowed) {
                return fail(
                    format!(
                        "cannot {action} a finding in state {} (allowed: {})",
                        py::repr(&st),
                        allowed.join(", ")
                    ),
                    Some(st),
                );
            }
            target
        };
        rec.insert("state".into(), target.into());
        rec.insert("decided_by".into(), by.into());
        rec.insert("decided_at".into(), Json::Float(now));
        self.save_findings(data)?;
        ok(target)
    }
}

/// `load_history`nin normalleştirmesi: `pairs`/`runs`/`version` + R10 göçü.
pub fn normalize_history(raw: &mut Map) -> Result<()> {
    if raw.get("pairs").and_then(Json::as_object).is_none() {
        raw.insert("pairs".into(), Json::object());
    }
    if raw.get("runs").and_then(Json::as_array).is_none() {
        raw.insert("runs".into(), Json::Array(Vec::new()));
    }
    raw.insert("version".into(), Json::Int(HISTORY_VERSION));
    migrate_r10_sub(raw)?;
    Ok(())
}

/// Abonelik açıldıktan sonra sub'suz anahtarla yazılan claude çiftlerini `-sub` anahtarına taşır (tek seferlik).
pub fn migrate_r10_sub(hist: &mut Map) -> Result<usize> {
    if py::truthy(hist.get(R10_MARK)) {
        return Ok(0);
    }
    let pairs = hist
        .get_mut("pairs")
        .and_then(Json::as_object_mut)
        .ok_or_else(|| Error::Value("history[\"pairs\"] yok".into()))?;
    let mut moved = 0;
    let keys: Vec<String> = pairs.keys().cloned().collect();
    for k in keys {
        let Some((proj, rest)) = k.split_once('|') else { continue };
        if !rest.starts_with("claude/") {
            continue;
        }
        let Some(rec) = pairs.get(&k).and_then(Json::as_object) else { continue };
        if py::float_or_zero(rec.get("started_at"))? < R10_SUB_SINCE {
            continue;
        }
        let (model, at, eff) = match rest.split_once('@') {
            Some((m, e)) => (m, "@", e),
            None => (rest, "", ""),
        };
        if model.ends_with("-sub") {
            continue;
        }
        let nk = format!("{proj}|{model}-sub{at}{eff}");
        if pairs.contains_key(&nk) {
            continue;
        }
        if let Some(v) = pairs.shift_remove(&k) {
            pairs.insert(nk, v);
            moved += 1;
        }
    }
    hist.insert(R10_MARK.into(), Json::Bool(true));
    Ok(moved)
}

/// Koşunun duvar süresi (sn, 1 basamak); tutarsızsa `None`.
pub fn run_seconds(rec: &Map) -> Option<f64> {
    let (a, b) = (py::num(rec.get("started_at")), py::num(rec.get("finished_at")));
    (a > 0.0 && b >= a).then(|| round_to(b - a, 1))
}

/// Python `round(x, n)`.
pub fn round_to(x: f64, n: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.n$}").parse().unwrap_or(x)
}

/// Büyük/küçük harf + aksan katlama (Türkçe İ/I/ı/i dahil).
fn fold(v: &str) -> String {
    let t = v.replace('İ', "I").replace('ı', "i");
    // Python 3.10 (Unicode 13) tanımadığı noktayı ayrıştırmaz, ccc=0 sayar: o noktalarda böl, aralarını NFKD'le.
    let mut plain = String::new();
    for part in t.split_inclusive(unassigned) {
        let (head, tail) = match part.chars().next_back().filter(|c| unassigned(*c)) {
            Some(c) => (&part[..part.len() - c.len_utf8()], Some(c)),
            None => (part, None),
        };
        plain.extend(head.nfkd().filter(|c| canonical_combining_class(*c) == 0));
        plain.extend(tail);
    }
    py::casefold(&plain)
}

/// Bulgu kimliği: (proje, dosya, normalize başlık) SHA-1'inin ilk 16 hanesi.
pub fn finding_key(proj: &str, r#where: &str, title: &str) -> String {
    static LINK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\[([^\]]*)\]\([^)]*\)").unwrap());
    static NON: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^0-9a-z]+").unwrap());
    let mut w = py::strip(r#where);
    if let Some(m) = LINK.captures(w) {
        w = py::strip(m.get(1).map_or("", |g| g.as_str()));
    }
    let trimmed = w.trim_matches('`');
    let cut = trimmed.split([':', '#']).next().unwrap_or("");
    let fil = py::strip(cut).trim_matches('`');
    let fil = fil.strip_prefix("./").or_else(|| fil.strip_prefix("file://")).unwrap_or(fil);
    let folded = fold(title);
    let ttl = NON.replace_all(&folded, " ");
    let ttl = py::strip(&ttl);
    sha1_hex(format!("{proj}\0{fil}\0{ttl}").as_bytes())[..16].to_string()
}

/// Tekilleştirmede kanonik kayıt sırası (küçük = tercih).
fn canon_rank(rec: &Map) -> (u8, f64) {
    let st = rec.get("state");
    let tier = if py::str_in(st, &["verified", "approved", "exported"]) {
        0
    } else if py::str_in(st, &["refuted", "rejected"]) {
        2
    } else {
        1
    };
    (tier, py::num(rec.get("created_at")))
}
