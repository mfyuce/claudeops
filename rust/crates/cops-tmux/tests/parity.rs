//! Python paritesi: aynı pane içeriğinde `claudeops.tmux_backend` ile Rust aynı sonucu verir.
//! `python3` ister; çekirdek `py/` ağacını salt okur (`-B`: bytecode yazmaz).

mod common;

use std::io::Write;
use std::os::unix::fs::{symlink, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common::{read_at_least, wait_until, Server};
use cops_tmux::{
    ctx_label, dim_fg, input_box, patterns, pid_childless, segment_typed, shell_quote, strip_ansi,
    tmux_available, tmux_conf_path, tty_is_masked, typed_input_in_box, CtxPusher, MaskGuard,
    PaneSize, Tmux, TmuxError, ALLOWED_SPECIAL_KEYS, ANCESTOR_WALK_LIMIT, BOX_RULE_CHAR,
    DEFAULT_TIMEOUT, GHOST_MIN_AGE_SECONDS, GHOST_SHELLS, HISTORY_LIMIT, PROMPT, RAW_PROBE_TTL,
    RESIZE_COLS, RESIZE_ROWS, SNAPSHOT_FORMAT, TMUX_SOCKET,
};
use serde_json::{json, Value};

/// Çekirdek `py/` dizini (salt okunur).
const CORE_PY: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../py");

/// `parity.py`yi verilen soket ve soket dizini (`TMUX_TMPDIR`) ile koşar. `HOME` ve `CLAUDEOPS_DIR` geçici dizinin
/// altındadır; `envs` ek çevre değişkenleridir (ör. sahte tmux için `PATH`, `LC_ALL`).
fn run_python(socket: &str, tmpdir: &Path, envs: &[(&str, String)], calls: &[Value]) -> Vec<Value> {
    let home = tmpdir.join("py-home");
    std::fs::create_dir_all(&home).unwrap();
    // `python3` çağıranın `PATH`inden çözülür (`envs` içindeki `PATH` yalnız Python'un göreceği yoldur).
    let python3 = std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .map(|d| d.join("python3"))
        .find(|p| p.is_file())
        .expect("python3");
    let mut cmd = Command::new(python3);
    cmd.arg("-B")
        .arg(format!("{}/tests/parity.py", env!("CARGO_MANIFEST_DIR")))
        .env("PYTHONPATH", CORE_PY)
        .env("CLAUDEOPS_DIR", tmpdir.join("state"))
        .env("HOME", &home)
        .env("TMUX_TMPDIR", tmpdir)
        .env_remove("TMUX")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped());
    for (k, v) in envs {
        cmd.env(k, v);
    }
    let mut child = cmd.spawn().expect("python3");
    let req = json!({"socket": socket, "calls": calls}).to_string();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(req.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(out.status.success(), "parity.py başarısız");
    let res: Vec<Value> = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(res.len(), calls.len(), "izinli olmayan işlev çağrıldı");
    res
}

fn python(s: &Server, calls: &[Value]) -> Vec<Value> {
    run_python(s.tmux.socket(), s.path(), &[], calls)
}

/// Python'a da Rust'a da aynı çağrılar; sonuçlar sırayla eşit olmalı.
fn assert_same(s: &Server, calls: &[Value], rust: &[Value]) {
    for (i, (py, rs)) in python(s, calls).iter().zip(rust).enumerate() {
        assert_eq!(py, rs, "fark: {}", calls[i]);
    }
}

fn size_json(p: PaneSize) -> Value {
    json!([p.cols, p.rows, p.history_size, p.alternate_on])
}

/// ANSI renkler, OSC, geniş/Türkçe harfler, sarılan satır, geçmiş ve Claude benzeri giriş kutusu.
const PAINT: &str = r##"#!/bin/sh
i=1; while [ $i -le 2300 ]; do printf '\033[3%dmsatir %d\033[0m şğüİ 漢字\n' $((i % 8)) $i; i=$((i+1)); done
printf '\033]8;;http://example.invalid\033\\baglanti\033]8;;\033\\ \033]0;baslik\007son\n'
printf '\033[38;2;10;200;30m%0200d\033[0m\n' 7
printf 'sekme\tvar   \n\033[7mters\033[0m \033[4malt\033[24m\n'
printf '────────────────────\n'
printf '\342\235\257\302\240yazilan \033[38;5;244monerilen\033[39m metin\n'
printf 'ikinci satir \033[2msoluk\033[22m\n'
printf '────────────────────\n'
printf '  \033[1m\033[38;5;220mplan\033[0m mode on\n'
echo READY
exec sleep 900
"##;

#[test]
fn reads_match_python() {
    let s = Server::new();
    let script = s.path().join("paint.sh");
    std::fs::write(&script, PAINT).unwrap();
    s.spawn("a", &format!("exec sh '{}'", script.display()));
    s.wait_screen("a", "READY");
    s.spawn("alt", r"printf '\033[?1049h'; echo READY; exec sleep 900");
    s.wait_screen("alt", "READY");
    s.spawn_ready("pw", "stty icanon -echo", "exec sleep 900");
    s.spawn("pre_1", "exec sleep 900");

    let t = &s.tmux;
    let ranges: [(i64, i64); 6] = [
        (0, 0),
        (-5, 3),
        (-2000, -1990),
        (-99999, -2290),
        (10, 999),
        (5, 2),
    ];
    let names = ["a", "alt", "pw", "pre_1", "pre", "yok"];
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for name in names {
        calls.push(json!(["tmux_has_session", name]));
        rust.push(json!(t.has_session(name).unwrap()));
        for lines in [2000u32, 40, 8, 0] {
            calls.push(json!(["tmux_capture", name, lines]));
            rust.push(json!(t.capture(name, lines).ok()));
        }
        for (start, end) in ranges {
            calls.push(json!(["tmux_capture_range", name, start, end]));
            rust.push(json!(t.capture_range(name, start, end).ok()));
        }
        calls.push(json!(["tmux_pane_size", name]));
        rust.push(json!(t.pane_size(name).ok().map(size_json)));
        calls.push(json!(["tmux_pane_snapshot", name]));
        rust.push(json!(t.snapshot(name).ok().map(|x| {
            let mut head = size_json(x.size);
            head.as_array_mut().unwrap().push(json!(x.tty));
            json!([head, x.text])
        })));
        calls.push(json!(["pane_is_masked_input", name]));
        rust.push(json!(t.pane_is_masked_input(name)));
        calls.push(json!(["tmux_client_count", name]));
        rust.push(json!(t.client_count(name).ok()));
    }
    for (i, (py, rs)) in python(&s, &calls).iter().zip(&rust).enumerate() {
        assert_eq!(py, rs, "fark: {}", calls[i]);
    }

    // Aynı gerçek ekran üzerinde saf işlevler (önemsiz eşitlik olmasın diye içerik de denetlenir).
    let screen = t.capture("a", 2000).unwrap();
    assert!(screen.lines().count() > 1800 && screen.contains("\x1b["));
    assert_eq!(typed_input_in_box(&screen), Some(true));
    assert!(input_box(&screen).unwrap().typed.contains("ikinci satir"));
    assert!(t.snapshot("alt").unwrap().size.alternate_on);
    assert_eq!(t.pane_is_masked_input("pw"), Some(true));
    compare_pure(&s, &[screen, t.snapshot("a").unwrap().text]);
}

fn box_json(text: &str) -> Value {
    json!(input_box(text).map(|b| [b.plain, b.typed, b.outside]))
}

fn compare_pure(s: &Server, inputs: &[String]) {
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for text in inputs {
        calls.push(json!(["strip_ansi", text]));
        rust.push(json!(strip_ansi(text)));
        calls.push(json!(["typed_input_in_box", text]));
        rust.push(json!(typed_input_in_box(text)));
        calls.push(json!(["input_box", text]));
        rust.push(box_json(text));
    }
    for (i, (py, rs)) in python(s, &calls).iter().zip(&rust).enumerate() {
        assert_eq!(py, rs, "fark: {}", calls[i]);
    }
}

#[test]
fn pure_functions_match_python_on_random_screens() {
    const TOKENS: &[&str] = &[
        "❯",
        "❯",
        "❯",
        "────",
        "────",
        "───",
        "\n",
        "\n",
        "\n",
        " ",
        "\u{a0}",
        "\u{2502}",
        "a",
        "devam",
        "ş",
        "\t",
        "\x1c",
        "\u{2028}",
        "\x1b[0m",
        "\x1b[m",
        "\x1b[;m",
        "\x1b[1m",
        "\x1b[2m",
        "\x1b[22m",
        "\x1b[39m",
        "\x1b[90m",
        "\x1b[31m",
        "\x1b[97m",
        "\x1b[38;5;240m",
        "\x1b[38;5;220m",
        "\x1b[38;5;8m",
        "\x1b[38;5;253m",
        "\x1b[48;5;244m",
        "\x1b[38;2;120;120;124m",
        "\x1b[38;2;200;100;100m",
        "\x1b[38;2;30;30;30m",
        "\x1b[48;2;2;2;2m",
        "\x1b[38;2m",
        "\x1b[38;5m",
        "\x1b[38;5;99999999999999999999m",
        "\x1b[0;2;38;5;220m",
        "\x1b[?25l",
        "\x1b[10C",
        "\x1b[K",
        "\x1b]0;t\x07",
        "\x1b]8;;u\x1b\\",
        "\x1b]",
        "\x07",
        "\x1b[",
        "\x1b",
    ];
    let s = Server::new();
    let mut state = 0x2545_f491_4f6c_dd1du64;
    let mut next = move |n: usize| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state % n as u64) as usize
    };
    let inputs: Vec<String> = (0..6000)
        .map(|i| {
            let mut text = if i % 2 == 0 {
                "────\n❯".to_string()
            } else {
                String::new()
            };
            for _ in 0..next(40) {
                text.push_str(TOKENS[next(TOKENS.len())]);
            }
            if i % 3 == 0 {
                text.push_str("\n────\n");
            }
            text
        })
        .collect();
    // Derlem her dalı gerçekten gezsin.
    for want in [Some(true), Some(false), None] {
        assert!(
            inputs.iter().any(|t| typed_input_in_box(t) == want),
            "{want:?}"
        );
    }
    assert!(inputs.iter().filter(|t| input_box(t).is_some()).count() > 100);
    compare_pure(&s, &inputs);

    let values: [i64; 11] = [
        -1, 0, 1, 499, 500, 1500, 2500, 3500, 120_400, 299_500, 1_000_000,
    ];
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for tokens in values.iter().map(|&v| Some(v)).chain([None]) {
        for warn in values {
            calls.push(json!(["ctx_label", tokens, warn]));
            rust.push(json!(ctx_label(tokens, warn)));
        }
    }
    assert_eq!(python(&s, &calls), rust);
}

