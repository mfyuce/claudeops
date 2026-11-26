//! Kurtarma kararları (grup 3): API hatası ve otomatik "devam", döngü kesici (L4), sonuç doğrulama (L5). Hepsi SAF;
//! eylemi uygulamak ve state'i yazmak çağırandadır.

use crate::cards::BadValue;
use crate::consts_gen::*;
use crate::identity::derived_of;
use crate::prompts::{bad, items_of, object_of};
use crate::pyc;
use crate::types::{Action, SessionView};
use indexmap::IndexMap;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::sync::LazyLock;

type Fancy = LazyLock<Option<fancy_regex::Regex>>;
type Doc = Map<String, Value>;

static API_ERR_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_API_ERR_RE.as_str()));
static API_RETRY_HEAD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_API_RETRY_HEAD_RE.as_str()));
static API_RETRY_WORD_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_API_RETRY_WORD_RE.as_str()));
static DATED_TAIL_RE: Fancy = LazyLock::new(|| pyc::py_regex(P_DATED_TAIL_RE.as_str()));

/// `float(v or 0)`
pub(crate) fn float_of(v: Option<&Value>) -> Result<f64, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(0.0),
        Some(v) => pyc::to_float(v).ok_or_else(|| bad(v)),
    }
}

/// `int(v or 0)`
pub(crate) fn int_of(v: Option<&Value>) -> Result<i64, BadValue> {
    match v.filter(|v| pyc::truthy(v)) {
        None => Ok(0),
        Some(v) => pyc::to_int(v).ok_or_else(|| bad(v)),
    }
}

/// `dict(v or {})` (ikili listesi kabul etmesi taklit edilmez).
pub(crate) fn dict_of(v: Option<&Value>) -> Result<Doc, BadValue> {
    Ok(object_of(v)?.cloned().unwrap_or_default())
}

pub(crate) fn truthy_at(d: &Doc, key: &str) -> bool {
    d.get(key).is_some_and(pyc::truthy)
}

/// `json!({..})` ile kurulan nesneyi `Map` olarak verir.
pub(crate) fn doc(v: Value) -> Doc {
    match v {
        Value::Object(o) => o,
        _ => Map::new(),
    }
}

fn sha_head(text: &str, n: usize) -> String {
    pyc::head(&pyc::sha1_hex(text.as_bytes()), n).to_string()
}

/// Son asistan metni için: "" (API hatası değil) | "retry" ("devam" işe yarayabilir) | "fatal".
///
/// py: api_error_kind
pub fn api_error_kind(text: &str) -> &'static str {
    let folded = pyc::ci_input(text);
    let Some(body) = API_ERR_RE.as_ref().and_then(|r| r.captures(&folded).ok().flatten()?.name("body")) else {
        return "";
    };
    let body = pyc::head(body.as_str(), 300);
    if pyc::is_match(&API_RETRY_HEAD_RE, body) || pyc::is_match(&API_RETRY_WORD_RE, body) {
        "retry"
    } else {
        "fatal"
    }
}

// ── L4 döngü kesici ───────────────────────────────────────────────────────────

/// Hedefin ilerleme imzası: çalışıyor mu + son asistan metninin özeti.
///
/// py: _loop_sig
pub fn loop_sig(name: &str, views: &[SessionView]) -> String {
    match views.iter().find(|v| v.name == name) {
        Some(v) if v.running => format!("run:{}", sha_head(&v.last_assistant, 12)),
        _ => "absent".to_string(),
    }
}

/// Tur eyleminin sunduğu madde kümesinin özeti (madde yoksa boş kümenin özeti).
fn tour_fingerprint(a: &Action) -> Result<String, BadValue> {
    let show = |v: Option<&Value>| pyc::str_of(v.unwrap_or(&Value::Null));
    let mut parts: Vec<String> = items_of(a.payload.get("items"))?
        .iter()
        .filter_map(Value::as_object)
        .map(|i| {
            let id = i.get("id").filter(|v| pyc::truthy(v)).or_else(|| i.get("name"));
            format!("{}:{}", show(i.get("kind")), show(id))
        })
        .collect();
    parts.sort();
    Ok(sha_head(&parts.join("|"), 8))
}

