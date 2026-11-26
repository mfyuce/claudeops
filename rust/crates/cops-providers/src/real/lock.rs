//! `atomic_json.file_lock`in süreçler arası yarısı: `<yol>.lock` üzerinde `flock` (Python ile aynı dosya, aynı kural).
//!
//! `rs/state` `cops-state::fsutil::FileLock` aynı sözleşmeyi uygular; o dal birleşince bu dosya onunla
//! tekleştirilmeli.
//!
//! Python'dan BİLİNÇLİ fark: kilit alınamazsa (symlink, başkasının dosyası, zaman aşımı) Python yalnız iş parçacığı
//! kilidiyle DEVAM eder; burada hata döner (kayıp güncelleme sessiz olmasın).

use crate::pyfmt::abspath;
use std::fs::{File, OpenOptions, TryLockError};
use std::io;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::time::{Duration, Instant};

/// `LOCK_TIMEOUT_SECONDS`.
pub const LOCK_TIMEOUT: Duration = Duration::from_secs(30);

/// Tutulan kilit; düşünce (tanıtıcı kapanınca) bırakılır. Her alım ayrı tanıtıcı açar: aynı süreçteki iş parçacıkları da
/// birbirini dışlar. İÇ İÇE alınamaz (Python'daki yeniden giriş yok).
#[derive(Debug)]
pub struct FileLock {
    _file: File,
}

impl FileLock {
    /// `path` kilitlenen BELGENİN yolu (`.lock` eki burada).
    pub fn acquire(path: &str, cwd: &str, timeout: Duration) -> io::Result<FileLock> {
        let path = abspath(path, cwd);
        if let Some((dir, _)) = path.rsplit_once('/') {
            if !dir.is_empty() {
                std::fs::create_dir_all(dir)?;
            }
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(format!("{path}.lock"))?;
        let meta = file.metadata()?;
        // SAFETY: `getuid` her zaman başarılı, argümansız sistem çağrısı.
        if !meta.is_file() || meta.uid() != unsafe { libc::getuid() } {
            return Err(io::Error::new(io::ErrorKind::PermissionDenied, "lock file not ours"));
        }
        let deadline = Instant::now() + timeout;
        loop {
            match file.try_lock() {
                Ok(()) => return Ok(FileLock { _file: file }),
                Err(TryLockError::WouldBlock) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(5));
                }
                Err(TryLockError::WouldBlock) => {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "flock zaman aşımı"));
                }
                Err(TryLockError::Error(e)) => return Err(e),
            }
        }
    }
}
