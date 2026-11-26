//! Arka plan federasyonu: durum poller'ı, push tüketicileri, kademe yoklayıcısı (Python `web_hosts` daemon'ları).

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tokio::task::{JoinHandle, JoinSet};
use tokio::time::Instant;

use crate::consts::*;
use crate::grpc::GrpcClient;
use crate::guard;
use crate::proxy::{HostClient, JsonCall};
use crate::push::{DeathLog, PushConsumer};
use crate::record::{self, HostRecord};
use crate::relay::Relays;
use crate::sign::Caller;
use crate::status::{self, HostStatus, StatusBook};
use crate::tier::{Tier, TierBook};
use crate::ws;

/// Host kayıtlarının sahibi (`cops-state` gelene kadar çağıran doldurur).
pub trait HostSource: Send + Sync {
    /// Güncel kayıtlar (her turda ve her vekil çağrısında taze okunur; engellemesi kısa olmalı).
    fn load(&self) -> Vec<HostRecord>;
    /// Çalışan adresi kalıcı yap: kilit altında oku, [`record::promote_base_url`], atomik yaz.
    fn promote(&self, name: &str, new_base_url: &str);
    /// Ayar `host_loopback_ports`.
    fn reach_ports(&self) -> BTreeSet<u16> {
        guard::reach_loopback_ports(None)
    }
    /// `host_probe` deposunun seçtiği en hızlı sağlıklı adres (ağa gitmez).
    fn probe_choice(&self, _host: &HostRecord) -> Option<String> {
        None
    }
    fn note_switch(&self, _name: &str) {}
}

pub(crate) fn epoch_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

struct StatusConsumer {
    consumer: PushConsumer,
    endpoint: (Tier, HostRecord),
}

pub struct Federation {
    pub client: Arc<HostClient>,
    pub grpc: GrpcClient,
    pub source: Arc<dyn HostSource>,
    pub book: Arc<StatusBook>,
    pub tiers: TierBook,
    consumers: Mutex<HashMap<String, StatusConsumer>>,
    pub(crate) relays: Relays,
    pub(crate) deaths: Arc<DeathLog>,
    probe_at: Mutex<HashMap<String, Instant>>,
    beat: Mutex<Option<Instant>>,
    restarts: AtomicU32,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PollerHealth {
    pub alive: bool,
    /// Son tamamlanan turdan beri geçen süre.
    pub age: Option<Duration>,
    pub restarts: u32,
}

/// Arka plan görevleri; düşürülünce durur.
pub struct Running {
    poller: JoinHandle<()>,
    prober: JoinHandle<()>,
}

impl Running {
    pub fn poller_alive(&self) -> bool {
        !self.poller.is_finished()
    }
}

impl Drop for Running {
    fn drop(&mut self) {
        self.poller.abort();
        self.prober.abort();
    }
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

impl Federation {
    pub fn new(client: Arc<HostClient>, source: Arc<dyn HostSource>) -> Arc<Federation> {
        Arc::new(Federation {
            grpc: GrpcClient::new(client.pool.connector.clone()),
            client,
            source,
            book: Arc::default(),
            tiers: TierBook::default(),
            consumers: Mutex::default(),
            relays: Relays::default(),
            deaths: Arc::default(),
            probe_at: Mutex::default(),
            beat: Mutex::default(),
            restarts: AtomicU32::new(0),
        })
    }

    async fn status_from(
        &self,
        host: &HostRecord,
        base_url: &str,
        timeout: Duration,
    ) -> Result<Value, String> {
        let query = [("token".to_string(), host.token.expose().to_string())];
        let (status, body) = self
            .client
            .json(JsonCall {
                host_name: &host.name,
                base_url,
                path: "/api/status",
                query: &query,
                body: None,
                method: http::Method::GET,
                timeout,
                dedup: true,
                caller: Caller::Unbound,
            })
            .await
            .map_err(|e| e.to_string())?;
        // Yetkisiz/hata yanıtı `sessions` taşımaz.
        if !(200..300).contains(&status) {
            return Err(format!("http {status}"));
        }
        if !body.get("sessions").is_some_and(Value::is_array) {
            return Err("unexpected response shape".into());
        }
        // `/api/status` üst düzey `ok` taşımaz.
        let mut body = body;
        body["ok"] = true.into();
        Ok(body)
    }

    /// Yalnız `base_url` (`extra_urls` yedeği poller'da, nadiren).
    pub async fn fetch_status(&self, host: &HostRecord) -> HostStatus {
        match self
            .status_from(host, &host.base_url, self.client.timeouts.status)
            .await
        {
            Ok(v) => status::finalize(&host.name, &v, epoch_now()),
            Err(e) => HostStatus::failed(e),
        }
    }

