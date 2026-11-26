//! `list`/`ls`: Rust'ta cevaplanır (Python'suz), Python ile bayt bayt aynı; şüpheli durumda devredilir.
//!
//! Gerçek `/proc` taranır; çıktı karşılaştırmaları testin kendi sahte süreçlerine `--base` ile daraltılır. Sahte süreç
//! `argv[0]`ı değiştirilmiş, stdin bekleyen bir bash'tir (canlı filoda kısa süre görünür, test sonunda kapatılır).

mod common;
use common::*;
use std::ffi::{OsStr, OsString};
use std::os::unix::ffi::OsStringExt;
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, Output, Stdio};

/// Testler gerçek `/proc`u tarar: birinin sahte süreci ötekinin taramasına düşmesin diye sıraya alınır.
fn serial() -> std::sync::MutexGuard<'static, ()> {
    static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
    LOCK.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

struct Fake(Child);

impl Drop for Fake {
    fn drop(&mut self) {
        drop(self.0.stdin.take());
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Test sürecine özgü, `base` kuralına uyan (yalnız küçük harf) ad.
fn unique(tag: &str) -> String {
    let pid: String = std::process::id()
        .to_string()
        .bytes()
        .map(|b| char::from(b'a' + (b - b'0')))
        .collect();
    format!("zzrslist{tag}{pid}")
}

fn fake(sb: &Sandbox, argv0: &str, args: &[&OsStr], cops_name: Option<&str>) -> Fake {
    let mut c = Command::new("/bin/bash");
    c.arg0(argv0)
        .args(["--norc", "--noprofile", "-c", "echo hazir; read -r _"])
        .args(args)
        .env_clear()
        .current_dir(sb.t.path())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped());
    if let Some(n) = cops_name {
        c.env("COPS_NAME", n);
    }
    let mut f = Fake(c.spawn().unwrap());
    // `exec` tamamlandı: argv ve environ artık sahte sürecin
    let mut line = [0u8; 6];
    std::io::Read::read_exact(f.0.stdout.as_mut().unwrap(), &mut line).unwrap();
    f
}

fn fake_claude(sb: &Sandbox, name: &OsStr, extra: &[&str]) -> Fake {
    let mut args = vec![OsStr::new("--remote-control"), name];
    args.extend(extra.iter().map(OsStr::new));
    fake(sb, "claude", &args, None)
}

/// Bu makinede çalışan gerçek agy süreçleri yalıtık durum dizininde "yeni öğrenilen" sayılıp devre yol açmasın:
/// eşlemeleri sandbox aynasına yazılır.
fn seed_agy(sb: &Sandbox) {
    let cfg = cops_procscan::Config {
        proc_root: "/proc".into(),
        claude_dir: sb.home().join(".claude"),
        agy_cache: sb
            .home()
            .join(".gemini/antigravity-cli/cache/last_conversations.json"),
        agy_sids: sb.state().join("agy_sids.json"),
        // SAFETY: argümansız libc çağrısı.
        uid: unsafe { libc::getuid() },
        clk_tck: 100,
    };
    let learned = cops_procscan::find_sessions(&cfg, cops_procscan::CpuMode::Skip).agy_learned;
    let map: serde_json::Map<String, serde_json::Value> = learned
        .into_iter()
        .map(|(n, s)| (n, serde_json::Value::String(s)))
        .collect();
    std::fs::write(
        &cfg.agy_sids,
        serde_json::to_vec(&serde_json::Value::Object(map)).unwrap(),
    )
    .unwrap();
}

/// Python CLI'sız koşu: yerelde cevaplanırsa 0, devredilirse 125.
fn without_python(sb: &Sandbox, args: &[&str]) -> Output {
    sb.cmd(&bin())
        .env("COPS_PY", "/yok/py/cops")
        .args(args)
        .output()
        .unwrap()
}

fn assert_delegated(out: &Output, what: &str) {
    assert_eq!(
        out.status.code(),
        Some(125),
        "{what}: devredilmeliydi\n{}",
        String::from_utf8_lossy(&out.stdout)
    );
    assert!(out.stdout.is_empty(), "{what}: devirde çıktı yazılmaz");
    assert!(
        String::from_utf8_lossy(&out.stderr).contains("COPS_PY geçersiz"),
        "{what}"
    );
}

#[test]
fn list_is_answered_without_python_and_matches_python_bytes() {
    let _sira = serial();
    let sb = Sandbox::new();
    let name = unique("par");
    let _a = fake_claude(&sb, OsStr::new(&name), &["--model", "claude-opus-5-5"]);
    // aynı adlı ikinci süreç (DUP satırı) ve devam bayraklı üçüncü ad
    let _b = fake_claude(&sb, OsStr::new(&name), &["--resume", "s1"]);
    let _c = fake_claude(&sb, OsStr::new(&format!("{name}2_1")), &["--model", "özel"]);
    seed_agy(&sb);
    let eq = format!("--base={name}");
    let none = unique("yok");
    let cases: &[&[&str]] = &[
        &["list", "--base", &name],
        &["ls", "--base", &name, "--no-cpu"],
        &["list", "--no-cpu", "--json", &eq],
        &["ls", "--js", "--no", "--ba", &name],
        &["list", "--no-cpu", "--base", &none],
        &["list", "--no-cpu", "--json", "--base", &none],
    ];
    for args in cases {
        let r = without_python(&sb, args);
        assert_eq!(
            r.status.code(),
            Some(0),
            "{args:?}: {}",
            String::from_utf8_lossy(&r.stderr)
        );
        let p = sb.run(&py_cops(), *args);
        same(&p, &r, &format!("{args:?}"));
    }
    let out = without_python(&sb, &["list", "--no-cpu", "--base", &name]);
    let so = String::from_utf8_lossy(&out.stdout);
    assert!(so.contains(&format!("⚠ DUP: {name}")), "{so}");
    assert!(so.contains("  3 session  "), "{so}");
}

#[test]
fn learned_agy_mapping_is_delegated_so_python_records_it() {
    let _sira = serial();
    let sb = Sandbox::new();
    seed_agy(&sb);
    let name = unique("agy");
    let _a = fake(
        &sb,
        "agy",
        &[OsStr::new("--conversation"), OsStr::new("sohbet-1")],
        Some(&name),
    );
    assert_delegated(&without_python(&sb, &["list", "--no-cpu"]), "agy_learned");
    // süzgeç eşleşmese de devir: yazım yan etkisi süzgece bağlı değil
    assert_delegated(
        &without_python(&sb, &["list", "--no-cpu", "--base", "yokboyle"]),
        "agy_learned süzgeçli",
    );
}

#[test]
fn unreadable_agy_mirror_is_delegated() {
    let _sira = serial();
    let sb = Sandbox::new();
    std::fs::write(sb.state().join("agy_sids.json"), "{bozuk").unwrap();
    assert_delegated(&without_python(&sb, &["list", "--no-cpu"]), "agy aynası");
}

#[test]
fn invalid_session_file_is_delegated() {
    let _sira = serial();
    let sb = Sandbox::new();
    seed_agy(&sb);
    let d = sb.home().join(".claude/sessions");
    std::fs::create_dir_all(&d).unwrap();
    // Python `NaN`i okur, serde okumaz
    std::fs::write(d.join("1.json"), r#"{"pid": 1, "x": NaN}"#).unwrap();
    assert_delegated(
        &without_python(&sb, &["list", "--no-cpu"]),
        "geçersiz oturum dosyası",
    );
}

#[test]
fn replacement_char_in_row_is_delegated() {
    let _sira = serial();
    for case in ["ad", "model", "cwd"] {
        let sb = Sandbox::new();
        seed_agy(&sb);
        let name = unique("bozuk");
        let bad = OsString::from_vec([name.as_bytes(), &[0xff]].concat());
        let _a = match case {
            "ad" => fake_claude(&sb, &bad, &[]),
            "model" => fake_claude(&sb, OsStr::new(&name), &["--model", "m\u{fffd}"]),
            _ => {
                let dir = sb.t.path().join(OsString::from_vec(vec![b'd', 0xff]));
                std::fs::create_dir(&dir).unwrap();
                let mut c = Command::new("/bin/bash");
                c.arg0("claude")
                    .args(["--norc", "--noprofile", "-c", "echo hazir; read -r _"])
                    .args(["--remote-control", &name])
                    .env_clear()
                    .current_dir(dir)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped());
                let mut f = Fake(c.spawn().unwrap());
                let mut line = [0u8; 6];
                std::io::Read::read_exact(f.0.stdout.as_mut().unwrap(), &mut line).unwrap();
                f
            }
        };
        assert_delegated(&without_python(&sb, &["list", "--no-cpu"]), case);
    }
}

#[test]
fn bad_roots_are_delegated() {
    let _sira = serial();
    for (key, val, what) in [
        ("CLAUDEOPS_DIR", "goreli", "göreli CLAUDEOPS_DIR"),
        ("HOME", "goreli", "göreli HOME"),
        ("HOME", "", "boş HOME (Config yok)"),
    ] {
        let sb = Sandbox::new();
        seed_agy(&sb);
        let out = sb
            .cmd(&bin())
            .env("COPS_PY", "/yok/py/cops")
            .env(key, val)
            .args(["list", "--no-cpu"])
            .output()
            .unwrap();
        assert_delegated(&out, what);
    }
}

#[test]
fn unusual_list_arguments_are_delegated() {
    let _sira = serial();
    let sb = Sandbox::new();
    seed_agy(&sb);
    for args in [
        &["list", "-h"][..],
        &["list", "--help"],
        &["list", "fazla"],
        &["list", "--base"],
        &["list", "--base", "--json"],
        &["list", "--json=1"],
        &["list", "--"],
        &["list", "--bilinmeyen"],
    ] {
        assert_delegated(&without_python(&sb, args), &format!("{args:?}"));
    }
}
