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
use crate::status::{truthy, HostStatus};

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

/// Python `host_capabilities` varsayılan bütçesi.
pub const CAPS_PROBE_TIMEOUT: Duration = Duration::from_secs(5);

impl CapabilityCache {
    /// Python `host_capabilities`: önbellekte varsa o (ağa gitmez), yoksa tek `/api/session/facts` yoklaması (ad
    /// listesi boş). Geçici arıza önbelleğe yazılmaz, sonuç boş yetenek kümesidir.
    pub async fn host_capabilities(
        &self,
        client: &HostClient,
        hosts: &[HostRecord],
        host: &str,
        timeout: Duration,
        now: f64,
    ) -> Capabilities {
        if let Some(c) = self.cached(host, now) {
            return c;
        }
        self.probe_facts(client, hosts, host, &[], timeout, now, None)
            .await
            .0
    }
}

/// Python `remote_health` satırı (değnekçi durum görünümü): `state` = `backoff` | `ok` | `down`, `api` (önbellek), `age`
/// (son başarılı yoklamadan beri sn), `ok` değilse `reason` (en çok 120 karakter) ve `last_try`. Ağa gitmez.
pub fn health_view(
    status: Option<&HostStatus>,
    last_ok_at: f64,
    last_try_at: f64,
    backing_off: bool,
    caps: Option<&Capabilities>,
    now: f64,
) -> Value {
    // Python: poller kaydı yoksa `last_ok_at` da yok sayılır.
    let last = if status.is_some() { last_ok_at } else { 0.0 };
    let state = if backing_off {
        "backoff"
    } else if host_fresh(status, last, now) {
        "ok"
    } else {
        "down"
    };
    let secs = |t: f64| (t != 0.0).then_some((now - t) as i64);
    let mut out = json!({"state": state, "api": caps.map(|c| c.api), "age": secs(last)});
    if state != "ok" {
        let err: String = match status {
            Some(s) => s.error.clone().unwrap_or_default(),
            None => "poller kaydı yok".into(),
        };
        let reason: String = err.chars().take(120).collect();
        out["reason"] = if !reason.is_empty() {
            reason.into()
        } else if state == "backoff" {
            "geri çekilmede".into()
        } else {
            "son başarılı poll bayat".into()
        };
        out["last_try"] = json!(secs(last_try_at));
    }
    out
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

/// Sıra Python `_remote_stop` ile aynı: tazelik + geri çekilme (`_remote_rows`), satır (0 = `no_exact_row`, 2+ =
/// `ambiguous_sessions`, Python kodları), sonra yetenek. `caps` = [`CapabilityCache::cached`]; `None` = yetenek şu an
/// bilinmiyor (`caps_unknown`), bilinip `exact_target` yoksa `remote_too_old`. Projeye göre satır seçimi (dünya, sahiplik,
/// `manual`, `not_own`) değnekçinindir (T10): bu kanıt yalnız TAM adı bilinen oturum içindir.
pub fn exact_target(
    host: &str,
    name: &str,
    status: Option<&HostStatus>,
    last_ok_at: f64,
    backing_off: bool,
    caps: Option<&Capabilities>,
    now: f64,
) -> Result<ExactTarget, &'static str> {
    if !host_fresh(status, last_ok_at, now) || backing_off {
        return Err("host_down");
    }
    match running_row(status, name) {
        Err(e) => return Err(e),
        Ok(None) => return Err("no_exact_row"),
        Ok(Some(_)) => {}
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

/// Python `_remote_named_rows`: adı TAM `name` olan, `running` alanı doğru (Python `bool(x)`) nesne satırlar.
pub fn named_running_rows<'a>(status: &'a HostStatus, name: &str) -> Vec<&'a Value> {
    status
        .sessions
        .iter()
        .filter(|r| r.is_object() && r["name"] == name && truthy(&r["running"]))
        .collect()
}

/// Python `_remote_running_row`ın satır kısmı (tazelik ve geri çekilme çağıranın, [`host_fresh`] ve
/// [`Breaker::backing_off`]): `Ok(None)` = çalışan satır yok, `Ok(Some)` = tek satır, `Err("ambiguous_sessions")` = aynı
/// adlı iki çalışan satır (bilinmiyor; kapalı yön), `Err("host_down")` = durum yok.
pub fn running_row<'a>(
    status: Option<&'a HostStatus>,
    name: &str,
) -> Result<Option<&'a Value>, &'static str> {
    let st = status.ok_or("host_down")?;
    let hits = named_running_rows(st, name);
    match hits.len() {
        0 => Ok(None),
        1 => Ok(hits.first().copied()),
        _ => Err("ambiguous_sessions"),
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

#[cfg(test)]
mod tests {
    use super::*;

    fn st(ok: bool, error: Option<&str>) -> HostStatus {
        HostStatus {
            ok,
            error: error.map(str::to_string),
            ..HostStatus::default()
        }
    }

    #[test]
    fn health_view_matches_python_remote_health() {
        let now = 10_000.0;
        let caps = Capabilities {
            api: 2,
            capabilities: vec![],
        };
        // Taze: ok, reason/last_try yok.
        let v = health_view(
            Some(&st(true, None)),
            now - 5.5,
            now - 1.0,
            false,
            Some(&caps),
            now,
        );
        assert_eq!(v, json!({"state": "ok", "api": 2, "age": 5}));
        // Geri çekilme tazelikten önce; hata metni boşsa sabit metin.
        let v = health_view(Some(&st(true, None)), now - 5.0, now - 3.0, true, None, now);
        assert_eq!(
            v,
            json!({"state": "backoff", "api": null, "age": 5, "reason": "geri çekilmede", "last_try": 3})
        );
        // Bayat (ok ama pencere dışı) ve hata metni 120 karaktere kırpılır.
        let long = "x".repeat(200);
        let v = health_view(
            Some(&st(false, Some(&long))),
            now - 61.0,
            0.0,
            false,
            None,
            now,
        );
        assert_eq!(v["state"], "down");
        assert_eq!(v["reason"].as_str().unwrap().chars().count(), 120);
        assert_eq!(v["last_try"], Value::Null);
        let v = health_view(
            Some(&st(true, None)),
            now - 61.0,
            now - 2.0,
            false,
            None,
            now,
        );
        assert_eq!(v["reason"], "son başarılı poll bayat");
        // Poller kaydı yok: `last_ok_at` yok sayılır.
        let v = health_view(None, now - 1.0, 0.0, false, None, now);
        assert_eq!(
            v,
            json!({"state": "down", "api": null, "age": null, "reason": "poller kaydı yok", "last_try": null})
        );
    }

    #[test]
    fn running_row_is_exact_truthy_and_ambiguous_is_unknown() {
        let s = HostStatus {
            ok: true,
            sessions: vec![
                json!({"name": "a", "running": 1}),
                json!({"name": "b", "running": true}),
                json!({"name": "b", "running": "yes"}),
                json!({"name": "c", "running": 0}),
                json!({"name": "C", "running": true}),
                json!({"name": "d_1", "running": true}),
            ],
            ..HostStatus::default()
        };
        assert_eq!(running_row(Some(&s), "a").unwrap().unwrap()["name"], "a");
        assert_eq!(running_row(Some(&s), "b"), Err("ambiguous_sessions"));
        for n in ["c", "d", "x"] {
            assert_eq!(running_row(Some(&s), n), Ok(None), "{n}");
        }
        assert_eq!(running_row(None, "a"), Err("host_down"));
    }
}
