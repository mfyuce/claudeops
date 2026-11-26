//! Sürekli açık akış tüketicisi (WS/gRPC ortak). Ayrı görev; `stop`/düşürme görevi iptal eder, bağlantı kapanır.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use futures_util::future::BoxFuture;
use futures_util::stream::BoxStream;
use futures_util::StreamExt;
use serde_json::{json, Value};
use tokio::task::JoinHandle;
use tokio::time::Instant;

use crate::consts::CONSUMER_DEATH_LOG_MIN_INTERVAL;
use crate::events::Events;

/// `Ok(None)` = çözülemeyen/ilgisiz çerçeve (yine de canlılık kanıtı).
pub type FrameStream = BoxStream<'static, Result<Option<Value>, String>>;
pub type Open = BoxFuture<'static, Result<FrameStream, String>>;

/// Aynı etiket için dakikada en çok bir ölüm kaydı.
#[derive(Default)]
pub struct DeathLog {
    last: Mutex<HashMap<String, Instant>>,
}

impl DeathLog {
    fn report(&self, events: &dyn Events, label: &str, tier: &str, reason: &str) {
        {
            let mut m = self.last.lock().unwrap_or_else(|e| e.into_inner());
            m.retain(|_, t| t.elapsed() < CONSUMER_DEATH_LOG_MIN_INTERVAL);
            if m.contains_key(label) {
                return;
            }
            m.insert(label.to_string(), Instant::now());
        }
        let reason: String = reason.chars().take(200).collect();
        events.log(
            "push_consumer_died",
            json!({"label": label, "tier": tier, "reason": reason}),
        );
    }
}

struct Shared {
    last_msg: Mutex<Instant>,
    has_data: AtomicBool,
}

pub struct PushConsumer {
    shared: Arc<Shared>,
    task: JoinHandle<()>,
}

impl PushConsumer {
    pub fn spawn(
        tier: &'static str,
        label: String,
        open: Open,
        on_item: impl Fn(Value) + Send + 'static,
        events: Arc<dyn Events>,
        deaths: Arc<DeathLog>,
    ) -> PushConsumer {
        let shared = Arc::new(Shared {
            last_msg: Mutex::new(Instant::now()),
            has_data: AtomicBool::new(false),
        });
        let s = shared.clone();
        let task = tokio::spawn(async move {
            let reason = match open.await {
                Err(e) => e,
                Ok(mut stream) => loop {
                    match stream.next().await {
                        None => break "stream_ended".to_string(),
                        Some(Err(e)) => break e,
                        Some(Ok(item)) => {
                            *s.last_msg.lock().unwrap_or_else(|e| e.into_inner()) = Instant::now();
                            if let Some(item) = item {
                                on_item(item);
                                s.has_data.store(true, Ordering::Release);
                            }
                        }
                    }
                },
            };
            deaths.report(events.as_ref(), &label, tier, &reason);
        });
        PushConsumer { shared, task }
    }

    pub fn is_alive(&self) -> bool {
        !self.task.is_finished()
    }

    /// En az bir öğe ulaştı mı (veri gelene kadar REST yoklaması sürer).
    pub fn has_data(&self) -> bool {
        self.shared.has_data.load(Ordering::Acquire)
    }

    /// Yarı açık bağlantı görevi canlı tutar ama hiç mesaj getirmez; `is_alive` tek başına yakalayamaz.
    pub fn silent(&self) -> std::time::Duration {
        self.shared
            .last_msg
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .elapsed()
    }
}

impl Drop for PushConsumer {
    fn drop(&mut self) {
        self.task.abort();
    }
}
