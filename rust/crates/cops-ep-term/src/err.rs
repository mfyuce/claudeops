//! web.py `_err(lang, key, **kw)`: `{"ok": false, "error": <şablon>, "code": <key>}`. Şablonlar web.py `ERR` sözlüğüyle
//! BİREBİR (parite testi `tests/pure_parity.rs` Python'daki metni okur). `str.format` değeri yorumlamaz: ad `{x}` içerse de
//! olduğu gibi girer (tek geçişli birleştirme, sıralı `replace` DEĞİL).
use cops_state::{Json, Map};

/// Bu uçların kullandığı hata anahtarları.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    NameRequired,
    InvalidRange,
    NotRunning,
    AmbiguousName,
    NotTmuxBacked,
    TermSessionGone,
}

impl Key {
    pub const ALL: [Key; 6] = [
        Key::NameRequired,
        Key::InvalidRange,
        Key::NotRunning,
        Key::AmbiguousName,
        Key::NotTmuxBacked,
        Key::TermSessionGone,
    ];

    pub fn code(self) -> &'static str {
        match self {
            Key::NameRequired => "name_required",
            Key::InvalidRange => "invalid_range",
            Key::NotRunning => "not_running",
            Key::AmbiguousName => "ambiguous_name",
            Key::NotTmuxBacked => "not_tmux_backed",
            Key::TermSessionGone => "term_session_gone",
        }
    }
}

/// Python `lang`: yalnız tam `"en"` İngilizce, gerisi Türkçe.
pub fn message(en: bool, key: Key, name: &str, candidates: &str) -> String {
    match (key, en) {
        (Key::NameRequired, false) => "name gerekli".into(),
        (Key::NameRequired, true) => "name is required".into(),
        (Key::InvalidRange, false) => "geçersiz satır aralığı".into(),
        (Key::InvalidRange, true) => "invalid line range".into(),
        (Key::NotRunning, false) => format!("{name}: çalışmıyor"),
        (Key::NotRunning, true) => format!("{name}: not running"),
        (Key::AmbiguousName, false) => format!(
            "{name}: birden fazla çalışan session bu isme indirgeniyor ({candidates}) — \
             hangisi hedeflenecek belirsiz, tam ismini kullanın"
        ),
        (Key::AmbiguousName, true) => format!(
            "{name}: more than one running session reduces to this name ({candidates}) — \
             ambiguous which one to target, use the exact name"
        ),
        (Key::NotTmuxBacked, false) => format!(
            "{name}: tmux-backed değil (eski/bare session) — \
             terminal görünümü için handover/devral ile yeniden açın"
        ),
        (Key::NotTmuxBacked, true) => format!(
            "{name}: not tmux-backed (old/bare session) — handover/adopt it to get a terminal view"
        ),
        (Key::TermSessionGone, false) => {
            format!("{name}: tmux session artık yok (kapanmış olabilir)")
        }
        (Key::TermSessionGone, true) => {
            format!("{name}: tmux session no longer exists (may have closed)")
        }
    }
}

/// `_err(lang, key, name=..., candidates=...)`.
pub fn err(en: bool, key: Key, name: &str, candidates: &str) -> Json {
    let mut m = Map::new();
    m.insert("ok".into(), Json::Bool(false));
    m.insert(
        "error".into(),
        Json::Str(message(en, key, name, candidates)),
    );
    m.insert("code".into(), Json::Str(key.code().into()));
    Json::Object(m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn braces_in_the_name_are_not_a_template() {
        assert_eq!(
            message(true, Key::AmbiguousName, "{candidates}", "a, b"),
            "{candidates}: more than one running session reduces to this name (a, b) — \
             ambiguous which one to target, use the exact name"
        );
    }

    #[test]
    fn codes_are_distinct() {
        let mut c: Vec<_> = Key::ALL.iter().map(|k| k.code()).collect();
        c.sort_unstable();
        c.dedup();
        assert_eq!(c.len(), Key::ALL.len());
    }
}