#[test]
fn writes_match_python() {
    let s = Server::new();
    let sink = |name: &str, bracketed: bool| {
        let out = s.path().join(format!("{name}.out"));
        let mode = if bracketed {
            r"stty raw -echo; printf '\033[?2004h'"
        } else {
            "stty raw -echo"
        };
        s.spawn_ready(name, mode, &format!("exec cat > '{}'", out.display()));
        out
    };
    let long = format!("{};{}", "ş".repeat(1999), "q;".repeat(2000));
    for bracketed in [false, true] {
        let suffix = if bracketed { "b" } else { "n" };
        let (py_name, rs_name) = (format!("py{suffix}"), format!("rs{suffix}"));
        let (py_out, rs_out) = (sink(&py_name, bracketed), sink(&rs_name, bracketed));
        let t = &s.tmux;
        let texts = [
            "merhaba",
            "foo;",
            "x;y;",
            r"bar\;",
            ";",
            "-x",
            "--",
            "",
            "a\nb;\n- c",
            "cr\r\nlf",
            "tek\r",
        ];
        let raws = [
            "foo;",
            r"bar\;",
            ";",
            "-",
            "\u{3}\u{1b}[A",
            "a\0b",
            "",
            "\0",
            "satır\nsonu",
            long.as_str(),
        ];
        let keys = [
            "Up", "Down", "Left", "Right", "Tab", "BTab", "Enter", "Escape", "C-d", "C-c", "C-z",
            "q",
        ];
        let mut calls = Vec::new();
        let mut rust = Vec::new();
        for text in texts {
            calls.push(json!(["tmux_send_keys", py_name, text, 0.0, false]));
            rust.push(
                t.send_text(&rs_name, text, Duration::ZERO, MaskGuard::UserTyped)
                    .is_ok(),
            );
        }
        for data in raws {
            calls.push(json!(["tmux_send_raw", py_name, data]));
            rust.push(t.send_raw(&rs_name, data, MaskGuard::UserTyped).is_ok());
        }
        for key in keys {
            calls.push(json!(["tmux_send_special_key", py_name, key]));
            rust.push(
                t.send_special_key(&rs_name, key, MaskGuard::UserTyped)
                    .is_ok(),
            );
        }
        // Bitiş işareti: iki dosya da buna ulaşınca karşılaştır.
        calls.push(json!(["tmux_send_raw", py_name, "<SON>"]));
        rust.push(t.send_raw(&rs_name, "<SON>", MaskGuard::UserTyped).is_ok());
        let py: Vec<bool> = python(&s, &calls)
            .iter()
            .map(|v| v.as_bool().unwrap())
            .collect();
        assert_eq!(py, rust);
        common::wait_until(
            || {
                [&py_out, &rs_out]
                    .iter()
                    .all(|p| std::fs::read(p).is_ok_and(|b| b.ends_with(b"<SON>")))
            },
            "bitiş işareti",
        );
        let a = read_at_least(&py_out, 1);
        assert!(a.len() > long.len());
        assert_eq!(a, read_at_least(&rs_out, 1), "bracketed={bracketed}");
    }

    // Boyut: sınırlar ve sonuç aynı.
    s.spawn("pys", "exec sleep 900");
    s.spawn("rss", "exec sleep 900");
    for (cols, rows) in [(20, 5), (500, 200), (19, 30), (80, 201), (111, 33)] {
        let py = python(
            &s,
            &[
                json!(["tmux_resize_window", "pys", cols, rows]),
                json!(["tmux_pane_size", "pys"]),
            ],
        );
        assert_eq!(
            py[0],
            json!(s.tmux.resize_window("rss", cols, rows).is_ok())
        );
        assert_eq!(py[1], size_json(s.tmux.pane_size("rss").unwrap()));
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Genişletilmiş parite (docs/rs-tmux.md "Açık işler" 2): sabitler, saf yardımcılar, sahte tmux'ta argv + sonuç,
// gerçek tmux'ta yaşam döngüsü/istemci işlevleri ve P1-P7 eşliği.

fn core_conf() -> PathBuf {
    tmux_conf_path(Path::new(CORE_PY))
}

#[test]
fn constants_patterns_and_shell_fragments_match_python() {
    let s = Server::new();
    let consts: Vec<(&str, Value)> = vec![
        ("TMUX_SOCKET", json!(TMUX_SOCKET)),
        ("_TIMEOUT", json!(DEFAULT_TIMEOUT.as_secs_f64())),
        ("_ANCESTOR_WALK_LIMIT", json!(ANCESTOR_WALK_LIMIT)),
        ("ALLOWED_SPECIAL_KEYS", {
            let mut keys = ALLOWED_SPECIAL_KEYS.to_vec();
            keys.sort_unstable();
            json!(keys)
        }),
        ("RESIZE_COLS", json!([RESIZE_COLS.0, RESIZE_COLS.1])),
        ("RESIZE_ROWS", json!([RESIZE_ROWS.0, RESIZE_ROWS.1])),
        ("_RAW_PROBE_TTL", json!(RAW_PROBE_TTL.as_secs_f64())),
        ("HISTORY_LIMIT", json!(HISTORY_LIMIT)),
        ("_SNAPSHOT_FORMAT", json!(SNAPSHOT_FORMAT)),
        ("_BOX_RULE_CHARS", json!(BOX_RULE_CHAR.to_string())),
        ("_PROMPT_CHAR", json!(PROMPT.to_string())),
        ("_GHOST_SHELLS", json!(GHOST_SHELLS)),
        ("GHOST_MIN_AGE_SECONDS", json!(GHOST_MIN_AGE_SECONDS)),
        // Başlangıçta boş önbellek (Rust: `CtxPusher::new()`).
        ("_CTX_PUSHED", json!({})),
    ];
    let mut calls: Vec<Value> = Vec::new();
    let mut rust: Vec<Value> = Vec::new();
    for (name, value) in consts {
        calls.push(json!(["const", name]));
        rust.push(value);
    }
    for (name, pattern) in patterns() {
        calls.push(json!(["const", name]));
        rust.push(json!(pattern));
    }
    calls.push(json!(["tmux_available"]));
    rust.push(json!(tmux_available()));
    calls.push(json!(["tmux_conf_path"]));
    let conf = core_conf().to_str().unwrap().to_string();
    rust.push(json!(conf));
    calls.push(json!(["_base_argv"]));
    rust.push(json!(s.tmux.base_argv()));
    let names = [
        "a",
        "",
        "$0",
        "zeta:0",
        "semi;",
        "we'ird name",
        "ş",
        "-x",
        "a.b",
        "x\"y",
        "a\nb",
        "%1",
    ];
    let cwds = ["/", "/tmp/a b", "", "/t;", "çalışma"];
    let inners = [
        "claude --model x",
        "",
        "a 'b' \"c\"; exec bash",
        "ş\t$HOME",
        "x;",
    ];
    for arg in ["semi;", "a;b", r"bar\;", ";", "", "x", "ş;"] {
        calls.push(json!(["_tmux_arg", arg]));
        rust.push(json!(cops_tmux::escape_arg(arg)));
    }
    for value in [
        "/a/b",
        "d#(touch Y)",
        "a#[x]",
        "a##[x]",
        "#",
        "##",
        "a#",
        "#{x}#[y]#z",
        "[#]",
        "ş#ğ",
    ] {
        calls.push(json!(["_tmux_format_literal", value]));
        rust.push(json!(cops_tmux::format_literal(value)));
    }
    for name in names.iter().chain(&[
        "=eq",
        "@1",
        "$",
        "a:",
        ":",
        "a#b",
        "#",
        "a\nb",
        "a\x7f",
        "a\u{85}",
        "a\u{200b}",
    ]) {
        calls.push(json!(["_addressable", name]));
        rust.push(json!(cops_tmux::addressable(name)));
    }
    for name in names {
        calls.push(json!(["_exact", name]));
        rust.push(text_or_value_error(cops_tmux::exact_target(name)));
        calls.push(json!(["tmux_attach_shell_fragment", name]));
        rust.push(text_or_value_error(
            s.tmux.attach_shell_fragment(&conf, name),
        ));
        for cwd in cwds {
            for inner in inners {
                calls.push(json!(["tmux_new_session_shell_fragment", name, cwd, inner]));
                rust.push(text_or_value_error(
                    s.tmux.new_session_shell_fragment(&conf, name, cwd, inner),
                ));
            }
        }
    }
    assert_same(&s, &calls, &rust);
    // Kabuk alıntısı her parçada `shlex.quote` ile aynı (parçalar yukarıda karşılaştırıldı; burada doğrudan da).
    assert_eq!(shell_quote("we'ird"), "'we'\"'\"'ird'");
}

#[test]
fn dim_fg_and_segment_typed_match_python() {
    const PARAMS: &[u64] = &[
        0, 1, 2, 4, 5, 8, 22, 30, 31, 37, 38, 39, 48, 59, 60, 90, 91, 97, 102, 120, 124, 145, 200,
        201, 231, 232, 244, 252, 253, 255, 99_999,
    ];
    const SEGS: &[&str] = &[
        "❯", " ", "\u{a0}", "\u{2502}", "a", "ş", "\t", "\x1c", "\x1f", "\u{2028}", "\u{3000}",
        "\u{200b}", "\u{180e}", "\u{85}", "x y", "❯❯",
    ];
    let s = Server::new();
    let mut state = 0x9e37_79b9_7f4a_7c15u64;
    let mut next = move |n: usize| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state % n as u64) as usize
    };
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for i in 0..3000 {
        let params: Vec<u64> = (0..next(9)).map(|_| PARAMS[next(PARAMS.len())]).collect();
        calls.push(json!(["_is_dim_fg", params, i % 2 == 0]));
        rust.push(json!(dim_fg(&params)));
        let seg: String = (0..next(6)).map(|_| SEGS[next(SEGS.len())]).collect();
        let (dim, seen) = (next(2) == 0, next(2) == 0);
        calls.push(json!(["_seg_typed", seg, dim, seen]));
        rust.push(json!(segment_typed(&seg, dim, seen)));
    }
    // Derlem dalları gezsin.
    for want in [json!(true), json!(false), Value::Null] {
        assert!(rust.iter().step_by(2).any(|v| *v == want), "{want}");
    }
    assert_same(&s, &calls, &rust);
}