/// `actions`tan döngüye girmiş olanları ayıklar; dönen: (kalan eylemler + gerekirse `loop_break`, yeni durum).
///
/// py: loop_guard
pub fn loop_guard(
    actions: &[Action],
    views: &[SessionView],
    st: &Doc,
    now: f64,
) -> Result<(Vec<Action>, Doc), BadValue> {
    let mut guard: IndexMap<String, Doc> = dict_of(st.get("loop_guard"))?
        .into_iter()
        .filter_map(|(k, v)| match v {
            Value::Object(o) => Some((k, o)),
            _ => None,
        })
        .collect();
    let (mut out, mut breaks) = (Vec::new(), Vec::new());
    for a in actions {
        if !LOOP_KINDS.contains(&a.kind.as_str()) || a.name.is_empty() {
            out.push(a.clone());
            continue;
        }
        let key = format!("{}|{}", a.kind, a.name);
        let mut rec = guard.get(&key).cloned().unwrap_or_default();
        let mut sig = loop_sig(&a.name, views);
        let mut fp = String::new();
        if a.kind == "tour" {
            // Sunulan MADDE kümesi değiştiyse tur ilerliyor sayılır.
            fp = tour_fingerprint(a)?;
            sig = format!("{sig}:{fp}");
            if rec.get("fp").is_some_and(|old| pyc::truthy(old) && old.as_str() != Some(fp.as_str())) {
                rec = Map::new();
            }
        }
        if float_of(rec.get("until"))? > now {
            continue;
        }
        let first = match rec.get("first").filter(|v| pyc::truthy(v)) {
            Some(v) if rec.get("sig").and_then(Value::as_str) == Some(sig.as_str()) => {
                pyc::to_float(v).ok_or_else(|| bad(v))?
            }
            _ => now,
        };
        let n = if rec.get("sig").and_then(Value::as_str) == Some(sig.as_str()) && now - first < LOOP_FORGET_SECONDS {
            let n = int_of(rec.get("n"))?.saturating_add(1);
            rec.insert("n".into(), json!(n));
            n
        } else {
            rec = doc(json!({"n": 1, "sig": sig, "first": now}));
            1
        };
        if !fp.is_empty() {
            rec.insert("fp".into(), json!(fp));
        }
        if n > LOOP_MAX {
            let pause = match a.kind.as_str() {
                "tour" => LOOP_PAUSE_TOUR_SECONDS,
                "deliver_answer" => LOOP_PAUSE_DELIVER_SECONDS,
                _ => LOOP_PAUSE_SECONDS,
            };
            rec.insert("until".into(), json!(now + pause));
            rec.insert("n".into(), json!(0));
            rec.insert("first".into(), json!(now));
            guard.insert(key, rec);
            let payload = doc(json!({"kind": a.kind, "n": LOOP_MAX, "pause_h": (pause / 3600.0) as i64,
                "pause_min": (pause / 60.0) as i64, "last_reason": pyc::head(&a.reason, 200)}));
            let reason = format!("{}: {LOOP_MAX} kez hedefte değişiklik olmadan tekrarlandı", a.kind);
            breaks.push(Action::new("loop_break", &a.name, reason, payload));
            continue;
        }
        guard.insert(key, rec);
        out.push(a.clone());
    }
    let mut kept = Map::new();
    for (k, v) in guard {
        if float_of(v.get("until"))? > now || now - float_of(v.get("first"))? < LOOP_FORGET_SECONDS {
            kept.insert(k, Value::Object(v));
        }
    }
    let mut st = st.clone();
    if kept.is_empty() {
        st.shift_remove("loop_guard");
    } else {
        st.insert("loop_guard".into(), Value::Object(kept));
    }
    out.extend(breaks);
    Ok((out, st))
}

/// Panel/CLI: şu an duraklatılmış (tür, hedef) listesi.
///
/// py: loop_paused
pub fn loop_paused(st: &Doc, now: f64) -> Result<Vec<Doc>, BadValue> {
    let mut items: Vec<(String, Value)> = dict_of(st.get("loop_guard"))?.into_iter().collect();
    items.sort_by(|a, b| a.0.cmp(&b.0));
    let mut out = Vec::new();
    for (key, r) in items {
        let Some(r) = r.as_object() else { continue };
        let until = float_of(r.get("until"))?;
        if until > now {
            let (kind, name) = key.split_once('|').unwrap_or((&key, ""));
            out.push(doc(json!({"kind": kind, "name": name, "until": until})));
        }
    }
    Ok(out)
}

// ── L5 sonuç doğrulama ────────────────────────────────────────────────────────

/// Eylem adı proje adı olabilir: tam ad, proje (blueprint) ya da ad + YALNIZ tarih/`_N` soneki.
///
/// py: _outcome_views
pub fn outcome_views<'a>(name: &str, views: &'a [SessionView]) -> Vec<&'a SessionView> {
    views.iter().filter(|v| v.name == name || v.project() == name || derived_of(&v.name, name)).collect()
}

