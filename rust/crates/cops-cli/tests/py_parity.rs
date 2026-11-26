//! Python ile PARİTE: aynı girdiyle `py/cops` (Python) ve `cops-rs` koşar; stdout, stderr, çıkış kodu karşılaştırılır. Salt
//! okuma yolları (status, planlar, devredilen komutlar, self) ve "Python hatası?" 1-8 düzeltmelerinden sonra engel ve geri alma
//! yolları. `--apply` yalnız yalıtık HOME/CLAUDEOPS_DIR ve PATH başındaki sahte `systemctl` ile; portlar testin kendi açtığı
//! loopback dinleyicileridir (canlı 8765/28765'e bağlanılmaz).

mod common;
use common::*;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

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
fn parity_bad_addresses_are_blockers_on_both_sides() {
    // "Python hatası?" 1 düzeltildi: iki taraf aynı engel/aynı metin; status rc 1.
    let sb = Sandbox::new();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    let (p, r) = both(
        &sb,
        &[
            "front",
            "status",
            "--listen",
            "[::1]:1",
            "--internal",
            "28765",
        ],
    );
    same(&p, &r, "status geçersiz adres");
    assert_eq!(r.status.code(), Some(1));
    for (listen, internal) in [
        ("127.0.0.1:1", "28765"),
        ("127.0.0.1:1", "127.0.0.1:abc"),
        ("127.0.0.1:1", "[::1]:28765"),
        ("127.0.0.1:1", "127.0.0.1:0"),
        ("127.0.0.1:1", "localhost:28765"),
        ("127.0.0.1:1", "127.0.0.1:８７"),
        ("8765", "127.0.0.1:1"),
        ("127.0.0.1:1", "127.0.0.1:1"),
    ] {
        let (p, r) = both(
            &sb,
            &[
                "front",
                "on",
                "--apply",
                "--listen",
                listen,
                "--internal",
                internal,
            ],
        );
        same(&p, &r, &format!("{listen} / {internal}"));
    }
    assert!(!sb.sc_log().exists(), "engel systemctl çağırmaz");
    assert!(!sb.state().join("front.secret").exists());
    // IPv6 dış adres geçerli (plan)
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--listen",
            "[::1]:1",
            "--internal",
            "127.0.0.1:2",
        ],
    );
    same(&p, &r, "IPv6 dış adres planı");
    assert_eq!(r.status.code(), Some(0));
}

#[test]
fn parity_foreign_internal_port_blocks_on_both_sides() {
    // "Python hatası?" 2 düzeltildi: drop-in varken iç portu yabancı süreç (burada test süreci) tutuyorsa iki taraf da engel.
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
            "--apply",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            &busy,
        ],
    );
    same(&p, &r, "yabancı iç port");
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
    assert!(!sb.sc_log().exists(), "engel systemctl çağırmaz");
}

#[test]
fn parity_relative_or_non_executable_bin_is_a_blocker() {
    // "Python hatası?" 5 düzeltildi: göreli `--bin` ve çalıştırılamaz ikili iki tarafta aynı engel.
    let sb = Sandbox::new();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    let noexec = sb.state().join("bin/copsd");
    std::fs::create_dir_all(noexec.parent().unwrap()).unwrap();
    std::fs::write(&noexec, "").unwrap();
    for b in ["yok-rel-copsd", noexec.to_str().unwrap()] {
        let (p, r) = both(
            &sb,
            &[
                "front",
                "on",
                "--apply",
                "--listen",
                "127.0.0.1:1",
                "--internal",
                "127.0.0.1:2",
                "--bin",
                b,
            ],
        );
        same(&p, &r, b);
        assert_eq!(r.status.code(), Some(1), "{b}");
    }
    assert!(!sb.sc_log().exists());
}

#[test]
fn parity_control_characters_in_bin_block() {
    // "Python hatası?" 6 düzeltildi: denetim karakterli yol iki tarafta aynı engel (tırnaklama: birim testleri).
    let sb = Sandbox::new();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    let evil = sb.state().join("a\nExecStartPre=evil");
    sb.exe(&evil);
    let (p, r) = both(
        &sb,
        &[
            "front",
            "on",
            "--apply",
            "--listen",
            "127.0.0.1:1",
            "--internal",
            "127.0.0.1:2",
            "--bin",
            evil.to_str().unwrap(),
        ],
    );
    same(&p, &r, "denetim karakteri");
    assert_eq!(r.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&r.stdout).contains("denetim karakteri"));
    assert!(!sb.sc_log().exists());
}

