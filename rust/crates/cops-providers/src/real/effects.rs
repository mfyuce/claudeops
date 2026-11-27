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
        Effect::WriteSecret { path, content } => {
            write_secret(path, content.as_bytes()).map_err(at(path))
        }
        Effect::WriteAtomic { path, content } => {
            atomic_write_text(path, content, None).map_err(at(path))
        }
        Effect::Touch { path } => touch(path).map_err(at(path)),
        Effect::Remove { path } => {
            // Python `try: os.remove(p) except OSError: pass`
            let _ = fs::remove_file(path);
            Ok(())
        }
        Effect::MkdirPrivate { path } => makedirs(path, 0o700),
        Effect::ChmodPrivate { path } => {
            fs::set_permissions(path, Permissions::from_mode(0o700)).map_err(at(path))
        }
        Effect::WriteSpawnEnv { dir, file, content } => {
            write_spawn_env(dir, file, content.as_bytes())
        }
    };
    done.map_err(|(path, error)| EffectError {
        index: 0,
        path,
        error,
    })
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
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "normal dosya değil",
        ));
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
    let mode = mode.or_else(|| {
        fs::metadata(path)
            .ok()
            .filter(|m| m.is_file())
            .map(|m| m.permissions().mode() & 0o7777)
    });
    let tmp = format!(
        "{path}.{}-{}.tmp",
        std::process::id(),
        TMP_SEQ.fetch_add(1, Ordering::Relaxed)
    );
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

/// S4: yüklenmeden kalan sır ortam dosyalarının ömrü (Python `spawn._SPAWN_ENV_STALE_SECONDS`).
pub const SPAWN_ENV_STALE_SECONDS: f64 = 3600.0;

/// `spawn._spawn_env_token`: `/dev/urandom`dan 8 bayt, onaltılık. Okunamazsa süreç kimliği + saat + sayaç (benzersizlik
/// yine sağlanır; yazım `O_EXCL`).
pub fn spawn_env_token() -> String {
    let mut buf = [0u8; 8];
    let ok = File::open("/dev/urandom")
        .and_then(|mut f| io::Read::read_exact(&mut f, &mut buf))
        .is_ok();
    if !ok {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.subsec_nanos());
        let mix = (u64::from(std::process::id()) << 32)
            ^ u64::from(nanos)
            ^ TMP_SEQ.fetch_add(1, Ordering::Relaxed).rotate_left(17);
        buf = mix.to_be_bytes();
    }
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

fn cstr(s: &str) -> io::Result<std::ffi::CString> {
    std::ffi::CString::new(s).map_err(|_| io::Error::from_raw_os_error(libc::EINVAL))
}

fn cvt(rc: libc::c_int) -> io::Result<libc::c_int> {
    if rc < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(rc)
    }
}

/// `_prune_spawn_env`: dizindeki eski `.env`/`.tmp` artıkları (bağlantı izlenmez, hata yutulur).
fn prune_spawn_env(dir: &File, path: &str, now: f64) {
    use std::os::fd::AsRawFd;
    let Ok(rd) = fs::read_dir(path) else { return };
    for ent in rd.flatten() {
        let name = ent.file_name().to_string_lossy().into_owned();
        if !(name.ends_with(".env") || name.ends_with(".tmp")) {
            continue;
        }
        let Ok(c) = cstr(&name) else { continue };
        let mut st: libc::stat = unsafe { std::mem::zeroed() };
        // SAFETY: geçerli dizin tanıtıcısı, NUL sonlu ad, çağıranın stat tamponu.
        let rc = unsafe {
            libc::fstatat(
                dir.as_raw_fd(),
                c.as_ptr(),
                &mut st,
                libc::AT_SYMLINK_NOFOLLOW,
            )
        };
        if rc != 0 {
            continue;
        }
        let mtime = st.st_mtime as f64 + st.st_mtime_nsec as f64 / 1e9;
        if now - mtime > SPAWN_ENV_STALE_SECONDS {
            // SAFETY: aynı tanıtıcı ve ad.
            unsafe { libc::unlinkat(dir.as_raw_fd(), c.as_ptr(), 0) };
        }
    }
}

/// [`Effect::WriteSpawnEnv`] (Python `spawn._write_spawn_env_file`).
pub fn write_spawn_env(dir: &str, file: &str, content: &[u8]) -> Result<(), Fail> {
    // SAFETY: yan etkisiz sistem çağrısı.
    write_spawn_env_as(unsafe { libc::geteuid() }, dir, file, content)
}

/// [`write_spawn_env`]; dizin sahibi `euid` ile karşılaştırılır (test başka sahip benzetir).
pub fn write_spawn_env_as(euid: u32, dir: &str, file: &str, content: &[u8]) -> Result<(), Fail> {
    use std::os::fd::{AsRawFd, FromRawFd};
    use std::os::unix::fs::MetadataExt;
    let (parent, _) = split(dir);
    if !parent.is_empty() {
        makedirs(parent, 0o700)?;
    }
    match DirBuilder::new().mode(0o700).create(dir) {
        Err(e) if e.kind() != io::ErrorKind::AlreadyExists => return Err((dir.into(), e)),
        _ => {}
    }
    let d = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(dir)
        .map_err(at(dir))?;
    let meta = d.metadata().map_err(at(dir))?;
    if meta.uid() != euid {
        return Err((dir.into(), io::Error::from_raw_os_error(libc::EPERM)));
    }
    if meta.mode() & 0o077 != 0 {
        d.set_permissions(Permissions::from_mode(0o700))
            .map_err(at(dir))?;
    }
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |t| t.as_secs_f64());
    prune_spawn_env(&d, dir, now);
    let fd = d.as_raw_fd();
    let tmp = format!(".{file}.tmp");
    let (ctmp, cfile) = (cstr(&tmp).map_err(at(dir))?, cstr(file).map_err(at(dir))?);
    let fail = |e| (format!("{dir}/{tmp}"), e);
    // SAFETY: geçerli dizin tanıtıcısı ve NUL sonlu ad; dönen tanıtıcının sahibi `File`.
    let raw = cvt(unsafe {
        libc::openat(
            fd,
            ctmp.as_ptr(),
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            0o600 as libc::c_uint,
        )
    })
    .map_err(fail)?;
    // SAFETY: `openat`ın az önce döndürdüğü, başka sahibi olmayan tanıtıcı.
    let mut f = unsafe { File::from_raw_fd(raw) };
    let written = f.write_all(content).and_then(|()| {
        drop(f);
        // SAFETY: aynı dizin tanıtıcısı; `linkat` var olan hedefi EZMEZ (EEXIST).
        cvt(unsafe { libc::linkat(fd, ctmp.as_ptr(), fd, cfile.as_ptr(), 0) }).map(drop)
    });
    // SAFETY: aynı dizin tanıtıcısı ve ad; hata yutulur (Python `try: os.unlink ... except OSError`).
    unsafe { libc::unlinkat(fd, ctmp.as_ptr(), 0) };
    written.map_err(|e| (format!("{dir}/{file}"), e))
}
