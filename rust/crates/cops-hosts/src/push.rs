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

/// Okunamayan ya da nesne olmayan uzak WS karesi (Python `_ws_envelope`): kare türü (`status`/`term`) başına dakikada
/// en çok bir `push_frame_skipped` kaydı. Kare atlanır, akış sürer.
#[derive(Default)]
pub struct SkipLog {
    last: Mutex<HashMap<&'static str, Instant>>,
}

impl SkipLog {
    pub fn report(&self, events: &dyn Events, kind: &'static str) {
        {
            let mut m = self.last.lock().unwrap_or_else(|e| e.into_inner());
            if m.get(kind)
                .is_some_and(|t| t.elapsed() < CONSUMER_DEATH_LOG_MIN_INTERVAL)
            {
                return;
            }
            m.insert(kind, Instant::now());
        }
        events.log("push_frame_skipped", json!({"kind": kind}));
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[derive(Default)]
    struct Rec(Mutex<Vec<(String, Value)>>);
    impl Events for Rec {
        fn log(&self, event: &str, fields: Value) {
            self.0.lock().unwrap().push((event.into(), fields));
        }
    }

    /// Python `_log_consumer_death`: etiket başına dakikada bir kayıt, neden 200 karaktere kırpılır.
    #[tokio::test(start_paused = true)]
    async fn consumer_death_is_logged_once_a_minute_per_label() {
        let ev = Rec::default();
        let log = DeathLog::default();
        log.report(&ev, "term:a/s1", "ws", "x");
        log.report(&ev, "term:a/s1", "ws", "y");
        log.report(&ev, "term:a/s1?lite", "ws", &"r".repeat(300));
        tokio::time::advance(CONSUMER_DEATH_LOG_MIN_INTERVAL).await;
        log.report(&ev, "term:a/s1", "grpc", "z");
        let got = ev.0.lock().unwrap().clone();
        assert_eq!(got.len(), 3);
        assert_eq!(
            got[0].1,
            json!({"label": "term:a/s1", "tier": "ws", "reason": "x"})
        );
        assert_eq!(got[1].1["label"], "term:a/s1?lite");
        assert_eq!(got[1].1["reason"].as_str().unwrap().len(), 200);
        assert_eq!(got[2].1["reason"], "z");
    }

    #[tokio::test(start_paused = true)]
    async fn skipped_frames_are_logged_at_most_once_a_minute_per_kind() {
        let ev = Rec::default();
        let log = SkipLog::default();
        for _ in 0..5 {
            log.report(&ev, "status");
        }
        log.report(&ev, "term");
        tokio::time::advance(CONSUMER_DEATH_LOG_MIN_INTERVAL - Duration::from_millis(1)).await;
        log.report(&ev, "status");
        assert_eq!(ev.0.lock().unwrap().len(), 2, "59.999 s: still suppressed");
        tokio::time::advance(Duration::from_millis(1)).await;
        log.report(&ev, "status");
        let got = ev.0.lock().unwrap().clone();
        assert_eq!(
            got,
            vec![
                ("push_frame_skipped".to_string(), json!({"kind": "status"})),
                ("push_frame_skipped".to_string(), json!({"kind": "term"})),
                ("push_frame_skipped".to_string(), json!({"kind": "status"})),
            ]
        );
    }
}
