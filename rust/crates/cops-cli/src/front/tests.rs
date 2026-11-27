//! `front` birim testleri: Python `tests/test_front_cmd.py` karşılıkları + düzeltmeler (a, b, c). Gerçek systemctl ve gerçek
//! birim dizini HİÇ kullanılmaz: [`World`] sahte systemctl + sahte port durumu, yollar geçici dizinde.

use super::*;
use crate::argp::{Action, FrontArgs};
use net::PortOwner;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use systemctl::UnitPaths;

const LIVE: &str = "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web'\n";
const NEW: &str = "[Service]\nExecStart=/bin/bash -ic 'exec /usr/bin/python3 -m claudeops web'\n";

/// Sahte dünya: hangi port kimde, systemctl çağrıları, hangi komut kaç dönecek.
#[derive(Default)]
struct World {
    owners: HashMap<SocketAddr, PortOwner>,
    calls: Vec<String>,
    /// bir kez başarısız olacak komutlar
    fail: HashMap<String, i32>,
    /// her seferinde başarısız olacak komutlar
    fail_always: HashMap<String, i32>,
    /// systemctl komutu -> (adres, yeni sahip) etkileri
    effects: Vec<(String, SocketAddr, PortOwner)>,
    /// `is-active` / `is-enabled` cevapları (sorgular `calls`a yazılmaz)
    front_active: bool,
    front_enabled: bool,
    /// durum sorgusu çalıştırılamasın
    query_err: bool,
    /// bu adres ilk sorgudan itibaren verilen süre boyunca dinlemiyor görünsün (yavaş web açılışı)
    slow: Option<(SocketAddr, Duration)>,
    slow_since: std::cell::Cell<Option<std::time::Instant>>,
    units: UnitPaths,
    units_err: Option<String>,
}

#[derive(Clone, Default)]
struct Fake(Rc<RefCell<World>>);

impl Net for Fake {
    fn busy(&self, a: SocketAddr) -> bool {
        !matches!(
            self.0.borrow().owners.get(&a),
            None | Some(PortOwner::NoListener)
        )
    }
    fn owner(&self, a: SocketAddr) -> PortOwner {
        let w = self.0.borrow();
        if let Some((_, d)) = w.slow.filter(|(s, _)| *s == a) {
            let now = std::time::Instant::now();
            let since = w.slow_since.get().unwrap_or(now);
            w.slow_since.set(Some(since));
            if now.duration_since(since) < d {
                return PortOwner::NoListener;
            }
        }
        w.owners.get(&a).cloned().unwrap_or(PortOwner::NoListener)
    }
}

impl Systemctl for Fake {
    fn unit_paths(&mut self) -> Result<UnitPaths, String> {
        let w = self.0.borrow();
        match &w.units_err {
            Some(e) => Err(e.clone()),
            None => Ok(w.units.clone()),
        }
    }
    fn run(&mut self, args: &[&str]) -> Result<i32, String> {
        let cmd = args.join(" ");
        let mut w = self.0.borrow_mut();
        if let [q @ ("is-active" | "is-enabled"), "--quiet", FRONT_UNIT_NAME] = args {
            if w.query_err {
                return Err("systemctl başlatılamadı".into());
            }
            let yes = if *q == "is-active" {
                w.front_active
            } else {
                w.front_enabled
            };
            return Ok(if yes { 0 } else { 3 });
        }
        w.calls.push(cmd.clone());
        if let Some(rc) = w
            .fail
            .remove(&cmd)
            .or_else(|| w.fail_always.get(&cmd).copied())
        {
            return Ok(rc);
        }
        let eff: Vec<_> = w
            .effects
            .iter()
            .filter(|(c, ..)| *c == cmd)
            .cloned()
            .collect();
        for (_, a, o) in eff {
            w.owners.insert(a, o);
        }
        Ok(0)
    }
}

fn unit(name: &str) -> PortOwner {
    PortOwner::Holders(vec![(10, Some(name.into()))])
}

struct Env {
    _t: tempfile::TempDir,
    root: PathBuf,
    paths: Paths,
    bin: String,
    w: Fake,
}

use std::path::PathBuf;

fn env() -> Env {
    let t = tempfile::tempdir().unwrap();
    let root = t.path().to_path_buf();
    let r = Roots {
        home: root.join("home").to_str().unwrap().into(),
        claudeops_dir: root.join("durum dizini %h $X").to_str().unwrap().into(),
    };
    let paths = Paths::new(&r, Some("/repo/py/webui/dist".into()));
    std::fs::create_dir_all(&paths.unit_dir).unwrap();
    std::fs::write(&paths.web_unit, LIVE).unwrap();
    let bin = root.join("copsd");
    std::fs::write(&bin, "#!/bin/sh\n").unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755)).unwrap();
    Env {
        _t: t,
        root,
        paths,
        bin: bin.to_str().unwrap().into(),
        w: Fake::default(),
    }
}

const L: &str = "127.0.0.1:8765";
const I: &str = "127.0.0.1:28765";

fn la() -> SocketAddr {
    L.parse().unwrap()
}
fn ia() -> SocketAddr {
    I.parse().unwrap()
}

fn fast() -> Timing {
    Timing {
        front_up: Duration::from_millis(50),
        port_free: Duration::from_millis(50),
        web_up: Duration::from_millis(50),
        poll: Duration::from_millis(5),
        lock: Duration::from_secs(5),
    }
}

impl Env {
    fn run(&self, action: Action, apply: bool, listen: &str, internal: &str) -> (i32, String) {
        self.run_timed(action, apply, listen, internal, fast())
    }

