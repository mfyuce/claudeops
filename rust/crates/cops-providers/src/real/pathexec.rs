//! Yol çözümü ve araç keşfi: `os.access`, `os.path.realpath`, `shutil.which`, `path_executables`, `rust_toolchain`.

use crate::pyfmt::{abspath, join_path, py_isspace, strip};
use crate::real::{fsio, Env};
use crate::ucli_opts::Toolchain;
use regex::Regex;
use std::collections::{BTreeSet, HashMap, HashSet};
use std::ffi::CString;
use std::fs;
use std::path::Path;
use std::sync::LazyLock;

/// `_CMD_RE` (tam eşleşme).
static CMD_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$").expect("sabit desen"));

fn access(path: &str, mode: libc::c_int) -> bool {
    let Ok(c) = CString::new(path) else { return false };
    // SAFETY: `c` NUL ile biten geçerli bir dizge; çağrı yalnız okur.
    unsafe { libc::access(c.as_ptr(), mode) == 0 }
}

/// Normal dosya VE (`os.access(X_OK)`, gerçek kullanıcı) çalıştırılabilir.
pub fn is_executable_file(path: &str) -> bool {
    Path::new(path).is_file() && access(path, libc::X_OK)
}

/// `shutil._access_check` (`F_OK | X_OK`, dizin değil).
fn runnable(path: &str) -> bool {
    access(path, libc::X_OK) && !Path::new(path).is_dir()
}

/// `shutil.which`.
pub fn which(env: &Env, name: &str) -> Option<String> {
    if name.contains('/') {
        return runnable(name).then(|| name.to_string());
    }
    // `PATH` yoksa `confstr("CS_PATH")`; boşsa hiçbir şey
    let path = env.get("PATH").unwrap_or_else(|| "/bin:/usr/bin".to_string());
    if path.is_empty() {
        return None;
    }
    let mut seen = HashSet::new();
    path.split(':').filter(|d| seen.insert(*d)).map(|d| join_path(d, name)).find(|p| runnable(p))
}

/// PATH'teki çalıştırılabilir dosya adları (sıralı, tekrarsız); okunamayan dizin atlanır.
pub fn path_executables(env: &Env) -> Vec<String> {
    let mut names = BTreeSet::new();
    for dir in env.get("PATH").unwrap_or_default().split(':').filter(|d| !d.is_empty()) {
        for name in fsio::list_dir(dir).unwrap_or_default() {
            if CMD_NAME.is_match(&name) && is_executable_file(&join_path(dir, &name)) {
                names.insert(name);
            }
        }
    }
    names.into_iter().collect()
}

/// `settings.toml` okuma sınırı.
const RUSTUP_SETTINGS_MAX_BYTES: u64 = 1 << 20;

/// `<rustup_home>/settings.toml` içindeki `default_toolchain`; yoksa/okunamazsa (UTF-8 değilse de) "".
pub fn rustup_default_toolchain(rustup_home: &str) -> String {
    let path = join_path(rustup_home, "settings.toml");
    let Some(data) = fsio::read_bytes(&path, RUSTUP_SETTINGS_MAX_BYTES) else { return String::new() };
    let Ok(text) = String::from_utf8(data) else { return String::new() };
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    for line in text.split_inclusive('\n') {
        // `\s*default_toolchain\s*=\s*"([^"]+)"` satır başında
        let rest = line.trim_start_matches(py_isspace);
        let value = rest
            .strip_prefix("default_toolchain")
            .and_then(|r| r.trim_start_matches(py_isspace).strip_prefix('='))
            .and_then(|r| r.trim_start_matches(py_isspace).strip_prefix('"'))
            .and_then(|r| r.split_once('"'))
            .map(|(v, _)| v)
            .filter(|v| !v.is_empty());
        if let Some(v) = value {
            return strip(v).to_string();
        }
    }
    String::new()
}

