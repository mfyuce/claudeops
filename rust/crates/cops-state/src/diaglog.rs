//! `diaglog.diag_log` yazma kısmı: `diag.log`a tek satır JSON ekler, 5 MiB'ı aşan dosyayı `.1`e taşır. Ekleme günlüğü
//! olduğu için atomik yazıcı değil (Python gibi `O_APPEND`). Çağıran: [`crate::StateDocs::diag_log`].
use crate::json::Json;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::Path;

/// Python `diaglog.MAX_BYTES`.
const MAX_BYTES: u64 = 5 * 1024 * 1024;

pub(crate) fn append(path: &Path, entry: &Json) -> io::Result<()> {
    crate::paths::guard_write(path);
    if fs::metadata(path).is_ok_and(|m| m.len() > MAX_BYTES) {
        let mut old = path.as_os_str().to_os_string();
        old.push(".1");
        // Python `_rotate_if_big` `OSError` yutar: taşınamazsa aynı dosyaya eklenir
        let _ = fs::rename(path, old);
    }
    let mut f = OpenOptions::new().append(true).create(true).open(path)?;
    f.write_all(format!("{}\n", entry.to_compact()).as_bytes())
}
