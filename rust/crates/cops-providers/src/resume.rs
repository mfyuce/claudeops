//! Oturum kimliği ve devam: hangi konuşma `--resume` edilecek, durmuş oturumun konuşması, canlı kimlik keşfi
//! (`CliProvider.resolve_resume_id`/`sid_for_stopped_session`/`snapshot_for_live_sid`/`discover_live_sid`,
//! `spawn._ids_held_by_others`) ve transkript okuyucularının ortak yardımcıları. Sağlayıcı kuralları kendi modülünde:
//! `claude_resume`, `codex_resume`, `agy_resume`, `copilot`.
//!
//! `None` = "devam edilecek konuşma yok ya da bilinmiyor" (çağıran taze açar). Python'un istisna attığı bozuk girdilerde
//! (UTF-8 olmayan dosya, nesne olmayan satır, metin olmayan kimlik, okunamayan dizin) burada yalnız o aday atlanır.

use crate::claude_resume::MetaCache;
use crate::live::Live;
use crate::provider::Cli;
use crate::pyfmt::abspath;
use std::collections::BTreeSet;

/// İlk satır(lar) okumasının üst sınırı (Python sınırsız); sınırda yarım kalan satır yok sayılır.
pub const HEAD_MAX_BYTES: u64 = 8 * 1024 * 1024;
/// [`Live::head_lines`]ın okuma adımı.
const HEAD_CHUNK_BYTES: u64 = 65_536;

/// Süreç taramasının (rs/proc `find_sessions`) bu modülün baktığı alanları.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LiveSession<'a> {
    pub name: &'a str,
    pub sid: Option<&'a str>,
}

