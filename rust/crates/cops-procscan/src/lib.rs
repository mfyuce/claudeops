//! Süreç tarafı keşfi: `cops list` ve `/api/status`in süreçten okunan alanlarının Rust karşılığı
//! (Python: `discovery.py`, `providers/*.{matches_proc,extract_name,extract_info}`, `tmux_backend.is_tmux_backed`,
//! `mirrors.py`, `session.py`, `session_usage.py`). psutil yerine doğrudan `/proc`.
//!
//! **Çok kullanıcılı makine:** başka kullanıcının sürecinden yalnız `status` (sahiplik tespiti) okunur;
//! `cmdline`/`environ`/`stat`/`cwd`/`fd` okumaları yalnız [`procfs::OwnProc`] üzerinden yapılabilir.
//!
//! Crate durum dosyası yazmaz; tek yazım `needs_ho::NeedsHo::repo_baseline_set` (çağıranın verdiği dizin).
//! Süreç öldürme yalnız `proc_cmd`te, yalnız kendi başlattığı çocuğa (`clippy.toml` `disallowed-methods`).

// Ders H5: üretim yolunda panik yok (testler hariç).
#![cfg_attr(not(test), deny(clippy::unwrap_used, clippy::expect_used, clippy::panic))]

pub mod discovery;
pub mod list;
pub mod mirrors;
pub mod needs_ho;
#[doc(hidden)]
pub mod proc_cmd;
pub mod procfs;
pub mod providers;
pub mod py;
pub mod session;
pub mod status;
pub mod transcript;
pub mod usage;

use std::path::{Path, PathBuf};

pub use discovery::{find_by_name, find_sessions, CpuMode, Scan, ScanDiag};
pub use procfs::{Liveness, ProcId};
pub use session::{duplicates, Session};

/// Taramanın okuduğu kökler. Testler hepsini geçici dizine çevirir.
#[derive(Debug, Clone)]
pub struct Config {
    /// `/proc`
    pub proc_root: PathBuf,
    /// `~/.claude` (`sessions/`, `projects/`)
    pub claude_dir: PathBuf,
    /// agy'nin cwd anahtarlı sohbet önbelleği (`last_conversations.json`)
    pub agy_cache: PathBuf,
    /// claudeops'un öğrendiği agy ad -> sohbet eşlemesi (`agy_sids.json` aynası; yalnız okunur)
    pub agy_sids: PathBuf,
    /// Yalnız bu gerçek uid'in süreçleri görülür.
    pub uid: u32,
    /// `sysconf(_SC_CLK_TCK)`
    pub clk_tck: u64,
}

impl Config {
    /// Canlı makine: `$HOME`, durum dizini ([`cops_state::StateDir::resolve`]: `CLAUDEOPS_DIR`, test ikilisinde süreç başına
    /// geçici dizin, yoksa `$HOME/.claude/claudeops`; H14) ve sürecin gerçek uid'i. `HOME` yoksa ya da boşsa `None`
    /// (çağıran Python'a devreder; Python `expanduser` burada parola veritabanına düşer, bkz. `docs/rs-proc.md` madde 12).
    pub fn from_env() -> Option<Self> {
        let home = cops_state::paths::home_env().filter(|v| !v.is_empty()).map(PathBuf::from)?;
        let state = cops_state::StateDir::resolve().ok()?;
        Some(Self::for_dirs(&home, state.root()))
    }

    /// Açık kökler (ör. copsd `--state-dir`): `home` = `$HOME`, `state_dir` = claudeops durum dizini.
    pub fn for_dirs(home: &Path, state_dir: &Path) -> Self {
        // SAFETY: ikisi de argümansız/salt okuma libc çağrısı.
        let (uid, tck) = unsafe { (libc::getuid(), libc::sysconf(libc::_SC_CLK_TCK)) };
        Config {
            proc_root: PathBuf::from("/proc"),
            agy_cache: home.join(".gemini/antigravity-cli/cache/last_conversations.json"),
            agy_sids: state_dir.join("agy_sids.json"),
            claude_dir: home.join(".claude"),
            uid,
            clk_tck: u64::try_from(tck).ok().filter(|t| *t > 0).unwrap_or(100),
        }
    }
}

#[cfg(test)]
mod config_tests {
    use super::*;

    /// H14: durum dizini `cops-state` kuralından gelir; test ikilisinde `CLAUDEOPS_DIR` yokken CANLI dizin asla dönmez.
    #[test]
    fn from_env_state_dir_comes_from_cops_state() {
        let Some(c) = Config::from_env() else {
            return; // HOME yok: devredilir
        };
        let want = cops_state::StateDir::resolve().unwrap();
        assert_eq!(c.agy_sids, want.join("agy_sids.json"));
        if std::env::var_os(cops_state::paths::ENV_DIR).is_none() {
            assert!(c.agy_sids.starts_with(std::env::temp_dir()), "{c:?}");
        }
    }

    #[test]
    fn for_dirs_layout() {
        let c = Config::for_dirs(Path::new("/h"), Path::new("/s"));
        assert_eq!(c.claude_dir, PathBuf::from("/h/.claude"));
        assert_eq!(c.agy_sids, PathBuf::from("/s/agy_sids.json"));
        assert_eq!(
            c.agy_cache,
            PathBuf::from("/h/.gemini/antigravity-cli/cache/last_conversations.json")
        );
        assert_eq!(c.proc_root, PathBuf::from("/proc"));
    }
}
