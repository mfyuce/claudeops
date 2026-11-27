//! tmux'a giden argv'nin tam denetimi (sahte tmux; sunucu YOK). Python testlerindeki mock'ların karşılığı.

use std::os::unix::fs::symlink;
use std::time::Duration;

use cops_tmux::{CtxPusher, MaskGuard, Tmux, TmuxError};
use tempfile::TempDir;

const NOW: Duration = Duration::ZERO;
const USER: MaskGuard = MaskGuard::UserTyped;

struct Fake {
    dir: TempDir,
    tmux: Tmux,
}

impl Fake {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let program = dir.path().join("tmux");
        symlink(
            concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fake_tmux.sh"),
            &program,
        )
        .unwrap();
        let tmux = Tmux::with_socket("cxrs-fake").program(program);
        let fake = Self { dir, tmux };
        fake.set(
            "list-commands.out",
            "paste-buffer (pasteb) [-dpr] [-s separator]\n",
        );
        fake
    }

    fn set(&self, file: &str, content: &str) -> &Self {
        std::fs::write(self.dir.path().join(file), content).unwrap();
        self
    }

    /// Çağrılar; her birinden `-L <soket>` önü atılmış.
    fn calls(&self) -> Vec<Vec<String>> {
        let raw = std::fs::read_to_string(self.dir.path().join("argv")).unwrap_or_default();
        raw.split_terminator('\x1e')
            .map(|rec| {
                let args: Vec<String> = rec.split_terminator('\x1f').map(str::to_string).collect();
                let skip = if args[0] == "-u" { 3 } else { 2 };
                assert_eq!(args[skip - 2..skip], ["-L", "cxrs-fake"]);
                args[skip..].to_vec()
            })
            .collect()
    }

    fn subcommands(&self) -> Vec<String> {
        self.calls().iter().map(|c| c[0].clone()).collect()
    }
}

#[test]
fn single_line_goes_through_stdin_never_argv() {
    let f = Fake::new();
    f.tmux.send_text("x", "foo;", NOW, USER).unwrap();
    assert_eq!(
        f.subcommands(),
        ["load-buffer", "paste-buffer", "send-keys"]
    );
    assert!(f.calls().iter().flatten().all(|a| !a.contains("foo")));
    assert_eq!(
        std::fs::read_to_string(f.dir.path().join("stdin")).unwrap(),
        "foo;"
    );
}

#[test]
fn raw_goes_through_stdin_in_one_process_never_argv() {
    let f = Fake::new();
    for data in ["gizli-parola;", "a\0b", "\u{1b}[A"] {
        f.tmux.send_raw("x", data, USER).unwrap();
        assert_eq!(
            std::fs::read(f.dir.path().join("stdin")).unwrap(),
            data.as_bytes()
        );
    }
    f.tmux.send_raw("x", "", USER).unwrap();
    // Yoklama bir kez, her gönderim tek süreç.
    assert_eq!(
        f.subcommands(),
        ["list-commands", "load-buffer", "load-buffer", "load-buffer"]
    );
    assert!(f.calls().iter().flatten().all(|a| !a.contains("gizli")));
    let c = &f.calls()[1];
    let buf = c[2].as_str();
    assert_eq!(
        c[..],
        [
            "load-buffer",
            "-b",
            buf,
            "-",
            ";",
            "paste-buffer",
            "-r",
            "-d",
            "-b",
            buf,
            "-t",
            "=x:"
        ]
    );
}

#[test]
fn raw_disables_sanitizing_only_where_the_server_knows_the_flag() {
    let f = Fake::new();
    f.set(
        "list-commands.out",
        "paste-buffer (pasteb) [-dprS] [-s separator]\n",
    );
    f.tmux.send_raw("x", "\u{3}", USER).unwrap();
    assert_eq!(f.calls()[1][5..9], ["paste-buffer", "-r", "-S", "-d"]);
}

#[test]
fn raw_sends_nothing_when_the_probe_fails() {
    for (out, rc) in [("", "0"), ("send-keys (send)\n", "0"), ("", "1")] {
        let f = Fake::new();
        f.set("list-commands.out", out).set("list-commands.rc", rc);
        assert!(f.tmux.send_raw("x", "a", USER).is_err(), "{out:?} {rc}");
        assert_eq!(f.subcommands(), ["list-commands"]);
    }
}

#[test]
fn raw_failure_deletes_the_buffer_and_probes_again() {
    let f = Fake::new();
    f.set("load-buffer.rc", "1\n0");
    assert!(f.tmux.send_raw("x", "gizli", USER).is_err());
    let calls = f.calls();
    assert_eq!(calls[2], ["delete-buffer", "-b", calls[1][2].as_str()]);
    f.tmux.send_raw("x", "y", USER).unwrap();
    assert_eq!(
        f.subcommands(),
        [
            "list-commands",
            "load-buffer",
            "delete-buffer",
            "list-commands",
            "load-buffer"
        ]
    );
}