    fn run_timed(
        &self,
        action: Action,
        apply: bool,
        listen: &str,
        internal: &str,
        timing: Timing,
    ) -> (i32, String) {
        let mut sc = self.w.clone();
        let mut out = Vec::new();
        let rc = {
            let mut ctx = Ctx {
                paths: self.paths.clone(),
                env_secret: None,
                net: &self.w,
                sc: &mut sc,
                out: &mut out,
                timing,
            };
            super::run(
                &mut ctx,
                &FrontArgs {
                    action,
                    apply,
                    listen: Some(listen.into()),
                    internal: Some(internal.into()),
                    bin: Some(self.bin.clone()),
                },
            )
        };
        (rc, String::from_utf8(out).unwrap())
    }

    fn calls(&self) -> Vec<String> {
        self.w.0.borrow().calls.clone()
    }

    /// Canlıdaki "kapalı" durum: web dış portta, ön kapı yok.
    fn web_outside(&self) {
        let mut w = self.w.0.borrow_mut();
        w.owners.insert(la(), unit(WEB_UNIT_NAME));
        w.effects = vec![
            (
                "restart claudeops-web.service".into(),
                la(),
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                ia(),
                unit(WEB_UNIT_NAME),
            ),
            (
                "enable --now claudeops-front.service".into(),
                la(),
                unit(FRONT_UNIT_NAME),
            ),
        ];
    }

    /// "açık" durum: ön kapı dışta, web içte, drop-in yazılı.
    fn front_on(&self) {
        std::fs::create_dir_all(Path::new(&self.paths.dropin).parent().unwrap()).unwrap();
        std::fs::write(&self.paths.dropin, "eski drop-in\n").unwrap();
        std::fs::write(
            &self.paths.front_unit,
            "eski birim\nExecStart=/x/copsd --listen 127.0.0.1:8765 --upstream y\n",
        )
        .unwrap();
        let mut w = self.w.0.borrow_mut();
        w.front_active = true;
        w.front_enabled = true;
        w.owners.insert(la(), unit(FRONT_UNIT_NAME));
        w.owners.insert(ia(), unit(WEB_UNIT_NAME));
        w.effects = vec![
            (
                "disable --now claudeops-front.service".into(),
                la(),
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                ia(),
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                la(),
                unit(WEB_UNIT_NAME),
            ),
            (
                "enable --now claudeops-front.service".into(),
                la(),
                unit(FRONT_UNIT_NAME),
            ),
        ];
    }
}

// ---- Python P9SlowWebAndSymlinkUnits karşılıkları ----

#[test]
fn slow_web_restart_is_waited_with_web_up() {
    let e = env();
    e.web_outside();
    e.w.0.borrow_mut().slow = Some((ia(), Duration::from_millis(200)));
    let timing = Timing {
        web_up: Duration::from_secs(3),
        ..fast()
    };
    let (rc, out) = e.run_timed(Action::On, true, L, I, timing);
    assert_eq!(rc, 0, "{out}");
}

fn link(e: &Env, p: &str, name: &str) -> PathBuf {
    let p = Path::new(p);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    let target = e.root.join(name);
    let body = std::fs::read(p).unwrap_or_else(|_| b"bagli icerik\n".to_vec());
    std::fs::write(&target, body).unwrap();
    let _ = std::fs::remove_file(p);
    std::os::unix::fs::symlink(&target, p).unwrap();
    target
}

#[test]
fn on_refuses_symlinked_unit_files() {
    let e = env();
    for (p, name) in [
        (e.paths.front_unit.clone(), "front-hedef"),
        (e.paths.dropin.clone(), "dropin-hedef"),
    ] {
        let target = link(&e, &p, name);
        let (rc, out) = e.run(Action::On, true, L, I);
        assert_eq!(rc, 1, "{out}");
        assert!(
            out.contains(&format!("birim dosyası sembolik bağ: {p} (")),
            "{out}"
        );
        assert_eq!(std::fs::read_link(&p).unwrap(), target);
        assert_eq!(std::fs::read(&target).unwrap(), b"bagli icerik\n");
        assert!(e.calls().is_empty());
        std::fs::remove_file(&p).unwrap();
    }
}

#[test]
fn off_rollback_restores_symlink() {
    let e = env();
    e.front_on();
    let target = link(&e, &e.paths.dropin, "dropin-hedef");
    e.w.0
        .borrow_mut()
        .fail_always
        .insert("restart claudeops-web.service".into(), 3);
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 3, "{out}");
    assert_eq!(std::fs::read_link(&e.paths.dropin).unwrap(), target);
    assert_eq!(std::fs::read(&target).unwrap(), "eski drop-in\n".as_bytes());
    assert!(
        out.contains(&format!(
            "geri yaz: {} (önceki sembolik bağ): tamam",
            e.paths.dropin
        )),
        "{out}"
    );
}

// ---- Python test_front_cmd.py karşılıkları ----

#[test]
fn execstart_patch() {
    let es = web_execstart(LIVE).unwrap();
    assert_eq!(
        with_internal_port(&es, "127.0.0.1:28765").unwrap(),
        "/bin/bash -ic '/usr/bin/python3 -m claudeops web --host 127.0.0.1 --port 28765'"
    );
    assert!(
        with_internal_port(&web_execstart(NEW).unwrap(), "127.0.0.1:1")
            .unwrap()
            .contains("exec /usr/bin/python3")
    );
    assert_eq!(with_internal_port("/usr/bin/other", "127.0.0.1:1"), None);
    assert_eq!(
        with_internal_port("/x web", "1.2.3.4:5").unwrap(),
        "/x web --host 1.2.3.4 --port 5"
    );
    // ilk ExecStart satırı, `\r` strip ile atılır; yorum ve `ExecStartPre` eşleşmez
    assert_eq!(
        web_execstart("a\nExecStart= y \r\nExecStart=z").as_deref(),
        Some("y")
    );
    assert_eq!(
        web_execstart("#ExecStart=a\n; ExecStart=b\nExecStartPre=c\n"),
        None
    );
    // systemd satır başındaki ve `=` çevresindeki boşluğu yok sayar
    for l in ["ExecStart =y", "  ExecStart=y", "\tExecStart \t= y"] {
        assert_eq!(web_execstart(l).as_deref(), Some("y"), "{l:?}");
    }
    assert_eq!(web_execstart("x").as_deref(), None);
}

