//! Ön kapı gizlisi: Python `front.read_secret` / `front.ensure_secret` karşılığı. Dosya okuma kuralı `cops_proxy::front::
//! read_secret_file` (copsd ile ortak; yeniden yazılmadı).
//!
//! Python ile ORTAK sözleşme (iki dil aynı anda üretebilir):
//! - gizli `<durum dizini>/front.secret`, 0600, içerik 64 küçük onaltılık + `\n` (`secrets.token_hex(32)`);
//! - kilit `<durum dizini>/front.secret.lock` (`O_WRONLY|O_CREAT`, 0600), `flock(LOCK_EX)`; kilit altında yeniden okunur,
//!   geçerliyse o döner;
//! - yeni değer aynı dizinde `.front.secret.*` geçici dosyaya (0600, `O_EXCL`) yazılır, `rename` ile yerine konur; okuyan
//!   yarım dosya görmez. Rust ayrıca dosya + dizin `fsync` yapar (ders H2) ve kilidi süre sınırıyla bekler (Python süresiz).
//!
//! Sapma (docs/rs-cli.md "Python hatası?" P1): Python `ensure_secret` `CLAUDEOPS_FRONT_SECRET` doluysa DOSYA ÜRETMEZ; o
//! ortam yalnız CLI kabuğunda olduğundan copsd ve web birimleri gizlisiz kalır. [`ensure_secret_file`] ortamı yok sayar,
//! yalnız dosyaya bakar.

use cops_proxy::front::{read_secret_file, SecretFile};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// `front.secret_path()` metni: `os.path.join(CLAUDEOPS_DIR, "front.secret")`.
pub fn secret_path(claudeops_dir: &str) -> String {
    crate::pyenv::join(claudeops_dir, "front.secret")
}

/// Python `read_secret`: ortam (boş değilse, kırpılmadan) yoksa dosya; kullanılamaz = boş.
pub fn read_secret(env: Option<&str>, path: &Path) -> String {
    if let Some(e) = env.filter(|e| !e.is_empty()) {
        return e.to_string();
    }
    match read_secret_file(path) {
        SecretFile::Value(v) => v,
        _ => String::new(),
    }
}

fn file_value(path: &Path) -> Option<String> {
    match read_secret_file(path) {
        SecretFile::Value(v) if !v.is_empty() => Some(v),
        _ => None,
    }
}