#[test]
fn multiline_uses_load_paste_then_single_enter() {
    let f = Fake::new();
    let text = "satır1\nsatır2\n- madde";
    f.tmux.send_text("x", text, NOW, USER).unwrap();
    assert_eq!(
        f.subcommands(),
        ["load-buffer", "paste-buffer", "send-keys"]
    );
    let calls = f.calls();
    let buffer = &calls[0][2];
    assert_eq!(calls[0], ["load-buffer", "-b", buffer, "-"]);
    assert_eq!(
        calls[1],
        ["paste-buffer", "-p", "-d", "-b", buffer, "-t", "=x:"]
    );
    assert_eq!(calls[2], ["send-keys", "-t", "=x:", "Enter"]);
    assert_eq!(
        std::fs::read_to_string(f.dir.path().join("stdin")).unwrap(),
        text
    );
}

#[test]
fn paste_failure_deletes_the_buffer_and_sends_no_enter() {
    let f = Fake::new();
    f.set("paste-buffer.rc", "1\n");
    assert!(f.tmux.send_text("x", "a\nb", NOW, USER).is_err());
    assert_eq!(
        f.subcommands(),
        ["load-buffer", "paste-buffer", "delete-buffer"]
    );
}

#[test]
fn load_failure_deletes_the_buffer_and_stops_before_paste() {
    let f = Fake::new();
    f.set("load-buffer.rc", "1\n");
    assert!(f.tmux.send_text("x", "a\nb", NOW, USER).is_err());
    assert_eq!(f.subcommands(), ["load-buffer", "delete-buffer"]);
}

/// TBD#369 P9: yapıştırma zaman aşımında da tampon silinir. En kısa süre 5 sn (`send_text` tabanı).
#[test]
fn paste_timeout_deletes_the_buffer_and_sends_no_enter() {
    let f = Fake::new();
    f.set("paste-buffer.sleep", "30");
    assert!(matches!(
        f.tmux.send_text("x", "metin", NOW, USER),
        Err(TmuxError::Timeout)
    ));
    assert_eq!(
        f.subcommands(),
        ["load-buffer", "paste-buffer", "delete-buffer"]
    );
    let calls = f.calls();
    assert_eq!(calls[2], ["delete-buffer", "-b", &calls[0][2]]);
}

#[test]
fn nul_text_spawns_nothing_and_empty_text_is_only_enter() {
    let f = Fake::new();
    assert!(matches!(
        f.tmux.send_text("x", "a\0b", NOW, USER),
        Err(TmuxError::BadArgument("text"))
    ));
    assert!(f.calls().is_empty());
    f.tmux.send_text("x", "", NOW, USER).unwrap();
    assert_eq!(f.calls(), [vec!["send-keys", "-t", "=x:", "Enter"]]);
}

/// Biçim genişletmesine ya da ekrana kaçabilecek ad: hiçbir tmux süreci başlamaz.
#[test]
fn hash_and_control_character_names_are_rejected_everywhere() {
    let f = Fake::new();
    let conf = std::path::Path::new("/x.conf");
    let bad = [
        "a#b",
        "d#(touch Y)",
        "v#{?0,x,}",
        "a\nb",
        "a\tb",
        "a\x7f",
        "a\u{85}",
    ];
    let name_err = |r: Result<(), TmuxError>| matches!(r, Err(TmuxError::BadArgument("name")));
    for name in bad {
        assert!(!cops_tmux::addressable(name), "{name:?}");
        let envs: [(&str, &str); 0] = [];
        assert!(name_err(f.tmux.spawn_direct(conf, name, "/", "true", envs)));
        assert!(name_err(f.tmux.send_text(name, "m", NOW, USER)));
        assert!(name_err(f.tmux.send_raw(name, "m", USER)));
        assert!(name_err(f.tmux.kill_session(name)));
        assert!(f
            .tmux
            .new_session_shell_fragment("/x.conf", name, "/", "true")
            .is_err());
        assert!(f.tmux.attach_shell_fragment("/x.conf", name).is_err());
        assert!(f.tmux.find_outer_bash_pids(name).is_empty(), "{name:?}");
    }
    assert!(f.calls().is_empty());
}

#[test]
fn masked_guard_asks_for_the_tty_before_sending() {
    let f = Fake::new();
    // pty okunamazsa durum bilinmez: otomatik gönderim YOK (TBD#367, kapalı yön).
    f.set("display-message.out", "/dev/yok\n");
    assert!(matches!(
        f.tmux.send_raw("x", "a", MaskGuard::RefuseMasked),
        Err(TmuxError::MaskUnknown)
    ));
    assert_eq!(f.subcommands(), ["display-message"]);
    assert_eq!(
        f.calls()[0],
        ["display-message", "-p", "-t", "=x:", "#{pane_tty}"]
    );
}

