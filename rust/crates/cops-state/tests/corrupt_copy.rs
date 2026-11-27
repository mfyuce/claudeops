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
