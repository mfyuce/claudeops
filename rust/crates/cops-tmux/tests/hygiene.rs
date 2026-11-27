//! Kaynak kod denetimi (ders listesi, `docs/rust-lessons-from-python.md` bölüm 3): yasak kalıplar üretim kodunda yok.
//! Üretim kodu = `src/*.rs` dosyasının `#[cfg(test)]` öncesi kısmı. Testler `tests/*.rs`.

use std::fs;
use std::path::PathBuf;

fn sources(dir: &str) -> Vec<(String, String)> {
    let root = PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"))).join(dir);
    let mut out: Vec<(String, String)> = fs::read_dir(&root)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "rs"))
        .map(|p| {
            (
                p.file_name().unwrap().to_string_lossy().into_owned(),
                fs::read_to_string(&p).unwrap(),
            )
        })
        .collect();
    out.sort();
    assert!(!out.is_empty());
    out
}

fn production() -> Vec<(String, String)> {
    sources("src")
        .into_iter()
        .map(|(name, text)| {
            let cut = text.find("#[cfg(test)]").unwrap_or(text.len());
            (name, text[..cut].to_string())
        })
        .collect()
}

/// `(dosya, satır no, satır)`; yorum satırları atlanır.
fn hits(files: &[(String, String)], needle: &str) -> Vec<String> {
    files
        .iter()
        .flat_map(|(name, text)| {
            text.lines().enumerate().filter_map(move |(i, line)| {
                let code = line.trim_start();
                (!code.starts_with("//") && code.contains(needle))
                    .then(|| format!("{name}:{}: {}", i + 1, code))
            })
        })
        .collect()
}

#[test]
fn no_swallowed_result_or_panic_in_production_code() {
    let src = production();
    // Madde 5 (H9/H20): `let _ =` ve `.ok()` ile hata yutma yok; `?`'li `.ok()?` "bilinmiyor" (None) eşlemesidir ve
    // aşağıda tek tek sayılır.
    assert_eq!(hits(&src, "let _ ="), Vec::<String>::new());
    assert_eq!(hits(&src, "unwrap_or_default"), Vec::<String>::new());
    assert_eq!(hits(&src, ".unwrap()"), Vec::<String>::new());
    assert_eq!(hits(&src, "panic!"), Vec::<String>::new());
    // Tek `expect`: sabit regex derlemesi (desen testlerde derlenir).
    let expects = hits(&src, ".expect(");
    assert_eq!(expects.len(), 1, "{expects:?}");
    assert!(expects[0].starts_with("text.rs:"), "{expects:?}");
    // `.ok()` yalnız "bilinmiyor = None" dönen okuyucularda: /proc okuma, pty yoklama, maske sorgusu.
    let oks: Vec<String> = hits(&src, ".ok()")
        .into_iter()
        .filter(|h| !(h.starts_with("proc.rs:") || h.starts_with("mask.rs:")))
        .collect();
    assert_eq!(oks.len(), 1, "{oks:?}");
    assert!(oks[0].starts_with("query.rs:"), "{oks:?}");
}

#[test]
fn no_state_dir_home_file_writes_or_signals_outside_the_runner() {
    let src = production();
    // Madde 2/12/17: bu crate dosya yazmaz, durum dizinine ve `$HOME`a dokunmaz.
    for needle in [
        "\"HOME\"",
        "home_dir",
        ".claude",
        "fs::write",
        "File::create",
        "create_dir",
        "remove_file",
    ] {
        assert_eq!(hits(&src, needle), Vec::<String>::new(), "{needle}");
    }
    // Sinyal yalnız kendi başlattığımız tmux istemcisine (`runner.rs` `kill`); pkill / libc::kill yok.
    assert_eq!(hits(&src, "pkill"), Vec::<String>::new());
    assert_eq!(hits(&src, "libc::kill"), Vec::<String>::new());
    let kills = hits(&src, ".kill()");
    assert!(
        kills.iter().all(|h| h.starts_with("runner.rs:")),
        "{kills:?}"
    );
    // İş parçacığı yalnız gecikmiş toplama için (runner.rs `kill`).
    let spawns = hits(&src, "thread::");
    assert!(
        spawns
            .iter()
            .all(|h| h.contains("thread::sleep") || h.starts_with("runner.rs:")),
        "{spawns:?}"
    );
}

#[test]
fn tests_never_touch_the_live_socket() {
    // Madde 17 (H16): testler `-L cops` sunucusuna ve varsayılan sokete gitmez.
    // Bu dosya aradığı kalıpları içerir: kendisi taranmaz.
    let tests = sources("tests")
        .into_iter()
        .filter(|(n, _)| n != "hygiene.rs");
    let mut common = sources("tests/common");
    common.retain(|(n, _)| n == "mod.rs");
    let all: Vec<(String, String)> = tests.into_iter().chain(common).collect();
    assert_eq!(hits(&all, "Tmux::cops()"), Vec::<String>::new());
    assert_eq!(hits(&all, "\"-L\", \"cops\""), Vec::<String>::new());
    assert_eq!(hits(&all, "with_socket(\"cops\")"), Vec::<String>::new());
}