#[test]
fn unknown_mask_state_blocks_every_automatic_send_but_not_user_typing() {
    for (out, rc) in [("/dev/yok\n", "0"), ("", "0"), ("/dev/pts/1\n", "1")] {
        let f = Fake::new();
        f.set("display-message.out", out)
            .set("display-message.rc", rc);
        let guard = MaskGuard::RefuseMasked;
        for r in [
            f.tmux.send_text("x", "metin", NOW, guard),
            f.tmux.send_text("x", "iki\nsatır", NOW, guard),
            f.tmux.send_raw("x", "a", guard),
            f.tmux.send_special_key("x", "Enter", guard),
        ] {
            assert!(matches!(r, Err(TmuxError::MaskUnknown)), "{out:?} {r:?}");
        }
        assert!(
            f.subcommands().iter().all(|c| c == "display-message"),
            "{:?}",
            f.subcommands()
        );
        // Kullanıcının kendi yazdığı girdi maske yoklamasına hiç uğramaz.
        f.tmux.send_raw("x", "a", USER).unwrap();
        assert_eq!(f.subcommands().last().unwrap(), "load-buffer");
    }
}

#[test]
fn disallowed_key_and_bad_size_spawn_nothing() {
    let f = Fake::new();
    assert!(f.tmux.send_special_key("x", "q", USER).is_err());
    assert!(f.tmux.resize_window("x", 5, 40).is_err());
    assert!(f.tmux.resize_window("x", 140, 500).is_err());
    assert!(f.calls().is_empty());
}

#[test]
fn resize_release_and_kill_use_the_exact_target() {
    let f = Fake::new();
    f.tmux.resize_window("s1", 140, 40).unwrap();
    f.tmux.release_size("s1").unwrap();
    f.tmux.kill_session("s1").unwrap();
    assert_eq!(
        f.calls(),
        [
            vec!["resize-window", "-t", "=s1:", "-x", "140", "-y", "40"],
            vec!["set-option", "-wu", "-t", "=s1:", "window-size"],
            vec!["kill-session", "-t", "=s1:"],
        ]
    );
}

#[test]
fn snapshot_is_one_process_running_two_commands_without_utf8_flag() {
    let f = Fake::new();
    f.set("display-message.out", "80 24 3 0 \nekran\n");
    let snap = f.tmux.snapshot("t").unwrap();
    assert_eq!((snap.tty.as_str(), snap.text.as_str()), ("", "ekran\n"));
    let calls = f.calls();
    assert_eq!(calls.len(), 1);
    let at = calls[0].iter().position(|a| a == ";").unwrap();
    assert_eq!(calls[0][at - 1], cops_tmux::SNAPSHOT_FORMAT);
    assert_eq!(calls[0][at + 1], "capture-pane");
}

#[test]
fn ctx_set_and_unset_argv_and_failure() {
    let f = Fake::new();
    f.tmux.set_ctx("ab", "ctx 1K").unwrap();
    f.tmux.set_ctx("ab", "").unwrap();
    assert_eq!(
        f.calls(),
        [
            vec!["set-option", "-t", "=ab:", "@cops_ctx", "ctx 1K"],
            vec!["set-option", "-t", "=ab:", "-u", "@cops_ctx"],
        ]
    );
    f.set("set-option.rc", "1\n");
    assert!(f.tmux.set_ctx("ab", "x").is_err());
    let missing = Tmux::with_socket("cxrs-fake").program("/nonexistent/tmux");
    assert!(missing.set_ctx("ab", "x").is_err());
}

#[test]
fn ctx_push_skips_unchanged_and_rewrites_on_new_pid_or_value() {
    let f = Fake::new();
    let pusher = CtxPusher::new();
    for (pid, label) in [
        (10, "ctx 1K"),
        (10, "ctx 1K"),
        (10, "ctx 2K"),
        (11, "ctx 2K"),
    ] {
        assert!(pusher.push(&f.tmux, "ab", pid, label));
    }
    assert_eq!(f.calls().len(), 3);
}

#[test]
fn failed_ctx_push_is_retried() {
    let f = Fake::new();
    f.set("set-option.rc", "1\n");
    let pusher = CtxPusher::new();
    assert!(!pusher.push(&f.tmux, "ab", 10, "ctx 1K"));
    assert!(!pusher.push(&f.tmux, "ab", 10, "ctx 1K"));
    assert_eq!(f.calls().len(), 2);
}