#[test]
fn dropin_resets_execstart() {
    let d = dropin_text("X");
    assert!(d.find("ExecStart=\n").unwrap() < d.find("ExecStart=X").unwrap());
    assert_eq!(d, "[Service]\nExecStart=\nExecStart=X\n");
}

#[test]
fn plan_blockers() {
    let e = env();
    let (rc, out) = {
        let mut e2 = env();
        e2.bin = "/yok/copsd".into();
        e2.run(Action::On, false, L, I)
    };
    assert_eq!(rc, 1);
    assert!(out.contains("ikili yok: /yok/copsd"), "{out}");
    assert!(out.contains("cargo build --release -p copsd"), "{out}");
    assert!(out.matches("\n  ").count() >= 5);
    std::fs::write(&e.paths.web_unit, "[Service]\nExecStart=/x\n").unwrap();
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 1);
    assert!(out.contains("tanınmadı"), "{out}");
}

#[test]
fn unit_template_has_no_secret_and_passes_state_dir_quoted() {
    let e = env();
    let u = unit_text(&e.paths, "/b/copsd", "a:1", "b:2");
    assert!(u.contains("--upstream b:2 --dist /repo/py/webui/dist --state-dir "));
    assert!(!u.to_uppercase().contains("SECRET"));
    let line = u.lines().find(|l| l.starts_with("ExecStart=")).unwrap();
    let want = format!(" --state-dir \"{}/durum dizini %%h $$X\"", e.root.display());
    assert!(line.ends_with(&want), "{line}");
}

#[test]
fn applied_unit_passes_the_secret_state_dir() {
    let e = env();
    e.web_outside();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.ends_with("açıldı: dış 127.0.0.1:8765 -> iç 127.0.0.1:28765\n"));
    let sp = Path::new(&e.paths.secret_path);
    assert_eq!(sp.parent().unwrap(), Path::new(&e.paths.claudeops_dir));
    assert!(sp.is_file());
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "[Service]\nExecStart=\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web --host 127.0.0.1 --port 28765'\n"
    );
    assert_eq!(
        e.calls(),
        [
            "daemon-reload",
            "restart claudeops-web.service",
            "enable --now claudeops-front.service"
        ]
    );
}

#[test]
fn plan_only_changes_nothing() {
    let e = env();
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 0);
    assert!(out.starts_with("PLAN:\n  gizli: "));
    assert!(out.ends_with("(plan; uygulamak için --apply)\n"));
    assert!(e.calls().is_empty());
    assert!(!Path::new(&e.paths.front_unit).exists());
    assert!(!Path::new(&e.paths.secret_path).exists());
    let (rc, out) = e.run(Action::Off, false, L, I);
    assert_eq!(rc, 0);
    assert!(out.contains("sil: ") && e.calls().is_empty());
}

// ---- (a) adres ayrıştırma ----

#[test]
fn fix_a_bad_internal_addresses_are_blockers_not_crashes() {
    for bad in [
        "28765",
        "127.0.0.1:abc",
        "127.0.0.1:0",
        "127.0.0.1:70000",
        "[::1]:28765",
        "localhost:28765",
        "",
    ] {
        let e = env();
        let (rc, out) = e.run(Action::On, true, L, bad);
        assert_eq!(rc, 1, "{bad}: {out}");
        assert!(out.contains("geçersiz --internal"), "{bad}: {out}");
        assert!(e.calls().is_empty(), "{bad}");
        assert!(
            !Path::new(&e.paths.front_unit).exists(),
            "{bad}: birim yazılmamalı"
        );
    }
}

#[test]
fn fix_a_bad_listen_is_a_blocker_and_ipv6_listen_is_fine() {
    let e = env();
    let (rc, out) = e.run(Action::On, false, "8765", I);
    assert_eq!(rc, 1);
    assert!(out.contains("geçersiz --listen"), "{out}");
    let (rc, out) = e.run(Action::On, false, "[::1]:8765", I);
    assert_eq!(rc, 0, "{out}");
    let (rc, out) = e.run(Action::On, false, I, I);
    assert_eq!(rc, 1);
    assert!(out.contains("çakışıyor"), "{out}");
}

#[test]
fn fix_a_status_reports_bad_address_without_crashing() {
    let e = env();
    let (rc, out) = e.run(Action::Status, false, "[::1]:8765", "28765");
    assert_eq!(rc, 1);
    assert!(out.contains("port [::1]:8765: boş\n"), "{out}");
    assert!(out.contains("port 28765: geçersiz adres"), "{out}");
}

// ---- (b) yabancı port ----

#[test]
fn fix_b_foreign_process_on_internal_port_blocks_even_with_dropin() {
    let e = env();
    e.front_on();
    e.w.0.borrow_mut().owners.insert(
        "127.0.0.1:29999".parse().unwrap(),
        PortOwner::Holders(vec![(99, None)]),
    );
    let (rc, out) = e.run(Action::On, true, L, "127.0.0.1:29999");
    assert_eq!(rc, 1, "{out}");
    assert!(
        out.contains("iç port başka bir süreçte: 127.0.0.1:29999 (pid 99 (birimsiz))"),
        "{out}"
    );
    assert!(e.calls().is_empty());
    for o in [
        PortOwner::OtherUser(5),
        PortOwner::Unknown,
        unit("other.service"),
    ] {
        e.w.0.borrow_mut().owners.insert(ia(), o.clone());
        let (rc, out) = e.run(Action::On, true, L, I);
        assert_eq!(rc, 1, "{o:?}");
        assert!(out.contains("başka bir süreçte"), "{out}");
    }
}

