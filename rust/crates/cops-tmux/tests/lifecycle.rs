//! Yaşam döngüsü işlevleri gerçek tmux'a ve gerçek süreçlere karşı (yalıtılmış sunucu).

mod common;

use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use common::{wait_until, Server};
use cops_tmux::{pid_childless, tmux_available, tmux_conf_path};

fn conf() -> PathBuf {
    tmux_conf_path(&PathBuf::from(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../py"
    )))
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

/// Kullanıcının kabuk ayarlarından bağımsız pane çevresi.
fn pane_env(s: &Server) -> Vec<(&'static str, String)> {
    let home = s.path().to_str().unwrap().to_string();
    vec![
        ("PATH", "/usr/bin:/bin".into()),
        ("HOME", home),
        ("SHELL", "/bin/sh".into()),
        ("TERM", "xterm-256color".into()),
        ("LANG", "en_US.UTF-8".into()),
        ("COPS_TEST_MARK", "evet".into()),
    ]
}

fn spawn(s: &Server, name: &str, inner: &str) {
    let cwd = s.path().to_str().unwrap();
    s.tmux
        .spawn_direct(&conf(), name, cwd, inner, pane_env(s))
        .unwrap();
}

#[test]
fn tmux_and_bundled_conf_are_found() {
    assert!(tmux_available());
    assert!(conf().is_file());
}

#[test]
fn spawn_direct_uses_conf_env_and_cwd_and_keeps_the_session_after_exit() {
    let s = Server::new();
    spawn(&s, "a", "echo \"mark=$COPS_TEST_MARK cwd=$(pwd)\"");
    let want = format!("mark=evet cwd={}", s.path().display());
    wait_until(
        || {
            s.tmux
                .capture_plain("a", 50)
                .unwrap()
                .replace('\n', "")
                .contains(&want)
        },
        "cikti",
    );
    assert_eq!(
        s.raw(&["show-options", "-gv", "set-titles-string"]).trim(),
        "#S"
    );
    // CLI çıktı, `exec bash` oturumu açık tutuyor.
    wait_until(
        || s.tmux.session_panes("a").unwrap()[0].current_command == "bash",
        "kabuk",
    );
    assert!(s.tmux.has_session("a").unwrap());
    // Var olan oturumda `-A` bağlanmaya çalışır: terminal olmadığından başarısız, ikinci oturum açılmaz.
    let again = s
        .tmux
        .spawn_direct(&conf(), "a", "/", "sleep 60", pane_env(&s));
    assert!(again.is_err());
    assert_eq!(s.tmux.list_sessions().unwrap().len(), 1);
    s.tmux.kill_session("a").unwrap();
    assert!(!s.tmux.has_session("a").unwrap());
    assert!(s.tmux.kill_session("a").is_err());
}

#[test]
fn ghost_is_only_an_old_childless_shell() {
    let s = Server::new();
    spawn(&s, "ghost", "true");
    spawn(&s, "busy", "sleep 60");
    wait_until(
        || s.tmux.ghost_session("ghost", Some(now() + 100.0)),
        "hayalet",
    );
    assert!(
        !s.tmux.ghost_session("ghost", None),
        "genç oturum hayalet değil"
    );
    assert!(!s.tmux.ghost_session("busy", Some(now() + 100.0)));
    assert!(
        !s.tmux.ghost_session("ghos", Some(now() + 100.0)),
        "ön ek eşleşmesi"
    );
    let busy = s.tmux.session_panes("busy").unwrap()[0].pane_pid;
    assert!(!pid_childless(&busy.to_string()));
}

#[test]
fn tmux_backed_walks_ancestors_to_this_socket_only() {
    let s = Server::new();
    spawn(&s, "a", "sleep 60");
    let pane = s.tmux.session_panes("a").unwrap()[0].pane_pid;
    assert!(s.tmux.is_tmux_backed(pane));
    let other = Server::new();
    assert!(!other.tmux.is_tmux_backed(pane), "başka soket");
    assert!(!s.tmux.is_tmux_backed(std::process::id()));
}

#[test]
fn outer_bash_is_found_through_the_client_list() {
    let s = Server::new();
    let outer = Server::new();
    s.spawn("m", "exec sleep 60");
    let attach = format!(
        "exec bash -c \"env -u TMUX TMUX_TMPDIR='{}' tmux -L {} attach-session -t '=m:'; sleep 60\"",
        s.path().display(),
        s.tmux.socket()
    );
    outer.spawn("o", &attach);
    wait_until(|| s.tmux.client_count("m").unwrap() == 1, "istemci");
    let found = s.tmux.outer_bash_via_list_clients("m");
    assert_eq!(found.len(), 1);
    assert_eq!(
        found[0].0,
        outer.tmux.session_panes("o").unwrap()[0].pane_pid
    );
    assert!(found[0].1 > 1_000_000_000.0);
    assert_eq!(s.tmux.find_outer_bash_pids("m"), found);
}

#[test]
fn outer_bash_falls_back_to_scanning_command_lines() {
    let s = Server::new();
    let name = format!("cxrs-yedek-{}", std::process::id());
    let attach = s.tmux.attach_shell_fragment("/x.conf", &name);
    let scripts = [
        format!("read x # tmux new-session -A -s {name} -c /x"),
        format!("read x # {attach}; exec bash"),
        format!("read x # attach-session -t {name};"),
        // Eşleşmemeli: daha uzun ad.
        format!("read x # new-session -A -s {name}_1 -c /x"),
    ];
    let mut children: Vec<_> = scripts
        .iter()
        .map(|script| {
            Command::new("bash")
                .args(["-c", script])
                .stdin(Stdio::piped())
                .spawn()
                .unwrap()
        })
        .collect();
    let mut want: Vec<u32> = children[..3].iter().map(|c| c.id()).collect();
    want.sort_unstable();
    let mut got = Vec::new();
    wait_until(
        || {
            got = s
                .tmux
                .find_outer_bash_pids(&name)
                .iter()
                .map(|x| x.0)
                .collect();
            got.len() >= want.len()
        },
        "yedek tarama",
    );
    // Yalnız bu testin KENDİ süreçleri: stdin kapanınca `read` biter.
    for child in &mut children {
        drop(child.stdin.take());
        child.wait().unwrap();
    }
    assert_eq!(got, want);
}
