//! Python ile PARİTE: aynı girdiyle `py/cops` (Python) ve `cops-rs` koşar; stdout, stderr, çıkış kodu karşılaştırılır. Yalnız
//! salt okuma yolları (status, planlar, devredilen komutlar, self). Python hiçbir zaman `--apply` ile koşmaz; portlar testin
//! kendi açtığı loopback dinleyicileridir (canlı 8765/28765'e bağlanılmaz).

mod common;
use common::*;
use std::os::unix::fs::PermissionsExt;

const LIVE: &str = "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web'\n";

fn both(sb: &Sandbox, args: &[&str]) -> (std::process::Output, std::process::Output) {
    (sb.run(&py_cops(), args), sb.run(&bin(), args))
}

#[test]
fn parity_front_status_variants() {
    let sb = Sandbox::new();
    let (_l, busy, free) = ports();
    let args = ["front", "status", "--listen", &busy, "--internal", &free];
    let (p, r) = both(&sb, &args);
    same(&p, &r, "boş durum");
    assert!(String::from_utf8_lossy(&r.stdout).contains("gizli: YOK"));
    // gizli 0600 + ikili + birimler
    let sec = sb.state().join("front.secret");
    std::fs::write(&sec, "abc\n").unwrap();
    std::fs::set_permissions(&sec, std::fs::Permissions::from_mode(0o600)).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    std::fs::write(sb.unit_dir().join("claudeops-front.service"), "x").unwrap();
    std::fs::create_dir_all(sb.unit_dir().join("claudeops-web.service.d")).unwrap();
    std::fs::write(
        sb.unit_dir().join("claudeops-web.service.d/front.conf"),
        "x",
    )
    .unwrap();
    let (p, r) = both(&sb, &args);
    same(&p, &r, "dolu durum");
    assert!(String::from_utf8_lossy(&r.stdout).contains("gizli: var"));
    // gevşek izin = gizli yok; = ile ve kısaltılmış bayraklar
    std::fs::set_permissions(&sec, std::fs::Permissions::from_mode(0o644)).unwrap();
    let l = format!("--li={busy}");
    let (p, r) = both(
        &sb,
        &["front", "--int", &free, "status", &l, "--b=/yok/copsd"],
    );
    same(&p, &r, "gevşek izin, kısaltma");
    assert!(String::from_utf8_lossy(&r.stdout).contains("gizli: YOK"));
    // ortam gizlisi
    let p = sb
        .cmd(&py_cops())
        .args(args)
        .env("CLAUDEOPS_FRONT_SECRET", "e")
        .output()
        .unwrap();
    let r = sb
        .cmd(&bin())
        .args(args)
        .env("CLAUDEOPS_FRONT_SECRET", "e")
        .output()
        .unwrap();
    same(&p, &r, "ortam gizlisi");
}

#[test]
fn parity_front_on_plans() {
    let sb = Sandbox::new();
    let (_l, busy, free) = ports();
    // birim yok, ikili yok: iki engel
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &free,
        ],
    );
    same(&p, &r, "engelli plan");
    assert_eq!(r.status.code(), Some(1));
    // birim ve ikili var: plan (DIST_DIR iki tarafta aynı depodan)
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &free,
        ],
    );
    same(&p, &r, "temiz plan");
    assert_eq!(r.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&r.stdout).contains("/py/webui/dist --state-dir "));
    // iç port dolu, drop-in yok
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &busy,
        ],
    );
    same(&p, &r, "iç port dolu");
    // off planı
    let (p, r) = both(&sb, &["front", "off"]);
    same(&p, &r, "off planı");
    assert!(!sb.sc_log().exists(), "plan systemctl çağırmaz");
    assert!(
        !sb.state().join("front.secret").exists(),
        "plan gizli üretmez"
    );
}

