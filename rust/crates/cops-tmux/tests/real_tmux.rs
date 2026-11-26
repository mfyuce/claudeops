//! Gerçek tmux'a karşı davranış testleri (yalıtılmış sunucu).

mod common;

use std::os::unix::fs::PermissionsExt;
use std::time::Duration;

use common::{read_at_least, wait_until, Server};
use cops_tmux::{MaskGuard, TmuxError};

const NOW: Duration = Duration::ZERO;

/// Pane'e giden baytları `out` dosyasına yazan ham kipli oturum.
fn sink(s: &Server, name: &str) -> std::path::PathBuf {
    let out = s.path().join(format!("{name}.out"));
    s.spawn_ready(
        name,
        "stty raw -echo",
        &format!("exec cat > '{}'", out.display()),
    );
    out
}

#[test]
fn prefix_name_never_matches_another_session() {
    let s = Server::new();
    let out = sink(&s, "abc_1");
    let t = &s.tmux;
    assert!(!t.has_session("abc").unwrap());
    assert!(t.has_session("abc_1").unwrap());
    assert!(t.capture("abc", 10).is_err());
    assert!(t.capture_range("abc", 0, 1).is_err());
    assert!(t.pane_size("abc").is_err());
    assert!(t.snapshot("abc").is_err());
    assert!(t.session_panes("abc").is_err());
    assert!(t.client_count("abc").is_err());
    assert_eq!(t.pane_is_masked_input("abc"), None);
    for guard in [MaskGuard::RefuseMasked, MaskGuard::UserTyped] {
        assert!(t.send_text("abc", "yanlis", NOW, guard).is_err());
        assert!(t.send_text("abc", "yan\nlis", NOW, guard).is_err());
        assert!(t.send_raw("abc", "yanlis", guard).is_err());
        assert!(t.send_special_key("abc", "Enter", guard).is_err());
    }
    assert!(t.resize_window("abc", 100, 30).is_err());
    assert!(t.release_size("abc").is_err());
    assert!(t.set_ctx("abc", "x").is_err());
    assert!(t.kill_session("abc").is_err());
    assert!(t.has_session("abc_1").unwrap());
    t.send_raw("abc_1", "dogru", MaskGuard::UserTyped).unwrap();
    assert_eq!(read_at_least(&out, 5), b"dogru");
    assert_eq!(t.pane_size("abc_1").unwrap().cols, 80);
    // Başarısız yapıştırma tampon bırakmaz.
    assert_eq!(s.raw(&["list-buffers"]), "");
}

#[test]
fn literal_text_raw_and_special_keys_arrive_unchanged() {
    let s = Server::new();
    let t = &s.tmux;
    let out = sink(&s, "k");
    let texts = [
        "foo;",
        "x;y;",
        r"bar\;",
        ";",
        "-help",
        "--foo",
        "--- a/f",
        "- madde şğüİ",
        r"a\nb",
        "#{pane_pid}",
        "",
    ];
    let mut want = Vec::new();
    for text in texts {
        t.send_text("k", text, NOW, MaskGuard::RefuseMasked)
            .unwrap();
        want.extend_from_slice(text.as_bytes());
        want.push(b'\r');
    }
    for data in ["foo;", r"bar\;", ";", "-", "\u{3}\u{1b}[A", "a\0b"] {
        t.send_raw("k", data, MaskGuard::UserTyped).unwrap();
        want.extend(data.bytes().filter(|&b| b != 0));
    }
    // Parça sınırında `;` (2000. karakter) ve çok baytlı harfler.
    let long = format!("{};{}", "ş".repeat(1999), "z;".repeat(1500));
    t.send_raw("k", &long, MaskGuard::UserTyped).unwrap();
    want.extend_from_slice(long.as_bytes());
    for key in ["Enter", "Tab", "Escape", "C-c"] {
        t.send_special_key("k", key, MaskGuard::UserTyped).unwrap();
    }
    want.extend_from_slice(b"\r\t\x1b\x03");
    assert_eq!(read_at_least(&out, want.len()), want);
    for bad in ["C-z", "q", "-X", "Enter;"] {
        assert!(matches!(
            t.send_special_key("k", bad, MaskGuard::UserTyped),
            Err(TmuxError::BadArgument(_))
        ));
    }
}

#[test]
fn multiline_goes_as_one_bracketed_paste() {
    let s = Server::new();
    let out = s.path().join("p.out");
    s.spawn_ready(
        "p",
        r"stty raw -echo; printf '\033[?2004h'",
        &format!("exec cat > '{}'", out.display()),
    );
    s.tmux
        .send_text("p", "satır1\n- iki;\nüç;", NOW, MaskGuard::RefuseMasked)
        .unwrap();
    let want = "\x1b[200~satır1\r- iki;\rüç;\x1b[201~\r".as_bytes();
    assert_eq!(read_at_least(&out, want.len()), want);
    assert_eq!(s.raw(&["list-buffers"]), "");
}