/// Eylem hedefinin projesi: eşleşen görünümün blueprint'i, yoksa addan tarih/`_N` soneki atılmış taban ("" = farksız).
///
/// py: _outcome_project
pub fn outcome_project(name: &str, views: &[SessionView]) -> String {
    let blueprint = outcome_views(name, views)
        .into_iter()
        .find_map(|v| v.blueprint.as_deref().filter(|bp| !bp.is_empty() && *bp != name));
    if let Some(bp) = blueprint {
        return bp.to_string();
    }
    // Python `$` sondaki tek satır sonundan önce de eşleşir
    let (body, newline) = name.strip_suffix('\n').map_or((name, ""), |b| (b, "\n"));
    let cut = DATED_TAIL_RE.as_ref().and_then(|r| r.find(body).ok().flatten()).map_or(body.len(), |m| m.start());
    let base = format!("{}{newline}", &body[..cut]);
    if base != name {
        base
    } else {
        String::new()
    }
}

/// Eylem uygulandığı andaki hedef durumu (doğrulama kaydı).
///
/// py: outcome_baseline
pub fn outcome_baseline(kind: &str, name: &str, views: &[SessionView], now: f64) -> Doc {
    let sigs: Doc =
        outcome_views(name, views).iter().map(|v| (v.name.clone(), json!(loop_sig(&v.name, views)))).collect();
    let mut rec = doc(json!({"kind": kind, "name": name, "at": now, "sigs": sigs}));
    if matches!(kind, "start" | "respawn") {
        let project = outcome_project(name, views);
        if !project.is_empty() {
            rec.insert("project".into(), json!(project));
        }
    }
    rec
}

/// py: _via
pub fn via(rec: &Doc) -> Doc {
    match rec.get("via").filter(|v| pyc::truthy(v)) {
        Some(v) => doc(json!({"via": pyc::str_of(v)})),
        None => Map::new(),
    }
}

/// Dönen: (sonuçlanan kayıtlar `{kind, name, result: changed|none, secs}`, hâlâ bekleyenler).
///
/// py: check_outcomes
pub fn check_outcomes(pending: &Doc, views: &[SessionView], now: f64) -> Result<(Vec<Doc>, Doc), BadValue> {
    let mut rows = Vec::new();
    for (key, rec) in pending {
        let at = float_of(object_of(Some(rec))?.and_then(|o| o.get("at")))?;
        rows.push((at, key, rec));
    }
    rows.sort_by(|a, b| a.0.total_cmp(&b.0));
    let (mut done, mut rest) = (Vec::new(), Vec::<(f64, &String, &Value)>::new());
    for (at, key, value) in rows {
        let Some(rec) = value.as_object() else { continue };
        let text = |k: &str| crate::cards::str_or_empty(rec.get(k));
        let (kind, name, project) = (text("kind"), text("name"), text("project"));
        let mut vs: Vec<&SessionView> = outcome_views(&name, views).into_iter().filter(|v| v.running).collect();
        let reopen = matches!(kind.as_str(), "start" | "respawn");
        if reopen && !project.is_empty() {
            // aynı projenin YENİ adlı oturumu da sayılır
            let seen: BTreeSet<&str> = vs.iter().map(|v| v.name.as_str()).collect();
            let more = outcome_views(&project, views);
            vs.extend(more.into_iter().filter(|v| v.running && !seen.contains(v.name.as_str())));
        }
        let changed = if reopen {
            vs.iter().any(|v| v.started_at >= at - 30.0)
                || (kind == "start" && !vs.is_empty() && !truthy_at(rec, "sigs"))
        } else {
            let sigs = dict_of(rec.get("sigs"))?;
            vs.iter().any(|v| {
                v.last_activity > at + 5.0
                    || sigs.get(&v.name).is_some_and(|s| s.as_str() != Some(loop_sig(&v.name, views).as_str()))
            })
        };
        if changed || now - at >= VERIFY_WINDOW_SECONDS {
            let result = if changed { "changed" } else { "none" };
            let mut d = doc(json!({"kind": kind, "name": name, "result": result, "secs": (now - at) as i64}));
            d.extend(via(rec));
            done.push(d);
        } else {
            rest.push((at, key, value));
        }
    }
    let cap = usize::try_from(VERIFY_MAX_PENDING).unwrap_or(0);
    if rest.len() > cap {
        rest.drain(..rest.len() - cap);
    }
    Ok((done, rest.into_iter().map(|(_, k, v)| (k.clone(), v.clone())).collect()))
}

// ── API hatasından kurtarma ───────────────────────────────────────────────────