#[test]
fn parity_relative_state_dir_is_refused() {
    // "Python hatası?" 8 düzeltildi: göreli CLAUDEOPS_DIR iki tarafta aynı açık hata (Rust önekli), hiçbir şey yazılmaz.
    let sb = Sandbox::new();
    for args in [&["front", "status"][..], &["front", "on", "--apply"]] {
        let run = |prog: &Path| {
            sb.cmd(prog)
                .env("CLAUDEOPS_DIR", "goreli-durum")
                .args(args)
                .output()
                .unwrap()
        };
        let (p, r) = (run(&py_cops()), run(&bin()));
        assert_eq!(p.status.code(), Some(1), "{args:?}");
        assert_eq!(r.status.code(), Some(1), "{args:?}");
        assert_eq!(p.stdout, r.stdout);
        let pe = String::from_utf8_lossy(&p.stderr);
        assert_eq!(pe, "CLAUDEOPS_DIR göreli (goreli-durum): mutlak yol verin\n");
        assert_eq!(String::from_utf8_lossy(&r.stderr), format!("cops-rs: {pe}"));
    }
    assert!(!sb.t.path().join("goreli-durum").exists());
    assert!(!repo().join("py/goreli-durum").exists());
    assert!(!sb.sc_log().exists());
}

#[test]
fn parity_apply_rollback_on_systemctl_failure() {
    // "Python hatası?" 3 düzeltildi: `on`/`off --apply` yarıda kalınca iki taraf aynı geri almayı yapar (sahte systemctl,
    // yalıtık HOME; canlı porta bağlanılmaz: web birimi testin boş portunu söyler). Aynı sandbox sırayla: önce Python,
    // sonra Rust; her koşu öncesi birim dosyaları ve systemctl günlüğü sıfırlanır.
    let sb = Sandbox::new();
    let (_l, _busy, free) = ports();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    let front = sb.unit_dir().join("claudeops-front.service");
    let dropin = sb.unit_dir().join("claudeops-web.service.d/front.conf");
    let run = |prog: &Path, args: &[&str], fail: &str, prepare: &dyn Fn()| {
        let _ = std::fs::remove_file(sb.sc_log());
        prepare();
        let o = sb
            .cmd(prog)
            .args(args)
            .env("FAKE_SC_FAIL", fail)
            .output()
            .unwrap();
        let log = std::fs::read_to_string(sb.sc_log()).unwrap_or_default();
        (o, log)
    };
    let on = [
        "front",
        "on",
        "--apply",
        "--listen",
        "127.0.0.1:1",
        "--internal",
        free.as_str(),
    ];
    let none = || {};
    let (p, plog) = run(&py_cops(), &on, "restart", &none);
    assert!(!front.exists() && !dropin.exists(), "Python geri aldı");
    let (r, rlog) = run(&bin(), &on, "restart", &none);
    same(&p, &r, "on geri alma");
    assert_eq!(plog, rlog, "on systemctl sırası");
    assert_eq!(r.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&r.stdout).contains("GERİ ALMA BAŞARISIZ"));
    // off: ön kapı birimi ve drop-in var; web restart başarısız -> drop-in geri, web restart (yine başarısız). Web birimi
    // boş portu söyler (`off` web'i kendi adresinde bekler; canlı 8765'e bakılmasın).
    std::fs::write(
        sb.unit_dir().join("claudeops-web.service"),
        format!(
            "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web --port {}'\n",
            free.rsplit(':').next().unwrap()
        ),
    )
    .unwrap();
    let prepare = || {
        std::fs::write(&front, "ExecStart=/x/copsd --listen 127.0.0.1:1 --upstream y\n").unwrap();
        std::fs::create_dir_all(dropin.parent().unwrap()).unwrap();
        std::fs::write(&dropin, "eski drop-in\n").unwrap();
    };
    let off = ["front", "off", "--apply"];
    let (p, plog) = run(&py_cops(), &off, "restart", &prepare);
    assert_eq!(std::fs::read_to_string(&dropin).unwrap(), "eski drop-in\n");
    let (r, rlog) = run(&bin(), &off, "restart", &prepare);
    same(&p, &r, "off geri alma");
    assert_eq!(plog, rlog, "off systemctl sırası");
    assert_eq!(r.status.code(), Some(1));
    // off: disable başarısız (birim var) -> hiçbir şey değişmez
    let (p, plog) = run(&py_cops(), &off, "disable", &prepare);
    let (r, rlog) = run(&bin(), &off, "disable", &prepare);
    same(&p, &r, "off disable hatası");
    assert_eq!(plog, rlog);
    assert!(String::from_utf8_lossy(&r.stdout).contains("neden: çıkış 1"));
    assert_eq!(std::fs::read_to_string(&dropin).unwrap(), "eski drop-in\n");
}

