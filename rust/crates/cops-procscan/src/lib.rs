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

use std::path::PathBuf;

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
    /// Canlı makine: `$HOME`, `$CLAUDEOPS_DIR` ve sürecin gerçek uid'i. `HOME` yoksa `None`.
    pub fn from_env() -> Option<Self> {
        let var = |k: &str| std::env::var_os(k).filter(|v| !v.is_empty()).map(PathBuf::from);
        let home = var("HOME")?;
        let claude_dir = home.join(".claude");
        let state = var("CLAUDEOPS_DIR").unwrap_or_else(|| claude_dir.join("claudeops"));
        // SAFETY: ikisi de argümansız/salt okuma libc çağrısı.
        let (uid, tck) = unsafe { (libc::getuid(), libc::sysconf(libc::_SC_CLK_TCK)) };
        Some(Config {
            proc_root: PathBuf::from("/proc"),
            agy_cache: home.join(".gemini/antigravity-cli/cache/last_conversations.json"),
            agy_sids: state.join("agy_sids.json"),
            claude_dir,
            uid,
            clk_tck: u64::try_from(tck).ok().filter(|t| *t > 0).unwrap_or(100),
        })
    }
}