/// `state.api_err`ten panel/CLI için kısa liste, ada göre sıralı.
///
/// py: api_error_brief
pub fn api_error_brief(st: &Doc) -> Result<Vec<Doc>, BadValue> {
    let mut items: Vec<(String, Value)> = dict_of(st.get("api_err"))?.into_iter().collect();
    items.sort_by(|a, b| a.0.cmp(&b.0));
    let mut out = Vec::new();
    for (name, r) in items {
        let Some(r) = r.as_object() else { continue };
        out.push(doc(json!({"name": name, "since": float_of(r.get("since"))?, "nudges": int_of(r.get("nudges"))?,
            "gave_up": truthy_at(r, "gave_up")})));
    }
    Ok(out)
}

fn required_float(r: &Doc, key: &str) -> Result<f64, BadValue> {
    let v = r.get(key).ok_or_else(|| BadValue(format!("missing key: {key}")))?;
    pyc::to_float(v).ok_or_else(|| bad(v))
}

struct Recovery {
    err: IndexMap<String, Doc>,
    actions: Vec<Action>,
    now: f64,
}

impl Recovery {
    fn rec(&mut self, name: &str) -> &mut Doc {
        self.err.entry(name.to_string()).or_default()
    }

    fn nudges(&mut self, name: &str) -> Result<i64, BadValue> {
        int_of(self.rec(name).get("nudges"))
    }

    fn nudge(&mut self, name: &str, why: &str) -> Result<(), BadValue> {
        let n = self.nudges(name)?.saturating_add(1);
        let now = self.now;
        let r = self.rec(name);
        r.insert("nudges".into(), json!(n));
        r.insert("last_nudge".into(), json!(now));
        self.actions.push(Action::new("nudge", name, why, doc(json!({"text": API_NUDGE_TEXT, "n": n}))));
        Ok(())
    }

    fn due_single(&mut self, name: &str) -> Result<bool, BadValue> {
        let n = self.nudges(name)?;
        if n >= API_NUDGE_MAX {
            return Ok(false);
        }
        let now = self.now;
        let r = self.rec(name);
        let base = required_float(r, if n == 0 { "since" } else { "last_nudge" })?;
        // Python negatif dizini sondan sayar; sınır dışı = `IndexError`
        let at = if n < 0 { n.saturating_add(API_NUDGE_MAX) } else { n };
        let delay = usize::try_from(at).ok().and_then(|i| API_NUDGE_DELAYS.get(i));
        let delay = delay.ok_or_else(|| BadValue(format!("nudges out of range: {n}")))?;
        Ok(now - base >= *delay)
    }

    fn give_up(&mut self, name: &str) -> Result<(), BadValue> {
        let n = self.nudges(name)?;
        let now = self.now;
        let r = self.rec(name);
        if n >= API_NUDGE_MAX && !truthy_at(r, "gave_up") && now - required_float(r, "last_nudge")? >= API_GIVEUP_AFTER
        {
            r.insert("gave_up".into(), json!(true));
            let why = format!("{API_NUDGE_MAX} 'devam' sonrası hâlâ API hatasında");
            self.actions.push(Action::new("api_giveup", name, why, Map::new()));
        }
        Ok(())
    }

    /// Tek oturum kuralı: süresi geldiyse "devam", değilse (hakkı bittiyse) vazgeç.
    fn single(&mut self, name: &str, why: &str) -> Result<(), BadValue> {
        if self.due_single(name)? {
            self.nudge(name, why)
        } else {
            self.give_up(name)
        }
    }
}

/// (eylemler, yeni `api_err` durumu, yeni `api_outage` durumu).
pub type ApiPlan = (Vec<Action>, IndexMap<String, Doc>, Value);

