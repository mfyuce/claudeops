//! Uzak `/api/status` yanıtının indirgenmesi, poller önbelleği (stale-while-error, ardışık hata toleransı) ve yerel
//! duruma karıştırma. Uzak veri GÜVENİLMEZ: yanlış tipteki alanlar boşa düşer.

use std::collections::{HashMap, HashSet};
use std::sync::Mutex;

use serde_json::{json, Map, Value};

use crate::consts::CONSECUTIVE_FAILURES_BEFORE_ERROR;
use crate::record::HostRecord;

/// Bir host'un son bilinen durumu. Başarı ve hata AYNI alan kümesi.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct HostStatus {
    pub ok: bool,
    pub error: Option<String>,
    pub sessions: Vec<Value>,
    pub closed: Vec<Value>,
    pub retired: Vec<Value>,
    pub cli_list: Vec<Value>,
    pub cli_options: Map<String, Value>,
    pub dups: Vec<Value>,
    pub disk_clean: Value,
    pub orphan_watch: Value,
    pub fwd: Value,
    pub build_running: Option<String>,
}

impl HostStatus {
    pub fn failed(error: impl Into<String>) -> HostStatus {
        HostStatus {
            error: Some(error.into()),
            ..HostStatus::default()
        }
    }
}

const CLI_OPTION_FIELDS: [&str; 4] = [
    "models",
    "permission_modes",
    "effort_levels",
    "cyclable_modes",
];

fn array(v: Option<&Value>) -> Vec<Value> {
    v.and_then(Value::as_array).cloned().unwrap_or_default()
}

/// Ön yüz 4 alanın HER cli girdisinde var olduğunu varsayar (eski uzak sürüm bazılarını göndermez).
pub fn normalize_cli_options(raw: Option<&Value>) -> Map<String, Value> {
    let Some(o) = raw.and_then(Value::as_object) else {
        return Map::new();
    };
    o.iter()
        .map(|(cli, opts)| {
            let full: Map<String, Value> = CLI_OPTION_FIELDS
                .iter()
                .map(|f| (f.to_string(), Value::Array(array(opts.get(f)))))
                .collect();
            (cli.clone(), Value::Object(full))
        })
        .collect()
}

/// Uzak tarafın kendi `local` etiketi bizim bildiğimiz host adıyla EZİLİR. Nesne olmayan satır atlanır.
fn tag_rows(v: Option<&Value>, host: &str) -> Vec<Value> {
    array(v)
        .into_iter()
        .filter_map(|r| match r {
            Value::Object(mut o) => {
                o.insert("host".into(), host.into());
                Some(Value::Object(o))
            }
            _ => None,
        })
        .collect()
}

fn int_of(v: Option<&Value>) -> Option<i64> {
    match v {
        None | Some(Value::Null) => Some(0),
        Some(Value::Bool(b)) => Some(*b as i64),
        Some(Value::Number(n)) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Some(Value::String(s)) if s.is_empty() => Some(0),
        Some(Value::String(s)) => s.trim().parse().ok(),
        _ => None,
    }
}

fn orphan_brief(v: Option<&Value>) -> Value {
    let Some(o) = v.and_then(Value::as_object) else {
        return Value::Null;
    };
    match (int_of(o.get("servers")), int_of(o.get("procs"))) {
        (Some(servers), Some(procs)) => {
            json!({"servers": servers, "procs": procs, "last_end": o.get("last_end").cloned().unwrap_or(Value::Null)})
        }
        _ => Value::Null,
    }
}

fn build_running(v: Option<&Value>) -> Option<String> {
    let r = v?.get("running")?.as_str()?;
    (!r.is_empty()).then(|| r.chars().take(12).collect())
}

fn fwd_brief(v: Option<&Value>, local_now: f64) -> Value {
    let Some(o) = v.and_then(Value::as_object) else {
        return Value::Null;
    };
    let skew = match o.get("now") {
        None | Some(Value::Null) => Value::Null,
        Some(now) => {
            let Some(n) = now
                .as_f64()
                .or_else(|| now.as_str().and_then(|s| s.trim().parse().ok()))
            else {
                return Value::Null;
            };
            json!(((n - local_now) * 10.0).round() / 10.0)
        }
    };
    let kids = match o.get("kids") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(a)) => a
            .iter()
            .take(4)
            .map(|k| {
                Value::String(
                    k.as_str()
                        .map(str::to_string)
                        .unwrap_or_else(|| k.to_string()),
                )
            })
            .collect(),
        Some(_) => return Value::Null,
    };
    json!({"mode": o.get("mode").and_then(Value::as_str).unwrap_or(""), "kids": kids, "skew": skew})
}

/// REST/WS/gRPC'nin ORTAK son adımı. `raw` başarılı bir durum nesnesidir.
pub fn finalize(host: &str, raw: &Value, local_now: f64) -> HostStatus {
    if raw.get("ok") == Some(&Value::Bool(false)) {
        return HostStatus::failed(
            raw.get("error")
                .and_then(Value::as_str)
                .unwrap_or("remote error"),
        );
    }
    HostStatus {
        ok: true,
        error: None,
        sessions: tag_rows(raw.get("sessions"), host),
        closed: tag_rows(raw.get("closed"), host),
        retired: tag_rows(raw.get("retired"), host),
        cli_list: array(raw.get("cli_list")),
        cli_options: normalize_cli_options(raw.get("cli_options")),
        dups: array(raw.get("dups")),
        disk_clean: raw
            .get("disk_clean")
            .filter(|v| v.is_object())
            .cloned()
            .unwrap_or(Value::Null),
        orphan_watch: orphan_brief(raw.get("orphan_watch")),
        fwd: fwd_brief(raw.get("fwd"), local_now),
        build_running: build_running(raw.get("build")),
    }
}

