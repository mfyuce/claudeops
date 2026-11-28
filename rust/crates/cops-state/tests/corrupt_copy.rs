//! Yarım kalmış `.corrupt-<sha8>` yedeği değiştirilir; sembolik bağ izlenmez; geçici dosya kalmaz.
use std::fs;
use std::os::unix::fs::{symlink, PermissionsExt};

use cops_state::fsutil::write_corrupt_copy;

#[test]
fn partial_or_linked_backup_is_replaced() {
    let dir = std::env::temp_dir().join(format!("cops-corrupt-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let src = dir.join("x.json");
    let raw = b"{bozuk-icerik-tam";
    let dest = write_corrupt_copy(&src, raw).unwrap();

    fs::write(&dest, &raw[..3]).unwrap();
    assert_eq!(write_corrupt_copy(&src, raw).unwrap(), dest);
    assert_eq!(fs::read(&dest).unwrap(), raw);
    assert_eq!(
        fs::metadata(&dest).unwrap().permissions().mode() & 0o777,
        0o600
    );

    let other = dir.join("other");
    fs::write(&other, raw).unwrap();
    fs::remove_file(&dest).unwrap();
    symlink(&other, &dest).unwrap();
    write_corrupt_copy(&src, raw).unwrap();
    assert!(fs::symlink_metadata(&dest).unwrap().is_file());

    let mut names: Vec<_> = fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect();
    names.sort();
    assert_eq!(names.len(), 2, "{names:?}");
    fs::remove_dir_all(&dir).unwrap();
}

fn dead_pid() -> u32 {
    let mut c = std::process::Command::new("true").spawn().unwrap();
    let pid = c.id();
    c.wait().unwrap();
    pid
}

/// Öksüz geçici yedek (Python `_sweep_dead_corrupt_tmps` ile aynı kural): yazım arada öldürülünce (SIGKILL, güç) kalan
/// `<belge>.corrupt-<sha8>.<pid>-<x>.tmp` sonraki yedek yazımında silinir; canlı sürecinki, başka belgeninki, ayrıştırılamayan
/// ad ve normal dosya olmayan kalır.
#[test]
fn dead_process_temp_backups_are_swept() {
    let dir = std::env::temp_dir().join(format!("cops-corrupt-sweep-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let dead = dead_pid();
    let parent = std::os::unix::process::parent_id();
    let touch = |n: String| {
        let p = dir.join(n);
        fs::write(&p, b"half").unwrap();
        p
    };
    let gone = [
        touch(format!("x.json.corrupt-aaaaaaaa.{dead}-140.tmp")),
        touch(format!("x.json.corrupt-bbbbbbbb.{dead}-rs3.tmp")),
    ];
    let kept = [
        touch(format!("x.json.corrupt-aaaaaaaa.{parent}-1.tmp")),
        touch(format!("y.json.corrupt-aaaaaaaa.{dead}-1.tmp")),
        touch("x.json.corrupt-aaaaaaaa.notapid-1.tmp".into()),
    ];
    let link = dir.join(format!("x.json.corrupt-cccccccc.{dead}-2.tmp"));
    symlink("/nonexistent", &link).unwrap();
    write_corrupt_copy(&dir.join("x.json"), b"raw").unwrap();
    for p in &gone {
        assert!(!p.exists(), "{p:?}");
    }
    for p in &kept {
        assert!(p.exists(), "{p:?}");
    }
    assert!(fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    fs::remove_dir_all(&dir).unwrap();
}
