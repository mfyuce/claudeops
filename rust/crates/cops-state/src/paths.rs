//! Durum dizini çözümü (Python `paths.py`): `CLAUDEOPS_DIR` (boş değilse), yoksa test koşucusu altında süreç başına GEÇİCİ
//! dizin, yoksa `$HOME/.claude/claudeops`.
//!
//! Test algısı (Python `_under_test_runner` karşılığı): ikili cargo'nun test ikilisiyse (`.../deps/<ad>-<16 hex>` ya da
//! rustdoc test dizini). `CLAUDEOPS_TEST_REAL_DIR=1` kapatır. Testin ALT SÜREÇ olarak başlattığı normal ikili test sayılmaz:
//! ona dizini [`StateDir::apply_env`] ile ver.
use std::ffi::OsString;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

pub const ENV_DIR: &str = "CLAUDEOPS_DIR";
pub const ENV_TEST_REAL: &str = "CLAUDEOPS_TEST_REAL_DIR";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateDir {
    root: PathBuf,
}

fn looks_like_test_binary(exe: &Path) -> bool {
    if exe
        .components()
        .any(|c| c.as_os_str().to_string_lossy().starts_with("rustdoctest"))
    {
        return true;
    }
    let in_deps = exe
        .parent()
        .and_then(Path::file_name)
        .is_some_and(|d| d == "deps");
    let hashed = exe
        .file_name()
        .and_then(|f| f.to_str())
        .and_then(|f| f.rsplit_once('-'))
        .is_some_and(|(_, h)| h.len() == 16 && h.bytes().all(|b| b.is_ascii_hexdigit()));
    in_deps && hashed
}

static TEST_DIR: OnceLock<PathBuf> = OnceLock::new();

extern "C" fn remove_test_dir() {
    if let Some(d) = TEST_DIR.get() {
        let _ = std::fs::remove_dir_all(d);
    }
}

fn test_dir() -> PathBuf {
    TEST_DIR
        .get_or_init(|| {
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_nanos());
            let name = format!("cops-test-state-{}-{nanos}", std::process::id());
            // SAFETY: atexit yalnız bir işlev göstericisi kaydeder; işleyici panik üretmez.
            unsafe { libc::atexit(remove_test_dir) };
            std::env::temp_dir().join(name)
        })
        .clone()
}

fn resolve_from(
    env_dir: Option<OsString>,
    test: bool,
    home: Option<OsString>,
) -> io::Result<PathBuf> {
    if let Some(d) = env_dir.filter(|d| !d.is_empty()) {
        return Ok(d.into());
    }
    if test {
        return Ok(test_dir());
    }
    match home.filter(|h| !h.is_empty()) {
        Some(h) => Ok(PathBuf::from(h).join(".claude").join("claudeops")),
        None => Err(io::Error::new(
            io::ErrorKind::NotFound,
            "HOME tanımsız ve CLAUDEOPS_DIR yok",
        )),
    }
}

impl StateDir {
    /// Ortamdan çöz (bkz. modül belgesi).
    pub fn resolve() -> io::Result<StateDir> {
        let real = std::env::var_os(ENV_TEST_REAL).is_some_and(|v| v == "1");
        let test = !real && std::env::current_exe().is_ok_and(|e| looks_like_test_binary(&e));
        let root = resolve_from(std::env::var_os(ENV_DIR), test, std::env::var_os("HOME"))?;
        Ok(StateDir { root })
    }
    /// Açık dizin (`--state-dir` ve testler).
    pub fn at(root: impl Into<PathBuf>) -> StateDir {
        StateDir { root: root.into() }
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn join(&self, rel: impl AsRef<Path>) -> PathBuf {
        self.root.join(rel)
    }
    /// `docs` belge adının dosya yolu: `steward/quota` -> `<dizin>/steward/quota.json`. DİKKAT: ad ile dosya adı her zaman aynı
    /// değil (ör. `snapshots`/`snapshots.json` aynı, ama eski `last_snapshot.json` ayrı).
    pub fn doc_path(&self, name: &str) -> PathBuf {
        self.root.join(format!("{name}.json"))
    }
    pub fn roster_tsv(&self) -> PathBuf {
        self.join("roster.tsv")
    }
    pub fn models_tsv(&self) -> PathBuf {
        self.join("models.tsv")
    }
    pub fn settings_json(&self) -> PathBuf {
        self.join("settings.json")
    }
    pub fn instances_json(&self) -> PathBuf {
        self.join("instances.json")
    }
    pub fn db(&self) -> PathBuf {
        self.join("claudeops.db")
    }
    /// Alt sürece (ör. Python) aynı durum dizinini devret.
    pub fn apply_env(&self, cmd: &mut std::process::Command) {
        cmd.env(ENV_DIR, &self.root);
    }
    /// `ensure_private_state_dir`: dizini oluştur ve 0700 yap.
    pub fn ensure_private(&self) -> io::Result<()> {
        use std::os::unix::fs::PermissionsExt;
        std::fs::create_dir_all(&self.root)?;
        std::fs::set_permissions(&self.root, std::fs::Permissions::from_mode(0o700))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rules() {
        let home = Some(OsString::from("/h"));
        let r = |e: Option<&str>, t| resolve_from(e.map(Into::into), t, home.clone()).unwrap();
        assert_eq!(r(Some("/x"), true), PathBuf::from("/x"));
        assert_eq!(r(Some(""), false), PathBuf::from("/h/.claude/claudeops"));
        assert_eq!(r(None, false), PathBuf::from("/h/.claude/claudeops"));
        assert!(r(None, true).starts_with(std::env::temp_dir()));
        assert!(resolve_from(None, false, None).is_err());
    }

    #[test]
    fn test_binary_detection() {
        let t = |p: &str| looks_like_test_binary(Path::new(p));
        assert!(t("/c/debug/deps/cops_state-0123456789abcdef"));
        assert!(t("/tmp/rustdoctestAb12/rust_out"));
        assert!(!t("/c/release/copsd"));
        assert!(!t("/home/u/.claude/claudeops/bin/copsd"));
        assert!(!t("/c/debug/deps/copsd"));
    }

    /// Bu testin kendisi test ikilisi: `CLAUDEOPS_DIR` yoksa CANLI dizin asla dönmez.
    #[test]
    fn under_cargo_test_never_real_dir() {
        if std::env::var_os(ENV_DIR).is_none() && std::env::var_os(ENV_TEST_REAL).is_none() {
            let d = StateDir::resolve().unwrap();
            assert!(d.root().starts_with(std::env::temp_dir()), "{d:?}");
        }
    }
}
