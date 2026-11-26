//! `COPSD_GIT_SHA`: derlenen kaynağın git commit'i (kısa) + `rust/` altında izlenen dosya değişikliği varsa `-dirty` (yalnız
//! derleme anındaki durum); git yoksa `unknown`. Ortamda `COPSD_GIT_SHA` verilirse o kullanılır.
//! `copsd --version` ve `/api/front/stats` `version` alanı gösterir (canlı ikili = main HEAD denetimi).
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
                // HEAD ve dalın ref'i değişince yeniden koş (worktree'de git dizini ayrı; yollar git'ten sorulur).
                for p in ["HEAD", "index"] {
                    if let Some(f) = git(&["rev-parse", "--path-format=absolute", "--git-path", p])
                    {
                        println!("cargo:rerun-if-changed={f}");
                    }
                }
                if let Some(r) = git(&["symbolic-ref", "-q", "HEAD"]) {
                    if let Some(f) = git(&["rev-parse", "--path-format=absolute", "--git-path", &r])
                    {
                        println!("cargo:rerun-if-changed={f}");
                    }
                }
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
