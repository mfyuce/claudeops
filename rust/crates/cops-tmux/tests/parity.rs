//! Python paritesi: aynı pane içeriğinde `claudeops.tmux_backend` ile Rust aynı sonucu verir.
//! `python3` ister; çekirdek `py/` ağacını salt okur (`-B`: bytecode yazmaz).

mod common;

use std::io::Write;
use std::process::{Command, Stdio};
use std::time::Duration;

use common::{read_at_least, Server};
use cops_tmux::{ctx_label, input_box, strip_ansi, typed_input_in_box, MaskGuard, PaneSize};
use serde_json::{json, Value};

fn python(s: &Server, calls: &[Value]) -> Vec<Value> {
    let manifest = env!("CARGO_MANIFEST_DIR");
    let state = s.path().join("state");
    let mut child = Command::new("python3")
        .arg("-B")
        .arg(format!("{manifest}/tests/parity.py"))
        .env("PYTHONPATH", format!("{manifest}/../../../py"))
        .env("CLAUDEOPS_DIR", &state)
        .env("TMUX_TMPDIR", s.path())
        .env_remove("TMUX")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("python3");
    let req = json!({"socket": s.tmux.socket(), "calls": calls}).to_string();
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
exec sleep 60
"##;

#[test]
fn reads_match_python() {
    let s = Server::new();
    let script = s.path().join("paint.sh");
    std::fs::write(&script, PAINT).unwrap();
    s.spawn("a", &format!("exec sh '{}'", script.display()));
    s.wait_screen("a", "READY");
    s.spawn("alt", r"printf '\033[?1049h'; echo READY; exec sleep 60");
    s.wait_screen("alt", "READY");
    s.spawn_ready("pw", "stty icanon -echo", "exec sleep 60");
    s.spawn("pre_1", "exec sleep 60");

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
            calls.push(json!(["tmux_send_keys", py_name, text]));
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
    s.spawn("pys", "exec sleep 60");
    s.spawn("rss", "exec sleep 60");
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