#[test]
fn masked_pane_refuses_injection_but_accepts_user_typing() {
    let s = Server::new();
    let t = &s.tmux;
    s.spawn_ready(
        "pw",
        "stty icanon -echo",
        "read x; echo \"got:$x:\"; sleep 60",
    );
    s.spawn_ready("cooked", "stty icanon echo", "sleep 60");
    s.spawn_ready("raw", "stty -icanon -echo", "sleep 60");
    assert_eq!(t.pane_is_masked_input("pw"), Some(true));
    assert_eq!(t.pane_is_masked_input("cooked"), Some(false));
    assert_eq!(t.pane_is_masked_input("raw"), Some(false));
    let guard = MaskGuard::RefuseMasked;
    assert!(matches!(
        t.send_text("pw", "komut", NOW, guard),
        Err(TmuxError::Masked)
    ));
    assert!(matches!(
        t.send_text("pw", "iki\nsatır", NOW, guard),
        Err(TmuxError::Masked)
    ));
    assert!(matches!(
        t.send_raw("pw", "komut", guard),
        Err(TmuxError::Masked)
    ));
    assert!(matches!(
        t.send_special_key("pw", "Enter", guard),
        Err(TmuxError::Masked)
    ));
    // Engellenen hiçbir bayt ulaşmadı: `read` yalnız kullanıcının yazdığını görür.
    t.send_text("pw", "gizli", NOW, MaskGuard::UserTyped)
        .unwrap();
    s.wait_screen("pw", "got:gizli:");
}

#[test]
fn unknown_mask_state_refuses_injection_on_a_real_server() {
    // "Bilinmiyor" (TBD#367): tmux pane'i bulamadı. (Ölçüm: `remain-on-exit` ile ölmüş pane'in pty'si de silinir ve
    // `None` verir; ama numara başka bir pty'ye yeniden verilmişse o pty'yi okur, paralel testte belirlenimsiz.)
    let s = Server::new();
    let t = &s.tmux;
    let out = sink(&s, "k");
    assert_eq!(t.pane_is_masked_input("yok"), None);
    let guard = MaskGuard::RefuseMasked;
    assert!(matches!(
        t.send_text("yok", "komut", NOW, guard),
        Err(TmuxError::MaskUnknown)
    ));
    assert!(matches!(
        t.send_raw("yok", "komut", guard),
        Err(TmuxError::MaskUnknown)
    ));
    assert!(matches!(
        t.send_special_key("yok", "Enter", guard),
        Err(TmuxError::MaskUnknown)
    ));
    // Durumu bilinen (ham kipli, maskesiz) pane otomatik gönderimi alır.
    assert_eq!(t.pane_is_masked_input("k"), Some(false));
    t.send_raw("k", "ok", guard).unwrap();
    assert_eq!(read_at_least(&out, 2), b"ok");
}

#[test]
fn history_read_never_enters_copy_mode() {
    let s = Server::new();
    let t = &s.tmux;
    s.spawn_ready("h", "seq -f 'satir-%g' 1 100", "sleep 60");
    let size = t.pane_size("h").unwrap();
    assert_eq!((size.cols, size.rows, size.alternate_on), (80, 24, false));
    // 100 satır + READY + imleç satırı = 102; 24'ü görünür.
    assert_eq!(size.history_size, 78);
    assert_eq!(
        t.capture_range("h", -78, -77).unwrap(),
        "satir-1\nsatir-2\n"
    );
    assert_eq!(t.capture_range("h", 0, 0).unwrap(), "satir-79\n");
    assert!(t.capture("h", 2000).unwrap().starts_with("satir-1\n"));
    assert!(t.capture("h", 3).unwrap().starts_with("satir-76\n"));
    let snap = t.snapshot("h").unwrap();
    assert_eq!(snap.size, size);
    assert!(snap.tty.starts_with("/dev/"));
    assert!(snap.text.starts_with("satir-79\n") && snap.text.lines().count() == 24);
    assert_eq!(
        s.raw(&["display-message", "-p", "-t", "=h:", "#{pane_in_mode}"])
            .trim(),
        "0"
    );
}

#[test]
fn capture_plain_strips_colour() {
    let s = Server::new();
    s.spawn_ready(
        "c",
        r"printf '\033[1;33mSwitch\033[0m \033[38;5;220mmodel?\033[0m\n'",
        "sleep 60",
    );
    assert!(!s.tmux.capture("c", 10).unwrap().contains("Switch model?"));
    assert!(s
        .tmux
        .capture_plain("c", 10)
        .unwrap()
        .contains("Switch model?"));
}

