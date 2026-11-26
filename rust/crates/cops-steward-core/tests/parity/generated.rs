use std::process::Command;

/// Sabitler ve veri sınıfları Python'dan üretilir; Python değişip üretilen dosya güncellenmezse kırmızı.
#[test]
fn generated_files_are_current() {
    let crate_dir = env!("CARGO_MANIFEST_DIR");
    let out = Command::new("python3")
        .arg(format!("{crate_dir}/parity/gen.py"))
        .arg("--check")
        .output()
        .expect("python3 gerekli");
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
}