/// Kafese verilecek Rust araç zinciri; `home` = `os.path.expanduser("~")`. İstenen zincir yoksa ya da aday tek değilse
/// HATA (başkası sessizce seçilmez).
pub fn rust_toolchain(home: &str, env: &Env) -> Result<Toolchain, String> {
    let trimmed = home.trim_end_matches('/');
    let home = if trimmed.is_empty() { "/" } else { trimmed };
    let rustup = join_path(home, ".rustup");
    let tdir = join_path(&rustup, "toolchains");
    let Some(mut names) = fsio::list_dir(&tdir) else { return Err(format!("Rust araç zinciri bulunamadı: {tdir}")) };
    let has = |n: &str, tool: &str| Path::new(&format!("{}/bin/{tool}", join_path(&tdir, n))).is_file();
    names.retain(|n| has(n, "cargo") && has(n, "rustc"));
    names.sort();
    let want = env.get("RUSTUP_TOOLCHAIN").unwrap_or_default();
    let mut pick: Vec<&String> = names.iter().filter(|n| n.starts_with(&want)).collect();
    if !want.is_empty() && pick.is_empty() {
        return Err(format!("RUSTUP_TOOLCHAIN={want} ile eşleşen araç zinciri yok: {tdir}"));
    }
    if pick.len() > 1 && want.is_empty() {
        let default = rustup_default_toolchain(&rustup);
        if !default.is_empty() {
            let prefix = format!("{default}-");
            pick.retain(|n| **n == default || n.starts_with(&prefix));
        }
    }
    let [only] = pick.as_slice() else {
        return Err(format!("Rust araç zinciri belirsiz/yok ({} aday): {tdir}", pick.len()));
    };
    let root = join_path(&tdir, only);
    let cargo_home = join_path(home, ".cargo");
    Ok(Toolchain {
        cargo: format!("{root}/bin/cargo"),
        rustc: format!("{root}/bin/rustc"),
        registry: format!("{cargo_home}/registry"),
        git: format!("{cargo_home}/git"),
        root,
        rustup_home: rustup,
        cargo_home,
    })
}

/// `posixpath._joinrealpath` (strict=False). Dönüş: (çözülen yol, döngüye girilmedi mi).
fn join_real(mut path: String, rest: &str, seen: &mut HashMap<String, Option<String>>) -> (String, bool) {
    let mut rest = rest.to_string();
    if let Some(r) = rest.strip_prefix('/') {
        rest = r.to_string();
        path = "/".to_string();
    }
    while !rest.is_empty() {
        let (name, tail) = rest.split_once('/').map_or((rest.as_str(), ""), |(a, b)| (a, b));
        let (name, tail) = (name.to_string(), tail.to_string());
        rest = tail;
        if name.is_empty() || name == "." {
            continue;
        }
        if name == ".." {
            if path.is_empty() {
                path = "..".to_string();
            } else {
                // `posixpath.split`
                let cut = path.rfind('/').map_or(0, |i| i + 1);
                let (head, last) = path.split_at(cut);
                let trimmed = head.trim_end_matches('/');
                let head = if trimmed.is_empty() { head } else { trimmed };
                path = if last == ".." { join_path(&join_path(head, ".."), "..") } else { head.to_string() };
            }
            continue;
        }
        let next = join_path(&path, &name);
        if !fs::symlink_metadata(&next).is_ok_and(|m| m.file_type().is_symlink()) {
            path = next;
            continue;
        }
        match seen.get(&next) {
            Some(Some(done)) => {
                path = done.clone();
                continue;
            }
            // symlink döngüsü: çözülen kısım + kalan olduğu gibi
            Some(None) => return (join_path(&next, &rest), false),
            None => {}
        }
        // Sınırsız özyineleme olmasın (Python `RecursionError`): çözülen bağlantı sayısı sınırı
        let target = fs::read_link(&next).ok().filter(|_| seen.len() < MAX_LINKS);
        let Some(target) = target else { return (join_path(&next, &rest), false) };
        seen.insert(next.clone(), None);
        let (resolved, ok) = join_real(path, &target.to_string_lossy(), seen);
        if !ok {
            return (join_path(&resolved, &rest), false);
        }
        seen.insert(next, Some(resolved.clone()));
        path = resolved;
    }
    (path, true)
}

/// Bir `realpath` çağrısında izlenen farklı symlink sayısı sınırı.
const MAX_LINKS: usize = 256;

/// `os.path.realpath` (strict değil): göreli yol `cwd`ye göre çözülür ve mutlaklaşır.
pub fn realpath(path: &str, cwd: &str) -> String {
    // bağlantı denetimi sürecin dizinine değil verilen `cwd`ye göre yapılsın
    let (resolved, _) = join_real(String::new(), &join_path(cwd, path), &mut HashMap::new());
    abspath(&resolved, cwd)
}
