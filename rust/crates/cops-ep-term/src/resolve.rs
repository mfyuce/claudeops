//! Ad -> tek, canlı, tmux'lu oturum (web.py `_find_running_for_action`, `_term_resolve`, `_term_resolve_for_output`).
//!
//! Önbellek (`_TERM_OUTPUT_RESOLVE_TTL`, 30 sn, KISALTILMAZ: CLAUDE.md "Perf"): yalnız BAŞARILI çözüm saklanır (ad -> oturum
//! adı + cli, an); hata önbelleğe girmez ve o adın kaydını siler. Süre içinde tam tarama yapılmaz (ad tmux'ta yaşadıkça
//! oturum adı ve cli sabit); tmux okuması başarısız olunca çağıran kaydı düşürür ([`Resolver::forget`]). Python'daki
//! önbellek `/ws/term` ile ORTAK, bu önbellek yalnız copsd'nin iki REST ucunun (R3: `docs/rs-ep-term.md`).
use crate::err::{err, Key};
use cops_state::Json;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// web.py `_TERM_OUTPUT_RESOLVE_TTL`.
pub const RESOLVE_TTL: Duration = Duration::from_secs(30);

/// Taramadan gelen canlı süreç (Python `Session`ın kullanılan alanları).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Live {
    pub name: String,
    pub pid: u32,
    pub cli: String,
}

/// Çözülen hedef: tmux oturum adı ve mod deseni için cli.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub name: String,
    pub cli: String,
}

/// Çözümün dış dünyası (üretimde `/proc` + tmux + `instances.json`; testte sahte).
pub trait Probe: Send + Sync {
    /// `find_sessions(measure_cpu=False)` sırasıyla. `Err` = süreç tablosu okunamadı (Python'da istisna).
    fn sessions(&self) -> Result<Vec<Live>, String>;
    /// `inst_mod.get_instance(name) is not None`.
    fn registered(&self, name: &str) -> bool;
    /// `is_tmux_backed(pid)` (bu soketin tmux sunucusu ata zincirinde mi).
    fn tmux_backed(&self, pid: u32) -> bool;
    /// `tmux_has_session(name)`; tmux sorulamadıysa `false` (Python `except: False`).
    fn has_session(&self, name: &str) -> bool;
}

/// `_find_running_for_action(name)` sonucu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Found {
    Exact(Vec<Live>),
    UniqueBase(Live),
    Ambiguous(Vec<Live>),
    None,
}

/// `_find_running_for_action(name)` (cli süzgeçsiz): önce tam ad; yoksa taban adı `name` olan VE kendi adı kayıtlı olmayan
/// süreçler (2+ = belirsiz).
pub fn find_for_action(probe: &dyn Probe, name: &str) -> Result<Found, String> {
    let sessions = probe.sessions()?;
    let exact: Vec<Live> = sessions
        .iter()
        .filter(|s| s.name == name)
        .cloned()
        .collect();
    if !exact.is_empty() {
        return Ok(Found::Exact(exact));
    }
    let mut base: Vec<Live> = sessions
        .into_iter()
        .filter(|s| {
            cops_procscan::session::base_name(&s.name) == name && !probe.registered(&s.name)
        })
        .collect();
    Ok(match base.len() {
        0 => Found::None,
        1 => Found::UniqueBase(base.remove(0)),
        _ => Found::Ambiguous(base),
    })
}

/// `_term_resolve(name, lang)`: `Ok(Ok(hedef))`, `Ok(Err(hata kare))`; dış `Err` = tarama istisnası.
pub fn term_resolve(
    probe: &dyn Probe,
    name: &str,
    en: bool,
) -> Result<Result<Target, Json>, String> {
    let s = match find_for_action(probe, name)? {
        Found::None => return Ok(Err(err(en, Key::NotRunning, name, ""))),
        Found::Ambiguous(procs) => {
            let c: Vec<&str> = procs.iter().map(|s| s.name.as_str()).collect();
            return Ok(Err(err(en, Key::AmbiguousName, name, &c.join(", "))));
        }
        Found::Exact(mut procs) => procs.remove(0),
        Found::UniqueBase(s) => s,
    };
    if !probe.tmux_backed(s.pid) {
        return Ok(Err(err(en, Key::NotTmuxBacked, name, "")));
    }
    if !probe.has_session(&s.name) {
        return Ok(Err(err(en, Key::TermSessionGone, name, "")));
    }
    Ok(Ok(Target {
        name: s.name,
        cli: s.cli,
    }))
}

/// `_term_output_resolve_cache` + `_term_resolve_for_output`.
pub struct Resolver {
    ttl: Duration,
    cache: Mutex<HashMap<String, (Target, Instant)>>,
}

impl Default for Resolver {
    fn default() -> Self {
        Resolver::with_ttl(RESOLVE_TTL)
    }
}