#[test]
fn ctx_push_cache_is_bounded_and_thread_safe() {
    let f = Fake::new();
    // Eşzamanlı çağrılarda argv kaydı iç içe geçebilir: çağrılar `set-option.n` satırlarıyla sayılır (tek `echo`).
    f.set("set-option.rc", "0\n");
    let count = || {
        std::fs::read_to_string(f.dir.path().join("set-option.n"))
            .unwrap()
            .lines()
            .count()
    };
    let pusher = CtxPusher::new();
    std::thread::scope(|scope| {
        for t in 0..6u32 {
            let (pusher, tmux) = (&pusher, &f.tmux);
            scope.spawn(move || {
                for i in 0..100u32 {
                    assert!(pusher.push(tmux, "ab", t * 1000 + i, "ctx 1K"));
                }
            });
        }
    });
    assert_eq!(count(), 600);
    // 600 farklı anahtar > 512: tablo en az bir kez boşaldı, ilk anahtarlardan en az biri yeniden yazılır.
    for t in 0..6u32 {
        assert!(pusher.push(&f.tmux, "ab", t * 1000, "ctx 1K"));
    }
    assert!(count() > 600);
}

const CLIENT: &str = "/dev/pts/3";

fn message_fake(session: &str) -> Fake {
    let f = Fake::new();
    f.set("list-clients.out", &format!("{CLIENT}\t{session}\n"));
    f
}

fn displayed(f: &Fake) -> Vec<Vec<String>> {
    f.calls()
        .into_iter()
        .filter(|c| c[0] == "display-message")
        .collect()
}

#[test]
fn message_is_neutralised_in_argv() {
    for (text, want) in [
        ("hata #(rm -rf ~) ve #{x}", "hata ##(rm -rf ~) ve ##{x}"),
        ("foo;", "foo"),
        ("foo ;;", "foo"),
        ("a ; b", "a ; b"),
        ("-t evil", " -t evil"),
        ("a\nb\r\nc", "a b c"),
    ] {
        let f = message_fake("demo_1");
        f.tmux.message(CLIENT, text, 4000).unwrap();
        assert_eq!(
            displayed(&f),
            [vec![
                "display-message",
                "-d",
                "4000",
                "-t",
                "=demo_1:",
                want
            ]]
        );
    }
}

#[test]
fn message_to_a_vanished_or_flag_like_client_sends_nothing() {
    let f = message_fake("");
    assert!(f.tmux.message(CLIENT, "x", 1).is_err());
    assert!(displayed(&f).is_empty());
    let f = message_fake("demo_1");
    for client in ["-t", ""] {
        assert!(f.tmux.message(client, "x", 1).is_err());
    }
    assert!(f.calls().is_empty());
}

#[test]
fn message_falls_back_to_no_duration_and_reports_total_failure() {
    let f = message_fake("demo_1");
    f.set("display-message.rc", "1\n0\n");
    f.tmux.message(CLIENT, "x", 4000).unwrap();
    let calls = displayed(&f);
    assert_eq!(calls.len(), 2);
    assert!(calls[0].contains(&"-d".to_string()) && !calls[1].contains(&"-d".to_string()));

    let f = message_fake("demo_1");
    f.set("display-message.rc", "1\n");
    assert!(matches!(
        f.tmux.message(CLIENT, "x", 1),
        Err(TmuxError::Failed { .. })
    ));
    let missing = Tmux::with_socket("cxrs-fake").program("/nonexistent/tmux");
    assert!(missing.message(CLIENT, "x", 1).is_err());
}

#[test]
fn broken_output_is_unknown_not_a_panic() {
    let f = Fake::new();
    f.set("list-panes.out", "80 24\n");
    assert!(matches!(f.tmux.pane_size("x"), Err(TmuxError::BadOutput)));
    f.set("list-panes.out", "");
    assert!(f.tmux.pane_size("x").is_err());
    assert!(!f.tmux.ghost_session("x", Some(1e12)));
    f.set("capture-pane.out", "\u{1}");
    std::fs::write(f.dir.path().join("capture-pane.out"), [0xff, 0xfe]).unwrap();
    assert!(matches!(f.tmux.capture("x", 1), Err(TmuxError::BadOutput)));
    f.set("list-clients.rc", "1\n");
    assert!(f.tmux.outer_bash_via_list_clients("n").is_empty());
    // tmux sorulamadı: "istemci yok" DEĞİL, hata (sebep korunur); mesaj da aynı hatayla döner.
    assert!(matches!(
        f.tmux.client_session(CLIENT),
        Err(TmuxError::Failed { .. })
    ));
    assert!(matches!(
        f.tmux.message(CLIENT, "x", 1),
        Err(TmuxError::Failed { .. })
    ));
    assert!(f.tmux.client_count("n").is_err());
}

#[test]
fn outer_bash_with_garbage_client_pids_is_empty() {
    let f = Fake::new();
    f.set("list-clients.out", "abc -3 0 1 4294967290\n");
    assert!(f.tmux.outer_bash_via_list_clients("n").is_empty());
}
