//! `front` argüman ayrıştırması Python'un GERÇEK argparse ayrıştırıcısına karşı (kâhin: `py_argparse_oracle.py`). Kural:
//! Rust bir argv'yi işliyorsa Python da aynı değerlerle kabul etmeli; Python kabul ediyorsa Rust devretmemeli (devredilen
//! biçim Python'un düzeltilmemiş kodunda koşardı). Belirteç havuzundan 3 uzunluğa kadar tüm diziler.

mod common;
use common::*;
use cops_cli::{route, Route};
use std::ffi::OsString;

const POOL: &[&str] = &[
    "on",
    "status",
    "off",
    "bogus",
    "--apply",
    "--app",
    "--a",
    "--apply=",
    "--listen",
    "--listen=1.2.3.4:5",
    "--l=x",
    "--li",
    "x:1",
    "--internal",
    "--int=",
    "--i",
    "--bin",
    "--b=/p",
    "-",
    "-5",
    "-.5",
    "--",
    "-h",
    "--he",
    "--zz",
    "",
    "-x",
    "--=a",
    "--version",
];

/// Python ayrıştırıcısının her argv için sonucu.
fn oracle(sb: &Sandbox, cases: &[Vec<String>]) -> Vec<serde_json::Value> {
    let f = sb.t.path().join("cases.json");
    std::fs::write(&f, serde_json::to_string(cases).unwrap()).unwrap();
    let out = sb
        .cmd(std::path::Path::new("/usr/bin/python3"))
        .arg(repo().join("rust/crates/cops-cli/tests/py_argparse_oracle.py"))
        .arg(repo().join("py"))
        .arg(&f)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let lines: Vec<serde_json::Value> = String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(lines.len(), cases.len());
    lines
}

#[test]
fn rust_parse_agrees_with_python_argparse() {
    let mut cases: Vec<Vec<String>> = Vec::new();
    let n = POOL.len();
    for len in 1..=3usize {
        let total = n.pow(len as u32);
        for k in 0..total {
            let mut v = vec!["front".to_string()];
            let mut x = k;
            for _ in 0..len {
                v.push(POOL[x % n].to_string());
                x /= n;
            }
            cases.push(v);
        }
    }
    let sb = Sandbox::new();
    let lines = oracle(&sb, &cases);
    let default_bin = format!("{}/bin/copsd", sb.state().display());
    let (mut handled, mut delegated) = (0, 0);
    for (c, py) in cases.iter().zip(&lines) {
        let args: Vec<OsString> = c.iter().map(OsString::from).collect();
        match route(&args) {
            Route::Front(a) => {
                handled += 1;
                assert_eq!(py["ok"], true, "{c:?}: Rust işledi, Python reddetti: {py}");
                assert_eq!(py["action"], a.action.as_str(), "{c:?}");
                assert_eq!(py["apply"], a.apply, "{c:?}");
                assert_eq!(
                    py["listen"],
                    a.listen.as_deref().unwrap_or("127.0.0.1:8765"),
                    "{c:?}"
                );
                assert_eq!(
                    py["internal"],
                    a.internal.as_deref().unwrap_or("127.0.0.1:28765"),
                    "{c:?}"
                );
                assert_eq!(py["bin"], a.bin.as_deref().unwrap_or(&default_bin), "{c:?}");
            }
            Route::Delegate(why) => {
                delegated += 1;
                assert_eq!(
                    py["ok"], false,
                    "{c:?}: Python kabul etti ama Rust devretti ({why}): {py}"
                );
            }
            Route::SelfCmd | Route::List(_) => unreachable!(),
        }
    }
    eprintln!("{} durum: {handled} Rust, {delegated} devir", cases.len());
    assert!(handled > 500 && delegated > 500);
}

const LIST_POOL: &[&str] = &[
    "--no-cpu",
    "--no",
    "--base",
    "--base=",
    "--base=-x",
    "--b",
    "--ba=hc",
    "--json",
    "--j",
    "--json=1",
    "--no-cpu=",
    "-h",
    "--help",
    "--h",
    "-",
    "-5",
    "-x",
    "--",
    "--=a",
    "--zz",
    "--version",
    "--v",
    "-b",
    "hc",
    "",
    "a b",
];

/// `list` için tek yönlü kural: Rust işliyorsa Python AYNI değerlerle kabul etmeli (devir her zaman güvenli: Python koşar).
#[test]
fn rust_list_parse_never_accepts_more_than_python() {
    let mut cases: Vec<Vec<String>> = Vec::new();
    let n = LIST_POOL.len();
    for len in 0..=3u32 {
        for k in 0..n.pow(len) {
            let mut v = vec![if k % 2 == 0 { "list" } else { "ls" }.to_string()];
            let mut x = k;
            for _ in 0..len {
                v.push(LIST_POOL[x % n].to_string());
                x /= n;
            }
            cases.push(v);
        }
    }
    let sb = Sandbox::new();
    let lines = oracle(&sb, &cases);
    let mut handled = 0;
    for (c, py) in cases.iter().zip(&lines) {
        let args: Vec<OsString> = c.iter().map(OsString::from).collect();
        match route(&args) {
            Route::List(a) => {
                handled += 1;
                assert_eq!(py["ok"], true, "{c:?}: Rust işledi, Python reddetti: {py}");
                assert_eq!(py["no_cpu"], a.no_cpu, "{c:?}");
                assert_eq!(py["json"], a.json, "{c:?}");
                assert_eq!(py["base"], serde_json::json!(a.base), "{c:?}");
            }
            Route::Delegate(_) => {}
            other => panic!("{c:?}: {other:?}"),
        }
    }
    eprintln!("{} durum: {handled} Rust", cases.len());
    assert!(handled > 200);
}
