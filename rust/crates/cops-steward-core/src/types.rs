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
