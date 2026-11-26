//! Uzak host sağlığı: tazelik, devre kesici + geri çekilme, yetenek yoklaması (`/api/session/facts`), dosya kapısı ve
//! uzak eylem gönderimi (Python `web_steward`in federasyon istemcisi parçaları). Politika (kimlik, sahiplik, kota)
//! değnekçide kalır.

use std::collections::{HashMap, HashSet};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::{json, Map, Value};

use crate::proxy::{GetOpts, HostClient};
use crate::record::{self, HostRecord};
use crate::sign::Caller;
use crate::status::HostStatus;

/// Son başarılı yoklama bundan eskiyse host "kapalı": bayat satırlarla karar verilmez.
pub const REMOTE_STALE_SECONDS: f64 = 60.0;
/// Art arda bu kadar tick'te taşıma hatası = geri çekilme.
pub const BACKOFF_TICKS: u32 = 3;
pub const BACKOFF_SECONDS: f64 = 600.0;
/// Tick başına bir host'a en çok bu kadar yıkıcı eylem.
pub const MAX_DESTRUCTIVE_PER_HOST: u32 = 1;
/// Tick başına en çok bu kadar bayat host yoklanır.
pub const PROBES_PER_TICK: usize = 2;
/// `api` 0 (eski host) kaydı bu süreden sonra yeniden yoklanır.
pub const CAPS_RECHECK_SECONDS: f64 = 600.0;

/// Uzak okumanın sonucu: "okunamadı", "bayat" ve "desteklenmiyor" birbirine karışmaz.
#[derive(Debug, Clone, PartialEq)]
pub enum Remote<T> {
    Ok(T),
    Unreachable(String),
    Stale {
        value: T,
        age: f64,
    },
    /// Uzak sürüm bu ucu bilmiyor (404): "host güncel değil".
    Unsupported,
}

/// `ok` VE son başarılı yoklama pencere içinde (stale-while-error'ın koruduğu satırlar taze sayılmaz).
pub fn host_fresh(status: Option<&HostStatus>, last_ok_at: f64, now: f64) -> bool {
    status.is_some_and(|s| s.ok) && last_ok_at > 0.0 && now - last_ok_at <= REMOTE_STALE_SECONDS
}

/// Taşıma (host düzeyi) hatası mı. 404 ve uygulama düzeyi ret taşıma hatası DEĞİLDİR.
pub fn is_transport_error(host: &str, body: &Value, status: u16) -> bool {
    if matches!(status, 502..=504) {
        return true;
    }
    matches!(status, 0 | 200)
        && body.get("ok") == Some(&Value::Bool(false))
        && body["error"].as_str().is_some_and(|e| {
            e.strip_prefix(host)
                .is_some_and(|r| r.starts_with(" unreachable:"))
        })
}

/// Bir değnekçi tick'inin uzak muhasebesi.
#[derive(Debug, Default)]
pub struct TickState {
    pub failed: HashSet<String>,
    pub succeeded: HashSet<String>,
    destructive: HashMap<String, u32>,
}

impl TickState {
    /// Bu tick'te taşıma hatası alan host'a başka eylem DENENMEZ.
    pub fn blocked(&self, host: &str) -> bool {
        self.failed.contains(host)
    }

