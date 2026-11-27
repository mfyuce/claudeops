//! `ucli_approval`in saf kısmı: ad biçimleri, askıya alma satırı ve kayıt defteri belgesinin dönüşümleri.
//!
//! Belge `<durum>/ucli_approval/index.json`: `{run_key: {cwd, session, argv_resume, owner, created_at, state}}`. Okuma,
//! kilit ve yazım [`crate::real::approval`] içindedir. Güvenlik yolu: belirsiz olan her şey REDDEDİLİR (canlı ya da
//! tanınmayan kayıt ezilmez, tanınmayan durum yazılmaz).

use crate::pyfmt::{splitlines, strip};
use crate::pyjson::Py;

/// `STATES`.
pub const STATES: [&str; 5] = ["running", "suspended", "resuming", "done", "expired"];

/// `_KEY`: `^[a-z][a-z0-9_-]{0,63}\Z`.
pub fn valid_run_key(key: &str) -> bool {
    let b = key.as_bytes();
    b.len() <= 64
        && b.first().is_some_and(u8::is_ascii_lowercase)
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_-".contains(c))
}

/// `_ID`: `^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z`.
pub fn valid_approval_id(id: &str) -> bool {
    let b = id.as_bytes();
    b.len() <= 100
        && b.first().is_some_and(u8::is_ascii_alphanumeric)
        && b.iter()
            .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(c))
}

/// `parse_suspended`: stdout'ta (sondan) `{"suspended":{"id": ..}}` satırı; dönen onay kimliği.
pub fn parse_suspended(stdout: &str) -> Option<String> {
    splitlines(stdout)
        .into_iter()
        .rev()
        .map(strip)
        .filter(|l| l.starts_with('{'))
        .find_map(|line| {
            let doc = Py::parse(line)?;
            let id = doc.get("suspended")?.get("id")?.as_str()?;
            valid_approval_id(id).then(|| id.to_string())
        })
}

/// Defter metni; JSON nesnesi değilse (bozuk, aşırı derin, başka tür) None.
pub fn parse_index(raw: &[u8]) -> Option<Vec<(String, Py)>> {
    match Py::parse(std::str::from_utf8(raw).ok()?)? {
        Py::Object(o) => Some(o),
        _ => None,
    }
}

/// `_slot_free`: `run_key` yeni koşuya verilebilir mi (kayıt yok ya da bitmiş).
pub fn slot_free(index: &[(String, Py)], run_key: &str) -> bool {
    index
        .iter()
        .find(|(k, _)| k == run_key)
        .is_none_or(|(_, rec)| {
            matches!(
                rec.get("state").and_then(Py::as_str),
                Some("done" | "expired")
            )
        })
}

/// Kayda alınacak koşu. `argv_resume` gizli değer taşımaz (anahtar ortamdan gider).
#[derive(Debug, Clone, Copy)]
pub struct NewRun<'a> {
    pub cwd: &'a str,
    pub session: &'a str,
    pub argv_resume: &'a [String],
    pub owner: &'a str,
}

/// `register`ın belge adımı: kayıt `running` olarak yazılır (var olan anahtar yerinde kalır). Yer doluysa false.
pub fn insert_run(
    index: &mut Vec<(String, Py)>,
    run_key: &str,
    run: NewRun<'_>,
    created_at: f64,
) -> bool {
    if !slot_free(index, run_key) {
        return false;
    }
    let text = |s: &str| Py::Str(s.to_string());
    let record = Py::Object(vec![
        ("cwd".into(), text(run.cwd)),
        ("session".into(), text(run.session)),
        (
            "argv_resume".into(),
            Py::Array(run.argv_resume.iter().map(|a| text(a)).collect()),
        ),
        ("owner".into(), text(run.owner)),
        ("created_at".into(), Py::Float(created_at)),
        ("state".into(), text("running")),
    ]);
    match index.iter_mut().find(|(k, _)| k == run_key) {
        Some(slot) => slot.1 = record,
        None => index.push((run_key.to_string(), record)),
    }
    true
}

/// `set_state`in belge adımı.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateChange {
    Changed,
    /// Kayıt yok (Python `False`).
    Missing,
    /// Kayıt nesne değil (Python `TypeError`): yazılmaz.
    NotARecord,
}

/// `state` çağıran tarafından [`STATES`] ile denetlenmiş olmalı.
pub fn change_state(index: &mut [(String, Py)], run_key: &str, state: &str) -> StateChange {
    let Some((_, record)) = index.iter_mut().find(|(k, _)| k == run_key) else {
        return StateChange::Missing;
    };
    let Py::Object(fields) = record else {
        return StateChange::NotARecord;
    };
    match fields.iter_mut().find(|(k, _)| k == "state") {
        Some(slot) => slot.1 = Py::Str(state.to_string()),
        None => fields.push(("state".into(), Py::Str(state.to_string()))),
    }
    StateChange::Changed
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_are_full_matches() {
        for ok in ["r", "run1", "a_b-c", &"a".repeat(64)] {
            assert!(valid_run_key(ok), "{ok}");
        }
        for bad in [
            "",
            "../x",
            "A",
            "a/b",
            "1a",
            "_a",
            "run1\n",
            "a b",
            "a.b",
            "ğ",
            "ağ",
            &"a".repeat(65),
        ] {
            assert!(!valid_run_key(bad), "{bad:?}");
        }
        for ok in ["a", "A1", "ab-1.c_d", &"b".repeat(100)] {
            assert!(valid_approval_id(ok), "{ok}");
        }
        for bad in [
            "",
            ".a",
            "-a",
            "../x",
            "a/b",
            "ab\n",
            "a b",
            "ğ",
            "a\0",
            &"b".repeat(101),
        ] {
            assert!(!valid_approval_id(bad), "{bad:?}");
        }
    }

    #[test]
    fn suspended_line_is_searched_from_the_end() {
        let out = "noise\n{\"suspended\":{\"id\":\"ab-1\",\"state\":\"/s\",\"resume\":\"r\"}}\n";
        assert_eq!(parse_suspended(out).as_deref(), Some("ab-1"));
        for none in [
            "",
            "{\"ok\":true}",
            "{\"suspended\":{\"id\":\"../x\"}}",
            "{\"suspended\":{\"id\":5}}",
            "{\"suspended\":[]}",
            "x {\"suspended\":{\"id\":\"a\"}}",
            "{\"suspended\":{\"id\":\"ab\\n\"}}",
        ] {
            assert_eq!(parse_suspended(none), None, "{none}");
        }
        let two =
            "{\"suspended\":{\"id\":\"eski\"}}\r\n  {\"suspended\":{\"id\":\"yeni\"}}  \n{bozuk";
        assert_eq!(parse_suspended(two).as_deref(), Some("yeni"));
        let deep = format!(
            "{{\"suspended\":{{\"id\":\"iyi\"}}}}\n{}",
            "{\"a\":".repeat(100_000)
        );
        assert_eq!(parse_suspended(&deep).as_deref(), Some("iyi"));
    }
}