#[test]
fn fix_b_our_web_on_internal_port_is_a_reapply() {
    let e = env();
    e.front_on();
    e.w.0.borrow_mut().effects.clear();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert_eq!(
        e.calls(),
        [
            "daemon-reload",
            "enable --now claudeops-front.service",
            "restart claudeops-front.service"
        ]
    );
}

#[test]
fn internal_busy_without_dropin_keeps_python_blocker() {
    let e = env();
    e.w.0.borrow_mut().owners.insert(ia(), unit(WEB_UNIT_NAME));
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 1);
    assert!(
        out.ends_with("ENGEL:\n  iç port dolu: 127.0.0.1:28765\n"),
        "{out}"
    );
}

// ---- (c) geri alma ----

#[test]
fn fix_c_on_rolls_back_at_every_systemctl_step() {
    for (i, step) in [
        "daemon-reload",
        "restart claudeops-web.service",
        "enable --now claudeops-front.service",
    ]
    .iter()
    .enumerate()
    {
        let e = env();
        e.web_outside();
        e.w.0.borrow_mut().fail.insert(step.to_string(), 5);
        let (rc, out) = e.run(Action::On, true, L, I);
        assert_eq!(rc, 1, "{step}: {out}");
        assert!(
            out.contains(&format!("HATA: systemctl --user {step}\n")),
            "{out}"
        );
        assert!(out.contains("geri alındı"), "{step}: {out}");
        assert!(!Path::new(&e.paths.front_unit).exists(), "{step}");
        assert!(!Path::new(&e.paths.dropin).exists(), "{step}");
        let c = e.calls();
        let undo: Vec<&str> = c[i + 1..].iter().map(String::as_str).collect();
        let want: &[&str] = match i {
            0 => &["daemon-reload"],
            1 => &["daemon-reload", "restart claudeops-web.service"],
            _ => &[
                "disable --now claudeops-front.service",
                "daemon-reload",
                "restart claudeops-web.service",
            ],
        };
        assert_eq!(undo, want, "{step}");
    }
}

#[test]
fn fix_c_front_not_listening_is_rolled_back() {
    let e = env();
    e.web_outside();
    // ön kapı başlıyor ama dışarıyı dinlemiyor (ör. web dış portu bırakmadı)
    e.w.0
        .borrow_mut()
        .effects
        .retain(|(c, ..)| c != "enable --now claudeops-front.service");
    e.w.0
        .borrow_mut()
        .effects
        .retain(|(c, a, _)| !(c == "restart claudeops-web.service" && *a == la()));
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1);
    assert!(
        out.contains("HATA: ön kapı 127.0.0.1:8765 üzerinde dinlemiyor"),
        "{out}"
    );
    assert!(out.contains("geri alındı"), "{out}");
    assert_eq!(
        e.calls()[3..],
        [
            "disable --now claudeops-front.service",
            "daemon-reload",
            "restart claudeops-web.service"
        ]
    );
}

#[test]
fn fix_c_reapply_failure_restores_previous_unit_and_restarts_old_front() {
    let e = env();
    e.front_on();
    e.w.0
        .borrow_mut()
        .fail_always
        .insert("restart claudeops-front.service".into(), 1);
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert!(std::fs::read_to_string(&e.paths.front_unit)
        .unwrap()
        .starts_with("eski birim"));
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "eski drop-in\n"
    );
    // geri almada restart yine başarısız: açıkça söylenir
    assert!(
        out.contains("restart claudeops-front.service: HATA (çıkış 1)"),
        "{out}"
    );
    assert!(out.contains("GERİ ALMA BAŞARISIZ"), "{out}");
}

#[test]
fn fix_c_write_failure_restores_files_without_systemctl() {
    let e = env();
    // drop-in dizini yazılamaz (0500): ön kapı birimi yazılır, drop-in yazılamaz
    use std::os::unix::fs::PermissionsExt;
    let dd = Path::new(&e.paths.dropin).parent().unwrap();
    std::fs::create_dir_all(dd).unwrap();
    std::fs::set_permissions(dd, std::fs::Permissions::from_mode(0o500)).unwrap();
    std::fs::write(&e.paths.front_unit, "onceki").unwrap();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1);
    assert!(out.contains("HATA: yazılamadı: "), "{out}");
    assert_eq!(
        std::fs::read_to_string(&e.paths.front_unit).unwrap(),
        "onceki"
    );
    assert!(
        out.contains("geri yaz: ") && out.contains("geri alındı"),
        "{out}"
    );
    assert!(e.calls().is_empty());
    std::fs::set_permissions(dd, std::fs::Permissions::from_mode(0o700)).unwrap();
}

#[test]
fn off_success_sequence_matches_python_and_verifies_web() {
    let e = env();
    e.front_on();
    let (rc, out) = e.run(Action::Off, true, "9.9.9.9:1", I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.ends_with("kapandı\n"));
    assert!(!Path::new(&e.paths.dropin).exists());
    assert_eq!(
        e.calls(),
        [
            "disable --now claudeops-front.service",
            "daemon-reload",
            "restart claudeops-web.service"
        ]
    );
}