    /// `extra_urls`i sırayla dener; çalışanı kalıcılaştırır. https tabanlı host'ta düz http aday HİÇ denenmez.
    pub async fn try_fallback_urls(&self, host: &HostRecord) -> Option<HostStatus> {
        let ports = self.source.reach_ports();
        for candidate in &host.extra_urls {
            if !guard::candidate_allowed(&host.base_url, candidate, &ports) {
                self.client
                    .events
                    .log("host_fallback_http_skipped", json!({"name": host.name}));
                continue;
            }
            if let Ok(v) = self
                .status_from(host, candidate, self.client.timeouts.fallback)
                .await
            {
                self.source.promote(&host.name, candidate);
                return Some(status::finalize(&host.name, &v, epoch_now()));
            }
        }
        None
    }

    fn apply_probe_choice(&self, host: &HostRecord) {
        if host.extra_urls.is_empty() {
            return;
        }
        let Some(best) = self.source.probe_choice(host) else {
            return;
        };
        // Seçim yalnız kayıtlı adaylardan ve aynı https->http kuralıyla.
        if host.extra_urls.contains(&best)
            && guard::candidate_allowed(&host.base_url, &best, &self.source.reach_ports())
        {
            self.source.promote(&host.name, &best);
            self.source.note_switch(&host.name);
            self.client
                .events
                .log("host_url_picked", json!({"name": host.name}));
        }
    }

    fn start_status_consumer(&self, host: &HostRecord, tier: Tier) -> PushConsumer {
        let (open, parse_ws) = if tier == Tier::Grpc {
            (
                self.grpc.status_stream(&host.grpc_url, host.token.expose()),
                false,
            )
        } else {
            let open = ws::open(
                self.client.clone(),
                host.clone(),
                "/ws",
                Vec::new(),
                ws::parse_status_frame,
            );
            (open, true)
        };
        let book = self.book.clone();
        let name = host.name.clone();
        PushConsumer::spawn(
            if parse_ws { "ws" } else { "grpc" },
            format!("status:{}", host.name),
            open,
            move |v| {
                let now = epoch_now();
                book.record(&name, status::finalize(&name, &v, now), now);
            },
            self.client.events.clone(),
            self.deaths.clone(),
        )
    }

    /// `true` = canlı ve veri getirmiş push akışı var, bu tur REST'e gitme. Yeni kurulan, ölen ya da sessiz akışın
    /// turu REST ile yoklanır (host asla sessizce bayatlamaz).
    pub fn ensure_status_consumer(&self, host: &HostRecord) -> bool {
        let tier = self.tiers.get(&host.name);
        let mut map = lock(&self.consumers);
        if tier == Tier::Rest {
            map.remove(&host.name);
            return false;
        }
        let endpoint = (tier, host.clone());
        if let Some(c) = map.get(&host.name) {
            if c.consumer.is_alive() && c.endpoint == endpoint {
                if c.consumer.silent() <= STATUS_PUSH_SILENCE {
                    return c.consumer.has_data();
                }
                self.client.events.log(
                    "status_consumer_silent",
                    json!({"name": host.name, "silent": c.consumer.silent().as_secs()}),
                );
            }
        }
        let consumer = self.start_status_consumer(host, tier);
        map.insert(host.name.clone(), StatusConsumer { consumer, endpoint });
        false
    }

    async fn poll_host(self: Arc<Self>, host: HostRecord) {
        self.apply_probe_choice(&host);
        if self.ensure_status_consumer(&host) {
            return;
        }
        let mut result = self.fetch_status(&host).await;
        if !result.ok && !host.extra_urls.is_empty() {
            // İlk "gerçek" arıza turunda, sonra ~20 turda bir.
            let next = self.book.fail_streak(&host.name).saturating_add(1);
            if next == CONSECUTIVE_FAILURES_BEFORE_ERROR || next.is_multiple_of(20) {
                if let Some(fallback) = self.try_fallback_urls(&host).await {
                    result = fallback;
                }
            }
        }
        self.book.record(&host.name, result, epoch_now());
    }

    /// Bir tur: host'lar EŞZAMANLI (yavaş host diğerlerini bekletmez), sonra silinenlerin temizliği.
    pub async fn poll_once(self: Arc<Self>) {
        let hosts = self.source.load();
        let names: HashSet<String> = hosts.iter().map(|h| h.name.clone()).collect();
        let urls: HashSet<String> = hosts.iter().map(|h| h.grpc_url.clone()).collect();
        let mut turn = JoinSet::new();
        for h in hosts {
            turn.spawn(self.clone().poll_host(h));
        }
        while let Some(r) = turn.join_next().await {
            if let Err(e) = r {
                self.client
                    .events
                    .log("host_poll_failed", json!({"error": e.to_string()}));
            }
        }
        self.book.retain(&names);
        self.tiers.retain(|n| names.contains(n));
        self.grpc.retain(|u| urls.contains(u));
        lock(&self.consumers).retain(|n, _| names.contains(n));
        lock(&self.probe_at).retain(|n, _| names.contains(n));
    }

