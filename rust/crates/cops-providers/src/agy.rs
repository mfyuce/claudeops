//! agy sağlayıcısı: effort model kimliğine gömülü.

use crate::effort::{nearest_effort, sort_levels, split_tier};
use crate::model_sources::{bounded, lock, ModelIo, RunRequest, AGY_MODELS_MAX_BYTES, AGY_MODELS_TIMEOUT};
use crate::provider::{BuildArgs, McpSpec, Providers};
use crate::pyfmt::{join_quoted, quote};
use std::sync::{Arc, Mutex};

pub const PERMISSION_MODES: [&str; 3] = ["auto", "acceptEdits", "plan"];
pub const EFFORT_LEVELS: [&str; 5] = ["low", "medium", "high", "xhigh", "max"];
/// Tur işlenirken durum çubuğunda görünen metin (küçük `e`; copilot'unkiyle karıştırma, arama büyük/küçük harf duyarlı).
pub const BUSY_STATUS_PATTERN: &str = "esc to cancel";

fn permission_flags(mode: &str) -> &'static [&'static str] {
    match if mode.is_empty() { "auto" } else { mode } {
        "auto" => &["--dangerously-skip-permissions"],
        "acceptEdits" => &["--mode", "accept-edits"],
        // Tanınmayan mod en kısıtlıya düşer.
        _ => &["--mode", "plan"],
    }
}

/// `agy models` çıktısı: yalnız `id<TAB>Etiket` satırları.
pub fn parse_models(output: &str) -> Vec<String> {
    crate::pyfmt::splitlines(output)
        .into_iter()
        .filter_map(|l| l.split_once('\t'))
        .map(|(id, _)| crate::pyfmt::strip(id).to_string())
        .collect()
}

/// Model listesinin ömrü (sn).
pub const MODELS_TTL: f64 = 300.0;

#[derive(Debug, Default)]
struct Cached {
    /// Son deneme anı (başarısız olsa da damgalanır). Başlangıç 0.0: Python gibi açılıştan sonraki ilk [`MODELS_TTL`]
    /// saniyede soğuk önbellek hiç çekilmez.
    ts: f64,
    models: Vec<String>,
}

/// `AgyProvider._cache_ts` / `_cache_models`.
#[derive(Debug, Default)]
pub struct ModelsCache(Arc<Mutex<Cached>>);

impl ModelsCache {
    /// Soğukta bloklayarak çeker; bayat ama doluysa eskiyi döndürür, yenisini arka planda çeker.
    pub(crate) fn get(&self, io: &Arc<dyn ModelIo>, binary: impl FnOnce() -> String) -> Vec<String> {
        let now = io.monotonic_secs();
        let stale = {
            let mut c = lock(&self.0);
            if now - c.ts <= MODELS_TTL {
                return c.models.clone();
            }
            c.ts = now;
            c.models.clone()
        };
        let binary = binary();
        if stale.is_empty() {
            refresh(io.as_ref(), &self.0, binary);
            return lock(&self.0).models.clone();
        }
        let (io2, cache) = (Arc::clone(io), Arc::clone(&self.0));
        io.spawn_background("agy-models-refresh", Box::new(move || refresh(io2.as_ref(), &cache, binary)));
        stale
    }
}

/// `agy models`; hata, zaman aşımı, UTF-8 olmayan ya da modelsiz çıktı eski listeyi bırakır.
fn refresh(io: &dyn ModelIo, cache: &Mutex<Cached>, binary: String) {
    let req = RunRequest { argv: vec![binary, "models".into()], timeout: AGY_MODELS_TIMEOUT, max_stdout: AGY_MODELS_MAX_BYTES };
    let Some(Ok(text)) = bounded(io.run_stdout(&req), req.max_stdout).map(String::from_utf8) else { return };
    let models = parse_models(&text);
    if !models.is_empty() {
        lock(cache).models = models;
    }
}

pub fn model_effort_levels(model: &str, models: &[String]) -> Option<Vec<String>> {
    if crate::pyfmt::strip(model).is_empty() {
        return None;
    }
    if let Some(tier) = split_tier(model).1 {
        return Some(vec![tier.to_string()]);
    }
    let siblings = models.iter().filter_map(|id| match split_tier(id) {
        (base, Some(tier)) if base == model => Some(tier.to_string()),
        _ => None,
    });
    Some(sort_levels(siblings)).filter(|s| !s.is_empty())
}

pub(crate) fn build_inner_command(p: &Providers<'_>, a: &BuildArgs<'_>) -> String {
    let mut parts = vec![quote(&p.resolved_binary("agy"))];
    if let Some(r) = a.resume_id.filter(|r| !r.is_empty()) {
        parts.extend(["--conversation".into(), quote(r)]);
    }
    parts.extend(["--model".into(), quote(a.model)]);
    // `--effort` yalnız gemini'de: diğer modellerde agy istenen modeli sessizce terk ediyor.
    if a.model.starts_with("gemini") {
        let effort = model_effort_levels(a.model, &p.catalog.agy_models)
            .and_then(|k| nearest_effort(a.effort, &k))
            .unwrap_or_else(|| a.effort.to_string());
        let effort = if effort.is_empty() { "medium" } else { &effort };
        parts.extend(["--effort".into(), quote(effort)]);
    }
    parts.extend(permission_flags(a.permission_mode).iter().map(|s| s.to_string()));
    parts.extend(a.extra_args.iter().map(|x| quote(x)));
    if let Some(pr) = a.prompt.filter(|s| !s.is_empty()) {
        parts.extend(["-i".into(), quote(pr)]);
    }
    parts.join(" ")
}

pub(crate) fn mcp_setup_command(spec: &McpSpec) -> String {
    let cmd = format!("agy mcp add {} {} {}", quote(&spec.name), quote(&spec.command), join_quoted(&spec.args));
    crate::pyfmt::strip(&cmd).to_string()
}
