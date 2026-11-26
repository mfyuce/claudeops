//! `atomic_json.py` ve `web._atomic_write_text`: izin, geçici dosya, eşzamanlılık, fsync sırası (strace ile sistem
//! çağrısı düzeyinde; `strace` gerekir), kilit bırakma ve kilit dosyası reddi.
use cops_state::fsutil::{atomic_write_json, atomic_write_text, atomic_write_tsv, FileLock};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

mod common;
use common::{j, Env};

fn mode(p: &Path) -> u32 {
    std::fs::metadata(p).unwrap().permissions().mode() & 0o7777
}

fn names(p: &Path) -> Vec<String> {
    let mut v: Vec<String> = std::fs::read_dir(p)
        .unwrap()
        .map(|x| x.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    v.sort();
    v
}

/// JSON yazıcı: var olan dosyanın izni korunur, açık izin onu ezer (Python aynı).
#[test]
fn json_mode_preserved_and_explicit() {
    let e = Env::new();
    let (a, b) = (e.root.join("py.json"), e.root.join("rs.json"));
    for p in [&a, &b] {
        std::fs::write(p, "{}").unwrap();
        std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o640)).unwrap();
    }
    e.py(
        "files",
        &format!("from claudeops.atomic_json import atomic_write_json\natomic_write_json('{}', {{'a': 'ş'}})", a.display()),
    );
    atomic_write_json(&b, &j(r#"{"a": "ş"}"#), None).unwrap();
    assert_eq!((mode(&a), mode(&b)), (0o640, 0o640));
    assert_eq!(std::fs::read(&a).unwrap(), std::fs::read(&b).unwrap());
    atomic_write_json(&b, &j("1"), Some(0o600)).unwrap();
    assert_eq!(mode(&b), 0o600);
}

/// Geçici adda bayat sembolik bağ izlenmez: hedef yaratılmaz, yazım tamamlanır.
#[test]
fn stale_symlink_tmp_not_followed() {
    let env = cops_state::TestEnv::new().unwrap();
    let dir = env.dir().root();
    let victim = env.root().join("kurban");
    let pid = std::process::id();
    // bu süreçteki sayaç bilinmediği için olası bütün geçici adlar dolu
    for n in 0..3000 {
        std::os::unix::fs::symlink(&victim, dir.join(format!(".tmp-{pid}-rs{n}.tsv"))).unwrap();
    }
    let (jp, tp, tsv) = (dir.join("a.json"), dir.join("b.txt"), dir.join("c.tsv"));
    plant(&jp, &victim);
    atomic_write_json(&jp, &j(r#"{"ad": "şğüİ"}"#), Some(0o600)).unwrap();
    plant(&tp, &victim);
    atomic_write_text(&tp, "metin", None).unwrap();
    atomic_write_tsv(&tsv, "a\tb\n").unwrap();
    assert!(!victim.exists(), "bağın hedefi yazılmadı");
    for p in [&jp, &tp, &tsv] {
        assert!(std::fs::symlink_metadata(p).unwrap().is_file());
    }
    assert!(std::fs::read_to_string(&jp).unwrap().contains("şğüİ"));
    assert_eq!(mode(&jp), 0o600);
}

/// `<yol>.<pid>-rs<n>.tmp` adlarına kurbanı gösteren bağ koyar.
fn plant(path: &Path, victim: &Path) {
    for n in 0..3000 {
        let mut s = path.as_os_str().to_os_string();
        s.push(format!(".{}-rs{n}.tmp", std::process::id()));
        std::os::unix::fs::symlink(victim, PathBuf::from(s)).unwrap();
    }
}

/// Yazım ortada düşerse (hedef dolu dizin: `rename` başarısız) üç yazıcı da geçici dosyasını siler.
#[test]
fn failed_write_removes_tmp() {
    let env = cops_state::TestEnv::new().unwrap();
    let dir = env.dir().root();
    let target = dir.join("hedef");
    std::fs::create_dir(&target).unwrap();
    std::fs::write(target.join("dolu"), "").unwrap();
    assert!(atomic_write_json(&target, &j("1"), None).is_err());
    assert!(atomic_write_text(&target, "x", None).is_err());
    assert!(atomic_write_tsv(&target, "x").is_err());
    assert_eq!(names(dir), ["hedef"]);
}

#[test]
fn concurrent_text_writers_leave_one_complete_file() {
    let env = cops_state::TestEnv::new().unwrap();
    let path = env.dir().join("alt/r.md");
    std::thread::scope(|s| {
        for i in 0..8 {
            let path = &path;
            s.spawn(move || {
                for _ in 0..30 {
                    atomic_write_text(path, &format!("yazar-{i}\n").repeat(400), None)
                        .expect("eşzamanlı yazım hata vermez");
                }
            });
        }
    });
    let body = std::fs::read_to_string(&path).unwrap();
    let lines: Vec<&str> = body.lines().collect();
    assert_eq!(lines.len(), 400);
    assert!(lines.iter().all(|l| *l == lines[0]), "karışık içerik");
    assert_eq!(names(path.parent().unwrap()), ["r.md"]);
}

const CHILD: &str = "COPS_STATE_STRACE_DIR";

/// Alt süreç gövdesi: [`fsync_before_rename_and_dir_after`] strace altında koşturur.
#[test]
fn strace_child() {
    let Some(dir) = std::env::var_os(CHILD) else {
        return;
    };
    let d = PathBuf::from(dir);
    atomic_write_json(&d.join("a.json"), &j("1"), None).unwrap();
    atomic_write_text(&d.join("b.txt"), "x", None).unwrap();
    std::thread::spawn({
        let p = d.join("b.txt");
        move || atomic_write_text(&p, "y", Some(0o600)).unwrap()
    })
    .join()
    .unwrap();
    atomic_write_tsv(&d.join("c.tsv"), "a\tb\n").unwrap();
}

/// Sıra: geçici dosya `O_EXCL|O_NOFOLLOW` açılır, dosya fsync, `rename`, dizin fsync. Geçici ad her yazımda farklı ve
/// sabit `<hedef>.tmp` değil.
#[test]
fn fsync_before_rename_and_dir_after() {
    let env = cops_state::TestEnv::new().unwrap();
    let dir = env.dir().root().to_path_buf();
    let trace = env.root().join("strace.log");
    let o = Command::new("strace")
        .args([
            "-f",
            "-y",
            "-qq",
            "-e",
            "trace=openat,fsync,fdatasync,rename,renameat,renameat2",
            "-o",
        ])
        .arg(&trace)
        .arg(std::env::current_exe().unwrap())
        .args(["--exact", "strace_child", "--nocapture", "--test-threads=1"])
        .env(CHILD, &dir)
        .output()
        .expect("strace gerekli");
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let d = dir.display().to_string();
    let mut events: Vec<(String, String)> = Vec::new();
    for l in std::fs::read_to_string(&trace).unwrap().lines() {
        if !l.contains(&d) {
            continue;
        }
        let quoted: Vec<&str> = l.split('"').skip(1).step_by(2).collect();
        if l.contains("openat(") && l.contains("O_CREAT") {
            assert!(l.contains("O_EXCL") && l.contains("O_NOFOLLOW"), "{l}");
            events.push(("ac".into(), quoted[0].to_string()));
        } else if l.contains("fsync(") || l.contains("fdatasync(") {
            let p = l.split(['<', '>']).nth(1).unwrap().to_string();
            events.push(("fsync".into(), p));
        } else if l.contains("rename") {
            events.push(("rename".into(), format!("{} {}", quoted[0], quoted[1])));
        }
    }
    let targets = ["a.json", "b.txt", "b.txt", "c.tsv"];
    assert_eq!(events.len(), 4 * targets.len(), "{events:#?}");
    let mut tmps = Vec::new();
    for (chunk, target) in events.chunks(4).zip(targets) {
        let kinds: Vec<&str> = chunk.iter().map(|(k, _)| k.as_str()).collect();
        assert_eq!(kinds, ["ac", "fsync", "rename", "fsync"], "{chunk:#?}");
        let tmp = &chunk[0].1;
        assert_eq!(&chunk[1].1, tmp, "rename'den önce dosyanın kendisi");
        assert_eq!(chunk[2].1, format!("{tmp} {d}/{target}"));
        assert_eq!(chunk[3].1, d, "rename'den sonra dizin");
        assert_ne!(tmp, &format!("{d}/{target}.tmp"));
        tmps.push(tmp.clone());
    }
    tmps.sort();
    tmps.dedup();
    assert_eq!(tmps.len(), targets.len(), "geçici adlar benzersiz");
}

#[test]
fn panic_releases_lock() {
    let env = cops_state::TestEnv::new().unwrap();
    let p = env.dir().join("a.json");
    let p2 = p.clone();
    let r = std::thread::spawn(move || {
        let _outer = FileLock::acquire(&p2).unwrap();
        let _inner = FileLock::acquire(&p2).unwrap();
        panic!("x");
    })
    .join();
    assert!(r.is_err());
    // aynı iş parçacığında yakalanan panik de bırakır ve kayıt temizlenir
    let caught = std::panic::catch_unwind(|| {
        let _l = FileLock::acquire(&p).unwrap();
        panic!("y");
    });
    assert!(caught.is_err());
    let p3 = p.clone();
    std::thread::spawn(move || {
        FileLock::acquire_within(&p3, Duration::from_millis(500)).map(|_| ())
    })
    .join()
    .unwrap()
    .expect("panikten sonra kilit boş");
}

/// Kilit dosyası normal dosya değilse (adlandırılmış boru) kullanılmaz.
#[test]
fn non_regular_lock_file_refused() {
    let env = cops_state::TestEnv::new().unwrap();
    let lock = env.dir().join("f.lock");
    let c = std::ffi::CString::new(lock.as_os_str().as_bytes()).unwrap();
    // SAFETY: geçerli C dizesi.
    assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o600) }, 0);
    let err = FileLock::acquire(&env.dir().join("f")).unwrap_err();
    assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied);
}