impl Resolver {
    /// Testler için süre; üretim [`RESOLVE_TTL`] ([`Resolver::default`]).
    pub fn with_ttl(ttl: Duration) -> Resolver {
        Resolver {
            ttl,
            cache: Mutex::new(HashMap::new()),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, (Target, Instant)>> {
        // zehirlenmiş kilit: içerik yalnız önbellek, kurtarılır (panikleyen istek 500 aldı)
        self.cache.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// `_term_resolve_for_output(name, lang)`.
    pub fn resolve(
        &self,
        probe: &dyn Probe,
        name: &str,
        en: bool,
    ) -> Result<Result<Target, Json>, String> {
        let now = Instant::now();
        if let Some((t, at)) = self.lock().get(name) {
            if now.saturating_duration_since(*at) < self.ttl {
                return Ok(Ok(t.clone()));
            }
        }
        match term_resolve(probe, name, en) {
            Ok(Ok(t)) => {
                self.lock().insert(name.to_string(), (t.clone(), now));
                Ok(Ok(t))
            }
            other => {
                // Python: hata dalında `pop`; istisnada önbelleğe dokunulmaz (Python'da istisna `pop`a varmaz)
                if let Ok(Err(_)) = other {
                    self.forget(name);
                }
                other
            }
        }
    }

    /// tmux okuması başarısız: sıradaki istek taze çözsün (`_term_output_resolve_cache.pop(name, None)`).
    pub fn forget(&self, name: &str) {
        self.lock().remove(name);
    }

    pub fn cached(&self, name: &str) -> Option<Target> {
        self.lock().get(name).map(|(t, _)| t.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[derive(Default)]
    pub struct Fake {
        pub live: Mutex<Vec<Live>>,
        pub reg: Vec<String>,
        pub unbacked: Vec<u32>,
        pub gone: Vec<String>,
        pub scans: AtomicUsize,
    }

    impl Probe for Fake {
        fn sessions(&self) -> Result<Vec<Live>, String> {
            self.scans.fetch_add(1, Ordering::SeqCst);
            Ok(self.live.lock().unwrap().clone())
        }
        fn registered(&self, name: &str) -> bool {
            self.reg.iter().any(|r| r == name)
        }
        fn tmux_backed(&self, pid: u32) -> bool {
            !self.unbacked.contains(&pid)
        }
        fn has_session(&self, name: &str) -> bool {
            !self.gone.iter().any(|g| g == name)
        }
    }

    fn l(name: &str, pid: u32) -> Live {
        Live {
            name: name.into(),
            pid,
            cli: "claude".into(),
        }
    }

    fn code(r: Result<Result<Target, Json>, String>) -> String {
        match r.unwrap() {
            Ok(t) => format!("ok:{}", t.name),
            Err(j) => j
                .get("code")
                .and_then(Json::as_str)
                .unwrap_or("?")
                .to_string(),
        }
    }

    #[test]
    fn exact_beats_base_and_base_needs_unregistered_unique() {
        let f = Fake {
            live: Mutex::new(vec![
                l("cops20261127", 1),
                l("cops", 2),
                l("hc58", 3),
                l("ab1", 4),
                l("ab2", 5),
            ]),
            reg: vec!["cops20261127".into()],
            ..Fake::default()
        };
        assert_eq!(code(term_resolve(&f, "cops", true)), "ok:cops");
        assert_eq!(code(term_resolve(&f, "hc", true)), "ok:hc58");
        assert_eq!(code(term_resolve(&f, "ab", true)), "ambiguous_name");
        assert_eq!(code(term_resolve(&f, "zz", true)), "not_running");
        f.live.lock().unwrap().retain(|s| s.name != "cops");
        assert_eq!(
            code(term_resolve(&f, "cops", true)),
            "not_running",
            "kayıtlı ad taban adayı olmaz"
        );
    }

    #[test]
    fn backed_then_session_checks_in_python_order() {
        let f = Fake {
            live: Mutex::new(vec![l("a", 1), l("b", 2)]),
            unbacked: vec![1],
            gone: vec!["a".into(), "b".into()],
            ..Fake::default()
        };
        assert_eq!(code(term_resolve(&f, "a", false)), "not_tmux_backed");
        assert_eq!(code(term_resolve(&f, "b", false)), "term_session_gone");
    }

    #[test]
    fn cache_serves_within_ttl_and_errors_are_not_cached() {
        let f = Fake {
            live: Mutex::new(vec![l("a", 1)]),
            ..Fake::default()
        };
        let r = Resolver::default();
        assert_eq!(code(r.resolve(&f, "a", true)), "ok:a");
        f.live.lock().unwrap().clear();
        assert_eq!(
            code(r.resolve(&f, "a", true)),
            "ok:a",
            "süre içinde tarama yok"
        );
        assert_eq!(f.scans.load(Ordering::SeqCst), 1);
        r.forget("a");
        assert_eq!(code(r.resolve(&f, "a", true)), "not_running");
        assert_eq!(r.cached("a"), None);
        assert_eq!(code(r.resolve(&f, "a", true)), "not_running");
        assert_eq!(f.scans.load(Ordering::SeqCst), 3, "hata önbelleğe girmez");
    }

    #[test]
    fn expired_entry_rescans() {
        let f = Fake {
            live: Mutex::new(vec![l("a", 1)]),
            ..Fake::default()
        };
        let r = Resolver::with_ttl(Duration::ZERO);
        assert_eq!(code(r.resolve(&f, "a", true)), "ok:a");
        f.live.lock().unwrap().clear();
        assert_eq!(code(r.resolve(&f, "a", true)), "not_running");
        assert_eq!(r.cached("a"), None, "hata eski kaydı da siler");
    }

    #[test]
    fn production_ttl_is_pythons_30s() {
        assert_eq!(RESOLVE_TTL, Duration::from_secs(30));
    }
}
