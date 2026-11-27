//! codex rollout arşivinde konuşma bulma (`codex_provider.py`: `_session_meta`, `resolve_resume_id`, `_rollout_path`).
//! Arşiv cwd'ye göre bölünmez: `sessions/*/*/*/*.jsonl`, cwd dosyanın ilk satırından okunur.

use crate::live::Live;
use crate::pyfmt::{basename, join_path};
use crate::pyjson::Py;
use regex::Regex;
use std::collections::BTreeSet;
use std::sync::LazyLock;

/// cwd taramasında ilk satırı okunan en yeni dosya sayısı.
pub const MAX_ROLLOUT_SCAN: usize = 500;

/// Dosya adının sonundaki konuşma kimliği.
static ROLLOUT_UUID: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"-([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})\.jsonl$").expect("sabit desen")
});

impl Live<'_> {
    /// `dir`in gizli olmayan girdileri (`glob` `*`), tam yol olarak.
    fn visible(&self, dir: &str) -> impl Iterator<Item = String> + '_ {
        let dir = dir.to_string();
        let names = self.probe.list_dir(&dir).unwrap_or_default();
        names
            .into_iter()
            .filter(|n| !n.starts_with('.'))
            .map(move |n| join_path(&dir, &n))
    }

    /// `glob(sessions/*/*/*/*{suffix})`, listeleme sırasıyla.
    fn rollout_files(&self, suffix: &str) -> Vec<String> {
        let mut dirs = vec![self.paths.codex_sessions_dir()];
        for _ in 0..3 {
            dirs = dirs.iter().flat_map(|d| self.visible(d)).collect();
        }
        dirs.iter()
            .flat_map(|d| self.visible(d))
            .filter(|p| basename(p).ends_with(suffix))
            .collect()
    }

    /// İlk satır `session_meta` ise boş olmayan `payload` nesnesi.
    fn session_meta(&self, path: &str) -> Option<Py> {
        let first = self.head_lines(path, 1)?.into_iter().next()?;
        let row = Py::parse(std::str::from_utf8(&first).ok()?)?;
        if row.get("type").and_then(Py::as_str) != Some("session_meta") {
            return None;
        }
        row.get("payload")
            .filter(|p| p.is_object() && p.truthy())
            .cloned()
    }

    /// cwd'si `cwd` olan rollout'lar, yeniden eskiye (tembel: ilk satırlar gerektikçe okunur).
    fn rollouts_for<'a>(&'a self, cwd: &'a str) -> impl Iterator<Item = (String, Py)> + 'a {
        self.newest_first(self.rollout_files(".jsonl"))
            .into_iter()
            .take(MAX_ROLLOUT_SCAN)
            .filter_map(move |path| {
                let payload = self.session_meta(&path)?;
                let raw = payload.get("cwd").filter(|c| c.truthy())?;
                self.same_path(&raw.py_str(), cwd)
                    .then_some((path, payload))
            })
    }

    /// cwd'nin en yeni, başkasının tutmadığı konuşması. Kimliği olmayan (ya da metin olmayan) dosya atlanır, tarama daha
    /// eski dosyalarla sürer.
    pub(crate) fn codex_resume_id(&self, cwd: &str, in_use: &BTreeSet<String>) -> Option<String> {
        for (path, payload) in self.rollouts_for(cwd) {
            let sid = match ROLLOUT_UUID
                .captures(basename(&path))
                .and_then(|c| c.get(1))
            {
                Some(m) => Some(m.as_str().to_string()),
                None => ["id", "session_id"]
                    .iter()
                    .find_map(|k| payload.get(k).filter(|v| v.truthy()))
                    .and_then(|v| v.as_str().map(String::from)),
            };
            match sid {
                Some(s) if !in_use.contains(&s) => return Some(s),
                _ => continue,
            }
        }
        None
    }

    /// `sid`in rollout dosyası: adının sonundaki konuşma kimliği TAM `sid` olan ilk dosya (kimliksiz adda `{sid}.jsonl`
    /// ya da `-{sid}.jsonl` ile biten); `sid` yoksa ya da eşleşmezse cwd'nin en yeni dosyası. Kısmi kimlik, joker ya
    /// da `/` taşıyan `sid` başka konuşmanın dosyasını vermez.
    pub fn codex_rollout_path(&self, cwd: &str, sid: Option<&str>) -> Option<String> {
        if let Some(sid) = sid.filter(|s| !s.is_empty() && !s.contains(['/', '\0'])) {
            let exact = |p: &String| {
                let name = basename(p);
                match ROLLOUT_UUID.captures(name).and_then(|c| c.get(1)) {
                    Some(m) => m.as_str() == sid,
                    None => name
                        .strip_suffix(".jsonl")
                        .and_then(|stem| stem.strip_suffix(sid))
                        .is_some_and(|rest| rest.is_empty() || rest.ends_with('-')),
                }
            };
            if let Some(path) = self.rollout_files(".jsonl").into_iter().find(exact) {
                return Some(path);
            }
        }
        self.rollouts_for(cwd).next().map(|(path, _)| path)
    }
}
