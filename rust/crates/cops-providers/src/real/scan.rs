//! G9 gerçek süreç taraması: [`SessionScan`] `cops-procscan::find_sessions(CpuMode::Skip)` üstüne (Python
//! `spawn._ids_held_by_others` içindeki `find_sessions(measure_cpu=False)`).
//!
//! Python'un taramadaki tek YAN ETKİSİ korunur: agy süreçlerinden öğrenilen (ad, sohbet) eşlemesi `agy_sids`e yazılır
//! (`agy_provider._remember_agy_sid`; kuru çalıştırmada yazılmaz). `cops-procscan` kalıcılaştırmayı çağırana bırakır;
//! burada crate'in kendi [`AgySidStore`] yolu ([`remember_agy_sid`]) kullanılır.
//!
//! "Tarama düştü" (None, çağıran boş küme kullanır) = Python `find_sessions`in istisna atacağı durumlar:
//! - süreç listesi okunamadı (`psutil.process_iter` -> `os.listdir("/proc")`),
//! - öğrenilen agy eşlemesi YAZILAMADI (Python `statedocs.write_json` istisnası taramayı düşürür).
//!
//! Kilit alınamazsa Python gibi tarama sürer, `agy_sids_lock_busy` günlüğe düşer.

use crate::agy_resume::{remember_agy_sid, AgySidStore};
use crate::probe::{Diag, Paths};
use crate::pyjson::Py;
use crate::spawn_exec::{DiagSink, SessionScan};
use cops_procscan::{find_sessions, Config, CpuMode};
use serde_json::json;
use std::cell::Cell;
use std::path::PathBuf;

/// Gerçek [`SessionScan`].
pub struct ProcScan<'a> {
    cfg: Config,
    agy: &'a dyn AgySidStore,
    diag: &'a dyn DiagSink,
}

/// Kullanıcının gerçek uid'i ve `sysconf(_SC_CLK_TCK)`.
fn uid_and_clk_tck() -> (u32, u64) {
    // SAFETY: ikisi de argümansız/salt okuma libc çağrısı.
    let (uid, tck) = unsafe { (libc::getuid(), libc::sysconf(libc::_SC_CLK_TCK)) };
    (
        uid,
        u64::try_from(tck).ok().filter(|t| *t > 0).unwrap_or(100),
    )
}

/// `paths`in köklerinden tarama yapılandırması (Python: `Path.home()`, `CLAUDEOPS_DIR`, `os.getuid()`).
pub fn scan_config(paths: &Paths) -> Config {
    let (uid, clk_tck) = uid_and_clk_tck();
    Config {
        proc_root: PathBuf::from("/proc"),
        claude_dir: PathBuf::from(format!("{}/.claude", paths.home)),
        agy_cache: PathBuf::from(paths.agy_conversations_cache()),
        agy_sids: PathBuf::from(paths.agy_sids_json()),
        uid,
        clk_tck,
    }
}

impl<'a> ProcScan<'a> {
    /// `cfg`: tarama kökleri ([`scan_config`]; testte geçici `/proc`). `agy`: öğrenilen eşlemenin yazım yolu
    /// (gerçek: [`crate::real::docs::DocAgySidStore`]), `diag`: `diag_log`.
    pub fn new(cfg: Config, agy: &'a dyn AgySidStore, diag: &'a dyn DiagSink) -> ProcScan<'a> {
        ProcScan { cfg, agy, diag }
    }
}

/// Yazım hatasını kilit hatasından ayırmak için kayıt tutan sarmalayıcı (ikisi de `remember_agy_sid`den `Err` döner).
struct SaveWatch<'a> {
    inner: &'a dyn AgySidStore,
    save_failed: Cell<bool>,
}

impl AgySidStore for SaveWatch<'_> {
    fn load(&self) -> Option<Py> {
        self.inner.load()
    }
    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String> {
        self.inner.locked(f)
    }
    fn save(&self, doc: &Py) -> Result<(), String> {
        let r = self.inner.save(doc);
        if r.is_err() {
            self.save_failed.set(true);
        }
        r
    }
}

/// Python `str(e)[:200]` (karakter).
fn first_chars(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

impl SessionScan for ProcScan<'_> {
    fn live_sessions(&self, preview: bool) -> Option<Vec<(String, Option<String>)>> {
        let scan = find_sessions(&self.cfg, CpuMode::Skip);
        if scan.diag.proc_root_error.is_some() {
            return None;
        }
        let watch = SaveWatch {
            inner: self.agy,
            save_failed: Cell::new(false),
        };
        for (name, sid) in &scan.agy_learned {
            if let Err(e) = remember_agy_sid(&watch, name, sid, preview) {
                if watch.save_failed.get() {
                    return None;
                }
                self.diag.log(&Diag {
                    event: "agy_sids_lock_busy",
                    fields: vec![("error", json!(first_chars(&e, 200)))],
                });
            }
        }
        Some(scan.sessions.into_iter().map(|s| (s.name, s.sid)).collect())
    }
}
