//! Atomik yazım ve süreçler arası kilit (Python `atomic_json.py` ve `web._atomic_write_text`).
use crate::json::Json;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

/// Python `LOCK_TIMEOUT_SECONDS`.
pub const LOCK_TIMEOUT: Duration = Duration::from_secs(30);

static COUNTER: AtomicU64 = AtomicU64::new(0);

fn with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut s = path.as_os_str().to_os_string();
    s.push(suffix);
    s.into()
}

fn parent_of(path: &Path) -> &Path {
    match path.parent() {
        Some(p) if !p.as_os_str().is_empty() => p,
        _ => Path::new("."),
    }
}

fn fsync_dir(path: &Path) {
    if let Ok(d) = File::open(parent_of(path)) {
        let _ = d.sync_all();
    }
}

fn write_replace(tmp: &Path, path: &Path, data: &[u8], mode: Option<u32>) -> io::Result<()> {
    crate::paths::guard_write(path);
    crate::paths::guard_write(tmp);
    let mut o = OpenOptions::new();
    o.write(true)
        .create_new(true)
        .custom_flags(libc::O_NOFOLLOW)
        .mode(mode.unwrap_or(0o666)); // None: umask uygulanır
    let res = (|| {
        let mut f = o.open(tmp)?;
        if let Some(m) = mode {
            let _ = f.set_permissions(fs::Permissions::from_mode(m)); // umask'ı aş
        }
        f.write_all(data)?;
        f.sync_all()?;
        fs::rename(tmp, path)?;
        fsync_dir(path);
        Ok(())
    })();
    if res.is_err() {
        let _ = fs::remove_file(tmp);
    }
    res
}

/// `atomic_write_json`: `mode=None` iken var olan normal dosyanın izni korunur. Üst dizin oluşturulur.
pub fn atomic_write_json(path: &Path, obj: &Json, mode: Option<u32>) -> io::Result<()> {
    fs::create_dir_all(parent_of(path))?;
    let mode = mode.or_else(|| {
        fs::metadata(path)
            .ok()
            .filter(fs::Metadata::is_file)
            .map(|m| m.mode() & 0o7777)
    });
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let tmp = with_suffix(path, &format!(".{}-rs{n}.tmp", std::process::id()));
    let _ = fs::remove_file(&tmp);
    write_replace(&tmp, path, obj.to_indented().as_bytes(), mode)
}

/// `atomic_json.atomic_write_text`: `atomic_write_json`un düz metin karşılığı (`mode=None` iken var olan izin korunur).
pub fn atomic_write_text(path: &Path, text: &str, mode: Option<u32>) -> io::Result<()> {
    fs::create_dir_all(parent_of(path))?;
    let mode = mode.or_else(|| {
        fs::metadata(path)
            .ok()
            .filter(fs::Metadata::is_file)
            .map(|m| m.mode() & 0o7777)
    });
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let tmp = with_suffix(path, &format!(".{}-rs{n}.tmp", std::process::id()));
    let _ = fs::remove_file(&tmp);
    write_replace(&tmp, path, text.as_bytes(), mode)
}

/// `dir` içinde `prefix<eşsiz>suffix` adlı YENİ dosya (`O_EXCL|O_NOFOLLOW`, 0600; Python `tempfile.mkstemp`).
pub fn create_unique(dir: &Path, prefix: &str, suffix: &str) -> io::Result<PathBuf> {
    for _ in 0..100 {
        let n = COUNTER.fetch_add(1, Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.subsec_nanos());
        let p = dir.join(format!(
            "{prefix}{}x{n}x{nanos:x}{suffix}",
            std::process::id()
        ));
        crate::paths::guard_write(&p);
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .custom_flags(libc::O_NOFOLLOW)
            .mode(0o600)
            .open(&p)
        {
            Ok(_) => return Ok(p),
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "eşsiz geçici ad bulunamadı",
    ))
}

/// Bozuk belgenin kanıt kopyası: `<path>.corrupt-<sha256 ilk 8>` (0600, `O_EXCL`; aynı içerik bir kez). Python
/// `settings._backup_if_corrupt` ad ve izin kuralı. Kopya zaten varsa aynı yol döner.
pub fn write_corrupt_copy(path: &Path, raw: &[u8]) -> io::Result<PathBuf> {
    let sha = crate::sha256::sha256_hex(raw);
    let dest = with_suffix(path, &format!(".corrupt-{}", &sha[..8]));
    crate::paths::guard_write(&dest);
    if dest.exists() {
        return Ok(dest);
    }
    let mut f = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&dest)?;
    f.write_all(raw)?;
    Ok(dest)
}

/// `web._atomic_write_text` (roster/models): aynı dizinde `.tmp-*.tsv`, her zaman 0600 (Python `mkstemp`).
pub fn atomic_write_tsv(path: &Path, text: &str) -> io::Result<()> {
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let tmp = parent_of(path).join(format!(".tmp-{}-rs{n}.tsv", std::process::id()));
    let _ = fs::remove_file(&tmp);
    write_replace(&tmp, path, text.as_bytes(), Some(0o600))
}

/// Tutulan `flock`; düşünce bırakılır. Aynı süreçte iç içe ALINMAZ (ikinci tanıtıcı kendini bekler): kilit isteyen
/// iç işlevler guard referansı alır.
#[derive(Debug)]
pub struct FileLock {
    _file: File,
}

fn flock(f: &File, op: libc::c_int) -> io::Result<()> {
    loop {
        // SAFETY: açık ve bu işlev boyunca yaşayan bir tanıtıcı.
        if unsafe { libc::flock(f.as_raw_fd(), op) } == 0 {
            return Ok(());
        }
        let e = io::Error::last_os_error();
        if e.kind() != io::ErrorKind::Interrupted {
            return Err(e);
        }
    }
}

impl FileLock {
    /// Python `file_lock(path)`: `path + ".lock"`, `O_NOFOLLOW`, kendi dosyamız olmalı, 30 sn beklenir.
    /// Sapma: alınamazsa HATA (Python uyarıp yalnız iş parçacığı kilidiyle sürer).
    pub fn acquire(path: &Path) -> io::Result<FileLock> {
        Self::acquire_within(path, LOCK_TIMEOUT)
    }

    pub fn acquire_within(path: &Path, timeout: Duration) -> io::Result<FileLock> {
        fs::create_dir_all(parent_of(path))?;
        let lock = with_suffix(path, ".lock");
        let f = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .custom_flags(libc::O_NOFOLLOW)
            .mode(0o600)
            .open(&lock)?;
        let m = f.metadata()?;
        // SAFETY: getuid her zaman başarılıdır.
        if !m.is_file() || m.uid() != unsafe { libc::getuid() } {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "kilit dosyası bize ait değil",
            ));
        }
        let deadline = Instant::now() + timeout;
        loop {
            match flock(&f, libc::LOCK_EX | libc::LOCK_NB) {
                Ok(()) => return Ok(FileLock { _file: f }),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Err(io::Error::new(io::ErrorKind::TimedOut, "flock zaman aşımı"));
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(e) => return Err(e),
            }
        }
    }

    /// Python `instances._locked`: verilen kilit dosyasında süresiz bekleyen `LOCK_EX`.
    pub fn blocking(lock_file: &Path) -> io::Result<FileLock> {
        fs::create_dir_all(parent_of(lock_file))?;
        let f = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(lock_file)?;
        flock(&f, libc::LOCK_EX)?;
        Ok(FileLock { _file: f })
    }
}
