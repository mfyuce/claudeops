//! Atomik yazım ve süreçler arası kilit (Python `atomic_json.py` ve `web._atomic_write_text`).
use crate::json::Json;
use std::cell::RefCell;
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::rc::{Rc, Weak};
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

thread_local! {
    /// Bu iş parçacığının tuttuğu `file_lock` kilitleri: normalize yol -> açık kilit tanıtıcısı.
    static HELD: RefCell<HashMap<PathBuf, Weak<File>>> = RefCell::new(HashMap::new());
}

/// Tutulan `flock`; son tutamaç düşünce bırakılır. [`FileLock::acquire`] AYNI iş parçacığında yeniden girilebilir (Python
/// `file_lock` gibi: iç içe alma yeni `flock` almaz, dış kilidi paylaşır; düşürme sırası önemsiz). Kilit iş parçacığına
/// bağlıdır: tutamaç `Send` DEĞİL (başka iş parçacığına taşınan tutamaç yeniden girişi bozardı; async kod
/// `spawn_blocking` içinde alıp bırakmalı).
#[derive(Debug)]
pub struct FileLock {
    file: Rc<File>,
    /// Yeniden girilebilir kilidin anahtarı (normalize yol); `blocking` kilitte yok.
    key: Option<PathBuf>,
}

impl Drop for FileLock {
    fn drop(&mut self) {
        if let Some(k) = &self.key {
            if Rc::strong_count(&self.file) == 1 {
                // son tutamaç: kayıt silinir, tanıtıcı kapanınca flock bırakılır
                let _ = HELD.try_with(|h| h.borrow_mut().remove(k));
            }
        }
    }
}

/// Kilit dosyası yalnız normal dosya VE çağırana aitse kullanılır (Python `_file_lock_outer`).
fn lock_file_usable(is_file: bool, owner: u32, me: u32) -> bool {
    is_file && owner == me
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
    /// Python `file_lock(path)`: yol `normpath(abspath)`, kilit `<yol>.lock` (`O_NOFOLLOW`, 0600, bize ait normal dosya),
    /// 30 sn beklenir. Aynı iş parçacığında iç içe alınabilir.
    /// Sapmalar (sahibe soruldu, `docs/rs-state.md`): zaman aşımında ve kilit dosyası bize ait değilse HATA (Python
    /// uyarıp yalnız iş parçacığı kilidiyle, süreçler arası korumasız sürer).
    pub fn acquire(path: &Path) -> io::Result<FileLock> {
        Self::acquire_within(path, LOCK_TIMEOUT)
    }

    pub fn acquire_within(path: &Path, timeout: Duration) -> io::Result<FileLock> {
        let key = crate::paths::abs_normpath(path);
        let held = HELD.with(|h| h.borrow().get(&key).and_then(Weak::upgrade));
        if let Some(file) = held {
            return Ok(FileLock {
                file,
                key: Some(key),
            });
        }
        let lock = with_suffix(&key, ".lock");
        crate::paths::guard_write(&lock);
        fs::create_dir_all(parent_of(&key))?;
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
        if !lock_file_usable(m.is_file(), m.uid(), unsafe { libc::getuid() }) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "kilit dosyası bize ait değil",
            ));
        }
        let deadline = Instant::now() + timeout;
        loop {
            match flock(&f, libc::LOCK_EX | libc::LOCK_NB) {
                Ok(()) => break,
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Err(io::Error::new(io::ErrorKind::TimedOut, "flock zaman aşımı"));
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(e) => return Err(e),
            }
        }
        let file = Rc::new(f);
        HELD.with(|h| h.borrow_mut().insert(key.clone(), Rc::downgrade(&file)));
        Ok(FileLock {
            file,
            key: Some(key),
        })
    }

    /// Python `atomic_json.roster_lock(tsv)`: roster.tsv + models.tsv için TEK kilit `<dizin>/roster.lock`.
    pub fn roster(tsv_path: &Path) -> io::Result<FileLock> {
        let dir = crate::paths::abs_normpath(tsv_path);
        let dir = dir.parent().unwrap_or(Path::new("/"));
        Self::acquire(&dir.join("roster"))
    }

    /// Python `instances._locked`: verilen kilit dosyasında süresiz bekleyen `LOCK_EX` (yeniden girilemez; Python'da da).
    pub fn blocking(lock_file: &Path) -> io::Result<FileLock> {
        crate::paths::guard_write(lock_file);
        fs::create_dir_all(parent_of(lock_file))?;
        let f = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(lock_file)?;
        flock(&f, libc::LOCK_EX)?;
        Ok(FileLock {
            file: Rc::new(f),
            key: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reentrant_same_thread_exclusive_across_threads() {
        let env = crate::paths::TestEnv::new().unwrap();
        let p = env.dir().join("belge.json");
        let outer = FileLock::acquire(&p).unwrap();
        // aynı iş parçacığı: farklı yazımla da (a/../belge.json) hemen alınır
        let alias = env.dir().join("alt/../belge.json");
        let inner = FileLock::acquire_within(&alias, Duration::from_millis(50)).unwrap();
        // başka iş parçacığı alamaz
        let p2 = p.clone();
        let t = std::thread::spawn(move || {
            FileLock::acquire_within(&p2, Duration::from_millis(100)).map(|_| ())
        });
        assert_eq!(
            t.join().unwrap().unwrap_err().kind(),
            io::ErrorKind::TimedOut
        );
        // dış önce düşse de iç tutamaç kilidi tutar
        drop(outer);
        let p3 = p.clone();
        let t = std::thread::spawn(move || {
            FileLock::acquire_within(&p3, Duration::from_millis(100)).map(|_| ())
        });
        assert!(
            t.join().unwrap().is_err(),
            "iç tutamaç yaşarken kilit sürmeli"
        );
        drop(inner);
        let p4 = p.clone();
        let t = std::thread::spawn(move || {
            FileLock::acquire_within(&p4, Duration::from_millis(500)).map(|_| ())
        });
        assert!(t.join().unwrap().is_ok(), "son tutamaç düşünce bırakılır");
        assert!(HELD.with(|h| h.borrow().is_empty()));
    }

    /// Başkasına ait kilit dosyası root olmadan üretilemez: karar işlevi sınanır (normal dosya olmayan gerçek dosya:
    /// `tests/fs_atomic.rs::non_regular_lock_file_refused`).
    #[test]
    fn lock_file_owner_and_type_rules() {
        assert!(lock_file_usable(true, 1000, 1000));
        assert!(!lock_file_usable(true, 0, 1000), "başkasının dosyası");
        assert!(!lock_file_usable(true, 1001, 1000));
        assert!(!lock_file_usable(false, 1000, 1000), "normal dosya değil");
    }

    /// H17: kilit dosyası sembolik bağ ya da başkasının dosyasıysa kullanılmaz (bağ izlenmez, hedef oluşturulmaz).
    #[test]
    fn lock_symlink_refused() {
        let env = crate::paths::TestEnv::new().unwrap();
        let target = env.root().join("hedef");
        std::os::unix::fs::symlink(&target, env.dir().join("b.lock")).unwrap();
        assert!(FileLock::acquire(&env.dir().join("b")).is_err());
        assert!(!target.exists(), "bağın hedefi oluşturulmadı");
    }
}
