//! [`Effect`] uygulayıcısı: Python yazım yardımcılarıyla (`atomic_json.atomic_write_text`, `os.open(..O_NOFOLLOW..)`,
//! `os.makedirs`) aynı anlam. Hata metnine dosya İÇERİĞİ girmez.

use crate::probe::Effect;
use crate::real::oserr;
use std::fmt;
use std::fs::{self, DirBuilder, File, OpenOptions, Permissions};
use std::io::{self, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

/// Bir yan etki uygulanamadı.
#[derive(Debug)]
pub struct EffectError {
    /// [`apply_all`] listesindeki sıra (tek uygulamada 0).
    pub index: usize,
    /// Hatayı veren yol (`makedirs`te düşen ara dizin olabilir).
    pub path: String,
    pub error: io::Error,
}

impl fmt::Display for EffectError {
    /// Python `str(OSError)`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&oserr::text(&self.error, &self.path))
    }
}

impl std::error::Error for EffectError {}

type Fail = (String, io::Error);

fn at(path: &str) -> impl Fn(io::Error) -> Fail + '_ {
    move |e| (path.to_string(), e)
}

/// Tek yan etkiyi uygular.
pub fn apply(effect: &Effect) -> Result<(), EffectError> {
    let done = match effect {
        Effect::WriteSecret { path, content } => write_secret(path, content.as_bytes()).map_err(at(path)),
        Effect::WriteAtomic { path, content } => atomic_write_text(path, content, None).map_err(at(path)),
        Effect::Touch { path } => touch(path).map_err(at(path)),
        Effect::Remove { path } => {
            // Python `try: os.remove(p) except OSError: pass`
            let _ = fs::remove_file(path);
            Ok(())
        }
        Effect::MkdirPrivate { path } => makedirs(path, 0o700),
        Effect::ChmodPrivate { path } => fs::set_permissions(path, Permissions::from_mode(0o700)).map_err(at(path)),
    };
    done.map_err(|(path, error)| EffectError { index: 0, path, error })
}

/// Verilen sırayla uygular; ilk hatada DURUR (Python'da istisna sonraki adımları da keser).
pub fn apply_all(effects: &[Effect]) -> Result<(), EffectError> {
    for (index, effect) in effects.iter().enumerate() {
        apply(effect).map_err(|e| EffectError { index, ..e })?;
    }
    Ok(())
}

/// Kırpıp yazmak için açar: baştan 0600, son bileşen symlink ise reddedilir, normal dosya değilse (FIFO/aygıt)
/// bloklamadan hata.
fn open_truncate(path: &str) -> io::Result<File> {
    let file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "normal dosya değil"));
    }
    Ok(file)
}

/// 0600 sır dosyası; var olan dosyanın izni de İÇERİK YAZILMADAN ÖNCE 0600'e çekilir.
pub fn write_secret(path: &str, data: &[u8]) -> io::Result<()> {
    let mut file = open_truncate(path)?;
    file.set_permissions(Permissions::from_mode(0o600))?;
    file.write_all(data)
}

/// Boş damga dosyası. Var olan dosyanın izni değiştirilmez (Python `os.open`, `fchmod` yok).
pub fn touch(path: &str) -> io::Result<()> {
    open_truncate(path).map(drop)
}

fn split(path: &str) -> (&str, &str) {
    let cut = path.rfind('/').map_or(0, |i| i + 1);
    let (head, tail) = path.split_at(cut);
    let trimmed = head.trim_end_matches('/');
    (if trimmed.is_empty() { head } else { trimmed }, tail)
}

/// `os.makedirs(path, mode, exist_ok=True)`: ara dizinler varsayılan izinle, SON dizin `mode & ~umask`.
pub fn makedirs(path: &str, mode: u32) -> Result<(), Fail> {
    let (mut head, mut tail) = split(path);
    if tail.is_empty() {
        (head, tail) = split(head);
    }
    if !head.is_empty() && !tail.is_empty() && !Path::new(head).exists() {
        match makedirs(head, 0o777) {
            Err((_, e)) if e.kind() == io::ErrorKind::AlreadyExists => {}
            other => other?,
        }
        if tail == "." {
            return Ok(());
        }
    }
    match DirBuilder::new().mode(mode).create(path) {
        Err(e) if !Path::new(path).is_dir() => Err((path.to_string(), e)),
        _ => Ok(()),
    }
}

/// `os.replace` sonrası dizin girdisini kalıcılaştır (en iyi çaba).
fn fsync_dir(path: &str) {
    let (head, _) = split(path);
    if let Ok(dir) = File::open(if head.is_empty() { "." } else { head }) {
        let _ = dir.sync_all();
    }
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// `atomic_write_text`: benzersiz geçici dosya (`O_EXCL|O_NOFOLLOW`), veri + dizin fsync, `rename`. `mode` None ise var
/// olan NORMAL dosyanın izni korunur, dosya yoksa umask uygulanır. Hedef symlink ise bağlantının yerine dosya geçer
/// (hedefe yazmak isteyen çağıran `realpath` verir). Hata halinde geçici dosya silinir.
pub fn atomic_write_text(path: &str, text: &str, mode: Option<u32>) -> io::Result<()> {
    let (head, _) = split(path);
    if !head.is_empty() {
        makedirs(head, 0o777).map_err(|(_, e)| e)?;
    }
    let mode = mode.or_else(|| fs::metadata(path).ok().filter(|m| m.is_file()).map(|m| m.permissions().mode() & 0o7777));
    let tmp = format!("{path}.{}-{}.tmp", std::process::id(), TMP_SEQ.fetch_add(1, Ordering::Relaxed));
    // önceki çöküşten kalan aynı adlı dosya ya da yerleştirilmiş symlink takip edilmesin
    let _ = fs::remove_file(&tmp);
    let written = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode.unwrap_or(0o666))
            .custom_flags(libc::O_NOFOLLOW)
            .open(&tmp)?;
        if let Some(m) = mode {
            // umask'ı aşarak istenen/korunan izin (başarısızlık Python'da da yutulur: dosya en az o kadar dar)
            let _ = file.set_permissions(Permissions::from_mode(m));
        }
        file.write_all(text.as_bytes())?;
        file.sync_all()?;
        drop(file);
        fs::rename(&tmp, path)
    })();
    match written {
        Ok(()) => {
            fsync_dir(path);
            Ok(())
        }
        Err(e) => {
            let _ = fs::remove_file(&tmp);
            Err(e)
        }
    }
}
