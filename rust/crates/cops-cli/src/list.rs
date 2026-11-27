//! `cops list` / `ls`: tarama ve çıktı `cops-procscan`den (Python `commands/ls.py` ile bayt bayt aynı).
//!
//! Salt okur. Python'un farklı davranacağı ya da bir şey YAZACAĞI her durumda hiçbir çıktı üretmeden Python'a devredilir
//! ([`delegate_reason`]); köklerin çözülemediği durumlar (`Roots`, `Config::from_env`) `main`de devredilir.

use crate::argp::ListArgs;
use cops_procscan::{find_sessions, list::render, Config, CpuMode, Scan};
use cops_state::json::Json;
use cops_state::statedocs::read_file;
use cops_state::{Backend, StateDocs};
use std::path::Path;

/// Taramanın Python'a bırakılması gerekiyorsa nedeni.
pub fn delegate_reason(scan: &Scan) -> Option<&'static str> {
    if !scan.agy_learned.is_empty() {
        // Python keşif sırasında `agy_sids`e yazar
        return Some("yeni agy sohbet eşlemesi (Python kaydeder)");
    }
    if scan.diag.agy_files_unreadable > 0 {
        return Some("agy önbelleği ya da aynası okunamadı");
    }
    if scan.diag.proc_root_error.is_some() {
        return Some("süreç listesi okunamadı");
    }
    if scan.diag.session_files_invalid > 0 {
        // serde, Python'un okuduğu `NaN`/`Infinity`yi okumaz
        return Some("ayrıştırılamayan oturum dosyası");
    }
    // UTF-8 olmayan argv/yol kayıpla okunur; Python baytı korur
    let lossy = |s: &str| s.contains('\u{fffd}');
    if scan
        .sessions
        .iter()
        .any(|s| lossy(&s.name) || lossy(&s.cwd) || s.model.as_deref().is_some_and(lossy))
    {
        return Some("satırda kayıplı karakter");
    }
    None
}

/// `db` kipinde `agy_sids`in doğruluk kaynağı DB'dir, tarama ise dosya aynasını okur: DB okunamıyorsa ya da ayna
/// belgeyle aynı değilse devir nedeni (Python DB'den okur, gerekirse içe aktarır). Belge yazmaz, günlük tutmaz.
pub fn agy_mirror_reason(docs: &StateDocs, mirror: &Path) -> Option<&'static str> {
    if docs.backend() != Backend::Db {
        return None;
    }
    let Ok(doc) = docs.store().and_then(|s| s.get_doc("agy_sids")) else {
        return Some("agy_sids DB'den okunamadı");
    };
    let same = match (doc, read_file(mirror).into_option()) {
        (None, None) => matches!(mirror.try_exists(), Ok(false)),
        (Some(d), Some(m)) => matches!(d, Json::Object(_)) && d.py_eq(&m),
        _ => false,
    };
    (!same).then_some("agy_sids aynası DB ile aynı değil")
}

/// Tarar; `Ok` = yazılacak metin, `Err` = devir nedeni.
pub fn run(cfg: &Config, args: &ListArgs) -> Result<String, &'static str> {
    let cpu = if args.no_cpu {
        CpuMode::Skip
    } else {
        CpuMode::Sleep
    };
    let scan = find_sessions(cfg, cpu);
    match delegate_reason(&scan) {
        Some(why) => Err(why),
        None => Ok(render(scan.sessions, args.base.as_deref(), args.json)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cops_procscan::Session;

    fn row() -> Session {
        Session {
            name: "a".into(),
            pid: 1,
            cwd: "/w".into(),
            ..Default::default()
        }
    }

    #[test]
    fn every_doubt_delegates_and_clean_scan_does_not() {
        let clean = || Scan {
            sessions: vec![row()],
            ..Default::default()
        };
        assert_eq!(delegate_reason(&clean()), None);
        let cases: [fn(&mut Scan); 7] = [
            |s| s.agy_learned.push(("a".into(), "s".into())),
            |s| s.diag.agy_files_unreadable = 1,
            |s| s.diag.proc_root_error = Some("x".into()),
            |s| s.diag.session_files_invalid = 1,
            |s| s.sessions[0].name = "a\u{fffd}".into(),
            |s| s.sessions[0].cwd = "/\u{fffd}".into(),
            |s| s.sessions[0].model = Some("\u{fffd}".into()),
        ];
        for (i, change) in cases.iter().enumerate() {
            let mut s = clean();
            change(&mut s);
            assert!(delegate_reason(&s).is_some(), "durum {i}");
        }
    }

    #[test]
    fn unreadable_proc_root_is_delegated_not_reported_empty() {
        let t = tempfile::tempdir().expect("tempdir");
        let cfg = Config {
            proc_root: t.path().join("yok"),
            claude_dir: t.path().into(),
            agy_cache: t.path().join("c.json"),
            agy_sids: t.path().join("s.json"),
            uid: 0,
            clk_tck: 100,
        };
        assert!(run(&cfg, &ListArgs::default()).is_err());
    }
}
