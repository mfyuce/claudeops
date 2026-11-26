//! `routing.py`: işe göre model/effort yönergesi. claude'a her açılışta dosya bayrağı; codex/agy küresel dosyalarında
//! işaretli blok.

use crate::probe::{BuildOutput, Effect};
use crate::provider::Providers;
use crate::pyfmt::strip;
use crate::settings::Settings;

pub const BLOCK_BEGIN: &str = "<!-- claudeops-routing:begin -->";
pub const BLOCK_END: &str = "<!-- claudeops-routing:end -->";

/// Etkin yönerge: ayardaki metin, yoksa paketlenmiş dosya içeriği (okunamadıysa "").
pub fn routing_text(settings: &Settings, bundled: Option<&str>) -> String {
    let over = settings.routing_guidance_text();
    if over.is_empty() {
        bundled.unwrap_or("").to_string()
    } else {
        over + "\n"
    }
}

/// `--append-system-prompt-file` yolu; kapalıysa ya da metin boşsa None. Override varsa dosyaya yazma istenir.
pub fn claude_guidance_path(p: &Providers<'_>, out: &mut BuildOutput) -> Option<String> {
    if !p.settings.routing_guidance_enabled() {
        return None;
    }
    let bundled_path = p.paths.routing_bundled();
    let text = routing_text(p.settings, p.probe.read_text(&bundled_path).as_deref());
    if strip(&text).is_empty() {
        return None;
    }
    if p.settings.routing_guidance_text().is_empty() {
        return Some(bundled_path);
    }
    let path = p.paths.routing_override();
    if p.probe.read_text(&path).as_deref() != Some(text.as_str()) {
        out.effects.push(Effect::WriteAtomic { path: path.clone(), content: text });
    }
    Some(path)
}

/// İşaretli bloğu değiştir (`None` = kaldır); blok yoksa sona ekle.
pub fn with_block(existing: &str, body: Option<&str>) -> String {
    let mut text = existing.to_string();
    if let Some(end) = existing.find(BLOCK_END) {
        // BEGIN'i END'e en yakın olandan seç: yetim bir BEGIN kullanıcı metnini götürmesin.
        if let Some(begin) = existing[..end].rfind(BLOCK_BEGIN) {
            let head = existing[..begin].trim_end_matches('\n');
            let tail = existing[end + BLOCK_END.len()..].trim_start_matches('\n');
            let sep = if !head.is_empty() && !tail.is_empty() { "\n\n" } else { "" };
            text = format!("{head}{sep}{tail}");
        }
    }
    let Some(body) = body else {
        if !text.is_empty() && !text.ends_with('\n') {
            text.push('\n');
        }
        return text;
    };
    let block = format!("{BLOCK_BEGIN}\n{}\n{BLOCK_END}\n", body.trim_end_matches(crate::pyfmt::py_isspace));
    if strip(&text).is_empty() {
        block
    } else {
        format!("{}\n\n{block}", text.trim_end_matches('\n'))
    }
}

/// Tek küresel dosya için karar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SyncAction {
    /// Dosya yok ve oluşturulmayacak.
    SkippedNoFile,
    Unchanged,
    /// Dosyayı sil (biz oluşturduk, içinde başka şey kalmadı).
    Remove,
    /// Yaz. `backup` = ilk yazımdan önce `<yol>.bak-routing` yoksa kopyala; `removed` = blok kaldırıldı.
    Write { content: String, backup: bool, removed: bool },
}

/// `_sync_one`: `current` = dosya içeriği (yoksa None), `create` = yoksa oluştur (agy).
pub fn sync_plan(settings: &Settings, bundled: Option<&str>, current: Option<&str>, create: bool) -> SyncAction {
    if current.is_none() && !create {
        return SyncAction::SkippedNoFile;
    }
    let exists = current.is_some();
    let current = current.unwrap_or("");
    let body = if settings.routing_guidance_enabled() { routing_text(settings, bundled) } else { String::new() };
    let has_body = !strip(&body).is_empty();
    let new = with_block(current, has_body.then_some(body.as_str()));
    if new == current {
        SyncAction::Unchanged
    } else if exists && strip(&new).is_empty() && create {
        SyncAction::Remove
    } else {
        SyncAction::Write { content: new, backup: exists, removed: !has_body }
    }
}
