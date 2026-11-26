//! İkili uçtan uca: sahte HOME/CLAUDEOPS_DIR, PATH başında sahte `systemctl` (gerçeğine ulaşılmaz), Python CLI bulma ve
//! özyineleme koruması, `on --apply` geri alması.

mod common;
use common::*;
use std::os::unix::fs::PermissionsExt;

const LIVE: &str = "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web'\n";

#[test]
fn on_apply_with_failing_systemctl_rolls_back_files() {
    let sb = Sandbox::new();
    let (_l, _busy, free) = ports();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    let out = sb
        .cmd(&bin())
        .args([
            "front",
            "on",
            "--apply",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &free,
        ])
        .env("FAKE_SC_FAIL", "restart")
        .output()
        .unwrap();
    let so = String::from_utf8_lossy(&out.stdout);
    assert_eq!(out.status.code(), Some(1), "{so}");
    assert!(
        so.contains("HATA: systemctl --user restart claudeops-web.service"),
        "{so}"
    );
    // geri almadaki web restart'ı da aynı sahte hatayı alır: açıkça BAŞARISIZ denir
    assert!(
        so.contains("restart claudeops-web.service: HATA (çıkış 1)")
            && so.contains("GERİ ALMA BAŞARISIZ"),
        "{so}"
    );
    let log = std::fs::read_to_string(sb.sc_log()).unwrap();
    assert_eq!(
        log,
        "--user is-active --quiet claudeops-front.service\n--user is-enabled --quiet claudeops-front.service\n\
         --user daemon-reload\n--user restart claudeops-web.service\n--user daemon-reload\n--user restart claudeops-web.service\n"
    );
    assert!(!sb.unit_dir().join("claudeops-front.service").exists());
    assert!(!sb
        .unit_dir()
        .join("claudeops-web.service.d/front.conf")
        .exists());
    // gizli üretildi (geri alınmaz: zararsız, Python sözleşmesi)
    let sec = sb.state().join("front.secret");
    assert_eq!(
        std::fs::metadata(&sec).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[test]
fn bad_internal_is_blocked_before_any_side_effect() {
    let sb = Sandbox::new();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    for bad in ["28765", "127.0.0.1:x", "[::1]:28765", "127.0.0.1:0"] {
        let out = sb.run(&bin(), ["front", "on", "--apply", "--internal", bad]);
        assert_eq!(out.status.code(), Some(1), "{bad}");
        assert!(
            String::from_utf8_lossy(&out.stdout).contains("geçersiz --internal"),
            "{bad}"
        );
    }
    assert!(!sb.sc_log().exists());
    assert!(!sb.state().join("front.secret").exists());
}

#[test]
fn python_not_found_is_loud_with_its_own_exit_code() {
    let sb = Sandbox::new();
    let exe = bin().canonicalize().unwrap();
    if exe.starts_with(repo()) {
        eprintln!(
            "atlandı: ikili depo içinde ({}), ikili konumu yolu Python'u bulur",
            exe.display()
        );
        return;
    }
    let out = sb
        .cmd(&bin())
        .env_remove("COPS_PY")
        .arg("--version")
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(125));
    assert!(String::from_utf8_lossy(&out.stderr).contains("Python CLI bulunamadı"));
    // `front on` de dist için Python deposuna ihtiyaç duyar
    let out = sb
        .cmd(&bin())
        .env_remove("COPS_PY")
        .args(["front", "on"])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(125));
    // status Python'suz çalışır
    let out = sb
        .cmd(&bin())
        .env_remove("COPS_PY")
        .args([
            "front",
            "status",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            "127.0.0.1:2",
        ])
        .output()
        .unwrap();
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn state_dir_link_finds_python() {
    let sb = Sandbox::new();
    std::fs::create_dir_all(sb.state().join("bin")).unwrap();
    std::os::unix::fs::symlink(py_cops(), sb.state().join("bin/cops-py")).unwrap();
    let p = sb.run(&py_cops(), ["--version"]);
    let r = sb
        .cmd(&bin())
        .env_remove("COPS_PY")
        .arg("--version")
        .output()
        .unwrap();
    same(&p, &r, "durum dizini bağlantısıyla devir");
}

#[test]
fn self_symlink_and_exec_loop_are_refused() {
    let sb = Sandbox::new();
    let link = sb.t.path().join("cops");
    std::os::unix::fs::symlink(bin(), &link).unwrap();
    let out = sb
        .cmd(&bin())
        .env("COPS_PY", &link)
        .arg("--version")
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(125));
    assert!(String::from_utf8_lossy(&out.stderr).contains("özyineleme"));
    // dolaylı döngü: başlatıcı yine cops-rs'yi çağırır; derinlik sınırı keser
    let wrap = sb.t.path().join("wrap.sh");
    write_exe(
        &wrap,
        &format!("#!/bin/sh\nexec {} \"$@\"\n", bin().display()),
    );
    let out = sb
        .cmd(&bin())
        .env("COPS_PY", &wrap)
        .arg("--version")
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(125));
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("COPS_RS_DEPTH=4"),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn exit_code_and_signal_pass_through() {
    let sb = Sandbox::new();
    let s = sb.t.path().join("py.sh");
    write_exe(
        &s,
        "#!/bin/sh\n[ \"$1\" = kill ] && kill -TERM $$\nprintf '%s|' \"$@\"\nexit 7\n",
    );
    use std::os::unix::ffi::OsStrExt;
    let out = sb
        .cmd(&bin())
        .env("COPS_PY", &s)
        .args(["x y", "--z"])
        .arg(std::ffi::OsStr::from_bytes(b"\xff"))
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(7));
    assert_eq!(out.stdout, b"x y|--z|\xff|");
    use std::os::unix::process::ExitStatusExt;
    let out = sb
        .cmd(&bin())
        .env("COPS_PY", &s)
        .arg("kill")
        .output()
        .unwrap();
    assert_eq!(out.status.signal(), Some(libc_sigterm()));
}

fn libc_sigterm() -> i32 {
    15
}

#[test]
fn leaked_depth_from_other_lineage_is_ignored() {
    // `COPS_RS_DEPTH` Python'un başlattığı uzun ömürlü süreçlere sızar; başka soydan gelen değer sayılmaz, kendi soyumuzdan
    // gelen (burada test süreci, cops-rs'nin atası) sayılır.
    let sb = Sandbox::new();
    let s = sb.t.path().join("py.sh");
    write_exe(&s, "#!/bin/sh\nexit 7\n");
    let mut other = std::process::Command::new("sleep")
        .arg("5")
        .spawn()
        .unwrap();
    let run = |v: String| {
        sb.cmd(&bin())
            .env("COPS_PY", &s)
            .env("COPS_RS_DEPTH", v)
            .arg("--version")
            .output()
            .unwrap()
    };
    assert_eq!(run(format!("9:{}", other.id())).status.code(), Some(7));
    let out = run(format!("9:{}", std::process::id()));
    assert_eq!(out.status.code(), Some(125));
    assert!(String::from_utf8_lossy(&out.stderr).contains("özyineleme"));
    other.kill().unwrap();
    other.wait().unwrap();
}
