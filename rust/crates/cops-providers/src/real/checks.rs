//! `ucli_checks.py` okuma yarısı: `run_checks` kayıt dosyasının yol ve biçim/boyut ön denetimi. (Yazım ucu T7.)

use crate::pyjson::Py;
use crate::real::oserr;
use regex::Regex;
use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::sync::LazyLock;

pub const MAX_BYTES: u64 = 256 * 1024;
pub const MAX_CHECKS: usize = 200;

/// `_OWNER` (tam eşleşme).
static OWNER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$").expect("sabit desen"));
/// `_NAME` (tam eşleşme).
static NAME: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_-]{0,47}$").expect("sabit desen"));

/// `registry_path(owner)`; `root` = [`crate::Paths::ucli_checks_root`].
pub fn registry_path(root: &str, owner: &str) -> Result<String, String> {
    let owner = if owner.is_empty() { "owner" } else { owner };
    if !OWNER.is_match(owner) {
        return Err("geçersiz kayıt sahibi".into());
    }
    Ok(format!("{root}/{owner}.json"))
}

/// `{"check": [ {name, argv[...]} ... ]}`: ad benzersiz ve güvenli, argv boş olmayan dize listesi.
pub fn check_shape(data: &Py) -> Result<(), String> {
    let Some(Py::Array(items)) = data.get("check") else { return Err("kayıt {\"check\": [...]} olmalı".into()) };
    if items.len() > MAX_CHECKS {
        return Err(format!("en çok {MAX_CHECKS} kontrol"));
    }
    let mut seen = HashSet::new();
    for item in items {
        let Some(text) = item.get("name").and_then(Py::as_str).filter(|n| NAME.is_match(n)) else {
            return Err("her kontrolün adı [a-z][a-z0-9_-]{0,47} olmalı".into());
        };
        if !seen.insert(text) {
            return Err(format!("kontrol adı yinelendi: {text}"));
        }
        let argv_ok = matches!(item.get("argv"), Some(Py::Array(a))
            if !a.is_empty() && a.iter().all(|x| x.as_str().is_some_and(|s| !s.is_empty())));
        if !argv_ok {
            return Err(format!("{text}: argv boş olmayan dize listesi olmalı"));
        }
    }
    Ok(())
}

/// Kayıt (ayrıştırılmış, biçim denetimli) ya da hata metni. Dosya: düz, symlink değil, grup/diğer izni yok, boyut
/// sınırlı; açılış `O_NOFOLLOW` (denetimle okuma arasında bağlantıya çevrilemez).
pub fn load_registry(path: &str) -> Result<Py, String> {
    let meta = match fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Err("kontrol kaydı yok (Ayarlar > Ucli > Kontroller'den kayıt ekle)".into());
        }
        Err(e) => return Err(format!("kayıt okunamadı: {}", oserr::class_name(&e))),
    };
    if !meta.is_file() {
        return Err("kayıt düz dosya olmalı (symlink/özel dosya reddedilir)".into());
    }
    if meta.permissions().mode() & 0o077 != 0 {
        return Err("kayıt dosyası 0600 olmalı".into());
    }
    if meta.len() > MAX_BYTES {
        return Err("kayıt çok büyük".into());
    }
    let invalid = || "kayıt geçerli JSON değil".to_string();
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)
        .map_err(|_| invalid())?;
    // tür ve izin açılan tanıtıcıdan yeniden denetlenir (denetimden sonra değişmiş olabilir)
    let opened = file.metadata().map_err(|_| invalid())?;
    if !opened.is_file() {
        return Err("kayıt düz dosya olmalı (symlink/özel dosya reddedilir)".into());
    }
    if opened.permissions().mode() & 0o077 != 0 {
        return Err("kayıt dosyası 0600 olmalı".into());
    }
    let mut data = Vec::new();
    file.take(MAX_BYTES + 1).read_to_end(&mut data).map_err(|_| invalid())?;
    if data.len() as u64 > MAX_BYTES {
        return Err("kayıt çok büyük".into());
    }
    let parsed = std::str::from_utf8(&data).ok().and_then(Py::parse).ok_or_else(invalid)?;
    check_shape(&parsed)?;
    Ok(parsed)
}