/// Sahte tmux (`fake_tmux.sh`, sunucu YOK): Python ve Rust aynı çağrıyı yapar, argv kayıtları ve sonuçlar karşılaştırılır.
struct Fake {
    dir: tempfile::TempDir,
    tmux: Tmux,
}

impl Fake {
    const SOCKET: &'static str = "cxrs-fake";

    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let program = dir.path().join("tmux");
        symlink(
            concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fake_tmux.sh"),
            &program,
        )
        .unwrap();
        let tmux = Tmux::with_socket(Self::SOCKET)
            .program(program)
            .tmpdir(dir.path());
        Self { dir, tmux }
    }

    fn path_env(&self) -> String {
        format!("{}:/usr/bin:/bin", self.dir.path().display())
    }

    /// Önceki çağrıların izini ve sayaçlarını siler, verilen çıktı/çıkış kodu dosyalarını yazar.
    fn reset(&self, files: &[(&str, &str)]) {
        // Python her çağrıda yeni süreçtir: Rust tarafının sürüm yoklaması da boş başlar.
        self.tmux.reset_raw_paste_probe();
        for entry in std::fs::read_dir(self.dir.path()).unwrap() {
            let path = entry.unwrap().path();
            let name = path.file_name().unwrap().to_string_lossy().into_owned();
            if name != "tmux" && path.is_file() {
                std::fs::remove_file(&path).unwrap();
            }
        }
        for (file, content) in files {
            std::fs::write(self.dir.path().join(file), content).unwrap();
        }
    }

    /// Argv kayıtları; tampon adı (`cops-<pid>-<tid>` / `cops-rs-<pid>-<sıra>`) `BUF` olur.
    fn calls(&self) -> Vec<Vec<String>> {
        let raw = std::fs::read_to_string(self.dir.path().join("argv")).unwrap_or_default();
        raw.split_terminator('\x1e')
            .map(|rec| {
                rec.split_terminator('\x1f')
                    .map(|a| {
                        let rest = a
                            .strip_prefix("cops-rs-")
                            .or_else(|| a.strip_prefix("cops-"))
                            .unwrap_or("x");
                        if rest
                            .split('-')
                            .all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
                        {
                            "BUF".to_string()
                        } else {
                            a.to_string()
                        }
                    })
                    .collect()
            })
            .collect()
    }

    fn stdin(&self) -> Option<Vec<u8>> {
        std::fs::read(self.dir.path().join("stdin")).ok()
    }

    /// Aynı dosyalarla önce Python, sonra Rust: sonuç, argv ve `load-buffer` girdisi aynı olmalı.
    fn same(&self, files: &[(&str, &str)], py: Value, rs: impl FnOnce(&Tmux) -> Value) {
        self.reset(files);
        let got = run_python(
            Self::SOCKET,
            self.dir.path(),
            &[("PATH", self.path_env())],
            std::slice::from_ref(&py),
        );
        let (py_argv, py_stdin) = (self.calls(), self.stdin());
        self.reset(files);
        let want = rs(&self.tmux);
        assert_eq!(got[0], want, "sonuç farkı: {py} {files:?}");
        assert_eq!(py_argv, self.calls(), "argv farkı: {py} {files:?}");
        assert_eq!(py_stdin, self.stdin(), "girdi farkı: {py}");
    }

    /// Python'da TEK süreçte bir dizi çağrı (önbellek yaşar), Rust'ta aynı dizi.
    fn same_seq(&self, files: &[(&str, &str)], py: &[Value], rs: impl FnOnce(&Tmux) -> Vec<Value>) {
        self.reset(files);
        let got = run_python(
            Self::SOCKET,
            self.dir.path(),
            &[("PATH", self.path_env())],
            py,
        );
        let py_argv = self.calls();
        self.reset(files);
        assert_eq!(got, rs(&self.tmux), "sonuç farkı: {py:?}");
        assert_eq!(py_argv, self.calls(), "argv farkı: {py:?}");
    }
}

