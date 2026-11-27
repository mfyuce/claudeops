//! `<ikili> --help` yoklaması ve önbelleği (`claude_help_text`, `ucli_client.chat_help_text`).
//!
//! Anahtar (yol, `mtime_ns`, boyut): güncellenen ikili yeniden yoklanır. Çalıştırılamayan, zaman aşımına uğrayan, sınırı
//! aşan, UTF-8 olmayan ya da boş çıktı ÖNBELLEĞE ALINMAZ ve "" sayılır (bayrak yok: güvenli taraf). UTF-8 olmayan çıktı
//! ikili sürümü başına bir kez günlüğe girer (`help_output_not_utf8`).

use crate::probe::Diag;
use crate::pyfmt::strip;
use crate::real::process::{self, Capture, Spec};
use crate::real::{fsio, Env};
use crate::spawn_exec::DiagSink;
use serde_json::json;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// `_HELP_TIMEOUT_SECONDS`.
pub const HELP_TIMEOUT: Duration = Duration::from_secs(10);
/// Her akış için çıktı sınırı (Python sınırsız).
pub const HELP_MAX_BYTES: u64 = 1 << 20;
/// Önbellek girdi sınırı (Python sınırsız).
const CACHE_MAX_ENTRIES: usize = 64;

type Key = (String, Vec<String>, i64, u64);

/// `_HELP_CACHE`; süreç başına tek örnek paylaşılır. Kilit alt süreç sırasında tutulmaz.
pub struct HelpCache {
    timeout: Duration,
    entries: Mutex<HashMap<Key, String>>,
    /// Günlüğe girmiş okunamayan sürümler.
    unreadable: Mutex<HashSet<Key>>,
    diag: Option<Arc<dyn DiagSink>>,
}

impl std::fmt::Debug for HelpCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("HelpCache")
            .field("timeout", &self.timeout)
            .field("entries", &self.len())
            .finish()
    }
}

impl Default for HelpCache {
    fn default() -> Self {
        HelpCache::with_timeout(HELP_TIMEOUT)
    }
}

impl HelpCache {
    pub fn with_timeout(timeout: Duration) -> HelpCache {
        HelpCache {
            timeout,
            entries: Mutex::new(HashMap::new()),
            unreadable: Mutex::default(),
            diag: None,
        }
    }

    /// `help_output_not_utf8` olayının yazılacağı günlük (gerçek: `diag_log`).
    pub fn with_diag(mut self, diag: Arc<dyn DiagSink>) -> HelpCache {
        self.diag = Some(diag);
        self
    }

    fn log_unreadable(&self, key: Key) {
        let binary = key.0.clone();
        let mut seen = self
            .unreadable
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if seen.len() >= CACHE_MAX_ENTRIES {
            seen.clear();
        }
        if !seen.insert(key) {
            return;
        }
        drop(seen);
        if let Some(sink) = &self.diag {
            sink.log(&Diag {
                event: "help_output_not_utf8",
                fields: vec![("binary", json!(binary))],
            });
        }
    }

    pub fn len(&self) -> usize {
        self.entries
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// `<binary> <args...>` çıktısı (stdout + stderr); kullanılamıyorsa "". Çıkış koduna bakılmaz.
    pub fn text(&self, env: &Env, binary: &str, args: &[&str]) -> String {
        let Some(st) = fsio::stat(binary) else {
            return String::new();
        };
        let key: Key = (
            binary.to_string(),
            args.iter().map(|a| a.to_string()).collect(),
            st.mtime_ns,
            st.size,
        );
        if let Some(hit) = self
            .entries
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&key)
        {
            return hit.clone();
        }
        let argv: Vec<String> = std::iter::once(binary)
            .chain(args.iter().copied())
            .map(str::to_string)
            .collect();
        let spec = Spec {
            argv: &argv,
            cwd: None,
            env,
            timeout: self.timeout,
            stdout: Capture::Bounded(HELP_MAX_BYTES),
            stderr: Capture::Bounded(HELP_MAX_BYTES),
        };
        let Ok(out) = process::run(&spec) else {
            return String::new();
        };
        let (Ok(a), Ok(b)) = (String::from_utf8(out.stdout), String::from_utf8(out.stderr)) else {
            self.log_unreadable(key);
            return String::new();
        };
        // Python metin kipi: evrensel satır sonu
        let text = (a.replace("\r\n", "\n") + &b.replace("\r\n", "\n")).replace('\r', "\n");
        if strip(&text).is_empty() {
            return String::new();
        }
        let mut entries = self.entries.lock().unwrap_or_else(PoisonError::into_inner);
        if entries.len() >= CACHE_MAX_ENTRIES {
            entries.clear();
        }
        entries.insert(key, text.clone());
        text
    }
}
