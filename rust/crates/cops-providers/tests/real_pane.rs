//! G4 gerçek [`Pane`] uygulayıcısı ([`TmuxPane`]): YALNIZ bu testin açtığı yalıtılmış sunucu (geçici `TMUX_TMPDIR` +
//! rastgele soket + `-f /dev/null`; `tests/real_tmux.rs` düzeni). Kullanıcının sunucusuna, `-L cops` soketine,
//! `~/.claude`a dokunulmaz; sunucu yalnız kendi soketiyle `kill-server` ile kapatılır. Her bekleme zaman aşımlı.
//! Pane'deki sahte claude ve sahte tmux betikleri alt süreçle yazılır (`write_exe`: paralel `fork` yazım tanıtıcısını
//! taşırsa `ETXTBSY`).
//!
//! Python ile birebirlik: aynı sahte claude TUI'sine Python `ClaudeProvider.apply_live_*_switch` /
//! `dismiss_stray_dialog` (gerçek `tmux_backend`, soket adı yamalı) ve Rust `Cli::Claude` + [`TmuxPane`] ayrı
//! oturumlarda koşar; TUI'nin aldığı baytlar karşılaştırılır.

use cops_providers::real::pane::TmuxPane;
use cops_providers::tui::{strip_ansi, DismissOutcome, Key, Pane, SwitchOutcome};
use cops_providers::Cli;
use cops_tmux::Tmux;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tempfile::TempDir;

fn repo() -> String {
    fs::canonicalize(concat!(env!("CARGO_MANIFEST_DIR"), "/../../.."))
        .unwrap()
        .to_string_lossy()
        .into_owned()
}

