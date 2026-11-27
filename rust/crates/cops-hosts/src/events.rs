//! Tanılama olayı çıkışı (Python `diag_log`). Alanlara token ya da sorgulu URL KONMAZ.

use serde_json::Value;

pub trait Events: Send + Sync {
    fn log(&self, event: &str, fields: Value);
}

pub struct NoEvents;

impl Events for NoEvents {
    fn log(&self, _event: &str, _fields: Value) {}
}
