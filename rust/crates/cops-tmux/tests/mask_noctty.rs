//! `tty_is_masked` pty'yi `O_NOCTTY` ile açar: denetim terminali OLMAYAN bir oturum lideri (ctty'siz servis süreci,
//! TODO K-02) yokladığı pty'yi denetim terminali edinmemeli, yoksa o pty kapanınca SIGHUP alır.
//!
//! Sınama ayrı süreçte koşar (`setsid` ile yeni oturum, ctty yok): test ikilisi kendini `--exact noctty_helper` ile
//! yeniden çalıştırır. Karşı sınama: aynı pty `O_NOCTTY`siz açılınca ctty edinildiği görülür (ölçüm gerçekten
//! yakalıyor).

use std::ffi::CStr;
use std::fs;
use std::os::unix::process::CommandExt;
use std::process::Command;

use cops_tmux::tty_is_masked;

const HELPER_ENV: &str = "COPS_TMUX_NOCTTY_HELPER";
const DONE: &str = "NOCTTY-CHECKED";

/// `/proc/self/stat` `tty_nr` (0 = denetim terminali yok).
fn ctty() -> i64 {
    let raw = fs::read_to_string("/proc/self/stat").unwrap();
    let rest = &raw[raw.rfind(')').unwrap() + 1..];
    // state ppid pgrp session tty_nr
    rest.split_whitespace().nth(4).unwrap().parse().unwrap()
}

fn fd_count() -> usize {
    fs::read_dir("/proc/self/fd").unwrap().count()
}

/// Yeni bir pty çifti: (ana fd, ikincil yol). Ana fd `O_NOCTTY` ile.
fn open_pty() -> (libc::c_int, String) {
    // SAFETY: libc pty çağrıları; dönüş değerleri denetleniyor, tampon boyutu doğru veriliyor.
    unsafe {
        let master = libc::posix_openpt(libc::O_RDWR | libc::O_NOCTTY);
        assert!(master >= 0, "posix_openpt");
        assert_eq!(libc::grantpt(master), 0);
        assert_eq!(libc::unlockpt(master), 0);
        let mut buf = [0 as libc::c_char; 128];
        assert_eq!(libc::ptsname_r(master, buf.as_mut_ptr(), buf.len()), 0);
        let path = CStr::from_ptr(buf.as_ptr()).to_str().unwrap().to_string();
        (master, path)
    }
}

fn set_echo(master: libc::c_int, on: bool) {
    // SAFETY: açık pty ana fd'si; termios yapısı tcgetattr ile doldurulup yazılıyor. Linux'ta ana uçtaki termios
    // işlemleri ikincil ucun ayarını değiştirir.
    unsafe {
        let mut t = std::mem::zeroed::<libc::termios>();
        assert_eq!(libc::tcgetattr(master, &mut t), 0);
        if on {
            t.c_lflag |= libc::ECHO;
        } else {
            t.c_lflag &= !libc::ECHO;
        }
        t.c_lflag |= libc::ICANON;
        assert_eq!(libc::tcsetattr(master, libc::TCSANOW, &t), 0);
    }
}

#[test]
fn noctty_helper() {
    if std::env::var_os(HELPER_ENV).is_none() {
        return;
    }
    assert_eq!(ctty(), 0, "setsid sonrası ctty olmamalı");
    let (master, slave) = open_pty();
    let fds = fd_count();
    for _ in 0..100 {
        assert_eq!(tty_is_masked(&slave), Some(false));
    }
    set_echo(master, false);
    assert_eq!(tty_is_masked(&slave), Some(true), "parola istemi");
    set_echo(master, true);
    assert_eq!(tty_is_masked(&slave), Some(false));
    assert_eq!(fd_count(), fds, "tty_is_masked fd sızdırdı");
    assert_eq!(ctty(), 0, "tty_is_masked pty'yi denetim terminali edindi");
    // Karşı sınama: O_NOCTTY olmadan açılınca ctty edinilir; ölçüm bunu görüyor. Ana uç kapanınca ctty'nin
    // oturumu SIGHUP alır (K-02'nin kendisi): yardımcı süreç ölmesin diye yok sayılır.
    // SAFETY: tek iş parçacıklı yardımcı süreçte sinyal eylemi değişimi.
    unsafe { libc::signal(libc::SIGHUP, libc::SIG_IGN) };
    let plain = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&slave)
        .unwrap();
    assert_ne!(
        ctty(),
        0,
        "karşı sınama: O_NOCTTY'siz açış ctty edinmeliydi"
    );
    drop(plain);
    // SAFETY: open_pty'nin döndürdüğü, başka yerde kapatılmayan fd.
    unsafe { libc::close(master) };
    println!("{DONE}");
}

#[test]
fn probing_a_pty_never_makes_it_the_controlling_terminal() {
    let exe = std::env::current_exe().unwrap();
    let mut cmd = Command::new(exe);
    cmd.args([
        "--exact",
        "noctty_helper",
        "--nocapture",
        "--test-threads=1",
    ])
    .env(HELPER_ENV, "1");
    // SAFETY: fork ile exec arasında yalnız async-signal-safe `setsid` çağrılır.
    unsafe {
        cmd.pre_exec(|| {
            if libc::setsid() < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let out = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success() && stdout.contains(DONE),
        "yardımcı başarısız ({:?}): {stdout}\n{}",
        out.status,
        String::from_utf8_lossy(&out.stderr)
    );
}
