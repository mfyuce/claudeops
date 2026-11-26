//! `COPSD_GIT_SHA`: derlenen kaynağın git commit'i (kısa) + `rust/` altında izlenen dosya değişikliği varsa `-dirty` (yalnız
//! derleme anındaki durum); git yoksa `unknown`. Ortamda `COPSD_GIT_SHA` verilirse o kullanılır.
//! `copsd --version` ve `/api/front/stats` `version` alanı gösterir (canlı ikili = main HEAD denetimi).
//! Yeniden koşma: git HEAD/index/ref/reflog VE çalışma alanındaki her sandığın `src`si ile manifestler (yoksa kaynak değişince
//! eski SHA/`-dirty` kalırdı). Var olmayan yol yazılmaz (cargo yoksa her derlemede yeniden koşar).
use std::path::{Path, PathBuf};
use std::process::Command;

fn git(args: &[&str]) -> Option<String> {
    let dir = std::env::var("CARGO_MANIFEST_DIR").ok()?;
    let out = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(args)
        .output()
        .ok()?;
    out.status
        .success()
        .then(|| String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn watch(p: &Path) {
    if p.exists() {
        println!("cargo:rerun-if-changed={}", p.display());
    }
}

/// `rust/crates/*/{src,Cargo.toml,build.rs}` ve çalışma alanı manifestleri.
fn watch_sources() {
    let Ok(dir) = std::env::var("CARGO_MANIFEST_DIR") else {
        return;
    };
    let crates = PathBuf::from(dir).join("..");
    watch(&crates.join("../Cargo.toml"));
    watch(&crates.join("../Cargo.lock"));
    for e in std::fs::read_dir(&crates).into_iter().flatten().flatten() {
        for name in ["src", "Cargo.toml", "build.rs"] {
            watch(&e.path().join(name));
        }
    }
}

fn main() {
    println!("cargo:rerun-if-env-changed=COPSD_GIT_SHA");
    let sha = match std::env::var("COPSD_GIT_SHA") {
        Ok(v) if !v.is_empty() => v,
        _ => match git(&["rev-parse", "--short=12", "HEAD"]) {
            Some(s) if !s.is_empty() => {
                let dirty = git(&[
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                    "--",
                    "../..",
                ])
                .is_some_and(|o| !o.is_empty());
                // HEAD, dalın ref'i ya da reflog değişince yeniden koş (worktree'de git dizini ayrı; yollar git'ten sorulur).
                // Paketlenmiş ref'in dosyası yoktur: o durumda `logs/HEAD` ve `packed-refs` izlenir.
                let head_ref = git(&["symbolic-ref", "-q", "HEAD"]);
                let names = ["HEAD", "index", "logs/HEAD", "packed-refs"];
                for p in names.into_iter().chain(head_ref.as_deref()) {
                    if let Some(f) = git(&["rev-parse", "--path-format=absolute", "--git-path", p])
                    {
                        watch(Path::new(&f));
                    }
                }
                watch_sources();
                if dirty {
                    format!("{s}-dirty")
                } else {
                    s
                }
            }
            _ => "unknown".into(),
        },
    };
    println!("cargo:rustc-env=COPSD_GIT_SHA={sha}");
}
