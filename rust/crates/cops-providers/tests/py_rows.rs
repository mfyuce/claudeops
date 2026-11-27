//! Test eşleme tablosundaki parite dışı satırlar (`docs/rs-prov.md`, eskiden TAŞINDI-TESTSİZ): Python testinin
//! denetimli düzenini (sahte dosya varlığı, okunamayan paketli dosya, gerçek kabukta `nice`) Rust'ta kuran birim testleri.
//! Gerçek HOME/`~/.claude`/ağ yok; geçici ağaç `g8/support.rs`.

#[path = "g8/support.rs"]
mod support;

use cops_providers::routing::claude_guidance_path;
use cops_providers::spawn::{detect_display, priority_prefix};
use cops_providers::{BuildOutput, ModelCatalog, Providers, Settings};
use std::process::Command;

/// `DetectDisplayTest`: ortamda `DISPLAY` yok, yalnız verilen yollar "var".
fn display_with(existing: &[&str]) -> String {
    detect_display(None, &|p: &str| existing.contains(&p))
}

#[test]
fn detect_display_socket_only_x0() {
    assert_eq!(display_with(&["/tmp/.X11-unix/X0"]), ":0");
}

#[test]
fn detect_display_lock_still_works() {
    assert_eq!(display_with(&["/tmp/.X1-lock"]), ":1");
}

#[test]
fn detect_display_prefers_1_over_0() {
    assert_eq!(display_with(&["/tmp/.X11-unix/X0", "/tmp/.X11-unix/X1"]), ":1");
    assert_eq!(display_with(&["/tmp/.X0-lock", "/tmp/.X11-unix/X1"]), ":1");
}

#[test]
fn detect_display_nothing_defaults_1_and_env_wins() {
    assert_eq!(display_with(&[]), ":1");
    assert_eq!(detect_display(Some(":7"), &|_| true), ":7");
    // Boş `DISPLAY` yok sayılır (Python `os.environ.get("DISPLAY") or ...`).
    assert_eq!(detect_display(Some(""), &|p| p == "/tmp/.X11-unix/X0"), ":0");
}

/// `SpawnPriority.test_child_inherits_nice`: önek gerçek kabukta çocuğa nice aktarır (yetkisiz süreç önceliği
/// ARTIRAMAZ: üst süreç zaten daha düşük öncelikteyse çocuk onu korur).
#[test]
fn priority_prefix_child_inherits_nice() {
    let pre = priority_prefix(&Settings::from_json(r#"{"spawn_nice": "10"}"#), "p");
    assert!(pre.contains("renice -n 10"), "{pre}");
    let out = Command::new("sh")
        .args(["-c", &format!("cd /tmp && {pre}bash -c 'cut -d\" \" -f19 /proc/$$/stat'")])
        .output()
        .unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    // SAFETY: `nice(0)` önceliği değiştirmez, yalnız okur.
    let ours = unsafe { libc::nice(0) };
    assert_eq!(String::from_utf8_lossy(&out.stdout).trim(), (ours.max(10)).to_string());
}

/// `GuidanceTest.test_guidance_failure_never_breaks_spawn`: paketli yönerge yok, dizin ya da UTF-8 değilse bayrak
/// eklenmez (None), panik yok, hiçbir şey yazılmaz.
#[test]
fn guidance_failure_never_breaks_spawn() {
    let t = support::Tmp::new();
    let probe = t.probe();
    let settings = Settings::default();
    let catalog = ModelCatalog::default();
    let paths = t.paths();
    let p = Providers { settings: &settings, catalog: &catalog, paths: &paths, probe: &probe };
    let bundled = paths.routing_bundled();
    let check = |what: &str| {
        let mut out = BuildOutput::default();
        assert_eq!(claude_guidance_path(&p, &mut out), None, "{what}");
        assert!(out.effects.is_empty() && out.diags.is_empty(), "{what}: {:?}", out.diags);
    };
    check("yok");
    std::fs::create_dir_all(&bundled).unwrap();
    check("dizin");
    std::fs::remove_dir(&bundled).unwrap();
    t.write(&bundled[t.root.len() + 1..], b"\xff\xfe bozuk", 0o644);
    check("utf-8 degil");
    t.write(&bundled[t.root.len() + 1..], "  \n", 0o644);
    check("bos");
    t.write(&bundled[t.root.len() + 1..], "yönerge\n", 0o644);
    let mut out = BuildOutput::default();
    assert_eq!(claude_guidance_path(&p, &mut out), Some(bundled.clone()));
}
