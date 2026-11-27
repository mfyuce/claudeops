//! Onay kayıt defterinin yazılan kısmı (`ucli_approval.{dir_for, register, set_state}`): Python ile aynı dosyalar, aynı
//! `flock`, aynı atomik 0600 yazım.
//!
//! Belirsizlikte RET: okunamayan ya da normal olmayan defter ezilmez; bozuk defterin önce `.corrupt-<özet>` kopyası
//! bırakılır; bitmemiş kayıt aynı anahtarla değiştirilmez; sembolik bağ olan koşu dizini kullanılmaz; kilit alınamazsa
//! yazılmaz. Cevap yazma, sürdürme ve listeleme panel uçlarındadır (T7), burada yok.

use crate::approval::{self, NewRun, StateChange};
use crate::probe::Paths;
use crate::pyfmt::abspath;
use crate::pyjson::Py;
use crate::real::effects::{atomic_write_text, makedirs};
use crate::real::lock::{log_refused, FileLock, LOCK_TIMEOUT};
use crate::real::oserr;
use crate::spawn_exec::DiagSink;
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs::{self, OpenOptions, Permissions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// Defter okuma sınırı (Python sınırsız): aşan defter okunamaz sayılır.
pub const INDEX_MAX_BYTES: u64 = 16 << 20;

/// Python istisnasının sınıfı ve metni (günlüğe ve `UcliError`a aynen gider). Belge içeriği taşımaz.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApprovalError {
    pub class: &'static str,
    pub text: String,
}

impl fmt::Display for ApprovalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.text)
    }
}

impl std::error::Error for ApprovalError {}

fn fail(class: &'static str, text: impl Into<String>) -> ApprovalError {
    ApprovalError {
        class,
        text: text.into(),
    }
}

fn os_error(e: &io::Error, path: &str) -> ApprovalError {
    fail(oserr::class_name(e), oserr::text(e, path))
}

/// `OSError(errno, strerror, path)` (Python'ın kendi metniyle).
fn custom(class: &'static str, errno: i32, what: &str, path: &str) -> ApprovalError {
    fail(
        class,
        format!(
            "[Errno {errno}] {what}: {}",
            crate::pyfmt::py_str_repr(path)
        ),
    )
}

fn unix_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

#[derive(Clone)]
pub struct ApprovalStore {
    root: String,
    now: fn() -> f64,
    lock_timeout: Duration,
    diag: Option<Arc<dyn DiagSink>>,
}

impl std::fmt::Debug for ApprovalStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApprovalStore")
            .field("root", &self.root)
            .field("lock_timeout", &self.lock_timeout)
            .finish_non_exhaustive()
    }
}

impl ApprovalStore {
    pub fn new(paths: &Paths) -> ApprovalStore {
        ApprovalStore {
            root: paths.ucli_approval_root(),
            now: unix_now,
            lock_timeout: LOCK_TIMEOUT,
            diag: None,
        }
    }

    /// Reddedilen defter kilidinin (`file_lock_refused`) yazılacağı günlük.
    pub fn with_diag(mut self, diag: Arc<dyn DiagSink>) -> ApprovalStore {
        self.diag = Some(diag);
        self
    }

    pub fn with_clock(mut self, now: fn() -> f64) -> ApprovalStore {
        self.now = now;
        self
    }

    pub fn with_lock_timeout(mut self, timeout: Duration) -> ApprovalStore {
        self.lock_timeout = timeout;
        self
    }

    pub fn index_path(&self) -> String {
        format!("{}/index.json", self.root)
    }

    /// `dir_for`: koşunun dizini; `create` ise dizin ve `pending|suspended|answers` 0700 açılır.
    pub fn dir_for(&self, run_key: &str, create: bool) -> Result<String, ApprovalError> {
        if !approval::valid_run_key(run_key) {
            return Err(fail("ValueError", "geçersiz run_key"));
        }
        let dir = format!("{}/{run_key}", self.root);
        if create {
            makedirs(&self.root, 0o700).map_err(|(p, e)| os_error(&e, &p))?;
            for sub in ["", "pending", "suspended", "answers"] {
                let path = if sub.is_empty() {
                    dir.clone()
                } else {
                    format!("{dir}/{sub}")
                };
                if fs::symlink_metadata(&path).is_ok_and(|m| m.file_type().is_symlink()) {
                    return Err(custom(
                        "OSError",
                        libc::ELOOP,
                        "onay dizini sembolik bağ",
                        &path,
                    ));
                }
                makedirs(&path, 0o700).map_err(|(p, e)| os_error(&e, &p))?;
                fs::set_permissions(&path, Permissions::from_mode(0o700))
                    .map_err(|e| os_error(&e, &path))?;
            }
        }
        Ok(dir)
    }

