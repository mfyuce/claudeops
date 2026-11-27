//! Yetenek kademesi: grpc > ws > rest. Anında yükselme, tolere edilen düşme. Erişilebilirlikten AYRI eksen.

use std::collections::HashMap;
use std::sync::Mutex;

use crate::consts::CONSECUTIVE_FAILURES_BEFORE_ERROR;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord)]
pub enum Tier {
    #[default]
    Rest,
    Ws,
    Grpc,
}

impl Tier {
    pub fn as_str(self) -> &'static str {
        match self {
            Tier::Rest => "rest",
            Tier::Ws => "ws",
            Tier::Grpc => "grpc",
        }
    }
}

#[derive(Default)]
pub struct TierBook {
    /// ad -> (etkin kademe, ardışık düşük yoklama)
    map: Mutex<HashMap<String, (Tier, u32)>>,
}

impl TierBook {
    pub fn update(&self, name: &str, probed: Tier) {
        let mut m = self.map.lock().unwrap_or_else(|e| e.into_inner());
        let e = m.entry(name.to_string()).or_default();
        if probed >= e.0 {
            *e = (probed, 0);
            return;
        }
        e.1 = e.1.saturating_add(1);
        if e.1 >= CONSECUTIVE_FAILURES_BEFORE_ERROR {
            // Python: sayaç sıfırlanmaz, sonraki düşük yoklama hemen uygulanır.
            e.0 = probed;
        }
    }

    /// gRPC artık denenemez (kayıttan `grpc_url` kaldırıldı): düşme toleransı beklenmeden `Ws`.
    pub(crate) fn drop_grpc(&self, name: &str) {
        let mut m = self.map.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(e) = m.get_mut(name) {
            if e.0 == Tier::Grpc {
                *e = (Tier::Ws, 0);
            }
        }
    }

    pub fn get(&self, name: &str) -> Tier {
        self.map
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(name)
            .map_or(Tier::Rest, |e| e.0)
    }

    pub fn retain(&self, keep: impl Fn(&str) -> bool) {
        self.map
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .retain(|k, _| keep(k));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn upgrade_is_immediate_downgrade_is_tolerated() {
        let b = TierBook::default();
        assert_eq!(b.get("a"), Tier::Rest);
        b.update("a", Tier::Grpc);
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR - 1 {
            b.update("a", Tier::Rest);
            assert_eq!(b.get("a"), Tier::Grpc);
        }
        b.update("a", Tier::Grpc);
        b.update("a", Tier::Rest);
        assert_eq!(b.get("a"), Tier::Grpc);
        for _ in 0..CONSECUTIVE_FAILURES_BEFORE_ERROR {
            b.update("a", Tier::Ws);
        }
        assert_eq!(b.get("a"), Tier::Ws);
    }
}
