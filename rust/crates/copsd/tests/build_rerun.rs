//! `build.rs` çıktısı: her sandığın `src`si izlenir (kaynak değişince `GIT_SHA` yenilenir) ve izlenen her yol vardır.
use std::path::Path;

#[test]
fn build_script_watches_every_crate_source_and_only_existing_paths() {
    let out = std::fs::read_to_string(Path::new(env!("OUT_DIR")).join("../output")).unwrap();
    let watched: Vec<_> = out
        .lines()
        .filter_map(|l| l.strip_prefix("cargo:rerun-if-changed="))
        .map(|p| Path::new(p).to_path_buf())
        .collect();
    for p in &watched {
        assert!(p.exists(), "olmayan yol izleniyor: {}", p.display());
    }
    let seen: Vec<_> = watched
        .iter()
        .filter_map(|p| p.canonicalize().ok())
        .collect();
    let crates = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    for e in std::fs::read_dir(crates).unwrap().flatten() {
        let src = e.path().join("src");
        if src.is_dir() {
            let src = src.canonicalize().unwrap();
            assert!(seen.contains(&src), "izlenmiyor: {}", src.display());
        }
    }
}