#[derive(Default)]
struct Entry {
    cache: Option<HostStatus>,
    /// Son GERÇEKTEN başarılı sonuç; hiçbir zaman ok:false'a düşmez.
    last_good: Option<HostStatus>,
    last_ok_at: f64,
    last_try_at: f64,
    streak: u32,
}

/// Poller önbelleği.
#[derive(Default)]
pub struct StatusBook {
    entries: Mutex<HashMap<String, Entry>>,
}

impl StatusBook {
    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, Entry>> {
        self.entries.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Eşiğin altındaki başarısızlık (önceki başarı varken) hiç yazılmaz; eşik aşılınca satırlar KORUNUR, yalnız
    /// `ok`/`error` güncellenir. Hiç başarı yoksa ilk hata anında görünür.
    pub fn record(&self, name: &str, result: HostStatus, now: f64) {
        let mut m = self.lock();
        let e = m.entry(name.to_string()).or_default();
        e.last_try_at = now;
        if result.ok {
            e.streak = 0;
            e.cache = Some(result.clone());
            e.last_good = Some(result);
            e.last_ok_at = now;
            return;
        }
        e.streak = e.streak.saturating_add(1);
        match &e.last_good {
            Some(_) if e.streak < CONSECUTIVE_FAILURES_BEFORE_ERROR => {}
            Some(good) => {
                let mut stale = good.clone();
                stale.ok = false;
                stale.error = result.error;
                e.cache = Some(stale);
            }
            None => e.cache = Some(result),
        }
    }

    pub fn cached(&self, name: &str) -> Option<HostStatus> {
        self.lock().get(name)?.cache.clone()
    }

    pub fn last_ok_at(&self, name: &str) -> f64 {
        self.lock().get(name).map_or(0.0, |e| e.last_ok_at)
    }

    pub fn last_try_at(&self, name: &str) -> f64 {
        self.lock().get(name).map_or(0.0, |e| e.last_try_at)
    }

    pub fn fail_streak(&self, name: &str) -> u32 {
        self.lock().get(name).map_or(0, |e| e.streak)
    }

    /// Silinmiş host'ların kaydı kalkar.
    pub fn retain(&self, names: &HashSet<String>) {
        self.lock().retain(|k, _| names.contains(k));
    }

    /// Yerel durum yanıtına uzak satırları ekler ve AYNI sıralamayla yeniden sıralar. Yalnız önbellek okur.
    /// `open_mirrors` (`"host:ad"`) verilirse uzak oturum satırları `mirror_open` taşır.
    pub fn merge_status(
        &self,
        payload: &mut Map<String, Value>,
        hosts: &[HostRecord],
        open_mirrors: Option<&HashSet<String>>,
        sort_by_cwd: bool,
    ) {
        let mut rows: [Vec<Value>; 3] = Default::default();
        const KEYS: [&str; 3] = ["sessions", "closed", "retired"];
        for (slot, key) in rows.iter_mut().zip(KEYS) {
            *slot = match payload.remove(key) {
                Some(Value::Array(a)) => a,
                _ => Vec::new(),
            };
        }
        let mut host_rows = Vec::new();
        for h in hosts {
            let Some(c) = self.cached(&h.name) else {
                host_rows.push(
                    json!({"name": h.name, "ok": false, "error": "not polled yet",
                                      "cli_list": [], "cli_options": {}, "dups": []}),
                );
                continue;
            };
            rows[0].extend(c.sessions.into_iter().map(|mut r| {
                if let (Some(open), Some(o)) = (open_mirrors, r.as_object_mut()) {
                    let key = format!(
                        "{}:{}",
                        h.name,
                        o.get("name").and_then(Value::as_str).unwrap_or("")
                    );
                    o.insert("mirror_open".into(), open.contains(&key).into());
                }
                r
            }));
            rows[1].extend(c.closed);
            rows[2].extend(c.retired);
            host_rows.push(json!({
                "name": h.name, "ok": c.ok, "error": c.error,
                "cli_list": c.cli_list, "cli_options": c.cli_options, "dups": c.dups,
                "disk_clean": c.disk_clean, "orphan_watch": c.orphan_watch, "fwd": c.fwd,
                "build_running": c.build_running,
            }));
        }
        for (mut slot, key) in rows.into_iter().zip(KEYS) {
            slot.sort_by_cached_key(|r| {
                let f = |k: &str| {
                    r.get(k)
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_lowercase()
                };
                if sort_by_cwd {
                    (f("cwd"), f("name"))
                } else {
                    (f("name"), f("cwd"))
                }
            });
            payload.insert(key.into(), slot.into());
        }
        payload.insert("hosts".into(), host_rows.into());
    }
}
