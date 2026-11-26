//! Kaynak taraması (test dışı kod, `#[cfg(test)]` öncesi):
//! - `$HOME` yalnız `paths.rs`te okunur (H14, `f7f9dbc`).
//! - Hata yutma kalıpları (H9): `.unwrap()`, `.expect(`, `let _ =`, `.ok()`, `unwrap_or_default()` dosya başına SAYILIR ve
//!   aşağıdaki izin tablosuyla birebir eşleşmeli. Her birinin gerekçesi `docs/rs-state.md` "Ders listesi" > "Hata yutma
//!   taraması". Yeni bir kullanım: gerekçeyi belgeye yaz, sayıyı burada güncelle.
use std::collections::BTreeMap;
use std::path::Path;

const PATTERNS: [&str; 5] = [
    ".unwrap()",
    ".expect(",
    "let _ =",
    ".ok()",
    "unwrap_or_default()",
];

/// (dosya, kalıp) -> izinli sayı.
const ALLOWED: &[(&str, &str, usize)] = &[
    ("fsutil.rs", "let _ =", 7),
    ("fsutil.rs", ".ok()", 2),
    ("json.rs", ".ok()", 1),
    ("paths.rs", "let _ =", 2),
    ("paths.rs", ".ok()", 1),
    ("pycompat.rs", ".ok()", 2),
    ("pytime.rs", ".ok()", 1),
    ("roster.rs", "unwrap_or_default()", 4),
    ("settings.rs", ".ok()", 2),
    ("settings_read.rs", ".ok()", 1),
    ("statedocs.rs", ".ok()", 3),
    ("statedocs.rs", "unwrap_or_default()", 2),
    ("statedocs.rs", "let _ =", 1),
    ("store.rs", "let _ =", 1),
];

fn sources() -> Vec<(String, String)> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut v: Vec<(String, String)> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "rs"))
        .map(|p| {
            let s = std::fs::read_to_string(&p).unwrap();
            let body = s.split("#[cfg(test)]").next().unwrap().to_string();
            (p.file_name().unwrap().to_string_lossy().into_owned(), body)
        })
        .collect();
    v.sort();
    v
}

#[test]
fn home_only_in_paths() {
    for (f, body) in sources() {
        if f == "paths.rs" {
            continue;
        }
        for pat in ["\"HOME\"", "home_dir(", "var_os(\"HOME", "var(\"HOME"] {
            assert!(
                !body.contains(pat),
                "{f}: `{pat}` (HOME yalnız paths.rs'te okunur)"
            );
        }
    }
}

/// H2: dosya yazımı yalnız `fsutil` (geçici dosya + fsync + rename) üzerinden; doğrudan `fs::write`/`File::create` yok.
#[test]
fn no_direct_file_writes() {
    for (f, body) in sources() {
        for pat in ["fs::write(", "File::create("] {
            assert!(!body.contains(pat), "{f}: `{pat}` (atomik yazıcı kullan)");
        }
    }
}

#[test]
fn swallow_patterns_match_allowlist() {
    let mut got: BTreeMap<(String, &str), usize> = BTreeMap::new();
    for (f, body) in sources() {
        for pat in PATTERNS {
            let n = body.matches(pat).count();
            if n > 0 {
                got.insert((f.clone(), pat), n);
            }
        }
    }
    let want: BTreeMap<(String, &str), usize> = ALLOWED
        .iter()
        .map(|(f, p, n)| ((f.to_string(), *p), *n))
        .collect();
    assert_eq!(
        got, want,
        "hata yutma kalıbı sayısı değişti: gerekçeyi docs/rs-state.md'ye yaz, tabloyu güncelle"
    );
}
