//! Python paritesi: `claudeops.review` işlevleri sarılır; Python'un KENDİ testleri ve ek kenar durumları koşarken her çağrı
//! aynı girdiyle Rust'a da sorulur, sonuçlar (depo işlevlerinde dosya baytları dahil) karşılaştırılır.
//! Canlı durum dizinine dokunmaz: `HOME` ve `CLAUDEOPS_DIR` geçici dizindir.
mod support;

use cops_review_core::prompts::LensRegistry;
use cops_state::{Json, Map};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::{Path, PathBuf};
use std::process::Command;

fn serve(listener: UnixListener) {
    for conn in listener.incoming() {
        let Ok(conn) = conn else { return };
        std::thread::spawn(move || {
            let mut lenses = LensRegistry::default();
            let Ok(mut out) = conn.try_clone() else { return };
            for line in BufReader::new(conn).lines() {
                let Ok(line) = line else { return };
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let req = Json::parse(&line).map_err(|e| format!("istek: {e}"))?;
                    support::call(req.as_object().ok_or("istek nesne değil")?, &mut lenses)
                }))
                .unwrap_or_else(|_| Err("PANİK".into()));
                let mut m = Map::new();
                match result {
                    Ok(v) => m.insert("ok".into(), v),
                    Err(e) => m.insert("err".into(), Json::Str(e)),
                };
                if writeln!(out, "{}", Json::Object(m).to_compact()).is_err() {
                    return;
                }
            }
        });
    }
}

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

#[test]
fn python_suite_and_edges_match() {
    let tmp = tempfile::tempdir().unwrap();
    let sock = tmp.path().join("parity.sock");
    let listener = UnixListener::bind(&sock).unwrap();
    std::thread::spawn(move || serve(listener));

    let home = tmp.path().join("home");
    let state = tmp.path().join("state");
    std::fs::create_dir_all(&home).unwrap();
    std::fs::create_dir_all(&state).unwrap();
    let here = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/py");
    let report = std::env::var_os("COPS_REV_PARITY_REPORT")
        .map_or_else(|| tmp.path().join("report.json"), PathBuf::from);
    let out = Command::new("python3")
        .arg(here.join("run_parity.py"))
        .env("HOME", &home)
        .env("CLAUDEOPS_DIR", &state)
        .env("CLAUDEOPS_EXTENSIONS", "off")
        .env_remove("CLAUDEOPS_STORE_BACKEND")
        .env_remove("CLAUDEOPS_DB_URL")
        .env("COPS_REV_PARITY_SOCK", &sock)
        .env("COPS_REV_PARITY_REPORT", &report)
        .env("COPS_REV_PY", repo().join("py"))
        .output()
        .expect("python3 çalıştırılamadı");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let stderr = String::from_utf8_lossy(&out.stderr);
    println!("{stdout}");
    assert!(out.status.success(), "parite başarısız:\n{stdout}\n{}", &stderr[stderr.len().saturating_sub(6000)..]);
}
