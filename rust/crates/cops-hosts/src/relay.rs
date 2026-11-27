//! Uzak terminal çıktısı aktarıcıları: (host, ad, dil, ...) başına TEK uzak akış; yerel okuyucu bellekten okur.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use tokio::time::Instant;

use crate::consts::{
    GRPC_TERM_REFUSED_TTL, TERM_RELAY_IDLE_TTL, TERM_RELAY_RESTART_MIN_INTERVAL, TERM_RELAY_SILENCE,
};
use crate::federation::{Federation, StreamEndpoint};
use crate::grpc::REFUSED_BY_HOST;
use crate::push::PushConsumer;
use crate::record;
use crate::tier::Tier;
use crate::ws;

/// Uzak akışın biçimini belirleyen seçenekler (her bileşim ayrı akış).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TermOpts {
    pub lite: bool,
    /// Uzak yoklama aralığı (sn).
    pub interval: Option<f64>,
    pub viewport: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct Key {
    host: String,
    name: String,
    lang: String,
    lite: bool,
    interval: Option<String>,
    viewport: bool,
}

struct Relay {
    latest: Arc<Mutex<Option<Value>>>,
    consumer: PushConsumer,
    created: Instant,
    last_read: Instant,
    /// Adres/token değişince akış yeniden kurulur (kademe değişimi tek başına yenilemez).
    endpoint: StreamEndpoint,
    /// Akış fiilen gRPC üzerinden mi (red sonrası kademe gRPC iken WS'ten kurulabilir).
    over_grpc: bool,
}

impl Relay {
    fn grpc_refused(&self) -> bool {
        self.over_grpc
            && self
                .consumer
                .end_reason()
                .is_some_and(|r| r.starts_with(REFUSED_BY_HOST))
    }
}

#[derive(Default)]
pub(crate) struct Relays {
    map: Mutex<HashMap<Key, Relay>>,
    /// gRPC'de terminali reddeden (host, grpc_url) -> bu ana dek relay WS'ten kurulur. Kilit sırası: `map`, sonra bu.
    refused: Mutex<HashMap<(String, String), Instant>>,
}

fn connecting(msg: &str) -> Value {
    json!({"ok": false, "error": msg, "code": "relay_connecting"})
}

impl Relays {
    pub(crate) fn reap_idle(&self) {
        let mut m = self.map.lock().unwrap_or_else(|e| e.into_inner());
        m.retain(|_, r| r.last_read.elapsed() < TERM_RELAY_IDLE_TTL);
    }

    pub(crate) fn len(&self) -> usize {
        self.map.lock().unwrap_or_else(|e| e.into_inner()).len()
    }
}

impl Federation {
    /// Son kare (ağ beklemez; akış ilk okumada tembel başlar). Tokio çalışma zamanı içinde çağrılır. Ölü ya da sessiz
    /// akışın DONMUŞ karesi verilmez.
    pub fn term_output(&self, host_name: &str, name: &str, lang: &str, opts: &TermOpts) -> Value {
        let hosts = self.source.load();
        let Some(host) = record::find(&hosts, host_name) else {
            return json!({"ok": false, "error": format!("unknown host: {host_name}"), "code": "unknown_host"});
        };
        let interval = opts
            .interval
            .filter(|i| i.is_finite() && *i > 0.0)
            .map(|i| i.to_string());
        let key = Key {
            host: host_name.into(),
            name: name.into(),
            lang: lang.into(),
            lite: opts.lite,
            interval: interval.clone(),
            viewport: opts.viewport,
        };
        let endpoint = StreamEndpoint::of(self.stream_tier(host), host);
        let mut map = self.relays.map.lock().unwrap_or_else(|e| e.into_inner());
        let refused_key = (host_name.to_string(), host.grpc_url.clone());
        let mut refused = self
            .relays
            .refused
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        refused.retain(|_, until| *until > Instant::now());
        if let Some(r) = map.get(&key) {
            if r.grpc_refused() {
                // Taşıma değişiyor: yeniden kurma arası beklenmez.
                // Reddeden, relay'in KENDİ adresi: kayıt o arada düzenlendiyse yeni adres engellenmez.
                let by = (host_name.to_string(), r.endpoint.grpc_url().to_string());
                refused.insert(by, Instant::now() + GRPC_TERM_REFUSED_TTL);
                map.remove(&key);
            } else if !r.endpoint.same_address(&endpoint) {
                map.remove(&key);
            } else if r.consumer.is_alive() && r.consumer.silent() > TERM_RELAY_SILENCE {
                self.client.events.log(
                    "term_relay_silent_restart",
                    json!({"host": host_name, "name": name, "silent": r.consumer.silent().as_secs()}),
                );
                map.remove(&key);
            } else if !r.consumer.is_alive() {
                if r.created.elapsed() < TERM_RELAY_RESTART_MIN_INTERVAL {
                    // Hemen ölen akışı her okumada yeniden kurma.
                    return connecting("relay: bağlantı koptu, yeniden deneniyor");
                }
                map.remove(&key);
            }
        }
        let use_grpc = endpoint.tier() == Tier::Grpc && !refused.contains_key(&refused_key);
        drop(refused);
        let relay = map.entry(key).or_insert_with(|| {
            let latest: Arc<Mutex<Option<Value>>> = Arc::default();
            let sink = latest.clone();
            let open = if use_grpc {
                self.grpc
                    .term_stream(&host.grpc_url, host.token.expose(), name, lang)
            } else {
                let mut q = vec![
                    ("name".to_string(), name.to_string()),
                    ("lang".to_string(), lang.to_string()),
                ];
                if opts.lite {
                    q.push(("lite".into(), "1".into()));
                }
                if let Some(i) = &interval {
                    q.push(("interval".into(), i.clone()));
                }
                if opts.viewport {
                    q.push(("viewport".into(), "1".into()));
                }
                ws::open(
                    self.client.clone(),
                    host.clone(),
                    "/ws/term",
                    q,
                    ws::parse_term_frame,
                    self.skips.clone(),
                )
            };
            let label = format!(
                "term:{host_name}/{name}{}{}{}",
                if opts.lite { "?lite" } else { "" },
                interval
                    .as_ref()
                    .map(|i| format!("@{i}s"))
                    .unwrap_or_default(),
                if opts.viewport { "+viewport" } else { "" },
            );
            let consumer = PushConsumer::spawn(
                if use_grpc { "grpc" } else { "ws" },
                label,
                open,
                move |item| *sink.lock().unwrap_or_else(|e| e.into_inner()) = Some(item),
                self.client.events.clone(),
                self.deaths.clone(),
            );
            Relay {
                latest,
                consumer,
                created: Instant::now(),
                last_read: Instant::now(),
                endpoint,
                over_grpc: use_grpc,
            }
        });
        relay.last_read = Instant::now();
        let latest = relay
            .latest
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone();
        latest.unwrap_or_else(|| connecting("relay: henüz veri gelmedi"))
    }
}