fn random_bytes<const N: usize>() -> std::io::Result<[u8; N]> {
    let mut b = [0u8; N];
    let mut got = 0;
    while got < N {
        // SAFETY: tamponun kalan kısmına en çok N-got bayt yazılır.
        let r = unsafe { libc::getrandom(b[got..].as_mut_ptr().cast(), N - got, 0) };
        if r < 0 {
            let e = std::io::Error::last_os_error();
            if e.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(e);
        }
        got += r as usize;
    }
    Ok(b)
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// Kilidi süre sınırıyla alır (dosya kapanınca bırakılır).
fn lock(path: &Path, timeout: Duration) -> std::io::Result<std::fs::File> {
    let f = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    let start = Instant::now();
    loop {
        // SAFETY: geçerli açık tanıtıcı.
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
            return Ok(f);
        }
        let e = std::io::Error::last_os_error();
        if e.raw_os_error() != Some(libc::EWOULDBLOCK)
            && e.kind() != std::io::ErrorKind::Interrupted
        {
            return Err(e);
        }
        if start.elapsed() >= timeout {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!("kilit {} sn'de alınamadı", timeout.as_secs()),
            ));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn write_new(dir: &Path, target: &Path, val: &str) -> std::io::Result<()> {
    let mut tmp: Option<PathBuf> = None;
    let mut file = None;
    for _ in 0..16 {
        let name = dir.join(format!(".front.secret.{}", hex(&random_bytes::<6>()?)));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&name)
        {
            Ok(f) => {
                tmp = Some(name);
                file = Some(f);
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
    let (Some(tmp), Some(mut f)) = (tmp, file) else {
        return Err(std::io::Error::other("geçici ad üretilemedi"));
    };
    let r = (|| {
        // umask ne olursa olsun 0600
        f.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        f.write_all(format!("{val}\n").as_bytes())?;
        f.sync_all()?;
        std::fs::rename(&tmp, target)?;
        std::fs::File::open(dir)?.sync_all()
    })();
    if r.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    r
}

/// Python `ensure_secret` (bkz. modül belgesi, P1 sapması). Geçerli dosya varsa onun değeri; yoksa (yok, boş, bozuk, izni
/// gevşek = sızmış) kilit altında yeni gizli.
pub fn ensure_secret_file(claudeops_dir: &str, lock_timeout: Duration) -> std::io::Result<String> {
    let p = PathBuf::from(secret_path(claudeops_dir));
    if let Some(v) = file_value(&p) {
        return Ok(v);
    }
    let d = p
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    std::fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&d)?;
    let _guard = lock(
        &PathBuf::from(format!("{}.lock", p.display())),
        lock_timeout,
    )?;
    if let Some(v) = file_value(&p) {
        return Ok(v);
    }
    let val = hex(&random_bytes::<32>()?);
    write_new(&d, &p, &val)?;
    Ok(val)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn creates_0600_stable_and_replaces_leaked_or_corrupt() {
        let t = tempfile::tempdir().unwrap();
        let sd = t.path().join("st");
        let sds = sd.to_str().unwrap();
        let v = ensure_secret_file(sds, Duration::from_secs(5)).unwrap();
        assert_eq!(v.len(), 64);
        assert!(v
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()));
        let p = sd.join("front.secret");
        assert_eq!(std::fs::read_to_string(&p).unwrap(), format!("{v}\n"));
        assert_eq!(
            std::fs::metadata(&p).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(
            std::fs::metadata(&sd).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(ensure_secret_file(sds, Duration::from_secs(5)).unwrap(), v);
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o644)).unwrap();
        let v2 = ensure_secret_file(sds, Duration::from_secs(5)).unwrap();
        assert_ne!(v2, v);
        for bad in [&b""[..], b" \n", b"\xff\xfe\n"] {
            std::fs::write(&p, bad).unwrap();
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600)).unwrap();
            let v3 = ensure_secret_file(sds, Duration::from_secs(5)).unwrap();
            assert_eq!(read_secret(None, &p), v3);
        }
        let mut left: Vec<_> = std::fs::read_dir(&sd)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect();
        left.sort();
        assert_eq!(left, ["front.secret", "front.secret.lock"]);
    }

    #[test]
    fn env_is_ignored_for_the_file_but_wins_for_reading() {
        let t = tempfile::tempdir().unwrap();
        let sds = t.path().to_str().unwrap();
        let p = PathBuf::from(secret_path(sds));
        assert_eq!(read_secret(Some("e"), &p), "e");
        assert_eq!(read_secret(Some(""), &p), "");
        let v = ensure_secret_file(sds, Duration::from_secs(5)).unwrap();
        assert!(p.is_file());
        assert_eq!(read_secret(None, &p), v);
        assert_eq!(read_secret(Some(" e "), &p), " e ");
    }

    #[test]
    fn concurrent_threads_agree_on_disk_value() {
        for _ in 0..10 {
            let t = tempfile::tempdir().unwrap();
            let sds = t.path().to_str().unwrap().to_string();
            let gate = std::sync::Arc::new(std::sync::Barrier::new(8));
            let hs: Vec<_> = (0..8)
                .map(|_| {
                    let (g, s) = (gate.clone(), sds.clone());
                    std::thread::spawn(move || {
                        g.wait();
                        ensure_secret_file(&s, Duration::from_secs(10)).unwrap()
                    })
                })
                .collect();
            let got: Vec<String> = hs.into_iter().map(|h| h.join().unwrap()).collect();
            let disk = read_secret(None, &PathBuf::from(secret_path(&sds)));
            assert!(got.iter().all(|g| *g == disk));
        }
    }

    #[test]
    fn lock_wait_is_bounded() {
        let t = tempfile::tempdir().unwrap();
        let sds = t.path().to_str().unwrap();
        let held = lock(&t.path().join("front.secret.lock"), Duration::from_secs(1)).unwrap();
        let e = ensure_secret_file(sds, Duration::from_millis(200)).unwrap_err();
        assert_eq!(e.kind(), std::io::ErrorKind::TimedOut);
        drop(held);
        assert!(ensure_secret_file(sds, Duration::from_secs(1)).is_ok());
    }
}