#[test]
fn fix_c_off_disable_failure_changes_nothing() {
    let e = env();
    e.front_on();
    e.w.0
        .borrow_mut()
        .fail
        .insert("disable --now claudeops-front.service".into(), 1);
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 1);
    assert!(
        out.contains("HATA: systemctl --user disable --now claudeops-front.service"),
        "{out}"
    );
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "eski drop-in\n"
    );
    assert_eq!(
        e.calls(),
        [
            "disable --now claudeops-front.service",
            "enable --now claudeops-front.service"
        ]
    );
}

#[test]
fn fix_c_off_web_restart_failure_returns_to_front() {
    let e = env();
    e.front_on();
    e.w.0
        .borrow_mut()
        .fail_always
        .insert("restart claudeops-web.service".into(), 3);
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 3, "Python gibi restart'ın kodu");
    assert!(out.contains("HATA: web restart\n"), "{out}");
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "eski drop-in\n"
    );
    let c = e.calls();
    assert_eq!(
        &c[3..],
        [
            "daemon-reload",
            "restart claudeops-web.service",
            "enable --now claudeops-front.service"
        ]
    );
    assert!(
        out.contains("GERİ ALMA BAŞARISIZ"),
        "geri almadaki restart da 3 döndü: {out}"
    );
}

#[test]
fn fix_c_off_web_not_back_outside_is_rolled_back() {
    let e = env();
    e.front_on();
    e.w.0
        .borrow_mut()
        .effects
        .retain(|(c, a, _)| !(c == "restart claudeops-web.service" && *a == la()));
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 1);
    assert!(
        out.contains("HATA: web 127.0.0.1:8765 üzerinde doğrulanamadı"),
        "{out}"
    );
    assert!(out.contains("geri alındı"), "{out}");
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "eski drop-in\n"
    );
}

#[test]
fn fix_c_off_port_not_released_stops_before_touching_web() {
    let e = env();
    e.front_on();
    e.w.0.borrow_mut().effects.clear();
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 1);
    assert!(out.contains("boşalmadı"), "{out}");
    assert!(Path::new(&e.paths.dropin).exists());
    assert_eq!(
        e.calls(),
        [
            "disable --now claudeops-front.service",
            "enable --now claudeops-front.service"
        ]
    );
}

#[test]
fn off_without_front_unit_ignores_disable_error_like_python() {
    let e = env();
    {
        let mut w = e.w.0.borrow_mut();
        w.owners.insert(la(), unit(WEB_UNIT_NAME));
        w.fail
            .insert("disable --now claudeops-front.service".into(), 5);
    }
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.contains("birimi yok; durdurma hatası yok sayıldı"));
}

#[test]
fn control_characters_in_paths_block() {
    let mut e = env();
    let p = e.root.join("a\nExecStartPre=evil");
    std::fs::write(&p, "").unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
    e.bin = p.to_str().unwrap().into();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1);
    assert!(out.contains("denetim karakteri"), "{out}");
}

#[test]
fn bin_and_dist_with_spaces_are_quoted() {
    let mut e = env();
    e.paths.dist = Some("/a b/dist".into());
    let u = unit_text(&e.paths, "/x y/copsd", "a:1", "b:2");
    assert!(
        u.contains(
            "ExecStart=\"/x y/copsd\" --listen a:1 --upstream b:2 --dist \"/a b/dist\" --state-dir"
        ),
        "{u}"
    );
}

#[test]
fn paths_follow_python_pathlib() {
    let r = Roots {
        home: "/".into(),
        claudeops_dir: "/s//x/".into(),
    };
    let p = Paths::new(&r, None);
    assert_eq!(p.unit_dir, "/.config/systemd/user");
    assert_eq!(p.default_bin, "/s/x/bin/copsd");
    assert_eq!(p.secret_path, "/s//x/front.secret");
}

#[test]
fn dist_dir_resolves_from_python_repo() {
    let t = tempfile::tempdir().unwrap();
    let repo = t.path().join("repo");
    std::fs::create_dir_all(repo.join("py/claudeops")).unwrap();
    std::fs::write(repo.join("py/claudeops/paths.py"), "").unwrap();
    let d = dist_dir(&repo.join("py")).unwrap();
    assert_eq!(
        d,
        format!(
            "{}/py/webui/dist",
            std::fs::canonicalize(&repo).unwrap().display()
        )
    );
}

// ---- gözden geçirme düzeltmeleri (rs/cli 2. tur) ----

#[test]
fn fix_c_on_listen_change_failure_restarts_old_front_instead_of_stopping_it() {
    // Ön kapı 8765'te çalışıyor; `--listen` 9000'e değişiyor ve yeni birim dinlemiyor. Eski kod "9000'de ön kapı yoktu"
    // deyip çalışan ön kapıyı `disable --now` ile kapatıyordu.
    let e = env();
    e.front_on();
    e.w.0.borrow_mut().effects.clear();
    let (rc, out) = e.run(Action::On, true, "127.0.0.1:9000", I);
    assert_eq!(rc, 1, "{out}");
    assert!(
        out.contains("ön kapı 127.0.0.1:9000 üzerinde dinlemiyor"),
        "{out}"
    );
    assert!(out.contains("geri alındı"), "{out}");
    assert_eq!(
        e.calls(),
        [
            "daemon-reload",
            "enable --now claudeops-front.service",
            "restart claudeops-front.service",
            "daemon-reload",
            "restart claudeops-front.service"
        ]
    );
    assert!(std::fs::read_to_string(&e.paths.front_unit)
        .unwrap()
        .starts_with("eski birim"));
}

