//! `routing._sync_one` dosya adımları ve `sync_global_files`: karar [`crate::routing::sync_plan`], burada okuma, ilk
//! yazımdan önce `.bak-routing` yedeği (`shutil.copy2`), silme ve bağlantının HEDEFİNE atomik yazım.
//!
//! Sonuç metinleri Python ile aynı: `written`, `removed`, `unchanged`, `skipped:no file`, `skipped:<OSError sınıfı>`,
//! `skipped:UnicodeDecodeError` (yalnız bu sonuçta `routing_guidance_unreadable` günlüğü).

use crate::probe::{Diag, Paths, Probe};
use crate::real::effects::atomic_write_text;
use crate::real::fsio::TEXT_MAX_BYTES;
use crate::real::oserr;
use crate::routing::{sync_plan, SyncAction};
use crate::settings::Settings;
use crate::spawn_exec::DiagSink;
use serde_json::json;
use std::fs::{self, File, FileTimes, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

/// `<yol>.bak-routing`.
pub const BACKUP_SUFFIX: &str = ".bak-routing";

fn skipped(e: &io::Error) -> String {
    format!("skipped:{}", oserr::class_name(e))
}

/// Python `open(path, encoding="utf-8").read()`in bayt kısmı ([`TEXT_MAX_BYTES`] üstü `OSError` sayılır; Python sınırsız).
fn read_raw(path: &str) -> io::Result<Vec<u8>> {
    let mut out = Vec::new();
    File::open(path)?.take(TEXT_MAX_BYTES + 1).read_to_end(&mut out)?;
    if out.len() as u64 > TEXT_MAX_BYTES {
        return Err(io::Error::from_raw_os_error(libc::EFBIG));
    }
    Ok(out)
}

/// `shutil.copy2(src, dst)`: içerik (hedef bağlantıysa izlenir), izin, erişim/değişim zamanı.
pub fn copy2(src: &str, dst: &str) -> io::Result<()> {
    let mut from = File::open(src)?;
    let meta = from.metadata()?;
    let mut to = OpenOptions::new().write(true).create(true).truncate(true).open(dst)?;
    io::copy(&mut from, &mut to)?;
    to.flush()?;
    let times = FileTimes::new().set_accessed(meta.accessed()?).set_modified(meta.modified()?);
    to.set_times(times)?;
    to.set_permissions(fs::Permissions::from_mode(meta.permissions().mode() & 0o7777))?;
    Ok(())
}

/// `_sync_one(path, create)`. `probe` yönerge metni (`routing_text`) ve `realpath` için.
pub fn sync_one(
    probe: &dyn Probe,
    settings: &Settings,
    paths: &Paths,
    path: &str,
    create: bool,
    diag: &dyn DiagSink,
) -> String {
    let exists = Path::new(path).is_file();
    if !exists && !create {
        return "skipped:no file".into();
    }
    let current = if exists {
        match read_raw(path) {
            Ok(b) => Some(b),
            Err(e) => return skipped(&e),
        }
    } else {
        None
    };
    let bundled = probe.read_text(&paths.routing_bundled());
    match sync_plan(settings, bundled.as_deref(), current.as_deref(), create) {
        SyncAction::SkippedNoFile => "skipped:no file".into(),
        SyncAction::SkippedBadUtf8 => {
            diag.log(&Diag {
                event: "routing_guidance_unreadable",
                fields: vec![("path", json!(path)), ("error", json!("UnicodeDecodeError"))],
            });
            "skipped:UnicodeDecodeError".into()
        }
        SyncAction::Unchanged => "unchanged".into(),
        SyncAction::Remove => match fs::remove_file(path) {
            Ok(()) => "removed".into(),
            Err(e) => skipped(&e),
        },
        SyncAction::Write { content, backup, removed } => {
            let bak = format!("{path}{BACKUP_SUFFIX}");
            // `os.path.exists`: bağlantı izlenir (kırık bağlantı = yok)
            if backup && !Path::new(&bak).exists() {
                if let Err(e) = copy2(path, &bak) {
                    return skipped(&e);
                }
            }
            // bağlantıyı düz dosyayla DEĞİŞTİRME (dotfiles deposu): asıl hedefe yaz, izin korunur
            match atomic_write_text(&probe.realpath(path), &content, None) {
                Ok(()) => (if removed { "removed" } else { "written" }).into(),
                Err(e) => skipped(&e),
            }
        }
    }
}

/// `sync_global_files(codex_path, agy_path)`: codex dosyası yoksa oluşturulmaz, agy dosyası oluşturulur.
/// Dönüş Python sözlüğünün sırasıyla `[("codex", ..), ("agy", ..)]`.
pub fn sync_global_files_at(
    probe: &dyn Probe,
    settings: &Settings,
    paths: &Paths,
    codex_path: &str,
    agy_path: &str,
    diag: &dyn DiagSink,
) -> [(&'static str, String); 2] {
    [
        ("codex", sync_one(probe, settings, paths, codex_path, false, diag)),
        ("agy", sync_one(probe, settings, paths, agy_path, true, diag)),
    ]
}

/// [`sync_global_files_at`] varsayılan yollarla (`~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`).
pub fn sync_global_files(
    probe: &dyn Probe,
    settings: &Settings,
    paths: &Paths,
    diag: &dyn DiagSink,
) -> [(&'static str, String); 2] {
    sync_global_files_at(probe, settings, paths, &paths.codex_agents_md(), &paths.agy_gemini_md(), diag)
}
