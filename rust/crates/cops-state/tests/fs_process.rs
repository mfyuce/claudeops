//! Süreç geneli durum isteyen `atomic_json.py` dalları: umask ve çalışma dizini. Ayrı test ikilisi (tek test).
use cops_state::fsutil::{atomic_write_json, atomic_write_text};
use cops_state::{Json, TestEnv};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn mode(p: &Path) -> u32 {
    std::fs::metadata(p).unwrap().permissions().mode() & 0o7777
}

#[test]
fn umask_and_bare_filename() {
    let env = TestEnv::new().unwrap();
    let d = env.dir().root();
    let one = Json::Int(1);
    // SAFETY: umask yalnız süreç maskesini değiştirir; bu ikilide tek test var.
    let old = unsafe { libc::umask(0o027) };
    atomic_write_json(&d.join("b.json"), &one, None).unwrap();
    atomic_write_text(&d.join("b.txt"), "x", None).unwrap();
    unsafe { libc::umask(0o077) };
    atomic_write_json(&d.join("c.json"), &one, Some(0o664)).unwrap();
    atomic_write_text(&d.join("c.txt"), "x", Some(0o664)).unwrap();
    unsafe { libc::umask(old) };
    for n in ["b.json", "b.txt"] {
        assert_eq!(mode(&d.join(n)), 0o640, "{n}: yeni dosya umask'a uyar");
    }
    for n in ["c.json", "c.txt"] {
        assert_eq!(mode(&d.join(n)), 0o664, "{n}: açık izin umask'ı aşar");
    }
    // dizinsiz ad: çalışma dizinine yazar
    let cwd = std::env::current_dir().unwrap();
    std::env::set_current_dir(d).unwrap();
    atomic_write_json(Path::new("plain.json"), &one, None).unwrap();
    atomic_write_text(Path::new("plain.txt"), "t", None).unwrap();
    std::env::set_current_dir(cwd).unwrap();
    assert_eq!(std::fs::read_to_string(d.join("plain.json")).unwrap(), "1");
    assert_eq!(std::fs::read_to_string(d.join("plain.txt")).unwrap(), "t");
}