    /// Ham defter; yoksa None. Okunamıyorsa, normal dosya değilse (FIFO bloklamaz) ya da sınırı aşıyorsa hata.
    fn read_index(&self) -> Result<Option<Vec<u8>>, ApprovalError> {
        let path = self.index_path();
        let open = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(&path);
        let file = match open {
            Ok(f) => f,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(os_error(&e, &path)),
        };
        if !file.metadata().map_err(|e| os_error(&e, &path))?.is_file() {
            return Err(custom("OSError", libc::EINVAL, "normal dosya değil", &path));
        }
        let mut raw = Vec::new();
        file.take(INDEX_MAX_BYTES + 1)
            .read_to_end(&mut raw)
            .map_err(|e| os_error(&e, &path))?;
        if raw.len() as u64 > INDEX_MAX_BYTES {
            return Err(custom("OSError", libc::EFBIG, "defter çok büyük", &path));
        }
        Ok(Some(raw))
    }

    /// `_load_index`: yok/okunamaz/bozuk defter boştur.
    fn load_index(&self) -> Vec<(String, Py)> {
        self.read_index()
            .ok()
            .flatten()
            .and_then(|raw| approval::parse_index(&raw))
            .unwrap_or_default()
    }

    /// `_load_index_for_overwrite`: bozuk defterin önce 0600 kopyası bırakılır.
    fn load_index_for_overwrite(&self) -> Result<Vec<(String, Py)>, ApprovalError> {
        let Some(raw) = self.read_index()? else {
            return Ok(Vec::new());
        };
        if let Some(index) = approval::parse_index(&raw) {
            return Ok(index);
        }
        let digest: String = Sha256::digest(&raw)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        let copy = format!("{}.corrupt-{}", self.index_path(), &digest[..12]);
        let open = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&copy);
        match open {
            Ok(mut f) => f.write_all(&raw).map_err(|e| os_error(&e, &copy))?,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(os_error(&e, &copy)),
        }
        Ok(Vec::new())
    }

    fn lock(&self) -> Result<FileLock, ApprovalError> {
        let path = self.index_path();
        let lock = format!("{path}.lock");
        // hatanın metnindeki yol, düşen adımın yoludur (dizin açma ya da kilit dosyası)
        let refused = |e: &io::Error, at: &str| {
            fail(
                "LockError",
                format!("{lock} alınamadı: {}", oserr::text(e, at)),
            )
        };
        makedirs(&self.root, 0o777).map_err(|(p, e)| {
            log_refused(&abspath(&path, "/"), self.diag.as_deref());
            refused(&e, &p)
        })?;
        FileLock::acquire_logged(&path, "/", self.lock_timeout, self.diag.as_deref())
            .map_err(|e| refused(&e, &lock))
    }

    fn write_index(&self, index: Vec<(String, Py)>) -> Result<(), ApprovalError> {
        let path = self.index_path();
        atomic_write_text(&path, &Py::Object(index).dumps_pretty(), Some(0o600))
            .map_err(|e| os_error(&e, &path))
    }

    /// `run_key` yeni koşuya verilebilir mi (kilitsiz ön denetim; kesin karar [`ApprovalStore::register`]de, kilit altında).
    pub fn slot_free(&self, run_key: &str) -> bool {
        approval::slot_free(&self.load_index(), run_key)
    }

    /// `register`: koşuyu `running` olarak kayda alır, dizinini açar ve döner.
    pub fn register(&self, run_key: &str, run: NewRun<'_>) -> Result<String, ApprovalError> {
        let dir = self.dir_for(run_key, true)?;
        let _lock = self.lock()?;
        let mut index = self.load_index_for_overwrite()?;
        if !approval::insert_run(&mut index, run_key, run, (self.now)()) {
            return Err(custom(
                "FileExistsError",
                libc::EEXIST,
                "run_key kullanımda",
                run_key,
            ));
        }
        self.write_index(index)?;
        Ok(dir)
    }

    /// `set_state`: kayıt yoksa `Ok(false)`.
    pub fn set_state(&self, run_key: &str, state: &str) -> Result<bool, ApprovalError> {
        if !approval::STATES.contains(&state) {
            return Err(fail("ValueError", "geçersiz durum"));
        }
        let _lock = self.lock()?;
        let mut index = self.load_index();
        match approval::change_state(&mut index, run_key, state) {
            StateChange::Missing => Ok(false),
            StateChange::NotARecord => Err(fail("TypeError", "onay kaydı nesne değil")),
            StateChange::Changed => self.write_index(index).map(|()| true),
        }
    }
}