#[test]
fn parity_on_restarts_running_front_then_rolls_back_unverified() {
    // "Python hatası?" 4 düzeltildi: ön kapı çalışıyorsa (`FAKE_SC_STATE=0`) `enable --now`dan sonra `restart` (yeni birim
    // uygulansın). Sahte ortamda ön kapı dinlemez: iki taraf 15 sn bekler, aynı doğrulama hatası ve aynı geri alma.
    let sb = Sandbox::new();
    let (_l, _busy, free) = ports();
    std::fs::write(sb.unit_dir().join("claudeops-web.service"), LIVE).unwrap();
    sb.exe(&sb.state().join("bin/copsd"));
    let args = [
        "front",
        "on",
        "--apply",
        "--listen",
        "127.0.0.1:1",
        "--internal",
        free.as_str(),
    ];
    let run = |prog: &Path| {
        let _ = std::fs::remove_file(sb.sc_log());
        let o = sb
            .cmd(prog)
            .args(args)
            .env("FAKE_SC_STATE", "0")
            .output()
            .unwrap();
        (o, std::fs::read_to_string(sb.sc_log()).unwrap())
    };
    let (p, plog) = run(&py_cops());
    let (r, rlog) = run(&bin());
    same(&p, &r, "çalışan ön kapı");
    assert_eq!(plog, rlog);
    assert_eq!(
        rlog,
        "--user is-active --quiet claudeops-front.service\n--user is-enabled --quiet claudeops-front.service\n\
         --user daemon-reload\n--user restart claudeops-web.service\n--user enable --now claudeops-front.service\n\
         --user restart claudeops-front.service\n--user daemon-reload\n--user restart claudeops-web.service\n\
         --user restart claudeops-front.service\n"
    );
    assert!(String::from_utf8_lossy(&r.stdout).contains("HATA: ön kapı 127.0.0.1:1 üzerinde dinlemiyor"));
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

#[test]
fn secret_lock_contract_with_python() {
    // Ortak sözleşme (ders H2: iki dilli yazar): aynı kilit dosyası, aynı dosya, biri ötekinin ürettiğini okur.
    use cops_cli::front::secret::{ensure_secret_file, read_secret};
    use std::io::{BufRead, BufReader};
    use std::time::Duration;
    let sb = Sandbox::new();
    let state = sb.state();
    let sds = state.to_str().unwrap();
    let sec = state.join("front.secret");
    let py = |code: &str| {
        let o = sb
            .cmd(std::path::Path::new("/usr/bin/python3"))
            .arg("-c")
            .arg(format!(
                "import sys; sys.path.insert(0, {:?}); from claudeops import front\n{code}",
                repo().join("py").display()
            ))
            .output()
            .unwrap();
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        String::from_utf8(o.stdout).unwrap().trim().to_string()
    };
    // 1) Python kilidi tutarken Rust bekler, süre dolunca hata verir ve dosya yazmaz.
    let mut holder = sb
        .cmd(std::path::Path::new("/usr/bin/python3"))
        .arg("-c")
        .arg(format!(
            "import fcntl, os, sys, time\nfd = os.open({:?}, os.O_WRONLY | os.O_CREAT, 0o600)\nfcntl.flock(fd, fcntl.LOCK_EX)\nprint('kilitli', flush=True)\nsys.stdin.read()",
            format!("{}.lock", sec.display())
        ))
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    BufReader::new(holder.stdout.as_mut().unwrap())
        .read_line(&mut line)
        .unwrap();
    assert_eq!(line.trim(), "kilitli");
    let e = ensure_secret_file(sds, Duration::from_millis(300)).unwrap_err();
    assert_eq!(e.kind(), std::io::ErrorKind::TimedOut);
    assert!(!sec.exists());
    drop(holder.stdin.take());
    holder.wait().unwrap();
    // 2) Rust üretir, Python aynı değeri okur ve yeniden üretmez.
    let v = ensure_secret_file(sds, Duration::from_secs(5)).unwrap();
    assert_eq!(py("print(front.read_secret())"), v);
    assert_eq!(py("print(front.ensure_secret())"), v);
    // 3) İzin gevşemiş (sızmış): Python yeniden üretir, Rust onu okur ve korur.
    std::fs::set_permissions(&sec, std::fs::Permissions::from_mode(0o644)).unwrap();
    let pv = py("print(front.ensure_secret())");
    assert_ne!(pv, v);
    assert_eq!(read_secret(None, &sec), pv);
    assert_eq!(ensure_secret_file(sds, Duration::from_secs(5)).unwrap(), pv);
    assert_eq!(
        std::fs::metadata(&sec).unwrap().permissions().mode() & 0o777,
        0o600
    );
    // 4) "Python hatası?" 7 düzeltildi: ortam gizlisi iki tarafta da dosya üretimini engellemez.
    std::fs::remove_file(&sec).unwrap();
    let o = sb
        .cmd(std::path::Path::new("/usr/bin/python3"))
        .env("CLAUDEOPS_FRONT_SECRET", "ortam")
        .arg("-c")
        .arg(format!(
            "import sys; sys.path.insert(0, {:?}); from claudeops import front\nprint(front.ensure_secret())",
            repo().join("py").display()
        ))
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let pv = String::from_utf8(o.stdout).unwrap().trim().to_string();
    assert_eq!(pv.len(), 64);
    assert_eq!(read_secret(None, &sec), pv);
}

#[test]
fn default_addresses_match_python_front_cmd() {
    let src =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../py/claudeops/commands/front_cmd.py");
    let src = std::fs::read_to_string(src).unwrap();
    for (name, value) in [
        ("DEFAULT_LISTEN", cops_cli::front::DEFAULT_LISTEN),
        ("DEFAULT_INTERNAL", cops_cli::front::DEFAULT_INTERNAL),
    ] {
        let line = format!("{name} = \"{value}\"");
        assert!(src.lines().any(|l| l == line), "{line}");
    }
}
