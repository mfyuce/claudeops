//! Birim dosyası yazımı: atomik (aynı dizinde `O_EXCL` geçici dosya, dosya + dizin `fsync`, `rename`) ve geri alınabilir
//! (yazmadan önce eski durum [`Prev`] olarak saklanır). Python `front_cmd._atomic_write/_snapshot/_restore` aynı yolu izler
//! (ders H2).

use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// Dosyanın yazımdan önceki durumu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Prev {
    /// Yoktu.
    Absent,
    /// İçerik ve izin bitleri.
    Content(Vec<u8>, u32),
    /// Sembolik bağ (hedefi).
    Link(PathBuf),
}

/// Eski durumu okur (okunamıyorsa hata: geri alınamayacak bir dosyaya yazılmaz).
pub fn snapshot(p: &Path) -> std::io::Result<Prev> {
    if std::fs::symlink_metadata(p).is_ok_and(|m| m.file_type().is_symlink()) {
        return std::fs::read_link(p).map(Prev::Link);
    }
    match std::fs::read(p) {
        Ok(b) => {
            let mode = std::fs::metadata(p)?.permissions().mode() & 0o7777;
            Ok(Prev::Content(b, mode))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Prev::Absent),
        Err(e) => Err(e),
    }
}

fn tmp_name(p: &Path, n: u32) -> PathBuf {
    let dir = p.parent().unwrap_or(Path::new("."));
    dir.join(format!(".cops-rs.{}.{}.tmp", std::process::id(), n))
}

/// Atomik yazım. `mode` `None` ise yeni dosya umask'e göre (0666 &! umask, Python `write_text` gibi).
pub fn atomic_write(p: &Path, data: &[u8], mode: Option<u32>) -> std::io::Result<()> {
    let dir = p.parent().unwrap_or(Path::new(".")).to_path_buf();
    let mut n = 0;
    let (tmp, mut f) = loop {
        let t = tmp_name(p, n);
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o666)
            .open(&t)
        {
            Ok(f) => break (t, f),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists && n < 64 => n += 1,
            Err(e) => return Err(e),
        }
    };
    let r = (|| {
        if let Some(m) = mode {
            f.set_permissions(std::fs::Permissions::from_mode(m))?;
        }
        f.write_all(data)?;
        f.sync_all()?;
        std::fs::rename(&tmp, p)?;
        std::fs::File::open(&dir)?.sync_all()
    })();
    if r.is_err() {
        // Geçici dosyayı bırakmamak için; asıl hata yukarı döner.
        let _ = std::fs::remove_file(&tmp);
    }
    r
}

/// Eski duruma döndürür.
pub fn restore(p: &Path, prev: &Prev) -> std::io::Result<()> {
    match prev {
        Prev::Absent => match std::fs::remove_file(p) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        },
        Prev::Content(b, m) => atomic_write(p, b, Some(*m)),
        // Yalnız `off` bir bağı siler (`on` bağlı birimi reddeder).
        Prev::Link(target) => {
            restore(p, &Prev::Absent)?;
            std::os::unix::fs::symlink(target, p)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_snapshot_restore_roundtrip() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path().join("u.service");
        assert_eq!(snapshot(&p).unwrap(), Prev::Absent);
        atomic_write(&p, b"a", None).unwrap();
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o640)).unwrap();
        let s = snapshot(&p).unwrap();
        assert_eq!(s, Prev::Content(b"a".to_vec(), 0o640));
        atomic_write(&p, b"b", None).unwrap();
        restore(&p, &s).unwrap();
        assert_eq!(std::fs::read(&p).unwrap(), b"a");
        assert_eq!(
            std::fs::metadata(&p).unwrap().permissions().mode() & 0o777,
            0o640
        );
        restore(&p, &Prev::Absent).unwrap();
        assert!(!p.exists());
        restore(&p, &Prev::Absent).unwrap();
        assert_eq!(std::fs::read_dir(t.path()).unwrap().count(), 0);
    }

    #[test]
    fn failed_write_leaves_no_temp_and_keeps_target() {
        let t = tempfile::tempdir().unwrap();
        // hedef bir dizin: rename başarısız olur
        let p = t.path().join("d");
        std::fs::create_dir(&p).unwrap();
        std::fs::write(p.join("x"), "1").unwrap();
        assert!(atomic_write(&p, b"z", None).is_err());
        let names: Vec<_> = std::fs::read_dir(t.path())
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect();
        assert_eq!(names, vec![std::ffi::OsString::from("d")]);
    }
}