#[test]
fn fix_c_on_rollback_keeps_previous_enablement() {
    // Önceden çalışan ama etkin olmayan ön kapı: geri almada yeniden başlar, `enable --now`un etkinleştirmesi geri alınır.
    let e = env();
    e.front_on();
    {
        let mut w = e.w.0.borrow_mut();
        w.front_enabled = false;
        w.fail.insert("restart claudeops-front.service".into(), 1);
    }
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert_eq!(
        e.calls()[3..],
        [
            "daemon-reload",
            "restart claudeops-front.service",
            "disable claudeops-front.service"
        ]
    );
    // Önceden durmuş ama etkin ön kapı: `disable --now` değil `stop` (etkinlik korunur).
    let e = env();
    e.web_outside();
    {
        let mut w = e.w.0.borrow_mut();
        w.front_enabled = true;
        w.fail
            .insert("enable --now claudeops-front.service".into(), 1);
    }
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert_eq!(
        e.calls()[3..],
        [
            "stop claudeops-front.service",
            "daemon-reload",
            "restart claudeops-web.service"
        ]
    );
}

#[test]
fn on_restarts_an_already_running_front_so_the_new_unit_applies() {
    // drop-in yok (ya da web iç portta değil) ama ön kapı çalışıyor: `enable --now` çalışan birimi yeniden başlatmaz.
    let e = env();
    e.web_outside();
    {
        let mut w = e.w.0.borrow_mut();
        w.front_active = true;
        w.front_enabled = true;
    }
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert_eq!(
        e.calls(),
        [
            "daemon-reload",
            "restart claudeops-web.service",
            "enable --now claudeops-front.service",
            "restart claudeops-front.service"
        ]
    );
}

#[test]
fn fix_c_on_web_not_on_internal_is_rolled_back() {
    let e = env();
    e.web_outside();
    e.w.0
        .borrow_mut()
        .effects
        .retain(|(c, a, _)| !(c == "restart claudeops-web.service" && *a == ia()));
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert!(
        out.contains("HATA: web iç adreste 127.0.0.1:28765 doğrulanamadı"),
        "{out}"
    );
    assert!(out.contains("geri alındı"), "{out}");
    assert!(!Path::new(&e.paths.dropin).exists());
}

#[test]
fn unknown_front_state_changes_nothing() {
    for action in [Action::On, Action::Off] {
        let e = env();
        e.front_on();
        e.w.0.borrow_mut().query_err = true;
        let (rc, out) = e.run(action, true, L, I);
        assert_eq!(rc, 1, "{out}");
        assert!(out.contains("durumu okunamadı"), "{out}");
        assert!(e.calls().is_empty());
        assert_eq!(
            std::fs::read_to_string(&e.paths.dropin).unwrap(),
            "eski drop-in\n"
        );
        assert!(!Path::new(&e.paths.secret_path).exists());
    }
}

#[test]
fn fix_c_off_disable_failure_keeps_stopped_front_stopped() {
    // Birim var ama durmuş ve etkin değil; `disable --now` başarısız: geri alma onu AÇMAZ (eski kod `enable --now` yapardı).
    let e = env();
    e.front_on();
    {
        let mut w = e.w.0.borrow_mut();
        w.front_active = false;
        w.front_enabled = false;
        w.fail
            .insert("disable --now claudeops-front.service".into(), 1);
    }
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert_eq!(e.calls(), ["disable --now claudeops-front.service"]);
    assert!(out.contains("geri alındı"), "{out}");
}

#[test]
fn off_verifies_web_on_its_own_port_when_front_listen_differs() {
    // Ön kapı 9000'de; web drop-in'siz birimiyle 8765'e döner. Doğrulama 9000'de web beklerse hep geri alırdı.
    let e = env();
    e.front_on();
    let alt: SocketAddr = "127.0.0.1:9000".parse().unwrap();
    std::fs::write(
        &e.paths.front_unit,
        "ExecStart=/x/copsd --listen 127.0.0.1:9000 --upstream y\n",
    )
    .unwrap();
    {
        let mut w = e.w.0.borrow_mut();
        w.owners.remove(&la());
        w.owners.insert(alt, unit(FRONT_UNIT_NAME));
        w.effects = vec![
            (
                "disable --now claudeops-front.service".into(),
                alt,
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                la(),
                unit(WEB_UNIT_NAME),
            ),
        ];
    }
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.ends_with("kapandı\n"), "{out}");
}

#[test]
fn web_addr_follows_web_unit_flags() {
    let a = |t: &str| web_addr(t).map(|a| a.to_string());
    assert_eq!(a(LIVE).as_deref(), Some("127.0.0.1:8765"));
    assert_eq!(
        a("ExecStart=/x -m claudeops web --port 9001 --host 0.0.0.0").as_deref(),
        Some("127.0.0.1:9001")
    );
    assert_eq!(
        a("ExecStart=/bin/bash -ic 'python3 -m claudeops web --host=127.0.0.2 --port=9002'")
            .as_deref(),
        Some("127.0.0.2:9002")
    );
    assert_eq!(a("ExecStart=/x web --port abc"), None);
    assert_eq!(a("[Service]\n"), None);
}

#[test]
fn web_addr_resolves_argparse_abbreviations() {
    let a = |t: &str| web_addr(t).map(|a| a.to_string());
    assert_eq!(
        a("ExecStart=/x web --po 9001").as_deref(),
        Some("127.0.0.1:9001")
    );
    assert_eq!(
        a("ExecStart=/x web --por=9002 --ho 127.0.0.3").as_deref(),
        Some("127.0.0.3:9002")
    );
    assert_eq!(
        a("ExecStart=/x web --hos=127.0.0.4").as_deref(),
        Some("127.0.0.4:8765")
    );
    for amb in ["--p 9001", "--p=9001", "--h 127.0.0.3"] {
        assert_eq!(a(&format!("ExecStart=/x web {amb}")), None, "{amb}");
    }
}