#[test]
fn lists_pid_cwd_and_names_even_in_c_locale() {
    let s = Server::new();
    let cwd = s.path().join("çalışma\ndizini");
    std::fs::create_dir(&cwd).unwrap();
    let name = "iş oturumu 'x'";
    s.raw(&[
        "new-session",
        "-d",
        "-s",
        name,
        "-c",
        cwd.to_str().unwrap(),
        "exec sleep 60",
    ]);
    s.spawn("iki", "exec sleep 60");
    let wrapper = s.path().join("tmux-c");
    std::fs::write(&wrapper, "#!/bin/sh\nLC_ALL=C LANG=C exec tmux \"$@\"\n").unwrap();
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o755)).unwrap();
    for t in [s.tmux.clone(), s.tmux.clone().program(&wrapper)] {
        let mut names: Vec<String> = Vec::new();
        wait_until(
            || match t.list_sessions() {
                Ok(list) => {
                    names = list.iter().map(|x| x.name.clone()).collect();
                    assert!(list.iter().all(|x| x.created > 0 && x.attached == 0));
                    true
                }
                // Paralel fork'ta yeni yazılan betik kısa süre ETXTBSY verebilir.
                Err(TmuxError::Io(_)) => false,
                Err(e) => panic!("{e}"),
            },
            "list-sessions",
        );
        names.sort();
        assert_eq!(names, ["iki", name]);
        assert_eq!(t.list_panes().unwrap().len(), 2);
        let panes = t.session_panes(name).unwrap();
        assert_eq!(panes.len(), 1);
        let pane = &panes[0];
        assert_eq!(pane.session, name);
        assert_eq!(pane.cwd, cwd.to_str().unwrap());
        assert_eq!(
            std::fs::read_link(format!("/proc/{}/cwd", pane.pane_pid)).unwrap(),
            cwd
        );
        assert!(pane.tty.starts_with("/dev/"));
    }
}

#[test]
fn resize_applies_and_release_restores_auto_size() {
    let s = Server::new();
    let t = &s.tmux;
    s.spawn("r", "exec sleep 60");
    t.resize_window("r", 132, 43).unwrap();
    let size = t.pane_size("r").unwrap();
    assert_eq!((size.cols, size.rows), (132, 43));
    for (cols, rows) in [(19, 30), (501, 30), (80, 4), (80, 201)] {
        assert!(matches!(
            t.resize_window("r", cols, rows),
            Err(TmuxError::BadArgument(_))
        ));
    }
    assert_eq!(
        s.raw(&["show-options", "-wv", "-t", "=r:", "window-size"])
            .trim(),
        "manual"
    );
    t.release_size("r").unwrap();
    assert_eq!(
        s.raw(&["show-options", "-wv", "-t", "=r:", "window-size"])
            .trim(),
        ""
    );
}

#[test]
fn attached_client_is_counted_and_receives_safe_message() {
    let s = Server::new();
    let outer = Server::new();
    let t = &s.tmux;
    s.spawn("m", "exec sleep 60");
    assert_eq!(t.client_count("m").unwrap(), 0);
    // İstemci, ikinci bir yalıtılmış sunucunun pane'inde bağlanır.
    let attach = format!(
        "env -u TMUX TMUX_TMPDIR='{}' tmux -u -L {} attach-session -t '=m:'",
        s.path().display(),
        t.socket()
    );
    outer.spawn("o", &attach);
    wait_until(|| t.client_count("m").unwrap() == 1, "istemci");
    let client = s
        .raw(&["list-clients", "-F", "#{client_name}"])
        .trim()
        .to_string();
    assert_eq!(t.client_session(&client).unwrap().as_deref(), Some("m"));
    assert_eq!(t.client_session("/dev/pts/yok").unwrap(), None);
    assert_eq!(t.client_session("-x").unwrap(), None);
    t.message(&client, "-kod #{pane_pid} bitti;", 5000).unwrap();
    outer.wait_screen("o", "-kod #{pane_pid} bitti");
    assert!(matches!(
        t.message("/dev/pts/yok", "x", 10),
        Err(TmuxError::BadArgument("client"))
    ));
    t.set_ctx("m", "ctx 1K;").unwrap();
    // Sondaki `;` kaçırılır, etiket olduğu gibi yazılır (TBD#366 P6; Python da aynı).
    assert_eq!(
        s.raw(&["show-options", "-v", "-t", "=m:", "@cops_ctx"])
            .trim(),
        "ctx 1K;"
    );
    t.set_ctx("m", "").unwrap();
    assert_eq!(
        s.raw(&["show-options", "-q", "-v", "-t", "=m:", "@cops_ctx"]),
        ""
    );
}

#[test]
fn no_server_is_an_error_not_a_panic() {
    let s = Server::new();
    assert!(!s.tmux.has_session("x").unwrap());
    assert!(matches!(
        s.tmux.list_sessions(),
        Err(TmuxError::Failed { .. })
    ));
    assert_eq!(s.tmux.pane_is_masked_input("x"), None);
}