/// Çalıştırılabilir dosyayı ALT SÜREÇLE yaz (bu süreçte yazım tanıtıcısı açılmaz).
fn write_exe(path: &Path, body: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut child = Command::new("/bin/sh")
        .args(["-c", "cat > \"$1\" && chmod 755 \"$1\"", "sh"])
        .arg(path)
        .stdin(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(body.as_bytes())
        .unwrap();
    assert!(child.wait().unwrap().success());
}

fn wait_until(mut done: impl FnMut() -> bool, what: &str) {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !done() {
        assert!(Instant::now() < deadline, "beklenen durum oluşmadı: {what}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

struct Server {
    socket: String,
    dir: TempDir,
}

impl Server {
    fn new() -> Server {
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let socket = format!(
            "cxpane{}-{}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .subsec_nanos(),
            SEQ.fetch_add(1, Ordering::Relaxed),
            std::process::id()
        );
        Server {
            socket,
            dir: tempfile::tempdir().unwrap(),
        }
    }

    fn path(&self) -> &Path {
        self.dir.path()
    }

    fn pane(&self) -> TmuxPane {
        TmuxPane::new(Tmux::with_socket(self.socket.clone()).tmpdir(self.path()))
    }

    /// Crate'ten bağımsız ham tmux çağrısı (kurulum ve doğrulama).
    fn raw(&self, args: &[&str]) -> String {
        let out = Command::new("tmux")
            .args(["-u", "-L", &self.socket, "-f", "/dev/null"])
            .args(args)
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "tmux {args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        String::from_utf8_lossy(&out.stdout).into_owned()
    }

    fn spawn(&self, name: &str, command: &str) {
        let cwd = self.path().to_str().unwrap().to_string();
        self.raw(&[
            "new-session",
            "-d",
            "-s",
            name,
            "-x",
            "100",
            "-y",
            "30",
            "-c",
            &cwd,
            command,
        ]);
    }

    fn screen(&self, name: &str) -> String {
        self.raw(&["capture-pane", "-p", "-t", &format!("={name}:")])
    }

    fn wait_screen(&self, name: &str, needle: &str) {
        wait_until(|| self.screen(name).contains(needle), needle);
    }

    fn in_mode(&self, name: &str) -> String {
        self.raw(&[
            "display-message",
            "-p",
            "-t",
            &format!("={name}:"),
            "#{pane_in_mode}",
        ])
    }

    /// Sahte claude TUI'si (`mode`): aldığı her baytı `<ad>.log`a yazar.
    fn tui(&self, name: &str, mode: &str) -> PathBuf {
        let script = self.path().join("fake_claude.py");
        if !script.exists() {
            write_exe(&script, FAKE_CLAUDE);
        }
        let log = self.path().join(format!("{name}.log"));
        self.spawn(
            name,
            &format!(
                "python3 -I '{}' '{}' {mode}",
                script.display(),
                log.display()
            ),
        );
        self.wait_screen(name, "READY");
        log
    }

    /// Python `ClaudeProvider` yöntemini bu sunucuda koşar (`tmux_backend.TMUX_SOCKET` yamalı, geçici HOME/durum).
    fn python(&self, op: &str, name: &str, arg: &str) {
        let home = self.path().join("home");
        fs::create_dir_all(&home).unwrap();
        let out = Command::new("python3")
            .args(["-I", "-c", PY_DRIVER, &repo(), &self.socket, op, name, arg])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", &home)
            .env("LANG", "C.UTF-8")
            .env("CLAUDEOPS_DIR", self.path().join("state"))
            .env("TMUX_TMPDIR", self.path())
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        let _ = Command::new("tmux")
            .args(["-L", &self.socket, "kill-server"])
            .env("TMUX_TMPDIR", self.path())
            .env_remove("TMUX")
            .output();
    }
}

const PY_DRIVER: &str = r#"
import sys
sys.path.insert(0, sys.argv[1] + "/py")
from claudeops import tmux_backend as t
t.TMUX_SOCKET = sys.argv[2]
from claudeops.providers.claude_provider import ClaudeProvider
p = ClaudeProvider()
op, name, arg = sys.argv[3], sys.argv[4], sys.argv[5]
if op == "model":
    p.apply_live_model_switch(name, arg)
elif op == "effort":
    p.apply_live_effort_switch(name, arg)
elif op == "dismiss":
    p.dismiss_stray_dialog(name)
elif op == "capture":
    import json
    print(json.dumps(t.tmux_capture(name, lines=int(arg))))
"#;

/// Sahte claude: ham kip (maskesiz), satırı Enter (`\r`) bitirir, `Down` (`ESC [B` / `ESC OB`) seçimi değiştirir.
/// Her durumda ekranı baştan çizer: geçmiş + (açık diyalog YA DA boş giriş kutusu). Diyalog başlığı kelime kelime
/// renkli (gerçek claude gibi: ham metinde "Switch model?" geçmez).
const FAKE_CLAUDE: &str = r#"#!/usr/bin/env python3
import os, sys, tty
log = open(sys.argv[1], "ab", buffering=0)
mode = sys.argv[2]
if mode == "masked":
    import termios
    a = termios.tcgetattr(0)
    a[3] = (a[3] | termios.ICANON) & ~termios.ECHO
    termios.tcsetattr(0, termios.TCSANOW, a)
else:
    tty.setraw(0)
history = []
pending = None
choice = 1
def draw():
    s = "\x1b[2J\x1b[H" + "".join("  ⎿  " + h + "\r\n" for h in history) + "READY\r\n"
    rule = "\x1b[38;5;244m" + "─" * 40 + "\x1b[0m\r\n"
    if pending is None:
        s += rule + "❯ " + ("yarim" if mode == "draft" else "") + "\r\n" + rule + "  auto mode on"
    else:
        kind, val = pending
        title = "Switch model?" if kind == "model" else "Change effort level?"
        label = "Sonnet 5.5" if val == "sonnet" else val
        words = ["\x1b[1;38;5;220m" + w + "\x1b[0m\x1b[39m" for w in title.split(" ")]
        yes, no = ("❯", " ") if choice == 1 else (" ", "❯")
        s += (rule + " " + " ".join(words) + "\r\n\r\n \x1b[36m" + yes + " 1. Yes, switch to " + label +
              "\x1b[0m\r\n " + no + " 2. No, go back\r\n\r\n Enter to confirm · Esc to cancel")
    os.write(1, s.encode())
if mode in ("stray", "masked"):
    pending = ("model", "sonnet")
draw()
buf = b""
while True:
    b = os.read(0, 1024)
    if not b:
        break
    log.write(b)
    buf += b
    for seq in (b"\x1b[B", b"\x1bOB"):
        if seq in buf:
            buf = buf.replace(seq, b"")
            choice = 2
            draw()
    while b"\r" in buf or b"\n" in buf:
        i = min(x for x in (buf.find(b"\r"), buf.find(b"\n")) if x >= 0)
        line, buf = buf[:i].decode("utf-8", "replace"), buf[i + 1:]
        if mode == "silent":
            continue
        if pending is not None and line == "":
            kind, val = pending
            pending = None
            if kind == "model":
                history.append("Set model to " + val if choice == 1 else "Kept model as opus")
            else:
                history.append("Set effort level to " + val)
        elif line.startswith("/model ") or line.startswith("/effort "):
            kind, val = line[1:].split(" ", 1)
            if mode == "dialog":
                pending, choice = (kind, val), 1
            else:
                history.append(("Set model to " if kind == "model" else "Set effort level to ") + val)
        draw()
"#;

/// Dosya `want` uzunluğuna ulaşana dek (en çok 15 sn) bekler, sonra kısa süre daha (fazlalık da görülsün).
fn read_log(path: &Path, want: usize) -> Vec<u8> {
    wait_until(
        || fs::metadata(path).is_ok_and(|m| m.len() >= want as u64),
        "günlük boyutu",
    );
    std::thread::sleep(Duration::from_millis(300));
    fs::read(path).unwrap()
}

/// Aynı senaryo iki tarafta: Python ve Rust ayrı oturumlarda aynı baytları göndermeli.
fn both(mode: &str, op: &str, arg: &str, want: &[u8]) -> (Server, SwitchOutcome) {
    let s = Server::new();
    let py_log = s.tui("py", mode);
    let rs_log = s.tui("rs", mode);
    s.python(op, "py", arg);
    let p = s.pane();
    let outcome = match op {
        "model" => Cli::Claude.apply_live_model_switch(&p, "rs", arg),
        "effort" => Cli::Claude.apply_live_effort_switch(&p, "rs", arg),
        _ => unreachable!(),
    };
    assert_eq!(read_log(&py_log, want.len()), want, "python");
    assert_eq!(read_log(&rs_log, want.len()), want, "rust");
    assert_eq!(s.in_mode("rs"), "0\n", "copy-mode'a girilmedi");
    (s, outcome)
}

#[test]
fn model_switch_confirms_the_dialog_like_python() {
    let (s, out) = both("dialog", "model", "sonnet", b"/model sonnet\r\r");
    assert_eq!(out, SwitchOutcome::Done { confirmed: true });
    assert!(s.screen("rs").contains("Set model to sonnet"));
}

#[test]
fn model_switch_without_dialog_sends_no_extra_enter_like_python() {
    let (_s, out) = both("direct", "model", "sonnet", b"/model sonnet\r");
    assert_eq!(out, SwitchOutcome::Done { confirmed: false });
}

#[test]
fn effort_switch_confirms_the_dialog_like_python() {
    let (s, out) = both("dialog", "effort", "high", b"/effort high\r\r");
    assert_eq!(out, SwitchOutcome::Done { confirmed: true });
    assert!(s.screen("rs").contains("Set effort level to high"));
}

#[test]
fn stray_dialog_is_declined_with_down_enter_like_python() {
    let s = Server::new();
    let py_log = s.tui("py", "stray");
    let rs_log = s.tui("rs", "stray");
    s.python("dismiss", "py", "-");
    assert_eq!(
        Cli::Claude.dismiss_stray_dialog(&s.pane(), "rs"),
        DismissOutcome::Closed
    );
    let py = read_log(&py_log, 4);
    assert_eq!(read_log(&rs_log, py.len()), py);
    assert!(py == b"\x1b[B\r" || py == b"\x1bOB\r", "{py:?}");
    s.wait_screen("rs", "Kept model as opus");
    s.wait_screen("py", "Kept model as opus");
}

/// Ekranda diyalog yoksa iki taraf da hiç tuş basmaz (6 sn sınır).
#[test]
fn no_dialog_means_no_keys_on_either_side() {
    let s = Server::new();
    let py_log = s.tui("py", "silent");
    let rs_log = s.tui("rs", "silent");
    let t0 = Instant::now();
    std::thread::scope(|sc| {
        sc.spawn(|| s.python("dismiss", "py", "-"));
        assert_eq!(
            Cli::Claude.dismiss_stray_dialog(&s.pane(), "rs"),
            DismissOutcome::NotSeen
        );
    });
    let took = t0.elapsed();
    assert!(
        took >= Duration::from_secs(6) && took < Duration::from_secs(15),
        "{took:?}"
    );
    assert_eq!(fs::read(py_log).unwrap(), b"");
    assert_eq!(fs::read(rs_log).unwrap(), b"");
}

/// Gizli girdi bekleyen pane: iki tarafta da hiçbir şey ulaşmaz. Açık diyalog varken komut hiç gönderilmez; Rust tuşu
/// maske yüzünden reddeder (Python `tmux_send_special_key` maske denetlemez: `Down` kanonik satır arabelleğinde kalır,
/// ekran değişmediği için Enter basmaz).
#[test]
fn masked_pane_gets_no_command_and_no_enter() {
    let s = Server::new();
    let py_log = s.tui("py", "masked");
    let rs_log = s.tui("rs", "masked");
    let p = s.pane();
    assert_eq!(p.tmux().pane_is_masked_input("rs"), Some(true));
    s.python("model", "py", "sonnet");
    assert_eq!(
        Cli::Claude.apply_live_model_switch(&p, "rs", "sonnet"),
        SwitchOutcome::DialogOpen
    );
    assert!(!p.send_text("rs", "gizli", 0.0));
    assert!(!p.send_key("rs", Key::Enter));
    assert_eq!(
        Cli::Claude.dismiss_stray_dialog(&p, "rs"),
        DismissOutcome::LeftOpen
    );
    s.python("dismiss", "py", "-");
    std::thread::sleep(Duration::from_millis(300));
    assert_eq!(fs::read(py_log).unwrap(), b"");
    assert_eq!(fs::read(rs_log).unwrap(), b"");
}

/// Kutuda yazılı taslak: iki taraf da komut göndermez.
#[test]
fn a_typed_draft_gets_no_command_on_either_side() {
    let s = Server::new();
    let py_log = s.tui("py", "draft");
    let rs_log = s.tui("rs", "draft");
    s.python("model", "py", "sonnet");
    assert_eq!(
        Cli::Claude.apply_live_model_switch(&s.pane(), "rs", "sonnet"),
        SwitchOutcome::Draft
    );
    std::thread::sleep(Duration::from_millis(300));
    assert_eq!(fs::read(py_log).unwrap(), b"");
    assert_eq!(fs::read(rs_log).unwrap(), b"");
}

/// Tam hedef: `k` yokken `k_1`e hiçbir şey gitmez, `k` yakalanmaz.
#[test]
fn prefix_name_never_reaches_another_session() {
    let s = Server::new();
    let log = s.tui("k_1", "silent");
    let p = s.pane();
    assert!(!p.send_text("k", "yanlis", 0.0));
    assert!(!p.send_key("k", Key::Enter));
    assert!(!p.send_key("k", Key::Down));
    assert_eq!(p.capture("k", 20), None);
    for bad in ["", "a:b", "k_1;", "$0", "#{pane_pid}"] {
        assert!(!p.send_text(bad, "yanlis", 0.0), "{bad:?}");
        assert_eq!(p.capture(bad, 20), None, "{bad:?}");
    }
    assert!(p.send_text("k_1", "dogru", 0.0));
    assert_eq!(read_log(&log, 6), b"dogru\r");
}

/// Metin argv'ye girmez: araya konan sahte tmux her argv'yi kaydeder, gerçek tmux'a devreder.
#[test]
fn text_never_appears_in_tmux_argv() {
    let s = Server::new();
    let log = s.tui("a", "silent");
    let argv_log = s.path().join("argv.log");
    let wrapper = s.path().join("bin/tmux-wrap");
    write_exe(
        &wrapper,
        &format!(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{}'\nexec tmux \"$@\"\n",
            argv_log.display()
        ),
    );
    let p = TmuxPane::new(
        Tmux::with_socket(s.socket.clone())
            .tmpdir(s.path())
            .program(&wrapper),
    );
    let secret = "GIZLI-ARGV-7f3a satır;\niki";
    assert!(p.send_text("a", secret, 0.0));
    assert!(p.send_key("a", Key::Enter));
    assert!(p.capture("a", 20).is_some());
    // Yapıştırma satır sonunu `\r` yapar (tmux `paste-buffer`), sonra metnin Enter'ı ve ayrı tuş.
    let want = "GIZLI-ARGV-7f3a satır;\riki\r\r".as_bytes();
    assert_eq!(read_log(&log, want.len()), want);
    let argv = fs::read_to_string(&argv_log).unwrap();
    assert!(!argv.contains("GIZLI") && !argv.contains("satır"), "{argv}");
    assert!(
        argv.contains("load-buffer -b") && argv.contains("send-keys -t =a: Enter"),
        "{argv}"
    );
    assert!(argv.contains("capture-pane -t =a: -e -p -S -20"), "{argv}");
    assert!(!argv.contains("copy-mode"), "{argv}");
}

/// Yakalama ANSI'yi korur (temizlik çekirdekte), Python `tmux_capture` ile aynı metni verir, copy-mode'a sokmaz.
#[test]
fn capture_matches_python_and_keeps_ansi() {
    let s = Server::new();
    s.spawn(
        "c",
        r"printf '\033[1mSwitch\033[0m \033[1mmodel?\033[0m\nşğüİ satır\n\nson\n'; echo READY; sleep 60",
    );
    s.wait_screen("c", "READY");
    s.spawn("e", "echo READY; sleep 60");
    s.wait_screen("e", "READY");
    let p = s.pane();
    for (name, lines) in [("c", 20u32), ("c", 0), ("e", 2000), ("yok", 20)] {
        let rust = p.capture(name, lines);
        let out = Command::new("python3")
            .args([
                "-I",
                "-c",
                PY_DRIVER,
                &repo(),
                &s.socket,
                "capture",
                name,
                &lines.to_string(),
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", s.path())
            .env("LANG", "C.UTF-8")
            .env("CLAUDEOPS_DIR", s.path().join("state"))
            .env("TMUX_TMPDIR", s.path())
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        let py: Option<String> = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(rust, py, "{name} {lines}");
    }
    let raw = p.capture("c", 20).unwrap();
    assert!(raw.contains('\u{1b}'), "{raw:?}");
    assert!(!raw.contains("Switch model?"));
    assert!(strip_ansi(&raw).contains("Switch model?\nşğüİ satır"));
    assert_eq!(s.in_mode("c"), "0\n");
}

/// Her çağrı 5 sn'de biter: hiç dönmeyen tmux (sahte) panik değil false / None verir.
#[test]
fn hung_tmux_times_out_to_false_and_none() {
    let s = Server::new();
    let wrapper = s.path().join("bin/tmux-hang");
    write_exe(&wrapper, "#!/bin/sh\nexec sleep 60\n");
    let p = TmuxPane::new(
        Tmux::with_socket(s.socket.clone())
            .tmpdir(s.path())
            .program(&wrapper),
    );
    let t0 = Instant::now();
    let (a, b, c) = std::thread::scope(|sc| {
        let a = sc.spawn(|| p.capture("x", 20));
        let b = sc.spawn(|| p.send_key("x", Key::Down));
        let c = p.send_text("x", "metin", 0.0);
        (a.join().unwrap(), b.join().unwrap(), c)
    });
    let took = t0.elapsed();
    assert_eq!((a, b, c), (None, false, false));
    assert!(
        took >= Duration::from_millis(4900) && took < Duration::from_secs(9),
        "{took:?}"
    );
}
