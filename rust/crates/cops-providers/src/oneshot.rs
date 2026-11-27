//! Tek atımlık çağrının saf kısmı: `ucli chat` argv'si, anahtar ortam adı, çıktı yorumu, bütçe notu, sır silme ve
//! `CliProvider.oneshot` sonucunun yorumu. Süreç ve dosya [`crate::real::oneshot`] içindedir.
//!
//! Hata metinlerine API anahtarı GİRMEZ: çocuk çıktısı metne eklenmeden önce [`redact`]ten geçer.

use crate::probe::SpawnError;
use crate::pyfmt::{py_str_repr, strip};
use crate::pyjson::Py;
use std::fmt;

/// `OneshotError`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OneshotError(pub String);

impl fmt::Display for OneshotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for OneshotError {}

/// `_SAFE_ENV_NAME_RE` (tam eşleşme): `[A-Z0-9_]+_API_KEY`. Genel bir ad (`LD_PRELOAD`, `PATH`) kod enjeksiyonu olurdu.
pub fn is_api_key_env_name(name: &str) -> bool {
    name.strip_suffix("_API_KEY").is_some_and(|head| {
        !head.is_empty()
            && head
                .bytes()
                .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == b'_')
    })
}

/// `build_chat_argv` girdisi (`repl` ayrı: tek atımlık çağrı repl'sizdir).
#[derive(Debug, Clone, Copy, Default)]
pub struct ChatArgv<'a> {
    pub binary: &'a str,
    pub root: &'a str,
    pub repl: bool,
    pub session: Option<&'a str>,
    pub model: Option<&'a str>,
    pub endpoint: Option<&'a str>,
    /// Boşsa bayrak eklenmez.
    pub api_key_env: &'a str,
    pub with_mcp: bool,
    pub max_steps: Option<i64>,
    /// Çağıranın ek bayrakları; prompt'tan ÖNCE.
    pub extra_args: &'a [String],
}

/// `build_chat_argv`.
pub fn build_chat_argv(a: &ChatArgv<'_>) -> Vec<String> {
    let mut argv: Vec<String> = vec![
        a.binary.into(),
        "--root".into(),
        a.root.into(),
        "chat".into(),
    ];
    if a.repl {
        argv.push("--repl".into());
    }
    let key_env = Some(a.api_key_env);
    for (flag, value) in [
        ("--session", a.session),
        ("--model", a.model),
        ("--endpoint", a.endpoint),
        ("--api-key-env", key_env),
    ] {
        if let Some(v) = value.filter(|v| !v.is_empty()) {
            argv.extend([flag.to_string(), v.to_string()]);
        }
    }
    if a.with_mcp {
        argv.push("--with-mcp".into());
    }
    if let Some(n) = a.max_steps {
        argv.extend(["--max-steps".into(), n.to_string()]);
    }
    argv.extend(a.extra_args.iter().cloned());
    argv
}

/// `prompt` konumsal argümandır: `-` ile başlayan (tek `-` dışında) ucli'de bayrak sayılır, reddedilir.
pub fn check_prompt(prompt: &str) -> Result<(), SpawnError> {
    if prompt.len() > 1 && prompt.starts_with('-') {
        return Err(SpawnError(
            "prompt '-' ile başlayamaz (ucli bayrak sanır)".into(),
        ));
    }
    Ok(())
}

/// `_redact`: en az 8 karakterlik anahtar metinden silinir.
pub fn redact(text: &str, secret: Option<&str>) -> String {
    match secret.map(strip) {
        Some(s) if s.chars().count() >= 8 => text.replace(s, "<redacted>"),
        _ => text.to_string(),
    }
}

/// `_BUDGET_NOTES`.
pub const BUDGET_NOTES: [(&str, &str); 1] = [(
    "failures",
    "ucli art arda başarısız araç çağrıları yüzünden takıldı; aşağıdaki cevap KISMİ, işi bitirmedi",
)];

const NOTE_PREFIX: &str = "[⚠ ";

/// `mark_budget_exhausted`: `budget_exhausted` doluysa `answer`ın başına bir kez uyarı satırı eklenir.
pub fn mark_budget_exhausted(mut value: Py) -> Py {
    let Some(why) = value
        .get("budget_exhausted")
        .filter(|v| v.truthy())
        .map(Py::py_str)
    else {
        return value;
    };
    let text = match BUDGET_NOTES.iter().find(|(k, _)| *k == why) {
        Some((_, note)) => (*note).to_string(),
        None => format!("ucli bütçesi tükendi ({why}); cevap KISMİ olabilir"),
    };
    if let Py::Object(fields) = &mut value {
        if let Some((_, Py::Str(answer))) = fields.iter_mut().find(|(k, _)| k == "answer") {
            if !answer.starts_with(NOTE_PREFIX) {
                *answer = format!("{NOTE_PREFIX}{text}]\n{answer}");
            }
        }
    }
    value
}

