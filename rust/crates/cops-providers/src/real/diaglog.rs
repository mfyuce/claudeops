//! `diaglog.diag_log`: ekleme kipinde JSONL, 5 MiB aşınca tek yedek. EN İYİ ÇABA: hata çağıran akışı kesmez.

use crate::probe::{Diag, Paths};
use crate::pyjson::Py;
use crate::real::Env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::Arc;

/// `MAX_BYTES`.
pub const MAX_BYTES: u64 = 5 * 1024 * 1024;

/// Dosyaya yazılan her kaydın DB `log` akışı aynası (`statedocs.mirror_log("diag", ..)`; rs/state bağlar).
pub type Mirror = Arc<dyn Fn(&str, &Py) + Send + Sync>;

#[derive(Clone)]
pub struct DiagLog {
    path: String,
    mirror: Option<Mirror>,
}

/// `datetime.now().isoformat(timespec="seconds")` (yerel saat, dilimsiz).
fn local_iso_now() -> String {
    // SAFETY: `time(NULL)` yalnız saati döner.
    let now = unsafe { libc::time(std::ptr::null_mut()) };
    // SAFETY: `tm` yalnız tam sayı ve işaretçi alanlıdır; sıfır geçerli başlangıçtır.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    // SAFETY: iki işaretçi de geçerli ve bu çağrıya özel; `localtime_r` yeniden girilebilir.
    if unsafe { libc::localtime_r(&now, &mut tm) }.is_null() {
        return String::new();
    }
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        i64::from(tm.tm_year) + 1900,
        tm.tm_mon + 1,
        tm.tm_mday,
        tm.tm_hour,
        tm.tm_min,
        tm.tm_sec
    )
}

fn py_of(v: &serde_json::Value) -> Py {
    use serde_json::Value as V;
    match v {
        V::Null => Py::Null,
        V::Bool(b) => Py::Bool(*b),
        V::Number(n) => match (n.as_i64(), n.as_f64()) {
            (Some(i), _) => Py::Int(i),
            _ if n.is_u64() => Py::BigInt(n.to_string()),
            (None, f) => Py::Float(f.unwrap_or(f64::NAN)),
        },
        V::String(s) => Py::Str(s.clone()),
        V::Array(a) => Py::Array(a.iter().map(py_of).collect()),
        V::Object(o) => Py::Object(o.iter().map(|(k, v)| (k.clone(), py_of(v))).collect()),
    }
}

impl DiagLog {
    pub fn new(path: impl Into<String>) -> DiagLog {
        DiagLog {
            path: path.into(),
            mirror: None,
        }
    }

    /// `diag_log_path()`: `CLAUDEOPS_DIAG_LOG` (boş değilse), yoksa `<durum dizini>/diag.log`.
    pub fn from_env(paths: &Paths, env: &Env) -> DiagLog {
        let over = env.get("CLAUDEOPS_DIAG_LOG").filter(|s| !s.is_empty());
        DiagLog::new(over.unwrap_or_else(|| format!("{}/diag.log", paths.claudeops_dir)))
    }

    pub fn with_mirror(mut self, mirror: Mirror) -> DiagLog {
        self.mirror = Some(mirror);
        self
    }

    pub fn path(&self) -> &str {
        &self.path
    }

    /// Tek kayıt; true = dosyaya yazıldı.
    pub fn log(&self, event: &str, fields: &[(&str, serde_json::Value)]) -> bool {
        if fs::metadata(&self.path).is_ok_and(|m| m.len() > MAX_BYTES) {
            let _ = fs::rename(&self.path, format!("{}.1", self.path));
        }
        // `{"ts": .., "event": .., **data}`: aynı adlı alan yerinde ezer
        let mut entry = vec![
            ("ts".to_string(), Py::Str(local_iso_now())),
            ("event".to_string(), Py::Str(event.to_string())),
        ];
        for (key, value) in fields {
            match entry.iter_mut().find(|(k, _)| k == key) {
                Some(slot) => slot.1 = py_of(value),
                None => entry.push((key.to_string(), py_of(value))),
            }
        }
        let entry = Py::Object(entry);
        let line = entry.dumps() + "\n";
        let open = OpenOptions::new()
            .append(true)
            .create(true)
            .mode(0o666)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(&self.path);
        let Ok(mut file) = open else { return false };
        // satır TEK `write` ile: eşzamanlı yazarların satırları karışmaz
        if !file.metadata().is_ok_and(|m| m.is_file()) || file.write_all(line.as_bytes()).is_err() {
            return false;
        }
        if let Some(mirror) = &self.mirror {
            mirror("diag", &entry);
        }
        true
    }

    /// [`crate::BuildOutput::diags`] sırasıyla yazılır; dönen değer yazılan kayıt sayısı.
    pub fn write_all(&self, diags: &[Diag]) -> usize {
        diags
            .iter()
            .filter(|d| self.log(d.event, &d.fields))
            .count()
    }
}
