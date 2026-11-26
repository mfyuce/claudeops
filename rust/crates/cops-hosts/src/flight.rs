//! Tek uçuş (single-flight) dedup + son başarılı yanıt önbelleği. YALNIZ poll/okuma çağrıları için: aksiyonlar asla
//! dedup'lanmaz (bir tuş vuruşu sessizce kaybolurdu).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::Value;
use tokio::time::Instant;

/// Takılı bir istek URL'i sonsuza dek "uçuşta" tutmasın.
pub const INFLIGHT_MAX: Duration = Duration::from_secs(600);
/// LRU sınırı (benzersiz URL'li çağrılar önbelleği şişirmesin).
pub const LAST_GOOD_MAX: usize = 256;

#[derive(Default)]
struct State {
    /// url -> (başlangıç, nesil)
    inflight: HashMap<String, (Instant, u64)>,
    good: HashMap<String, (u64, u16, Value)>,
    seq: u64,
}

#[derive(Clone, Default)]
pub struct Flights {
    state: Arc<Mutex<State>>,
}

/// Uçuş sahibi. Düşürülünce (iptal edilen görev dahil) kayıt kalkar.
pub struct Flight {
    state: Arc<Mutex<State>>,
    url: String,
    gen: u64,
}

pub enum Begin {
    Go(Flight),
    /// Aynı URL uçuşta: varsa son başarılı yanıt.
    Busy(Option<(u16, Value)>),
}

fn lock(m: &Mutex<State>) -> std::sync::MutexGuard<'_, State> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

impl Flights {
    pub fn begin(&self, url: &str) -> Begin {
        let mut st = lock(&self.state);
        if st
            .inflight
            .get(url)
            .is_some_and(|(at, _)| at.elapsed() < INFLIGHT_MAX)
        {
            return Begin::Busy(st.good.get(url).map(|(_, s, v)| (*s, v.clone())));
        }
        st.seq += 1;
        let gen = st.seq;
        st.inflight.insert(url.to_string(), (Instant::now(), gen));
        Begin::Go(Flight {
            state: self.state.clone(),
            url: url.to_string(),
            gen,
        })
    }

    #[cfg(test)]
    fn len_good(&self) -> usize {
        lock(&self.state).good.len()
    }
}

impl Flight {
    pub fn remember(&self, status: u16, body: &Value) {
        let mut st = lock(&self.state);
        st.seq += 1;
        let seq = st.seq;
        st.good
            .insert(self.url.clone(), (seq, status, body.clone()));
        while st.good.len() > LAST_GOOD_MAX {
            let Some(old) = st
                .good
                .iter()
                .min_by_key(|(_, v)| v.0)
                .map(|(k, _)| k.clone())
            else {
                break;
            };
            st.good.remove(&old);
        }
    }
}

impl Drop for Flight {
    fn drop(&mut self) {
        let mut st = lock(&self.state);
        // Bayatlayıp yenisi başladıysa onun kaydını silme.
        if st
            .inflight
            .get(&self.url)
            .is_some_and(|(_, g)| *g == self.gen)
        {
            st.inflight.remove(&self.url);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn go(f: &Flights, u: &str) -> Flight {
        match f.begin(u) {
            Begin::Go(g) => g,
            Begin::Busy(_) => panic!("busy"),
        }
    }

    #[tokio::test(start_paused = true)]
    async fn busy_returns_last_good_and_releases_on_drop() {
        let f = Flights::default();
        let a = go(&f, "u");
        assert!(matches!(f.begin("u"), Begin::Busy(None)));
        a.remember(200, &json!({"n":1}));
        match f.begin("u") {
            Begin::Busy(Some((200, v))) => assert_eq!(v["n"], 1),
            _ => panic!(),
        }
        drop(a);
        drop(go(&f, "u"));
    }

    #[tokio::test(start_paused = true)]
    async fn stale_flight_is_replaced_and_old_drop_does_not_free_new() {
        let f = Flights::default();
        let old = go(&f, "u");
        tokio::time::advance(INFLIGHT_MAX + Duration::from_secs(1)).await;
        let _new = go(&f, "u");
        drop(old);
        assert!(matches!(f.begin("u"), Begin::Busy(_)));
    }

    #[tokio::test]
    async fn lru_is_bounded_and_keeps_recent() {
        let f = Flights::default();
        for i in 0..LAST_GOOD_MAX + 10 {
            let g = go(&f, &format!("u{i}"));
            g.remember(200, &json!({}));
        }
        assert_eq!(f.len_good(), LAST_GOOD_MAX);
        let _g = go(&f, "u0");
        assert!(matches!(f.begin("u0"), Begin::Busy(None)));
        let last = format!("u{}", LAST_GOOD_MAX + 9);
        let _g = go(&f, &last);
        assert!(matches!(f.begin(&last), Begin::Busy(Some(_))));
    }
}
