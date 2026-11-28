//! Kareler: web.py `_term_output` (+ `_term_output_viewport`) ve `_term_history`. tmux yalnız okunur: `capture-pane -p`
//! (copy-mode YOK), `list-panes`, `display-message`; hedef hep `=ad:` (`cops_tmux::exact_target`).
use crate::err::{err, Key};
use crate::lite::{obj, viewport_text};
use crate::resolve::{Probe, Resolver};
use crate::{lite, mode};
use cops_state::Json;
use cops_tmux::Tmux;

/// web.py `TERM_HISTORY_MAX_LINES`.
pub const TERM_HISTORY_MAX_LINES: i64 = 500;

/// `_term_output` capture derinliği (`tmux_capture(lines=2000)`).
pub const OUTPUT_HISTORY_LINES: u32 = 2000;

fn int(n: impl Into<i64>) -> Json {
    Json::Int(n.into())
}

fn mode_json(m: Option<&str>) -> Json {
    m.map_or(Json::Null, |m| Json::Str(m.into()))
}

/// `_term_output_viewport`: tek tmux süreci (boyut + görünür ekran); başarısızsa `None` (çağıran sıradan yola düşer).
fn viewport(tmux: &Tmux, name: &str, cli: &str) -> Option<Json> {
    let snap = tmux.snapshot(name).ok()?;
    let s = snap.size;
    Some(obj(vec![
        ("ok", Json::Bool(true)),
        (
            "text",
            Json::Str(viewport_text(&snap.text, u64::from(s.rows))),
        ),
        ("cols", int(s.cols)),
        ("rows", int(s.rows)),
        ("history_size", int(s.history_size)),
        ("alternate_screen", Json::Bool(s.alternate_on)),
        (
            "masked",
            Json::Bool(cops_tmux::tty_is_masked(&snap.tty) == Some(true)),
        ),
        ("mode", mode_json(mode::detect(&snap.text, cli))),
        ("lite", Json::Bool(true)),
        ("urls", Json::Array(vec![])),
        ("paths", Json::Array(vec![])),
    ]))
}

/// `_term_output(name, lang, viewport)`. Dış `Err` = süreç tablosu okunamadı (Python istisnası).
pub fn term_output(
    probe: &dyn Probe,
    tmux: &Tmux,
    cache: &Resolver,
    name: &str,
    en: bool,
    want_viewport: bool,
) -> Result<Json, String> {
    let t = match cache.resolve(probe, name, en)? {
        Ok(t) => t,
        Err(e) => return Ok(e),
    };
    if want_viewport {
        if let Some(f) = viewport(tmux, &t.name, &t.cli) {
            return Ok(f);
        }
    }
    let Ok(text) = tmux.capture(&t.name, OUTPUT_HISTORY_LINES) else {
        cache.forget(name);
        return Ok(err(en, Key::TermSessionGone, name, ""));
    };
    let size = tmux.pane_size(&t.name).ok();
    let masked = tmux.pane_is_masked_input(&t.name) == Some(true);
    let opt = |f: fn(&cops_tmux::PaneSize) -> Json| size.as_ref().map_or(Json::Null, f);
    let m = mode::detect(&text, &t.cli);
    Ok(obj(vec![
        ("ok", Json::Bool(true)),
        ("text", Json::Str(text)),
        ("cols", opt(|s| int(s.cols))),
        ("rows", opt(|s| int(s.rows))),
        ("history_size", opt(|s| int(s.history_size))),
        ("alternate_screen", opt(|s| Json::Bool(s.alternate_on))),
        ("masked", Json::Bool(masked)),
        ("mode", mode_json(m)),
    ]))
}

/// `GET /api/term/output` gövdesi: `lite` ise `to_lite` (memo'suz).
pub fn output_payload(
    probe: &dyn Probe,
    tmux: &Tmux,
    cache: &Resolver,
    name: &str,
    en: bool,
    lite: bool,
    want_viewport: bool,
) -> Result<Json, String> {
    let f = term_output(probe, tmux, cache, name, en, want_viewport)?;
    Ok(if lite { lite::to_lite(f) } else { f })
}

/// `_term_history(name, start, end, lang)`. `start`/`end` Python `int`inin `i64`e doyurulmuş hali. Oturum çözülüyorsa sonuç
/// Python'unkiyle aynı (iki uç aynı sınıra doyarsa kırpma sonrası ikinci denetim `invalid_range` verir). Tek fark hata
/// SIRASI: `end < start` ama ikisi de `i64` dışında aynı yöne taşıyorsa Python ilk denetimde `invalid_range` döner; burada
/// ilk denetim geçer ve oturum çözülemiyorsa çözüm hatası döner.
pub fn term_history(
    probe: &dyn Probe,
    tmux: &Tmux,
    cache: &Resolver,
    name: &str,
    start: i64,
    end: i64,
    en: bool,
) -> Result<Json, String> {
    if end < start {
        return Ok(err(en, Key::InvalidRange, "", ""));
    }
    let t = match cache.resolve(probe, name, en)? {
        Ok(t) => t,
        Err(e) => return Ok(e),
    };
    let Ok(size) = tmux.pane_size(&t.name) else {
        cache.forget(name);
        return Ok(err(en, Key::TermSessionGone, name, ""));
    };
    let (hist, rows) = (i64::from(size.history_size), i64::from(size.rows));
    let (start, end) = (start.max(-hist), end.min(rows - 1));
    if end < start {
        return Ok(err(en, Key::InvalidRange, "", ""));
    }
    let end = end.min(start + TERM_HISTORY_MAX_LINES - 1);
    let Ok(text) = tmux.capture_range(&t.name, start, end) else {
        cache.forget(name);
        return Ok(err(en, Key::TermSessionGone, name, ""));
    };
    let text = text.strip_suffix('\n').map(str::to_string).unwrap_or(text);
    Ok(obj(vec![
        ("ok", Json::Bool(true)),
        ("text", Json::Str(text)),
        ("start", int(start)),
        ("end", int(end)),
        ("history_size", int(size.history_size)),
        ("rows", int(size.rows)),
        ("cols", int(size.cols)),
        ("alternate_screen", Json::Bool(size.alternate_on)),
    ]))
}