#[test]
fn web_addr_last_execstart_wins_and_empty_resets() {
    let over = format!("{LIVE}[Service]\nExecStart=\nExecStart=/x web --port 9003\n");
    assert_eq!(
        web_addr(&over).map(|a| a.to_string()).as_deref(),
        Some("127.0.0.1:9003")
    );
    assert_eq!(web_addr(&format!("{LIVE}[Service]\nExecStart=\n")), None);
}

fn off_with_dropins(files: &[(&str, &[u8])], port: u16) {
    let e = env();
    e.front_on();
    let dir = std::path::Path::new(&e.paths.dropin).parent().unwrap();
    for (name, body) in files {
        std::fs::write(dir.join(name), body).unwrap();
    }
    let alt: SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    {
        let mut w = e.w.0.borrow_mut();
        w.owners.insert(alt, unit(FRONT_UNIT_NAME));
        w.effects = vec![
            (
                "disable --now claudeops-front.service".into(),
                alt,
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                alt,
                unit(WEB_UNIT_NAME),
            ),
        ];
    }
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.ends_with("kapandı\n"), "{out}");
}

#[test]
fn off_follows_overriding_dropins_in_name_order() {
    let ex = |p: u16| format!("[Service]\nExecStart=\nExecStart=/x web --port {p}\n").into_bytes();
    off_with_dropins(
        &[
            ("b.conf", &ex(9005)),
            ("a.conf", &ex(9004)),
            ("z.conf.bak", &ex(9006)),
            ("env.conf", b"[Service]\nEnvironment=A=1\n"),
        ],
        9005,
    );
}

#[test]
fn off_falls_back_on_unreadable_dropin() {
    off_with_dropins(&[("bozuk.conf", b"\xff")], 8765);
}

#[test]
fn relative_bin_is_a_blocker() {
    let mut e = env();
    std::fs::write(e.root.join("rel-copsd"), "").unwrap();
    e.bin = "rel-copsd".into();
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 1);
    assert!(out.contains("ikili yolu mutlak değil: rel-copsd"), "{out}");
}

// ---- Python düzeltmeleriyle (docs/rs-cli.md "Python hatası?" 1-8) eşlenen ek testler ----

#[test]
fn unreadable_web_unit_is_a_blocker() {
    let e = env();
    std::fs::write(&e.paths.web_unit, b"[Service]\nExecStart=\xff web\n").unwrap();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert!(
        out.contains(&format!(
            "ENGEL:\n  claudeops-web.service okunamadı: {}: UTF-8 değil\n",
            e.paths.web_unit
        )),
        "{out}"
    );
    assert!(e.calls().is_empty());
}

#[test]
fn non_executable_bin_is_a_blocker() {
    use std::os::unix::fs::PermissionsExt;
    let e = env();
    std::fs::set_permissions(&e.bin, std::fs::Permissions::from_mode(0o644)).unwrap();
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 1);
    assert!(
        out.contains(&format!("ikili çalıştırılabilir dosya değil: {}\n", e.bin)),
        "{out}"
    );
}

#[test]
fn off_falls_back_to_front_listen_when_web_unit_is_missing() {
    let e = env();
    e.front_on();
    std::fs::remove_file(&e.paths.web_unit).unwrap();
    let alt: SocketAddr = "127.0.0.1:9000".parse().unwrap();
    std::fs::write(
        &e.paths.front_unit,
        "ExecStart=\"/x y/copsd\" --listen 127.0.0.1:9000 --upstream y\n",
    )
    .unwrap();
    {
        let mut w = e.w.0.borrow_mut();
        w.owners.remove(&la());
        w.owners.insert(alt, unit(FRONT_UNIT_NAME));
        w.effects = vec![
            (
                "disable --now claudeops-front.service".into(),
                alt,
                PortOwner::NoListener,
            ),
            (
                "restart claudeops-web.service".into(),
                alt,
                unit(WEB_UNIT_NAME),
            ),
        ];
    }
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert!(out.ends_with("kapandı\n"), "{out}");
}

fn other_dropin(e: &Env, name: &str, body: &[u8]) -> PathBuf {
    let dir = Path::new(&e.paths.dropin).parent().unwrap();
    std::fs::create_dir_all(dir).unwrap();
    let p = dir.join(name);
    std::fs::write(&p, body).unwrap();
    p
}

#[test]
fn on_builds_front_dropin_from_earlier_dropin_override() {
    let e = env();
    e.web_outside();
    other_dropin(
        &e,
        "enterprise.conf",
        b"[Service]\nExecStart=\nExecStart=/opt/py -m claudeops web\n",
    );
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 0, "{out}");
    assert_eq!(
        std::fs::read_to_string(&e.paths.dropin).unwrap(),
        "[Service]\nExecStart=\nExecStart=/opt/py -m claudeops web --host 127.0.0.1 --port 28765\n"
    );
}

#[test]
fn on_blocks_late_override_empty_execstart_and_unreadable_dropin() {
    let e = env();
    for (name, body, want) in [
        (
            "zz.conf",
            &b"[Service]\nExecStart=\nExecStart=/z -m claudeops web\n"[..],
            "zz.conf",
        ),
        ("a.conf", &b"[Service]\nExecStart=\n"[..], "tanınmadı"),
        ("a.conf", &b"\xff"[..], "drop-in'leri okunamadı"),
    ] {
        let p = other_dropin(&e, name, body);
        let (rc, out) = e.run(Action::On, true, L, I);
        assert_eq!(rc, 1, "{name}: {out}");
        assert!(out.contains(want), "{out}");
        assert!(e.calls().is_empty());
        assert!(!Path::new(&e.paths.front_unit).exists());
        assert!(!Path::new(&e.paths.dropin).exists());
        std::fs::remove_file(p).unwrap();
    }
}

