//! Veri modeli (üretilen yapılar + Python yöntemleri).
pub use crate::types_gen::*;

impl SessionView {
    /// Blueprint doluysa o, değilse oturum adı.
    ///
    /// py: SessionView.project
    pub fn project(&self) -> &str {
        match &self.blueprint {
            Some(b) if !b.is_empty() => b,
            _ => &self.name,
        }
    }
}

impl Action {
    /// `Action(kind, name, reason, payload)`.
    pub fn new(
        kind: &str,
        name: &str,
        reason: impl Into<String>,
        payload: serde_json::Map<String, serde_json::Value>,
    ) -> Self {
        Action { kind: kind.into(), name: name.into(), reason: reason.into(), payload }
    }
}