/// Biten `ucli chat`in (askıya alma dışı) sonucu: çıkış kodu, tek JSON nesnesi, `error` alanı, bütçe notu.
///
/// JSON ayrıştırma ayrıntısı (Python `JSONDecodeError` metni) taşınmaz.
pub fn chat_result(
    code: i32,
    stdout: &str,
    stderr: &str,
    secret: Option<&str>,
) -> Result<Py, SpawnError> {
    if code != 0 {
        let err = redact(strip(stderr), secret);
        return Err(SpawnError(if err.is_empty() {
            format!("ucli exit={code}")
        } else {
            err
        }));
    }
    let shown = || py_str_repr(&redact(stdout, secret));
    let Some(value) = Py::parse(stdout) else {
        return Err(SpawnError(format!(
            "ucli çıktısı JSON değildi\nstdout={}",
            shown()
        )));
    };
    if !value.is_object() {
        return Err(SpawnError(format!(
            "ucli çıktısı JSON nesnesi değildi: stdout={}",
            shown()
        )));
    }
    if let Some(error) = value.get("error") {
        return Err(SpawnError(redact(&error.py_str(), secret)));
    }
    Ok(mark_budget_exhausted(value))
}

/// `UcliProvider.oneshot`un cevap metni: `str(answer or "").strip()`, boşsa hata.
pub fn ucli_answer(value: &Py) -> Result<String, OneshotError> {
    let text = value
        .get("answer")
        .filter(|a| a.truthy())
        .map(Py::py_str)
        .unwrap_or_default();
    let text = strip(&text);
    if text.is_empty() {
        return Err(OneshotError("ucli: boş yanıt".into()));
    }
    Ok(text.to_string())
}

/// Python metin kipi: katı UTF-8 ve evrensel satır sonu; UTF-8 değilse None.
pub fn decode_text(bytes: Vec<u8>) -> Option<String> {
    let text = String::from_utf8(bytes).ok()?;
    Some(if text.contains('\r') {
        text.replace("\r\n", "\n").replace('\r', "\n")
    } else {
        text
    })
}

/// `CliProvider.oneshot`un süreç sonrası yorumu.
pub fn argv_result(
    name: &str,
    code: i32,
    stdout: &str,
    stderr: &str,
) -> Result<String, OneshotError> {
    let text = strip(stdout);
    if code != 0 {
        let source = if stderr.is_empty() { text } else { stderr };
        let head: String = source.chars().take(300).collect();
        return Err(OneshotError(format!(
            "{name}: exit={code}: {}",
            strip(&head)
        )));
    }
    if text.is_empty() {
        return Err(OneshotError(format!("{name}: boş yanıt")));
    }
    Ok(text.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mark(json: &str) -> Py {
        mark_budget_exhausted(Py::parse(json).unwrap())
    }

    fn answer(v: &Py) -> &str {
        v.get("answer").and_then(Py::as_str).unwrap()
    }

    #[test]
    fn budget_note_prefixes_the_answer_once() {
        let v = mark(r#"{"answer": "yarım", "budget_exhausted": "failures"}"#);
        assert!(answer(&v).starts_with("[⚠ ") && answer(&v).ends_with("yarım"));
        assert_eq!(answer(&mark_budget_exhausted(v)).matches("[⚠ ").count(), 1);
    }

    #[test]
    fn unknown_budget_reason_is_still_marked() {
        assert!(answer(&mark(r#"{"answer": "x", "budget_exhausted": "steps"}"#)).contains("steps"));
    }

    #[test]
    fn absent_or_empty_budget_field_leaves_the_value_unchanged() {
        for json in [
            r#"{"answer": "tam"}"#,
            r#"{"answer": "t", "budget_exhausted": null}"#,
            r#"{"answer": "t", "budget_exhausted": ""}"#,
            r#"{"answer": 5, "budget_exhausted": "x"}"#,
            "[1]",
        ] {
            assert_eq!(mark(json), Py::parse(json).unwrap(), "{json}");
        }
    }

    #[test]
    fn only_api_key_names_may_receive_a_secret() {
        for ok in ["UCLI_API_KEY", "A_API_KEY", "_X9_API_KEY"] {
            assert!(is_api_key_env_name(ok), "{ok}");
        }
        for bad in [
            "",
            "_API_KEY",
            "API_KEY",
            "LD_PRELOAD",
            "ucli_API_KEY",
            "X_API_KEY\n",
            "X_API_KEY=1",
            "X_API_KEYS",
        ] {
            assert!(!is_api_key_env_name(bad), "{bad:?}");
        }
    }

    #[test]
    fn secrets_are_removed_from_every_error_text() {
        let key = "sk-gizli-anahtar";
        for (code, out, err) in [
            (2, "", "bad key sk-gizli-anahtar"),
            (0, "not json sk-gizli-anahtar", ""),
            (0, "[\"sk-gizli-anahtar\"]", ""),
            (0, "{\"error\": \"key sk-gizli-anahtar\"}", ""),
        ] {
            let text = chat_result(code, out, err, Some(" sk-gizli-anahtar\n"))
                .unwrap_err()
                .0;
            assert!(!text.contains(key) && text.contains("<redacted>"), "{text}");
        }
        assert_eq!(redact("kisa kisa", Some("kisa")), "kisa kisa");
    }
}