#[test]
fn on_sees_spaced_and_indented_execstart() {
    let e = env();
    for line in ["ExecStart =", "  ExecStart=", "\tExecStart \t= "] {
        let body = format!(
            "[Service]\n{}\n{line}/z -m claudeops web\n",
            line.trim_end()
        );
        let p = other_dropin(&e, "zz.conf", body.as_bytes());
        let (rc, out) = e.run(Action::On, true, L, I);
        assert_eq!(rc, 1, "{line:?}: {out}");
        assert!(out.contains("zz.conf"), "{out}");
        assert!(e.calls().is_empty());
        std::fs::remove_file(p).unwrap();
    }
    let over = format!("{LIVE}[Service]\n ExecStart =\n\tExecStart = /x web --port 9003\n");
    assert_eq!(web_addr(&over).map(|a| a.port()), Some(9003));
}

fn ext(e: &Env, rel: &str, body: &str) -> String {
    let p = e.root.join("etc").join(rel);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    std::fs::write(&p, body).unwrap();
    p.to_str().unwrap().into()
}

fn units(e: &Env, fragment: &str, dropins: &[String]) {
    e.w.0.borrow_mut().units = UnitPaths {
        fragment: fragment.into(),
        dropins: dropins.to_vec(),
    };
}

fn es(extra: &str) -> String {
    format!("[Service]\nExecStart=\nExecStart=/z -m claudeops web{extra}\n")
}

fn assert_blocked(e: &mut Env, want: &str) {
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 1, "{out}");
    assert!(out.contains(want), "{out}");
    assert!(e.calls().is_empty());
    assert!(!Path::new(&e.paths.front_unit).exists());
    assert!(!Path::new(&e.paths.dropin).exists());
}

fn applied_dropin(e: &mut Env) -> String {
    e.web_outside();
    let (rc, out) = e.run(Action::On, true, L, I);
    assert_eq!(rc, 0, "{out}");
    std::fs::read_to_string(&e.paths.dropin).unwrap()
}

#[test]
fn on_blocks_later_outside_dropin() {
    let mut e = env();
    let d = ext(&e, "service.d/zz.conf", &es(""));
    units(&e, &e.paths.web_unit, &[d]);
    assert_blocked(&mut e, "zz.conf");
}

#[test]
fn on_uses_earlier_outside_dropin_as_base() {
    let mut e = env();
    let d = ext(&e, "service.d/aa.conf", &es(""));
    units(&e, &e.paths.web_unit, &[d]);
    assert!(applied_dropin(&mut e)
        .contains("ExecStart=/z -m claudeops web --host 127.0.0.1 --port 28765\n"));
}

#[test]
fn user_dropin_shadows_same_name_outside_but_not_control_dir() {
    for (rel, blocked) in [
        ("d/aa.conf", false),
        ("user.control/claudeops-web.service.d/aa.conf", true),
    ] {
        let mut e = env();
        let d = ext(&e, rel, "[Service]\nExecStart=\n");
        units(&e, &e.paths.web_unit, &[d]);
        other_dropin(&e, "aa.conf", es("").as_bytes());
        if blocked {
            assert_blocked(&mut e, "tanınmadı");
        } else {
            assert!(applied_dropin(&mut e).contains("ExecStart=/z "));
        }
    }
}

#[test]
fn front_conf_elsewhere_blocks_only_when_it_wins() {
    let mut e = env();
    let d = ext(
        &e,
        "user.control/claudeops-web.service.d/front.conf",
        &es(""),
    );
    units(&e, &e.paths.web_unit, &[d]);
    assert_blocked(&mut e, "front.conf sonrasındaki drop-in ExecStart= atıyor");
    let d = ext(&e, "d/front.conf", &es(""));
    units(&e, &e.paths.web_unit, &[d]);
    assert!(!applied_dropin(&mut e).contains("/z "));
}

#[test]
fn on_reads_main_unit_outside_user_dir_and_skips_deleted_dropin() {
    let mut e = env();
    std::fs::remove_file(&e.paths.web_unit).unwrap();
    let f = ext(
        &e,
        "claudeops-web.service",
        "[Service]\nExecStart=/e -m claudeops web\n",
    );
    let gone = e.root.join("etc/yok.conf").to_str().unwrap().to_string();
    units(&e, &f, &[gone]);
    assert!(applied_dropin(&mut e).contains("ExecStart=/e -m claudeops web --host"));
}

#[test]
fn unit_query_error_blocks_on_but_not_off() {
    let mut e = env();
    e.w.0.borrow_mut().units_err = Some("çıkış 1".into());
    assert_blocked(
        &mut e,
        "claudeops-web.service birim yolları okunamadı: çıkış 1",
    );
    e.front_on();
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
}

#[test]
fn off_reads_outside_dropin_address() {
    let e = env();
    e.front_on();
    let d = ext(&e, "d/aa.conf", &es(" --port 9004"));
    units(&e, &e.paths.web_unit, &[d]);
    e.w.0.borrow_mut().effects[2].1 = "127.0.0.1:9004".parse().unwrap();
    let (rc, out) = e.run(Action::Off, true, L, I);
    assert_eq!(rc, 0, "{out}");
}

#[test]
fn show_output_is_parsed() {
    assert_eq!(
        crate::front::systemctl::parse_unit_paths(
            "FragmentPath=/a/w.service\nDropInPaths=/a/x.conf /b/y.conf\n"
        ),
        UnitPaths {
            fragment: "/a/w.service".into(),
            dropins: vec!["/a/x.conf".into(), "/b/y.conf".into()],
        }
    );
}

#[test]
fn on_allows_late_dropin_without_execstart() {
    let e = env();
    other_dropin(&e, "zz.conf", b"[Service]\nEnvironment=A=1\n");
    let (rc, out) = e.run(Action::On, false, L, I);
    assert_eq!(rc, 0, "{out}");
}