#[test]
fn fix_b_diverges_from_python_on_foreign_internal_port() {
    // Python: drop-in varken dolu iç port engel değil (yeniden uygulama); Rust: dinleyen web birimi değilse engel.
    let sb = Sandbox::new();
    let (_l, busy, _) = ports();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    std::fs::create_dir_all(sb.unit_dir().join("claudeops-web.service.d")).unwrap();
    std::fs::write(
        sb.unit_dir().join("claudeops-web.service.d/front.conf"),
        "x",
    )
    .unwrap();
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &busy,
        ],
    );
    assert_eq!(
        p.status.code(),
        Some(0),
        "Python yabancı portu kabul ediyor"
    );
    assert_eq!(r.status.code(), Some(1));
    let out = String::from_utf8_lossy(&r.stdout);
    assert!(
        out.contains(&format!("iç port başka bir süreçte: {busy}")),
        "{out}"
    );
    assert!(
        out.contains(&format!("pid {}", std::process::id())),
        "{out}"
    );
}

#[test]
fn parity_delegated_commands_and_argparse_errors() {
    let sb = Sandbox::new();
    for args in [
        &["yok-boyle-komut"][..],
        &["--version"],
        &["front"],
        &["front", "on", "--apply=1"],
        &["front", "-h"],
        &["front", "bogus"],
        &["front", "on", "off"],
        &["front", "on", "--zz"],
        &["front", "on", "--bin"],
        &["list", "--help"],
        &["self-test-yok"],
    ] {
        let (p, r) = both(&sb, args);
        same(&p, &r, &format!("{args:?}"));
    }
    // UTF-8 olmayan argüman aynen geçer (Python ne yapıyorsa o)
    use std::os::unix::ffi::OsStrExt;
    let bad = std::ffi::OsStr::from_bytes(b"/yok/\xff");
    let p = sb
        .cmd(&py_cops())
        .args([
            "front",
            "status",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            "127.0.0.1:1",
            "--bin",
        ])
        .arg(bad)
        .output()
        .unwrap();
    let r = sb
        .cmd(&bin())
        .args([
            "front",
            "status",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            "127.0.0.1:1",
            "--bin",
        ])
        .arg(bad)
        .output()
        .unwrap();
    same(&p, &r, "UTF-8 olmayan argv");
}

#[test]
fn parity_self_with_bash_claudeops() {
    // Python CLI'da `self` yok; karşılığı bash `./claudeops self`. bash betiği /tmp/claudeops'u `mkdir -p` eder: dizin
    // yoksa test onu oluşturmamak için atlanır.
    if !std::path::Path::new("/tmp/claudeops").is_dir() {
        eprintln!("atlandı: /tmp/claudeops yok");
        return;
    }
    let sb = Sandbox::new();
    let sess = sb.home().join(".claude/sessions");
    std::fs::create_dir_all(&sess).unwrap();
    let pid = std::process::id();
    std::fs::write(
        sess.join(format!("{pid}.json")),
        format!(r#"{{"pid": {pid}, "sessionId": "SID-1", "cwd": "/w d", "status": "idle", "bridgeSessionId": "br", "name": "ad"}}"#),
    )
    .unwrap();
    let claudeops = repo().join("claudeops");
    let run = |prog: &std::path::Path, sid: Option<&str>| {
        let mut c = sb.cmd(prog);
        c.arg("self");
        if let Some(s) = sid {
            c.env("CLAUDE_CODE_SESSION_ID", s);
        }
        c.output().unwrap()
    };
    let (b, r) = (run(&claudeops, Some("SID-1")), run(&bin(), Some("SID-1")));
    assert_eq!(
        (b.status.code(), &b.stdout),
        (r.status.code(), &r.stdout),
        "eşleşen oturum"
    );
    assert!(String::from_utf8_lossy(&r.stdout).contains("bridge-url:  https://claude.ai/code/br"));
    // eşleşme yok: ata zinciri (bu test bir claude altında koşuyorsa onun kaydı sahte HOME'da yok; iki taraf da 1)
    let (b, r) = (run(&claudeops, None), run(&bin(), None));
    assert_eq!(
        (b.status.code(), &b.stdout),
        (r.status.code(), &r.stdout),
        "ata zinciri"
    );
}