/// `Ok(metin)` metin, `BadArgument` Python'un `ValueError`u (`parity.py` `{"error": "ValueError"}`).
fn text_or_value_error(r: Result<String, TmuxError>) -> Value {
    match r {
        Ok(s) => json!(s),
        Err(TmuxError::BadArgument(_)) => json!({"error": "ValueError"}),
        Err(e) => panic!("beklenmeyen hata: {e}"),
    }
}

fn ok(r: Result<(), TmuxError>) -> Value {
    json!(r.is_ok())
}

/// stdin'i açık tuttukça yaşayan, alt süreçsiz yardımcı süreç (yalnız bu testin çocuğu; stdin kapanınca biter).
struct Helper(Child);

impl Helper {
    fn new(program: &str, args: &[&str]) -> Self {
        Self(
            Command::new(program)
                .args(args)
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .spawn()
                .unwrap(),
        )
    }

    fn pid(&self) -> u32 {
        self.0.id()
    }

    /// `bash -c` ise onun (tek) çocuğu.
    fn child_pid(&self) -> u32 {
        let path = format!("/proc/{0}/task/{0}/children", self.pid());
        let mut found = String::new();
        wait_until(
            || {
                found = std::fs::read_to_string(&path).unwrap_or_default();
                !found.trim().is_empty()
            },
            "bash çocuğu",
        );
        found.split_whitespace().next().unwrap().parse().unwrap()
    }
}

impl Drop for Helper {
    fn drop(&mut self) {
        drop(self.0.stdin.take());
        let _ = self.0.wait();
    }
}