    /// Paralel okumalar: başka okuması temiz dönen host suçlanmaz (tek yavaş oturum host'u düşürmesin).
    pub fn record_reads(&mut self, bad: &HashSet<String>, good: &HashSet<String>) {
        self.failed.extend(bad.difference(good).cloned());
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct Health {
    streak: u32,
    until: f64,
    down: bool,
}

/// `down` durumu DEĞİŞTİĞİNDE üretilir.
#[derive(Debug, Clone, PartialEq)]
pub enum Change {
    Down { host: String, ticks: u32 },
    Up { host: String },
}

#[derive(Default)]
pub struct Breaker {
    map: Mutex<HashMap<String, Health>>,
}

impl Breaker {
    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, Health>> {
        self.map.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn backing_off(&self, host: &str, now: f64) -> bool {
        self.lock().get(host).is_some_and(|h| h.until > now)
    }

    /// Hafif yoklama host'u taze buldu: sayaç ve geri çekilme ANINDA sıfırlanır. Bildirilmiş `down` idiyse `true`.
    pub fn clear(&self, host: &str) -> bool {
        self.lock()
            .get_mut(host)
            .is_some_and(|h| std::mem::take(h).down)
    }

    /// Tick sonu: hatalı tick sayacı artırır, temiz tick sıfırlar, eylemsiz tick sayılmaz.
    pub fn settle(&self, tick: &TickState, now: f64) -> Vec<Change> {
        let mut hosts: Vec<&String> = tick.failed.union(&tick.succeeded).collect();
        hosts.sort();
        let mut m = self.lock();
        let mut out = Vec::new();
        for host in hosts {
            let h = m.entry(host.clone()).or_default();
            if tick.failed.contains(host) {
                h.streak = h.streak.saturating_add(1);
                if h.streak >= BACKOFF_TICKS {
                    h.until = now + BACKOFF_SECONDS;
                    if !h.down {
                        h.down = true;
                        out.push(Change::Down {
                            host: host.clone(),
                            ticks: h.streak,
                        });
                    }
                }
            } else {
                if h.down {
                    out.push(Change::Up { host: host.clone() });
                }
                *h = Health::default();
            }
        }
        out
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Capabilities {
    /// 0 = eski host ya da bilinmiyor.
    pub api: i64,
    pub capabilities: Vec<String>,
}

impl Capabilities {
    pub fn has(&self, name: &str) -> bool {
        self.capabilities.iter().any(|c| c == name)
    }
}

/// Facts yanıtındaki `sessions` nesnesi.
pub type Facts = Map<String, Value>;

#[derive(Default)]
pub struct CapabilityCache {
    map: Mutex<HashMap<String, (f64, Capabilities)>>,
}

impl CapabilityCache {
    /// `None` = yoklanmalı (hiç yok ya da eskimiş api 0).
    pub fn cached(&self, host: &str, now: f64) -> Option<Capabilities> {
        let m = self.map.lock().unwrap_or_else(|e| e.into_inner());
        let (at, caps) = m.get(host)?;
        (caps.api != 0 || now - at < CAPS_RECHECK_SECONDS).then(|| caps.clone())
    }

    fn put(&self, host: &str, caps: Capabilities, now: f64) -> Capabilities {
        let mut m = self.map.lock().unwrap_or_else(|e| e.into_inner());
        m.insert(host.to_string(), (now, caps.clone()));
        caps
    }

    /// Tek istek hem yetenek yoklaması hem veri okuması. 404 = eski host (api 0 önbelleğe). Geçici arıza önbelleğe
    /// YAZILMAZ (yeteneği silmesin); taşıma hatası `tick.failed`e düşer.
    #[allow(clippy::too_many_arguments)]
    pub async fn probe_facts(
        &self,
        client: &HostClient,
        hosts: &[HostRecord],
        host: &str,
        names: &[&str],
        timeout: Duration,
        now: f64,
        tick: Option<&mut TickState>,
    ) -> (Capabilities, Remote<Facts>) {
        let cached = self.cached(host, now);
        if let Some(c) = cached.as_ref().filter(|c| c.api == 0) {
            return (c.clone(), Remote::Unsupported);
        }
        let joined = names.join(",");
        let opts = GetOpts {
            dedup: false,
            timeout: Some(timeout),
        };
        let (body, status) = client
            .proxy_get(
                hosts,
                host,
                "/api/session/facts",
                &[("names", &joined)],
                opts,
                Caller::Unbound,
            )
            .await;
        if is_transport_error(host, &body, status) {
            if let Some(t) = tick {
                t.failed.insert(host.to_string());
            }
        }
        if status == 404 {
            return (
                self.put(host, Capabilities::default(), now),
                Remote::Unsupported,
            );
        }
        if status == 200 && body.get("ok") != Some(&Value::Bool(false)) {
            if let Some(api) = body.get("api").and_then(Value::as_i64) {
                let list = body["capabilities"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|c| c.as_str().map(str::to_string))
                            .collect()
                    })
                    .unwrap_or_default();
                let caps = self.put(
                    host,
                    Capabilities {
                        api,
                        capabilities: list,
                    },
                    now,
                );
                let facts = body
                    .get("sessions")
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_default();
                return (caps, Remote::Ok(facts));
            }
        }
        let why = body["error"]
            .as_str()
            .map_or_else(|| format!("http {status}"), str::to_string);
        (cached.unwrap_or_default(), Remote::Unreachable(why))
    }
}

/// Uzak proje dosyasına dokunma kapısı: uzak eylemler açık, host kayıtlı + taze, geri çekilmede değil.
pub fn files_gate(
    hosts: &[HostRecord],
    host: &str,
    remote_actions: bool,
    fresh: bool,
    backing_off: bool,
) -> bool {
    remote_actions && record::find(hosts, host).is_some() && fresh && !backing_off
}

/// Oturumu durduran yollar: yalnız [`remote_stop`] ile.
const DESTRUCTIVE_PATHS: [&str; 4] = ["/api/stop", "/api/close", "/api/retire", "/api/compact"];

fn fail(host: &str, code: &str, error: String) -> Value {
    json!({"ok": false, "error": error, "code": code, "host": host})
}

async fn send(
    client: &HostClient,
    hosts: &[HostRecord],
    host: &str,
    path: &str,
    body: Map<String, Value>,
    timeout: Duration,
    tick: Option<&mut TickState>,
) -> Value {
    if tick.as_ref().is_some_and(|t| t.blocked(host)) {
        return json!({"ok": false, "error": "host_down", "host": host});
    }
    let (mut out, status) = client
        .proxy_action(hosts, host, path, body, Some(timeout), Caller::Unbound)
        .await;
    let transport = is_transport_error(host, &out, status);
    if transport {
        let error: String = out["error"]
            .as_str()
            .unwrap_or("")
            .chars()
            .take(200)
            .collect();
        client.events.log(
            "remote_transport_error",
            json!({"host": host, "path": path, "status": status, "error": error}),
        );
    }
    if let Some(t) = tick {
        let set = if transport {
            &mut t.failed
        } else {
            &mut t.succeeded
        };
        set.insert(host.to_string());
    }
    if status == 404 {
        return fail(
            host,
            "remote_not_found",
            format!("remote endpoint not found on {host}: {path}"),
        );
    }
    if transport {
        if let Some(o) = out.as_object_mut() {
            o.insert("ok".into(), false.into());
            o.insert("code".into(), "host_down".into());
            o.insert("host".into(), host.into());
        }
    }
    out
}

/// Yıkıcı OLMAYAN uzak eylemin gönderim yolu. Gövdede `host` ve yıkıcı yol reddedilir.
pub async fn remote_post(
    client: &HostClient,
    hosts: &[HostRecord],
    host: &str,
    path: &str,
    body: Map<String, Value>,
    timeout: Duration,
    tick: Option<&mut TickState>,
) -> Value {
    if body.contains_key("host") {
        return fail(
            host,
            "bad_request",
            "remote action body must not carry 'host'".into(),
        );
    }
    if DESTRUCTIVE_PATHS.contains(&path) {
        return fail(
            host,
            "needs_exact_target",
            format!("{path} requires an exact target proof"),
        );
    }
    send(client, hosts, host, path, body, timeout, tick).await
}

/// Yıkıcı eylem kanıtı: taze host + adı TAM eşleşen tek çalışan satır + `exact_target` yeteneği.
#[derive(Debug)]
pub struct ExactTarget {
    host: String,
    name: String,
}

/// Python doğruluk değeri (`bool(x)`): uzak `running` alanı `true` dışında da gelebilir; belirsizlik kapalı yöne
/// düşsün diye eşleşme SAYIMI Python ile aynı kuralı kullanır.
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Sıra Python `_remote_stop` ile aynı: tazelik, satır (0 = `no_exact_match`, 2+ = `ambiguous`), sonra yetenek.
/// `caps` = [`CapabilityCache::cached`]; `None` = yetenek şu an bilinmiyor (`caps_unknown`), bilinip `exact_target`
/// yoksa `remote_too_old`.
pub fn exact_target(
    host: &str,
    name: &str,
    status: Option<&HostStatus>,
    last_ok_at: f64,
    caps: Option<&Capabilities>,
    now: f64,
) -> Result<ExactTarget, &'static str> {
    if !host_fresh(status, last_ok_at, now) {
        return Err("host_down");
    }
    let matches = status
        .map(|s| {
            s.sessions
                .iter()
                .filter(|r| r["name"] == name && truthy(&r["running"]))
                .count()
        })
        .unwrap_or(0);
    match matches {
        1 => {}
        0 => return Err("no_exact_match"),
        _ => return Err("ambiguous"),
    }
    match caps {
        None => Err("caps_unknown"),
        Some(c) if !c.has("exact_target") => Err("remote_too_old"),
        Some(_) => Ok(ExactTarget {
            host: host.into(),
            name: name.into(),
        }),
    }
}

/// `POST /api/stop {"name", "exact": true}`. Kanıt tüketilir; tick başına host başına bütçe.
pub async fn remote_stop(
    client: &HostClient,
    hosts: &[HostRecord],
    target: ExactTarget,
    lang: &str,
    timeout: Duration,
    tick: &mut TickState,
) -> Value {
    let host = target.host.as_str();
    if tick.blocked(host) {
        return fail(host, "host_down", "host_down".into());
    }
    let sent = tick.destructive.entry(host.to_string()).or_default();
    if *sent >= MAX_DESTRUCTIVE_PER_HOST {
        return fail(
            host,
            "destructive_budget",
            format!("one destructive action per host per tick ({host})"),
        );
    }
    *sent += 1;
    let mut body = Map::new();
    body.insert("name".into(), target.name.clone().into());
    body.insert("exact".into(), true.into());
    body.insert("lang".into(), lang.into());
    let mut out = send(client, hosts, host, "/api/stop", body, timeout, Some(tick)).await;
    // Python: `dict(_remote_post(...), host=host, name=name)`; `ok` olmayan yanıt uygulanmış SAYILMAZ.
    if let Some(o) = out.as_object_mut() {
        o.insert("host".into(), host.into());
        o.insert("name".into(), target.name.clone().into());
        if !o.get("ok").is_some_and(truthy) {
            o.insert("ok".into(), false.into());
        }
    }
    out
}