/// BAŞKA canlı oturumları tanımlayan dizeler: `--resume` ettikleri kimlikler VE adları. `name` adlı oturum dışarıda
/// (tam eşleşme). `live` None = süreç taraması başarısız: boş küme (spawn engellenmez, Python gibi).
pub fn ids_held_by_others(name: &str, live: Option<&[LiveSession<'_>]>) -> BTreeSet<String> {
    live.unwrap_or_default()
        .iter()
        .filter(|s| s.name != name)
        .flat_map(|s| [s.sid.unwrap_or(""), s.name])
        .filter(|id| !id.is_empty())
        .map(String::from)
        .collect()
}

impl Live<'_> {
    /// `cwd` için devam edilecek konuşma. `in_use`: [`ids_held_by_others`]; buradaki hiçbir kimlik dönmez.
    /// `session_name` yalnız claude (başlık tercihi) ve agy (öğrenilen kimlik) için anlamlı.
    pub fn resolve_resume_id(
        &self,
        cli: Cli,
        cwd: &str,
        in_use: &BTreeSet<String>,
        session_name: &str,
    ) -> Option<String> {
        match cli {
            Cli::Claude => self.claude_resume_id(cwd, in_use, session_name),
            Cli::Codex => self.codex_resume_id(cwd, in_use),
            Cli::Agy => self.agy_resume_id(cwd, in_use, session_name),
            Cli::Copilot => self.copilot_resume_id(cwd, in_use),
            // shell'de konuşma yok; ucli'de "resume" oturum adının kendisi.
            Cli::Shell | Cli::Ucli => None,
        }
    }

    /// DURMUŞ oturumun konuşma kimliği, ADINDAN. Yalnız kesin eşleşme döner; None = çağıran eski davranışa düşer.
    pub fn sid_for_stopped_session(
        &self,
        cli: Cli,
        cwd: &str,
        session_name: &str,
        cache: &MetaCache,
    ) -> Option<String> {
        match cli {
            Cli::Claude => self.claude_stopped_sid(cwd, session_name, cache),
            Cli::Agy => self.agy_stopped_sid(session_name),
            Cli::Ucli => Some(session_name.to_string()).filter(|n| !n.is_empty()),
            Cli::Codex | Cli::Copilot | Cli::Shell => None,
        }
    }

    /// Mesaj gönderilmeden ÖNCE alınan durum; [`Live::discover_live_sid`]e verilir. None = bu CLI'da gerekmiyor.
    pub fn snapshot_for_live_sid(&self, cli: Cli) -> Option<BTreeSet<String>> {
        match cli {
            Cli::Agy => Some(self.agy_conversation_ids()),
            Cli::Claude | Cli::Codex | Cli::Copilot | Cli::Shell | Cli::Ucli => None,
        }
    }

    /// `snapshot`tan sonra beliren TEK yeni konuşma; hiç ya da birden çoksa None (tahmin yok).
    pub fn discover_live_sid(
        &self,
        cli: Cli,
        snapshot: Option<&BTreeSet<String>>,
    ) -> Option<String> {
        match cli {
            Cli::Agy => self.agy_discover(snapshot?),
            Cli::Claude | Cli::Codex | Cli::Copilot | Cli::Shell | Cli::Ucli => None,
        }
    }

    /// `normpath(abspath(a)) == normpath(abspath(b))`.
    pub(crate) fn same_path(&self, a: &str, b: &str) -> bool {
        let cwd = self.probe.current_dir();
        abspath(a, &cwd) == abspath(b, &cwd)
    }

    /// `_safe_mtime`: `st_mtime` (float saniye); okunamazsa 0.
    pub(crate) fn safe_mtime(&self, path: &str) -> f64 {
        self.probe.stat(path).map_or(0.0, |s| {
            s.mtime_ns.div_euclid(1_000_000_000) as f64
                + 1e-9 * s.mtime_ns.rem_euclid(1_000_000_000) as f64
        })
    }

    /// Yeniden eskiye; eşit zamanlıların listeleme sırası korunur.
    pub(crate) fn newest_first(&self, paths: Vec<String>) -> Vec<String> {
        let mut timed: Vec<(f64, String)> = paths
            .into_iter()
            .map(|p| (self.safe_mtime(&p), p))
            .collect();
        timed.sort_by(|a, b| b.0.total_cmp(&a.0));
        timed.into_iter().map(|(_, p)| p).collect()
    }

    /// Dosyanın ilk `count` satırı (metin kipi satır sonları: `\n`, `\r\n`, `\r`), en çok [`HEAD_MAX_BYTES`] okunarak.
    /// Açılamayan dosya None.
    pub(crate) fn head_lines(&self, path: &str, count: usize) -> Option<Vec<Vec<u8>>> {
        let mut data = Vec::new();
        let mut ends = 0;
        loop {
            let want = HEAD_CHUNK_BYTES.min(HEAD_MAX_BYTES - data.len() as u64);
            let chunk = self.probe.read_range(path, data.len() as u64, want)?;
            let short = (chunk.len() as u64) < want;
            ends += chunk.iter().filter(|b| matches!(b, b'\n' | b'\r')).count();
            data.extend(chunk);
            let end = short || data.len() as u64 >= HEAD_MAX_BYTES;
            // `\r\n` iki sayılır: yeterlilik gerçek satırlarla ölçülür.
            if end || ends >= count {
                let truncated = !short && end;
                let mut lines = universal_lines(&data);
                let open = !data.ends_with(b"\n") && !data.ends_with(b"\r");
                if open && (truncated || !end) {
                    lines.pop();
                }
                if end || lines.len() >= count {
                    lines.truncate(count);
                    return Some(lines);
                }
            }
        }
    }
}

/// Evrensel satır sonlarıyla bölünmüş satırlar (sonlandırıcısız); sondaki sonlandırıcı boş satır üretmez.
pub(crate) fn universal_lines(data: &[u8]) -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut i = 0;
    while i < data.len() {
        if matches!(data[i], b'\n' | b'\r') {
            out.push(data[start..i].to_vec());
            if data[i] == b'\r' && data.get(i + 1) == Some(&b'\n') {
                i += 1;
            }
            start = i + 1;
        }
        i += 1;
    }
    if start < data.len() {
        out.push(data[start..].to_vec());
    }
    out
}