#[test]
fn every_tmux_call_matches_python_argv_and_result_on_a_fake_tmux() {
    let f = Fake::new();
    let t = |files: &[(&str, &str)], py: Value, rs: &dyn Fn(&Tmux) -> Value| f.same(files, py, rs);

    // Sorgular.
    for rc in ["0", "1"] {
        for name in ["a", "", "$0", "zeta:0", "semi;", "a b"] {
            t(
                &[("has-session.rc", rc)],
                json!(["tmux_has_session", name]),
                &|x| json!(x.has_session(name).unwrap_or(false)),
            );
        }
        let screen = "satır\r\nikinci\rüç\n\x1b[31mr\x1b[0m\n";
        for lines in [2000u32, 0, 7] {
            t(
                &[("capture-pane.out", screen), ("capture-pane.rc", rc)],
                json!(["tmux_capture", "a", lines]),
                &|x| json!(x.capture("a", lines).ok()),
            );
        }
        for (start, end) in [(-5i64, 3i64), (0, 0), (10, -2)] {
            t(
                &[("capture-pane.out", screen), ("capture-pane.rc", rc)],
                json!(["tmux_capture_range", "a", start, end]),
                &|x| json!(x.capture_range("a", start, end).ok()),
            );
        }
        t(
            &[
                ("display-message.out", "/dev/null\n"),
                ("display-message.rc", rc),
            ],
            json!(["pane_is_masked_input", "a"]),
            &|x| json!(x.pane_is_masked_input("a")),
        );
        t(
            &[("set-option.rc", rc)],
            json!(["tmux_release_size", "a"]),
            &|x| ok(x.release_size("a")),
        );
        t(
            &[("kill-session.rc", rc)],
            json!(["tmux_kill_session", "a"]),
            &|x| {
                let _ = x.kill_session("a");
                Value::Null
            },
        );
    }
    for out in [
        "80 24 5 0\n",
        "80 24 5 1\nyoksay\n",
        "  \n 80 24 5 0 \n",
        "",
        "x\n",
        "80 24 5\n",
        "80 24 5 0 9\n",
        "80 24 5 300\n",
        "80 24 5 -1\n",
        "80\x0c24 5 0\n",
        "80 24\x1c5 0\n",
        "80\x1f24 5 0\n",
        "+80 24 5 0\n",
    ] {
        t(
            &[("list-panes.out", out)],
            json!(["tmux_pane_size", "a"]),
            &|x| {
                json!(x.pane_size("a").ok().map(|p| json!([
                    p.cols,
                    p.rows,
                    p.history_size,
                    p.alternate_on
                ])))
            },
        );
    }
    for (out, rc) in [
        ("80 24 0 1 /dev/pts/3\nekran\r\nalt\n", "0"),
        ("80 24 0 0 \nx", "0"),
        ("80 24 0 0 /dev/pts/1", "0"),
        ("bozuk\nx", "0"),
        ("80 24 0 0 /dev/pts/1 ek\nx", "0"),
        ("80 24 0 0 /dev/pts/1\nx", "1"),
    ] {
        t(
            &[("display-message.out", out), ("display-message.rc", rc)],
            json!(["tmux_pane_snapshot", "a"]),
            &|x| {
                json!(x.snapshot("a").ok().map(|s| json!([
                    [
                        s.size.cols,
                        s.size.rows,
                        s.size.history_size,
                        s.size.alternate_on,
                        s.tty
                    ],
                    s.text
                ])))
            },
        );
    }
    for (out, rc) in [
        ("a\n\n b\n", "0"),
        ("a\x0cb\n", "0"),
        ("\x1c\n", "0"),
        ("", "0"),
        ("a\n", "1"),
    ] {
        t(
            &[("list-clients.out", out), ("list-clients.rc", rc)],
            json!(["tmux_client_count", "a"]),
            &|x| json!(x.client_count("a").ok()),
        );
    }
    let clients =
        "/dev/pts/1\tm\n/dev/pts/2\t\n/dev/pts/3\tx\ty\n/dev/pts/4_m\n/dev/pts/5\x1c\tq\n";
    for rc in ["0", "1"] {
        for client in [
            "/dev/pts/1",
            "/dev/pts/2",
            "/dev/pts/3",
            "/dev/pts/4",
            "/dev/pts/5",
            "",
            "-x",
            "/dev/pts/9",
        ] {
            t(
                &[("list-clients.out", clients), ("list-clients.rc", rc)],
                json!(["tmux_client_session", client]),
                &|x| json!(x.client_session(client).ok().flatten()),
            );
        }
    }
    for rc in ["0", "1\n0", "1"] {
        for text in ["a #(rm -rf)\n b;", "-x", " ;; ", "ok", "\x1c ş\t;"] {
            for client in ["/dev/pts/1", "/dev/pts/9"] {
                t(
                    &[("list-clients.out", clients), ("display-message.rc", rc)],
                    json!(["tmux_message", client, text, 1234]),
                    &|x| ok(x.message(client, text, 1234)),
                );
            }
        }
    }

    // Yazımlar.
    for (files, text) in [
        (&[][..], "merhaba"),
        (&[][..], "abc;"),
        (&[][..], "-x"),
        (&[][..], ""),
        (&[][..], "a\nb;"),
        (&[][..], "cr\r\nlf"),
        (&[("load-buffer.rc", "1")][..], "a\nb"),
        (&[("paste-buffer.rc", "1")][..], "a\nb"),
        (
            &[("paste-buffer.rc", "1"), ("delete-buffer.rc", "1")][..],
            "a\nb",
        ),
        (&[("send-keys.rc", "1")][..], "tek"),
        (&[("send-keys.rc", "0\n1")][..], "tek"),
        (&[("send-keys.rc", "1")][..], "a\nb"),
    ] {
        t(
            files,
            json!(["tmux_send_keys", "a", text, 0.0, false]),
            &|x| ok(x.send_text("a", text, Duration::ZERO, MaskGuard::UserTyped)),
        );
    }
    let long = format!("{};{}", "ş".repeat(1999), "q".repeat(2600));
    let old = "paste-buffer (pasteb) [-dpr] [-s separator]\n";
    let new = "paste-buffer (pasteb) [-dprS] [-s separator]\n";
    for (usage, extra, data) in [
        (old, &[][..], "foo;"),
        (old, &[][..], r"bar\;"),
        (old, &[][..], "a\0b"),
        (old, &[][..], ""),
        (old, &[][..], "\0"),
        (old, &[][..], "-"),
        (old, &[][..], ";"),
        (old, &[][..], long.as_str()),
        (new, &[][..], "\u{1b}[A\u{3}\u{7f}"),
        ("send-keys (send) [-l]\n", &[][..], "x"),
        (old, &[("list-commands.rc", "1")][..], "x"),
        (old, &[("load-buffer.rc", "1")][..], "x"),
        (
            old,
            &[("load-buffer.rc", "1"), ("delete-buffer.rc", "1")][..],
            "x",
        ),
    ] {
        let mut files = vec![("list-commands.out", usage)];
        files.extend_from_slice(extra);
        t(&files, json!(["tmux_send_raw", "a", data]), &|x| {
            ok(x.send_raw("a", data, MaskGuard::UserTyped))
        });
    }
    for key in ["Up", "BTab", "C-c", "q", "C-z", "Enter;"] {
        t(&[], json!(["tmux_send_special_key", "a", key]), &|x| {
            ok(x.send_special_key("a", key, MaskGuard::UserTyped))
        });
    }
    for (cols, rows) in [(19, 30), (20, 5), (80, 24), (500, 200), (501, 5), (80, 201)] {
        t(&[], json!(["tmux_resize_window", "a", cols, rows]), &|x| {
            ok(x.resize_window("a", cols, rows))
        });
    }
    for rc in ["0", "1"] {
        for label in ["ctx 1K", "", "a;", "-x", "#{session_name}"] {
            t(
                &[("set-option.rc", rc)],
                json!(["tmux_set_ctx", "a", label]),
                &|x| ok(x.set_ctx("a", label)),
            );
        }
    }
    let seq: [(&str, u32, &str); 6] = [
        ("m", 1, "x"),
        ("m", 1, "x"),
        ("m", 2, "x"),
        ("m", 2, "y"),
        ("n", 2, "y"),
        ("m", 2, ""),
    ];
    for rc in ["0", "1\n0", "1\n1\n0"] {
        f.same_seq(
            &[("set-option.rc", rc)],
            &seq.iter()
                .map(|(n, p, l)| json!(["push_ctx", n, p, l]))
                .collect::<Vec<_>>(),
            |x| {
                let pusher = CtxPusher::new();
                seq.iter()
                    .map(|(n, p, l)| json!(pusher.push(x, n, *p, l)))
                    .collect()
            },
        );
    }

    // Yaşam döngüsü (sahte tmux; süreç tarafı gerçek /proc).
    let conf = core_conf();
    let env: Vec<(String, String)> = vec![
        ("PATH".into(), f.path_env()),
        ("TMUX_TMPDIR".into(), f.dir.path().display().to_string()),
        ("HOME".into(), f.dir.path().display().to_string()),
        ("COPS_X".into(), "ş y".into()),
    ];
    let env_map: serde_json::Map<String, Value> =
        env.iter().map(|(k, v)| (k.clone(), json!(v))).collect();
    for rc in ["0", "1"] {
        for (name, cwd, inner) in [
            ("a", "/tmp", "claude --x"),
            ("semi;", "/tmp;", "a; b"),
            ("", "", ""),
        ] {
            t(
                &[("new-session.rc", rc)],
                json!(["tmux_spawn_direct", name, cwd, inner, env_map]),
                &|x| ok(x.spawn_direct(&conf, name, cwd, inner, env.clone())),
            );
        }
    }
    let idle = Helper::new("cat", &[]);
    let busy = Helper::new("bash", &["-c", "cat; true"]);
    let busy_child = busy.child_pid();
    let me = std::process::id();
    let (idle_pid, busy_pid) = (idle.pid(), busy.pid());
    for pid in [
        idle_pid.to_string(),
        format!(" {idle_pid}\x1c"),
        format!("+{idle_pid}"),
        busy_pid.to_string(),
        me.to_string(),
        "x".into(),
        "-1".into(),
        "0".into(),
        "1".into(),
        "".into(),
        "4294967295".into(),
        "99999999999".into(),
    ] {
        t(&[], json!(["_pid_childless", pid]), &|_| {
            json!(pid_childless(&pid))
        });
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    let ghost_outputs = [
        format!("bash\t{}\t{idle_pid}\n", now as i64 - 100),
        format!(
            "bash\t{}\t{idle_pid}\nsh\t{}\t{idle_pid}\n",
            now as i64 - 100,
            now as i64
        ),
        format!("bash\t{}\t{busy_pid}\n", now as i64 - 100),
        format!("claude\t{}\t{idle_pid}\n", now as i64 - 100),
        format!("bash\t{}\t{idle_pid}\n", now as i64 - 5),
        format!("bash\t {} \t{idle_pid}\n\n", now as i64 - 100),
        format!("bash_{}_{idle_pid}\n", now as i64 - 100),
        "bash\tx\t1\n".into(),
        "bash\t1\n".into(),
        String::new(),
    ];
    for out in &ghost_outputs {
        for when in [Some(now), Some(now + 1000.0), None] {
            t(
                &[("list-panes.out", out)],
                json!(["tmux_ghost_session", "g", when]),
                &|x| json!(x.ghost_session("g", when)),
            );
        }
    }
    t(
        &[
            ("list-panes.out", &ghost_outputs[0]),
            ("list-panes.rc", "1"),
        ],
        json!(["tmux_ghost_session", "g", now + 1000.0]),
        &|x| json!(x.ghost_session("g", Some(now + 1000.0))),
    );
    let as_json =
        |v: Vec<(u32, f64)>| json!(v.iter().map(|(p, c)| json!([p, c])).collect::<Vec<_>>());
    for (out, rc) in [
        (format!("{busy_child}\n{busy_child}\n"), "0"),
        (format!("{busy_child}\n"), "1"),
        (format!("{me} x -1 0 {idle_pid}\n"), "0"),
        (String::new(), "0"),
    ] {
        t(
            &[("list-clients.out", &out), ("list-clients.rc", rc)],
            json!(["_outer_bash_via_list_clients", "m"]),
            &|x| as_json(x.outer_bash_via_list_clients("m")),
        );
    }
    // Yedek tarama: istemci yokken bu kullanıcının tüm `bash -c` betikleri (P7, TBD#366: iki taraf da kullanıcıya göre süzer).
    let name = format!("cxrs-fake we'ird {me}");
    let attach = f.tmux.attach_shell_fragment("/x.conf", &name).unwrap();
    let scanned = [
        Helper::new(
            "bash",
            &[
                "-c",
                &format!("cat # -s {} -c /x\ntrue", shell_quote(&name)),
            ],
        ),
        Helper::new("bash", &["-c", &format!("cat # {attach}; exec bash\ntrue")]),
        Helper::new(
            "bash",
            &[
                "-c",
                &format!("cat # -s {}_1 -c /x\ntrue", shell_quote(&name)),
            ],
        ),
    ];
    wait_until(
        || f.tmux.find_outer_bash_pids(&name).len() == 2,
        "yedek tarama",
    );
    for out in [String::new(), format!("{busy_child}\n")] {
        t(
            &[("list-clients.out", &out)],
            json!(["find_outer_bash_pids", name]),
            &|x| as_json(x.find_outer_bash_pids(&name)),
        );
    }
    for pid in [me, busy_pid, busy_child, idle_pid, 0, 1, 4_294_967_295] {
        t(&[], json!(["is_tmux_backed", pid]), &|x| {
            json!(x.is_tmux_backed(pid))
        });
    }
    drop(scanned);

    // tmux kurulu değil: Python `PATH`te bulamaz, Rust olmayan ikiliyi çalıştıramaz; sonuç aynı.
    let gone = Tmux::with_socket(Fake::SOCKET)
        .program(f.dir.path().join("yok/tmux"))
        .tmpdir(f.dir.path());
    let calls = [
        json!(["tmux_has_session", "a"]),
        json!(["tmux_pane_snapshot", "a"]),
        json!(["tmux_capture", "a", 10]),
        json!(["tmux_send_keys", "a", "x", 0.0, false]),
        json!(["tmux_set_ctx", "a", "x"]),
        json!(["tmux_client_session", "/dev/pts/1"]),
        json!(["tmux_ghost_session", "a", 1.0]),
        json!(["tmux_kill_session", "a"]),
    ];
    let rust = [
        json!(gone.has_session("a").unwrap_or(false)),
        json!(gone.snapshot("a").ok().map(|_| ())),
        json!(gone.capture("a", 10).ok()),
        ok(gone.send_text("a", "x", Duration::ZERO, MaskGuard::UserTyped)),
        ok(gone.set_ctx("a", "x")),
        json!(gone.client_session("/dev/pts/1").ok().flatten()),
        json!(gone.ghost_session("a", Some(1.0))),
        {
            assert!(matches!(gone.kill_session("a"), Err(TmuxError::Io(_))));
            Value::Null
        },
    ];
    let empty_path = f.dir.path().join("yok").display().to_string();
    assert_eq!(
        run_python(Fake::SOCKET, f.dir.path(), &[("PATH", empty_path)], &calls),
        rust
    );
}

/// Python'un `env=` ile verdiği çevre: pane'ler kullanıcının kabuk ayarından bağımsız.
fn spawn_env(s: &Server) -> Vec<(String, String)> {
    let home = s.path().display().to_string();
    vec![
        ("PATH".into(), "/usr/bin:/bin".into()),
        ("HOME".into(), home.clone()),
        ("SHELL".into(), "/bin/sh".into()),
        ("TERM".into(), "xterm-256color".into()),
        ("LANG".into(), "en_US.UTF-8".into()),
        ("TMUX_TMPDIR".into(), home),
    ]
}

fn env_json(env: &[(String, String)]) -> Value {
    Value::Object(env.iter().map(|(k, v)| (k.clone(), json!(v))).collect())
}

/// Sıralı oturum adları; sunucu yoksa (hiç oturum kalmadı) boş.
fn sessions(s: &Server) -> Vec<String> {
    let mut v: Vec<String> = match s.tmux.list_sessions() {
        Ok(list) => list.into_iter().map(|x| x.name).collect(),
        Err(TmuxError::Failed { .. }) => Vec::new(),
        Err(e) => panic!("{e}"),
    };
    v.sort();
    v
}

fn pane_pid(s: &Server, name: &str) -> u32 {
    s.tmux.session_panes(name).unwrap()[0].pane_pid
}

fn unix_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

#[test]
fn lifecycle_matches_python_on_a_real_server() {
    let s = Server::new();
    let conf = core_conf();
    let env = spawn_env(&s);
    let cwd = s.path().display().to_string();
    // Sunucuyu `spawn_direct` başlatır (argv'si `tmux -L <soket> -f <conf> ...`: `is_tmux_backed` bunu arar).
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for (side, name, inner) in [
        ("rs", "rs_g", "true"),
        ("py", "py_g", "true"),
        ("rs", "rs_b", "sleep 900"),
        ("py", "py_b", "sleep 900"),
    ] {
        if side == "rs" {
            assert!(s
                .tmux
                .spawn_direct(&conf, name, &cwd, inner, env.clone())
                .is_ok());
        } else {
            assert_eq!(
                python(
                    &s,
                    &[json!([
                        "tmux_spawn_direct",
                        name,
                        cwd,
                        inner,
                        env_json(&env)
                    ])]
                ),
                [json!(true)]
            );
        }
    }
    // İki taraf da aynı biçimde açtı.
    let fmt = "#{session_name} #{pane_width}x#{pane_height} #{pane_current_path}";
    let row = |n: &str| s.raw(&["list-panes", "-t", &format!("={n}:"), "-F", fmt]);
    for (py, rs) in [("py_g", "rs_g"), ("py_b", "rs_b")] {
        assert_eq!(row(py).replacen(py, "", 1), row(rs).replacen(rs, "", 1));
    }
    wait_until(
        || {
            ["py_g", "rs_g"]
                .iter()
                .all(|n| s.tmux.ghost_session(n, Some(unix_now() + 100.0)))
        },
        "hayalet",
    );
    // Var olan ada ikinci açılış (terminal yok, `-A` bağlanamaz) iki tarafta da başarısız.
    calls.push(json!([
        "tmux_spawn_direct",
        "py_b",
        "/",
        "sleep 1",
        env_json(&env)
    ]));
    rust.push(ok(s.tmux.spawn_direct(
        &conf,
        "rs_b",
        "/",
        "sleep 1",
        env.clone(),
    )));
    let later = unix_now() + 100.0;
    let me = std::process::id();
    // Her oturum (Python ya da Rust açmış olsun) iki tarafa da sorulur.
    for pair in [["py_g", "rs_g"], ["py_b", "rs_b"]] {
        for name in pair {
            calls.push(json!(["tmux_ghost_session", name, later]));
            rust.push(json!(s.tmux.ghost_session(name, Some(later))));
            calls.push(json!(["tmux_ghost_session", name, Value::Null]));
            rust.push(json!(s.tmux.ghost_session(name, None)));
            let pid = pane_pid(&s, name);
            calls.push(json!(["_pid_childless", pid.to_string()]));
            rust.push(json!(pid_childless(&pid.to_string())));
            calls.push(json!(["is_tmux_backed", pid]));
            rust.push(json!(s.tmux.is_tmux_backed(pid)));
            let tty = s.tmux.session_panes(name).unwrap()[0].tty.clone();
            calls.push(json!(["tty_is_masked", tty]));
            rust.push(json!(tty_is_masked(&tty)));
        }
    }
    for name in ["py_g", "rs_", "yok", ""] {
        calls.push(json!(["tmux_ghost_session", name, later]));
        rust.push(json!(s.tmux.ghost_session(name, Some(later))));
    }
    for path in ["", "/dev/null", "/yok/pts/0", "/dev/pts"] {
        calls.push(json!(["tty_is_masked", path]));
        rust.push(json!(tty_is_masked(path)));
    }
    for pid in [me, 0, 1] {
        calls.push(json!(["is_tmux_backed", pid]));
        rust.push(json!(s.tmux.is_tmux_backed(pid)));
    }
    assert_same(&s, &calls, &rust);
    // Ön koşullar gerçekten oluştu (önemsiz eşitlik olmasın).
    assert!(s.tmux.ghost_session("py_g", Some(later)));
    assert!(!s.tmux.ghost_session("py_b", Some(later)));
    assert!(s.tmux.is_tmux_backed(pane_pid(&s, "py_b")));

    // Kapatma: tam adlı oturum gider, ön ek eşleşmesi yok, ikinci kapatma etkisiz.
    s.spawn("rs_b_1", "exec sleep 900");
    s.spawn("py_b_1", "exec sleep 900");
    assert_eq!(
        python(
            &s,
            &[
                json!(["tmux_kill_session", "py_b"]),
                json!(["tmux_kill_session", "py_b"])
            ]
        ),
        [Value::Null, Value::Null]
    );
    assert!(s.tmux.kill_session("rs_b").is_ok());
    assert!(s.tmux.kill_session("rs_b").is_err());
    assert_eq!(sessions(&s), ["py_b_1", "py_g", "rs_b_1", "rs_g"]);
}

/// İkinci yalıtılmış sunucunun pane'inde `bash -c` ile bağlı bir istemci (Python'un aradığı dış pencere biçimi).
fn attach_client(s: &Server, outer: &Server, session: &str) -> String {
    let attach = format!(
        "exec bash -c \"env -u TMUX TMUX_TMPDIR='{}' tmux -u -L {} attach-session -t '={session}:'; sleep 900\"",
        s.path().display(),
        s.tmux.socket()
    );
    outer.spawn("o", &attach);
    wait_until(|| s.tmux.client_count(session).unwrap() == 1, "istemci");
    s.raw(&["list-clients", "-F", "#{client_name}"])
        .trim()
        .to_string()
}

#[test]
fn clients_messages_ctx_and_sizes_match_python_on_a_real_server() {
    let s = Server::new();
    let outer = Server::new();
    for n in ["m", "cpy", "crs", "zpy", "zrs"] {
        s.spawn(n, "exec sleep 900");
    }
    // Maske: parola istemi (icanon -echo), ham kip (-icanon -echo, kabuk/readline gibi), normal.
    s.spawn_ready("pw", "stty icanon -echo", "exec sleep 900");
    s.spawn_ready("raw", "stty -icanon -echo", "exec sleep 900");
    s.spawn_ready("norm", "stty icanon echo", "exec sleep 900");
    let client = attach_client(&s, &outer, "m");
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for c in [client.as_str(), "", "-x", "/dev/pts/yok", "m"] {
        calls.push(json!(["tmux_client_session", c]));
        rust.push(json!(s.tmux.client_session(c).unwrap()));
    }
    for n in ["pw", "raw", "norm"] {
        calls.push(json!(["pane_is_masked_input", n]));
        rust.push(json!(s.tmux.pane_is_masked_input(n)));
        let tty = s.tmux.session_panes(n).unwrap()[0].tty.clone();
        calls.push(json!(["tty_is_masked", tty]));
        rust.push(json!(tty_is_masked(&tty)));
    }
    for n in ["m", "cpy", "yok"] {
        calls.push(json!(["tmux_client_count", n]));
        rust.push(json!(s.tmux.client_count(n).ok()));
    }
    let as_json =
        |v: Vec<(u32, f64)>| json!(v.iter().map(|(p, c)| json!([p, c])).collect::<Vec<_>>());
    for n in ["m", "cpy"] {
        calls.push(json!(["_outer_bash_via_list_clients", n]));
        rust.push(as_json(s.tmux.outer_bash_via_list_clients(n)));
        calls.push(json!(["find_outer_bash_pids", n]));
        rust.push(as_json(s.tmux.find_outer_bash_pids(n)));
    }
    assert_same(&s, &calls, &rust);
    assert_eq!(s.tmux.find_outer_bash_pids("m")[0].0, pane_pid(&outer, "o"));
    let masks: Vec<_> = ["pw", "raw", "norm"]
        .iter()
        .map(|n| s.tmux.pane_is_masked_input(n))
        .collect();
    assert_eq!(masks, [Some(true), Some(false), Some(false)]);

    // Mesaj: iki taraf da aynı sonucu verir ve istemcinin durum satırında AYNI metni gösterir.
    let shown = || {
        outer
            .screen("o")
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("")
            .trim_end()
            .to_string()
    };
    let reset = |mark: &str| {
        s.raw(&["display-message", "-d", "60000", "-t", "=m:", mark]);
        wait_until(|| shown().contains(mark), mark);
    };
    for text in ["-kod #{pane_pid} bitti;", "a #(echo x)\n b", " ;; ", "ş\tç"] {
        reset("SIFIRLA-PY");
        let py = python(&s, &[json!(["tmux_message", client, text, 60000])]);
        let mut py_line = String::new();
        wait_until(
            || {
                py_line = shown();
                !py_line.contains("SIFIRLA-PY")
            },
            "python mesajı",
        );
        reset("SIFIRLA-RS");
        let rs = ok(s.tmux.message(&client, text, 60000));
        let mut rs_line = String::new();
        wait_until(
            || {
                rs_line = shown();
                !rs_line.contains("SIFIRLA-RS")
            },
            "rust mesajı",
        );
        assert_eq!(py[0], rs, "{text:?}");
        assert_eq!(py_line, rs_line, "{text:?}");
    }
    assert_eq!(
        python(&s, &[json!(["tmux_message", "/dev/pts/yok", "x", 10])]),
        [ok(s.tmux.message("/dev/pts/yok", "x", 10))]
    );

    // `@cops_ctx`: aynı dizi iki oturuma; yazılan değer ve dönüşler aynı (P6 dahil: sondaki `;` artık korunur).
    let opt = |n: &str| {
        s.raw(&[
            "show-options",
            "-q",
            "-v",
            "-t",
            &format!("={n}:"),
            "@cops_ctx",
        ])
    };
    let pusher = CtxPusher::new();
    for label in ["ctx 1K", "a;", "#{session_name}", "-x", ""] {
        let py = python(
            &s,
            &[
                json!(["tmux_set_ctx", "cpy", label]),
                json!(["push_ctx", "zpy", 7, label]),
            ],
        );
        let rs = [
            ok(s.tmux.set_ctx("crs", label)),
            json!(pusher.push(&s.tmux, "zrs", 7, label)),
        ];
        assert_eq!(py, rs, "{label:?}");
        assert_eq!(opt("cpy"), opt("crs"), "{label:?}");
        // P6 (TBD#366): sondaki `;` korunur.
        if !label.is_empty() {
            assert_eq!(opt("crs").trim_end_matches('\n'), label, "{label:?}");
        }
        assert_eq!(opt("zpy"), opt("zrs"), "{label:?}");
    }
    assert_eq!(
        python(&s, &[json!(["tmux_set_ctx", "yok", "x"])]),
        [ok(s.tmux.set_ctx("yok", "x"))]
    );

    // Boyut bırakma.
    let wsize = |n: &str| {
        s.raw(&[
            "show-options",
            "-wv",
            "-t",
            &format!("={n}:"),
            "window-size",
        ])
    };
    s.tmux.resize_window("cpy", 90, 30).unwrap();
    s.tmux.resize_window("crs", 90, 30).unwrap();
    assert_eq!(wsize("cpy").trim(), "manual");
    let py = python(
        &s,
        &[
            json!(["tmux_release_size", "cpy"]),
            json!(["tmux_release_size", "yok"]),
        ],
    );
    assert_eq!(
        py,
        [
            ok(s.tmux.release_size("crs")),
            ok(s.tmux.release_size("yok"))
        ]
    );
    assert_eq!(wsize("cpy"), wsize("crs"));
}

/// Aynı adlarla, aynı sırayla kurulmuş iki sunucu: biri Python'a, biri Rust'a.
fn twins(names: &[&str]) -> (Server, Server) {
    let (a, b) = (Server::new(), Server::new());
    for n in names {
        a.spawn(n, "exec sleep 900");
        b.spawn(n, "exec sleep 900");
    }
    (a, b)
}

#[test]
fn python_bug_fixes_p1_to_p7_behave_the_same_in_rust() {
    // P1-P3: hedef çözümü. Okuma çağrıları aynı sunucuda, yıkıcı çağrı ikiz sunucularda. Python `None`/`False`, Rust
    // `Err` (aşağıda `.ok()`/`unwrap_or(false)` ile eşlenir).
    let (a, b) = twins(&["alpha", "beta", "zeta"]);
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    // Son üçü: `;` içeren ad komut kaçıramaz (`=ad:` tek argv elemanı, `:` ile biter).
    for name in [
        "",
        "$0",
        "$1",
        "zeta:0",
        "alpha:0.0",
        "%0",
        "x; kill-server",
        "x;",
        "x;kill-session -t alpha;",
    ] {
        calls.push(json!(["tmux_has_session", name]));
        rust.push(json!(b.tmux.has_session(name).unwrap_or(false)));
        calls.push(json!(["tmux_pane_size", name]));
        rust.push(json!(b.tmux.pane_size(name).ok().map(|p| json!([
            p.cols,
            p.rows,
            p.history_size,
            p.alternate_on
        ]))));
        calls.push(json!(["tmux_capture", name, 0]));
        rust.push(json!(b.tmux.capture(name, 0).ok()));
        calls.push(json!(["pane_is_masked_input", name]));
        rust.push(json!(b.tmux.pane_is_masked_input(name)));
        calls.push(json!(["tmux_pane_snapshot", name]));
        rust.push(json!(b.tmux.snapshot(name).ok().map(|x| json!([
            [
                x.size.cols,
                x.size.rows,
                x.size.history_size,
                x.size.alternate_on,
                x.tty
            ],
            x.text
        ]))));
    }
    assert_same(&b, &calls, &rust);
    assert_eq!(
        sessions(&b),
        ["alpha", "beta", "zeta"],
        "hiçbir okuma oturum kapatmadı"
    );
    // Önemsiz eşitlik değil: tmux bu hedefleri gerçekten başka oturuma çözer (P1-P3); iki taraf da artık hiçbir komut
    // çalıştırmadan reddeder (TBD#366, sahip kararı 26 Kas: iki tarafta düzelt).
    let resolved = |target: &str| {
        b.raw(&["display-message", "-p", "-t", target, "#{session_name}"])
            .trim()
            .to_string()
    };
    assert_eq!(resolved("=$0:"), "alpha");
    assert_eq!(resolved("=zeta:0:"), "zeta");
    assert!(["alpha", "beta", "zeta"].contains(&resolved("=:").as_str()));
    for name in ["", "$0", "$1", "zeta:0", "alpha:0.0"] {
        assert!(matches!(
            b.tmux.has_session(name),
            Err(TmuxError::BadArgument("name"))
        ));
        assert_eq!(b.tmux.pane_is_masked_input(name), None);
        assert!(matches!(
            b.tmux.snapshot(name),
            Err(TmuxError::BadArgument("name"))
        ));
        for guard in [MaskGuard::UserTyped, MaskGuard::RefuseMasked] {
            assert!(matches!(
                b.tmux.send_text(name, "x", Duration::ZERO, guard),
                Err(TmuxError::BadArgument("name"))
            ));
        }
    }
    for name in ["$1", "zeta:0", "", "$0"] {
        assert_eq!(
            python(&a, &[json!(["tmux_kill_session", name])]),
            [Value::Null]
        );
        assert!(matches!(
            b.tmux.kill_session(name),
            Err(TmuxError::BadArgument("name"))
        ));
        assert_eq!(sessions(&a), sessions(&b), "kill {name:?}");
    }
    assert_eq!(
        sessions(&b),
        ["alpha", "beta", "zeta"],
        "hiçbir oturum yanlış hedefle kapanmadı"
    );
    // tmux'un adı olduğu gibi tuttuğu `=`, `@`, `%` ile başlayan adlar hâlâ TAM o oturumu hedefler.
    let (a, b) = twins(&["=eq", "@1", "%1", "eq"]);
    let mut calls = Vec::new();
    let mut rust = Vec::new();
    for name in ["=eq", "@1", "%1"] {
        calls.push(json!(["tmux_has_session", name]));
        rust.push(json!(b.tmux.has_session(name).unwrap()));
        calls.push(json!(["pane_is_masked_input", name]));
        rust.push(json!(b.tmux.pane_is_masked_input(name)));
    }
    assert!(rust.iter().step_by(2).all(|v| *v == json!(true)));
    assert_same(&b, &calls, &rust);
    assert_eq!(
        python(&a, &[json!(["tmux_kill_session", "=eq"])]),
        [Value::Null]
    );
    b.tmux.kill_session("=eq").unwrap();
    assert_eq!(sessions(&a), sessions(&b));
    assert_eq!(sessions(&b), ["%1", "@1", "eq"]);

    // P4: `;` ile biten ad ya da cwd ile açılış iki tarafta da başarılı (TBD#366: argüman `\;` ile kaçırılır); oturum
    // tam o adla, o dizinde açılır.
    let (a, b) = twins(&[]);
    let conf = core_conf();
    let semi_dir = a.path().join("w;");
    std::fs::create_dir(&semi_dir).unwrap();
    let semi_dir = semi_dir.display().to_string();
    for (name, cwd) in [
        ("semi;", "/tmp"),
        ("ok", semi_dir.as_str()),
        ("düz", "/tmp"),
    ] {
        let py = python(
            &a,
            &[json!([
                "tmux_spawn_direct",
                name,
                cwd,
                "sleep 900",
                env_json(&spawn_env(&a))
            ])],
        );
        let rs = ok(b
            .tmux
            .spawn_direct(&conf, name, cwd, "sleep 900", spawn_env(&b)));
        assert_eq!(py, std::slice::from_ref(&rs), "{name:?} {cwd:?}");
        assert_eq!(rs, json!(true), "{name:?} {cwd:?}");
        assert_eq!(sessions(&a), sessions(&b));
        for s in [&a, &b] {
            let path = s.raw(&[
                "display-message",
                "-p",
                "-t",
                &format!("={name}:"),
                "#{pane_current_path}",
            ]);
            assert_eq!(path.trim(), cwd, "{name:?}");
        }
    }
    assert_eq!(sessions(&b), ["düz", "ok", "semi;"]);

    // P5: C yerelinde `-F` sekmesi `_` olur; `client_session` ve `ghost_session` `tmux -u` ile iki tarafta da bulur
    // (TBD#366).
    let s = Server::new();
    let outer = Server::new();
    let env = spawn_env(&s);
    let cwd = s.path().display().to_string();
    s.tmux
        .spawn_direct(&conf, "g", &cwd, "true", env.clone())
        .unwrap();
    s.spawn("m", "exec sleep 900");
    let client = attach_client(&s, &outer, "m");
    let later = unix_now() + 100.0;
    wait_until(|| s.tmux.ghost_session("g", Some(later)), "hayalet");
    let wrapper = s.path().join("tmux-c");
    // `TMUX` de silinir: tmux, `$TMUX` varken istemciyi yerelden bağımsız UTF-8 sayar (Python köprüsü onu zaten siler;
    // testler tmux içinden koşunca Rust tarafı onu miras alıyordu).
    std::fs::write(
        &wrapper,
        "#!/bin/sh\nunset TMUX\nLC_ALL=C LANG=C exec tmux \"$@\"\n",
    )
    .unwrap();
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o755)).unwrap();
    let c_tmux = s.tmux.clone().program(&wrapper);
    let mut c_session = None;
    // Paralel fork'ta yeni yazılan betik kısa süre ETXTBSY verebilir.
    wait_until(
        || match c_tmux.client_session(&client) {
            Err(TmuxError::Io(_)) => false,
            other => {
                c_session = Some(other.unwrap());
                true
            }
        },
        "C yereli",
    );
    let c_ghost = c_tmux.ghost_session("g", Some(later));
    // Önemsiz değil: bu yerelde `-u`suz tmux sekmeyi gerçekten `_` yapar.
    let plain = Command::new(&wrapper)
        .args([
            "-L",
            s.tmux.socket(),
            "list-clients",
            "-F",
            "#{client_name}\t#{client_session}",
        ])
        .env("TMUX_TMPDIR", s.path())
        .output()
        .unwrap();
    let plain = String::from_utf8(plain.stdout).unwrap();
    assert!(!plain.is_empty() && !plain.contains('\t'), "{plain:?}");
    assert_eq!((&c_session, c_ghost), (&Some(Some("m".to_string())), true));
    let c_env = [("LC_ALL", "C".to_string()), ("LANG", "C".to_string())];
    let calls = [
        json!(["tmux_client_session", client]),
        json!(["tmux_ghost_session", "g", later]),
    ];
    assert_eq!(
        run_python(s.tmux.socket(), s.path(), &c_env, &calls),
        [json!(c_session.unwrap()), json!(c_ghost)]
    );
    // UTF-8 yerelinde de aynı.
    assert_eq!(
        python(&s, &calls),
        [json!("m"), json!(true)],
        "UTF-8 yerelinde bulunmalı"
    );
    // P6 ve P7: `clients_messages_ctx_and_sizes_match_python_on_a_real_server` (`a;` etiketi) ve
    // `every_tmux_call_matches_python_argv_and_result_on_a_fake_tmux` (yedek tarama) içinde.
}