/// API hatasında takılan oturumlar: `nudge` / `api_outage` / `api_recovered` / `api_giveup`.
///
/// py: plan_api_recovery
pub fn plan_api_recovery(
    views: &[SessionView],
    eligible: &dyn Fn(&SessionView) -> bool,
    skip: &BTreeSet<String>,
    st_err: &Doc,
    st_out: &Value,
    now: f64,
) -> Result<ApiPlan, BadValue> {
    let mut run = Recovery { err: IndexMap::new(), actions: Vec::new(), now };
    let mut stuck: Vec<&SessionView> = Vec::new();
    for v in views {
        if !v.running || skip.contains(&v.name) || !eligible(v) || api_error_kind(&v.last_assistant) != "retry" {
            continue;
        }
        if v.busy == Some(true) || v.subagent_active || v.subagent_unknown {
            continue;
        }
        if v.last_activity != 0.0 && now - v.last_activity < API_QUIET_SECONDS {
            continue;
        }
        // aynı hata metni sürüyorsa kayıt devam eder; metin değiştiyse sayaç sıfırlanır
        let hash = sha_head(&v.last_assistant, 10);
        let mut rec = match st_err.get(&v.name).and_then(Value::as_object) {
            Some(prev) if prev.get("hash").and_then(Value::as_str) == Some(hash.as_str()) => prev.clone(),
            _ => doc(json!({"since": now, "nudges": 0, "last_nudge": 0.0, "gave_up": false})),
        };
        rec.insert("hash".into(), json!(hash));
        run.err.insert(v.name.clone(), rec);
        stuck.push(v);
    }
    let mut out: Doc = st_out.as_object().cloned().unwrap_or_default();
    let live: Vec<&str> = stuck
        .iter()
        .map(|v| v.name.as_str())
        .filter(|n| !run.err.get(*n).is_some_and(|r| truthy_at(r, "gave_up")))
        .collect();
    let is_stuck = |name: &str| stuck.iter().any(|v| v.name == name);
    if live.len() as i64 >= API_OUTAGE_MIN || (!out.is_empty() && !live.is_empty()) {
        // kesinti: oturumlara tek tek yazma
        if out.is_empty() {
            out = doc(json!({"since": now, "probe": "", "probe_at": 0.0, "woken": [], "recovered": false}));
            let mut names = live.clone();
            names.sort_unstable();
            let why = format!("{} oturum aynı anda API hatasında", live.len());
            run.actions.push(Action::new("api_outage", "", why, doc(json!({"names": names}))));
        }
        let mut woken = BTreeSet::new();
        for w in items_of(out.get("woken"))? {
            match w {
                Value::String(s) => {
                    woken.insert(s);
                }
                Value::Array(_) | Value::Object(_) => return Err(bad(&w)),
                _ => {}
            }
        }
        let probe = crate::cards::str_or_empty(out.get("probe"));
        if !truthy_at(&out, "recovered")
            && !probe.is_empty()
            && !is_stuck(&probe)
            && views.iter().any(|v| v.name == probe && v.running)
        {
            out.insert("recovered".into(), json!(true));
            run.actions.push(Action::new("api_recovered", &probe, "yoklama oturumu API hatasından çıktı", Map::new()));
        }
        if truthy_at(&out, "recovered") {
            let already = woken.clone();
            let group = usize::try_from(API_WAKE_GROUP).unwrap_or(0);
            let waiting: Vec<&str> = live.iter().copied().filter(|n| !woken.contains(*n)).take(group).collect();
            for name in waiting {
                run.nudge(name, "kesinti bitti, sırayla uyandırma")?;
                woken.insert(name.to_string());
            }
            for name in live.iter().filter(|n| already.contains(**n)) {
                // uyandırıldı ama hâlâ takılı: tek-oturum kurallarına dön
                run.single(name, "uyandırıldı ama hâlâ API hatasında, otomatik devam")?;
            }
        } else if now >= float_of(out.get("probe_at"))? {
            let mut sorted = live.clone();
            sorted.sort_unstable();
            let mut candidate = None;
            for name in sorted {
                if run.nudges(name)? < API_NUDGE_MAX {
                    candidate = Some(name);
                    break;
                }
            }
            if let Some(name) = candidate {
                run.nudge(name, "kesinti yoklaması")?;
                out.insert("probe".into(), json!(name));
                out.insert("probe_at".into(), json!(now + API_OUTAGE_PROBE_SECONDS));
            } else {
                for name in &live {
                    run.give_up(name)?;
                }
            }
        }
        woken.retain(|n| is_stuck(n));
        out.insert("woken".into(), json!(woken));
    } else {
        out = Map::new(); // kesinti bitti: kalanlar tek-oturum kurallarına döner
        for name in &live {
            run.single(name, "API hatası, otomatik devam")?;
        }
    }
    if stuck.is_empty() {
        out = Map::new();
    }
    Ok((run.actions, run.err, Value::Object(out)))
}

/// İletim eylemlerinin `would:` tekilleştirme eki: bulgu/ders KÜMESİ.
///
/// py: _observe_cluster
pub fn observe_cluster(a: &Action) -> Result<String, BadValue> {
    let mut ids: Vec<String> = match a.kind.as_str() {
        "deliver_findings" => items_of(a.payload.get("rows"))?
            .iter()
            .filter_map(Value::as_object)
            .map(|r| pyc::str_of(r.get("id").unwrap_or(&Value::Null)))
            .collect(),
        "deliver_lesson" => items_of(a.payload.get("hashes"))?.iter().map(pyc::str_of).collect(),
        _ => return Ok(String::new()),
    };
    ids.sort();
    Ok(sha_head(&ids.join("|"), 10))
}