    /// Hafif tek yoklama, poller ile AYNI kayıt yolundan. Hız sınırına takılırsa ya da host yoksa `None`.
    pub async fn probe_host(&self, name: &str) -> Option<bool> {
        let hosts = self.source.load();
        let host = record::find(&hosts, name)?;
        {
            let mut at = lock(&self.probe_at);
            if at.get(name).is_some_and(|t| t.elapsed() < PROBE_MIN_GAP) {
                return None;
            }
            at.insert(name.to_string(), Instant::now());
        }
        let result = self.fetch_status(host).await;
        let ok = result.ok;
        self.book.record(name, result, epoch_now());
        Some(ok)
    }

    /// "Şimdi test et": dönüş HER ZAMAN bu çağrının taze sonucu ve kademesi (paylaşılan toleransla yumuşatılmaz).
    pub async fn test_now(&self, name: &str) -> Option<(HostStatus, Tier)> {
        let hosts = self.source.load();
        let host = record::find(&hosts, name)?;
        let result = self.fetch_status(host).await;
        self.book.record(name, result.clone(), epoch_now());
        let tier = self.probe_tier(host).await;
        self.tiers.update(name, tier);
        Some((result, tier))
    }

    pub async fn probe_tier(&self, host: &HostRecord) -> Tier {
        let t = &self.client.timeouts;
        if !host.grpc_url.is_empty()
            && self
                .grpc
                .probe(&host.grpc_url, host.token.expose(), t.grpc_probe)
                .await
        {
            return Tier::Grpc;
        }
        if self.client.ws_probe(host).await {
            return Tier::Ws;
        }
        Tier::Rest
    }

    pub async fn probe_tiers_once(self: Arc<Self>) {
        let mut turn = JoinSet::new();
        for h in self.source.load() {
            let me = self.clone();
            turn.spawn(async move {
                let tier = me.probe_tier(&h).await;
                me.tiers.update(&h.name, tier);
            });
        }
        while turn.join_next().await.is_some() {}
        self.relays.reap_idle();
    }

    pub fn open_relays(&self) -> usize {
        self.relays.len()
    }

    /// Poller + kademe yoklayıcısı. Takılan ([`POLLER_STALL`]) ya da panikleyen tur iptal edilip yenisi başlatılır.
    pub fn start(self: &Arc<Self>) -> Running {
        let me = self.clone();
        *lock(&me.beat) = Some(Instant::now());
        let poller = tokio::spawn(async move {
            loop {
                let mut turn = JoinSet::new();
                turn.spawn(me.clone().poll_once());
                match tokio::time::timeout(POLLER_STALL, turn.join_next()).await {
                    Ok(Some(Ok(()))) => *lock(&me.beat) = Some(Instant::now()),
                    other => {
                        me.restarts.fetch_add(1, Ordering::Relaxed);
                        me.client
                            .events
                            .log("host_poller_restarted", json!({"stalled": other.is_err()}));
                    }
                }
                tokio::time::sleep(POLL_INTERVAL).await;
            }
        });
        let me = self.clone();
        let prober = tokio::spawn(async move {
            loop {
                let mut turn = JoinSet::new();
                turn.spawn(me.clone().probe_tiers_once());
                if tokio::time::timeout(CAPABILITY_PROBE_INTERVAL, turn.join_next())
                    .await
                    .is_err()
                {
                    me.client
                        .events
                        .log("host_prober_restarted", json!({"stalled": true}));
                }
                tokio::time::sleep(CAPABILITY_PROBE_INTERVAL).await;
            }
        });
        Running { poller, prober }
    }

    pub fn poller_health(&self, running: &Running) -> PollerHealth {
        PollerHealth {
            alive: running.poller_alive(),
            age: lock(&self.beat).map(|b| b.elapsed()),
            restarts: self.restarts.load(Ordering::Relaxed),
        }
    }

    /// `/api/hosts` satırları: token yok. `probe` = adres yoklaması görünümü (`host_probe`), `local_build` = yerel commit.
    pub fn public_rows(
        &self,
        local_build: Option<&str>,
        probe: impl Fn(&str) -> Value,
    ) -> Vec<Value> {
        self.source
            .load()
            .iter()
            .map(|h| {
                let c = self.book.cached(&h.name);
                let remote = c.as_ref().and_then(|c| c.build_running.clone());
                let differs = match (local_build.filter(|l| !l.is_empty()), &remote) {
                    (Some(l), Some(r)) => !l.starts_with(r.as_str()) && !r.starts_with(l),
                    _ => false,
                };
                let mut row = h.public();
                let c = c.unwrap_or_else(|| HostStatus::failed("not polled yet"));
                row["ok"] = c.ok.into();
                row["error"] = json!(c.error);
                row["tier"] = self.tiers.get(&h.name).as_str().into();
                row["build_running"] = json!(remote);
                row["build_diff"] = differs.into();
                row["fwd"] = c.fwd;
                row["orphan_watch"] = c.orphan_watch;
                row["disk_clean"] = c.disk_clean;
                row["probe"] = probe(&h.name);
                row
            })
            .collect()
    }
}
