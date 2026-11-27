//! agy konuşma kimliği (`agy_provider.py`: öğrenilen `agy_sids` eşlemesi, cwd önbelleği, konuşma dizini).
//!
//! `agy_sids` yazımı [`AgySidStore`] ile çağırandadır: belge claudeops.db'de + dosya aynasıdır (rs/state `statedocs`).

use crate::live::Live;
use crate::pyfmt::{abspath, join_path, strip};
use crate::pyjson::Py;
use std::collections::BTreeSet;

/// agy cwd önbelleğinin okuma sınırı (Python sınırsız).
const CACHE_MAX_BYTES: u64 = 8 * 1024 * 1024;

/// `agy_sids` belgesinin yazım yolu.
pub trait AgySidStore {
    /// Belge; yok, bozuk ya da okunamıyorsa None.
    fn load(&self) -> Option<Py>;
    /// `f` süreç içi VE süreçler arası kilit altında koşar (Python `file_lock(AGY_SIDS_JSON)`).
    fn locked(&self, f: &mut dyn FnMut() -> Result<bool, String>) -> Result<bool, String>;
    /// Belgeyi atomik yazar (DB + ayna).
    fn save(&self, doc: &Py) -> Result<(), String>;
}

/// Belgenin girdileri; nesne olmayan belge boş sayılır.
fn entries(doc: Option<Py>) -> Vec<(String, Py)> {
    match doc {
        Some(Py::Object(o)) => o,
        _ => Vec::new(),
    }
}

fn learned<'a>(known: &'a [(String, Py)], name: &str) -> Option<&'a Py> {
    known.iter().find(|(k, _)| k == name).map(|(_, v)| v)
}

/// `sid`, `session_name` DIŞINDA bir ada kayıtlı mı (kardeş oturumun kimliği öğrenilmez).
pub fn sid_claimed_by_other(doc: &Py, sid: &str, session_name: &str) -> bool {
    match doc {
        Py::Object(o) => o
            .iter()
            .any(|(name, other)| other.as_str() == Some(sid) && name != session_name),
        _ => false,
    }
}

/// `session_name -> sid` kaydı; değer aynıysa yazmaz (kilitsiz ucuz yol, sonra kilit altında yeniden okuma).
/// `preview` (kuru çalıştırma) hiçbir şey yazmaz. Dönüş: yazıldı mı.
pub fn remember_agy_sid(
    store: &dyn AgySidStore,
    session_name: &str,
    sid: &str,
    preview: bool,
) -> Result<bool, String> {
    let same =
        |known: &[(String, Py)]| learned(known, session_name).and_then(Py::as_str) == Some(sid);
    if preview || same(&entries(store.load())) {
        return Ok(false);
    }
    store.locked(&mut || {
        let mut known = entries(store.load());
        if same(&known) {
            return Ok(false);
        }
        let value = Py::Str(sid.to_string());
        match known.iter_mut().find(|(k, _)| k == session_name) {
            Some(entry) => entry.1 = value,
            None => known.push((session_name.to_string(), value)),
        }
        store.save(&Py::Object(known))?;
        Ok(true)
    })
}

impl Live<'_> {
    /// Önce bu ADA öğrenilen kimlik; yoksa (ya da başkasının elindeyse) agy'nin cwd başına TEK kimlik tutan önbelleği.
    pub(crate) fn agy_resume_id(
        &self,
        cwd: &str,
        in_use: &BTreeSet<String>,
        session_name: &str,
    ) -> Option<String> {
        let known = entries(self.probe.agy_sids_doc());
        let own = learned(&known, session_name)
            .filter(|_| !session_name.is_empty())
            .and_then(Py::as_str);
        if let Some(own) = own.filter(|o| !o.is_empty() && !in_use.contains(*o)) {
            return Some(own.to_string());
        }
        let bytes = self
            .probe
            .read_bytes(&self.paths.agy_conversations_cache(), CACHE_MAX_BYTES)?;
        let data = Py::parse(std::str::from_utf8(&bytes).ok()?)?;
        let value = data
            .get(cwd)
            .filter(|v| v.truthy())
            .or_else(|| data.get(&abspath(cwd, &self.probe.current_dir())))?;
        let sid = strip(value.as_str()?);
        (!sid.is_empty() && !in_use.contains(sid)).then(|| sid.to_string())
    }

    /// Yalnız bu ADA öğrenilmiş VE veritabanı duran konuşma (cwd önbelleğine düşülmez).
    pub(crate) fn agy_stopped_sid(&self, session_name: &str) -> Option<String> {
        if session_name.is_empty() {
            return None;
        }
        let known = entries(self.probe.agy_sids_doc());
        let sid = learned(&known, session_name)?
            .as_str()
            .filter(|s| !s.is_empty())?;
        let db = join_path(&self.paths.agy_conversations_dir(), &format!("{sid}.db"));
        self.probe.is_file(&db).then(|| sid.to_string())
    }

    /// Konuşma dizinindeki kimlikler (`*.db*` adlarının `.db` öncesi); dizin yoksa boş.
    pub(crate) fn agy_conversation_ids(&self) -> BTreeSet<String> {
        self.probe
            .list_dir(&self.paths.agy_conversations_dir())
            .unwrap_or_default()
            .iter()
            .filter(|n| !n.starts_with('.'))
            .filter_map(|n| n.split_once(".db").map(|(id, _)| id.to_string()))
            .collect()
    }

    pub(crate) fn agy_discover(&self, snapshot: &BTreeSet<String>) -> Option<String> {
        let current = self.agy_conversation_ids();
        let mut new = current.difference(snapshot);
        match (new.next(), new.next()) {
            (Some(id), None) => Some(id.clone()),
            _ => None,
        }
    }
}
