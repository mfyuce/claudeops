//! `ucli_approval`in saf kısmı: ad biçimleri, askıya alma satırı, onay kartları ve kayıt defteri belgesinin dönüşümleri.
//!
//! Belge `<durum>/ucli_approval/index.json`: `{run_key: {cwd, session, argv_resume, owner, created_at, state}}`. Okuma,
//! kilit ve yazım [`crate::real::approval`] içindedir. Güvenlik yolu: belirsiz olan her şey REDDEDİLİR (canlı ya da
//! tanınmayan kayıt ezilmez, tanınmayan durum yazılmaz).

use crate::pyfmt::{parse_float, py_str_repr, splitlines, strip};
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

/// `_pending_files`in süzgeci: nesne ve `id` geçerli bir dize.
pub fn is_card(card: &Py) -> bool {
    card.get("id")
        .and_then(Py::as_str)
        .is_some_and(valid_approval_id)
}

fn is_text(value: Option<&Py>, text: &str) -> bool {
    value.and_then(Py::as_str) == Some(text)
}

/// `_resume_started`in karar kısmı: kart var ama hiçbiri `pending` değil (ucli sürdürmeye başlarken `resumed` yazar;
/// yerine yeni bekleyen kart yoksa onay kullanılmış, sonuç kayıp).
pub fn resume_started(cards: &[Py]) -> bool {
    !cards.is_empty() && !cards.iter().any(|c| is_text(c.get("status"), "pending"))
}

/// `pending`in satırı: yalnız `status: "pending"` kart; yalnız arayüzde gösterilecek alanlar.
pub fn pending_view(card: &Py, now: f64) -> Option<Py> {
    if !is_card(card) || !is_text(card.get("status"), "pending") {
        return None;
    }
    let field = |k: &str| card.get(k).cloned().unwrap_or(Py::Null);
    let text = |k: &str| {
        let v = card.get(k).filter(|v| v.truthy());
        Py::Str(v.map(Py::py_str).unwrap_or_default())
    };
    // `isinstance(exp, (int, float)) and exp <= now` (bool de int)
    let expired = match card.get("expires_at") {
        Some(Py::Bool(b)) => f64::from(u8::from(*b)) <= now,
        Some(Py::Int(i)) => (*i as f64) <= now,
        Some(Py::BigInt(s)) => s.starts_with('-'),
        Some(Py::Float(f)) => *f <= now,
        _ => false,
    };
    Some(Py::Object(vec![
        ("id".into(), field("id")),
        ("kind".into(), text("kind")),
        ("tool".into(), text("tool")),
        ("summary".into(), text("summary")),
        ("created_at".into(), field("created_at")),
        ("expires_at".into(), field("expires_at")),
        ("expired".into(), Py::Bool(expired)),
    ]))
}

/// Kapatılan yarım koşunun `result.error`ı.
pub const RESULT_LOST: &str = "resume ran but its result was not recorded";

/// `float(created_at)`in Python istisnası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FloatError {
    pub class: &'static str,
    pub text: String,
}

/// `float(rec.get("created_at") or now)`.
fn created_at_or(value: Option<&Py>, now: f64) -> Result<f64, FloatError> {
    let error = |class, text: String| Err(FloatError { class, text });
    let Some(value) = value.filter(|v| v.truthy()) else {
        return Ok(now);
    };
    match value {
        Py::Bool(_) => Ok(1.0),
        Py::Int(i) => Ok(*i as f64),
        Py::Float(f) => Ok(*f),
        Py::BigInt(s) => match s.parse::<f64>() {
            Ok(f) if f.is_finite() => Ok(f),
            _ => error("OverflowError", "int too large to convert to float".into()),
        },
        Py::Str(s) => match parse_float(s) {
            Some(f) => Ok(f),
            None => error(
                "ValueError",
                format!("could not convert string to float: {}", py_str_repr(s)),
            ),
        },
        _ => error("TypeError", "created_at sayı değil".into()),
    }
}

fn set_field(fields: &mut Vec<(String, Py)>, key: &str, value: Py) {
    match fields.iter_mut().find(|(k, _)| k == key) {
        Some(slot) => slot.1 = value,
        None => fields.push((key.to_string(), value)),
    }
}

/// `recover_resuming`in belge adımı: yapılan değişiklik sayısı (0 ise yazılmaz). `lost(run_key)` yalnız `resuming` ya da
/// `suspended` kayıtta sorulur: onay kullanılmış ama sonucu yazılmamışsa kayıt `done` olur (onaylı eylem ikinci kez
/// sürmesin). Kalan `resuming` `suspended`a döner; `max_age`i aşan `suspended` `expired` olur. Hata: belge yazılmamalı.
pub fn recover(
    index: &mut [(String, Py)],
    now: f64,
    max_age: f64,
    lost: impl Fn(&str) -> bool,
) -> Result<usize, FloatError> {
    let mut n = 0;
    for (key, record) in index.iter_mut() {
        let Py::Object(fields) = record else {
            continue;
        };
        let state = |fields: &[(String, Py)], wanted: &str| {
            fields
                .iter()
                .any(|(k, v)| k == "state" && v.as_str() == Some(wanted))
        };
        if (state(fields, "resuming") || state(fields, "suspended")) && lost(key) {
            let result = Py::Object(vec![("error".into(), Py::Str(RESULT_LOST.into()))]);
            set_field(fields, "state", Py::Str("done".into()));
            set_field(fields, "result", result);
            set_field(fields, "finished_at", Py::Float(now));
            n += 1;
        }
        if state(fields, "resuming") {
            set_field(fields, "state", Py::Str("suspended".into()));
            n += 1;
        }
        if state(fields, "suspended") {
            let created = fields.iter().find(|(k, _)| k == "created_at");
            if now - created_at_or(created.map(|(_, v)| v), now)? > max_age {
                set_field(fields, "state", Py::Str("expired".into()));
                n += 1;
            }
        }
    }
    Ok(n)
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
