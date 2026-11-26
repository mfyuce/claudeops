//! Strangler: Rust'ın bilmediği her komut Python CLI'a (`py/cops`) devredilir.
//!
//! Python CLI'ın bulunması (sırayla; derleme anındaki yol GÖMÜLMEZ, kaynak çalışma anında ve açık):
//! 1. `COPS_PY` (boş değilse): `py/cops` başlatıcısının yolu. Geçersizse (yok, düzenli dosya değil, çalıştırılamaz, kendimiz)
//!    açık hata; sonraki adımlara DÜŞÜLMEZ (yanlış ayar sessizce başka bir kopyaya gitmesin).
//! 2. Kendi ikilimizin gerçek yolundan (`/proc/self/exe`, symlink çözülmüş) yukarı: `<ata>/py/cops` VE `<ata>/py/claudeops/cli.py`
//!    birlikte varsa o (ikili depo içindeyse, ör. `<depo>/bin/cops-rs`).
//! 3. `<durum dizini>/bin/cops-py` (kurulumun bıraktığı symlink ya da dosya; `CLAUDEOPS_DIR`, yoksa `~/.claude/claudeops`).
//!
//! Bulunamazsa [`EXIT_DELEGATE`] (125) ile açık hata. Özyineleme koruması: (a) aday, gerçek yolu ya da (aygıt, inode) ile
//! kendi ikilimizse reddedilir (`cops` adlı symlink'in kendine dönmesi); (b) her devirde `COPS_RS_DEPTH` bir artar,
//! [`MAX_DEPTH`]'i aşınca devir reddedilir (başlatıcı dolaylı olarak yine bizi çağırıyorsa sonsuz `exec` olmaz; meşru iç içe
//! çağrı zinciri bu derinliğe ulaşmaz).
//!
//! Devir Unix `exec` ile: argv AYNEN (UTF-8 olmayan dahil, `OsString`), çıkış kodu ve sinyaller Python sürecinin kendisinin.
//! `argv[0]` başlatıcının gerçek yoludur (`py/cops` `cd "$(dirname "$0")"` yapar; symlink yolu ile `claudeops` paketi bulunamazdı).

use std::ffi::{OsStr, OsString};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// Devir yapılamadığında (Python CLI bulunamadı, geçersiz, özyineleme, `exec` hatası) çıkış kodu. Python CLI'ın kendi
/// kodlarından (0, 1, 2) ve kabuğun 126/127'sinden ayrı.
pub const EXIT_DELEGATE: i32 = 125;
/// `COPS_RS_DEPTH` üst sınırı.
pub const MAX_DEPTH: u32 = 4;
/// Derinlik ortam değişkeni.
pub const DEPTH_ENV: &str = "COPS_RS_DEPTH";

/// Python CLI'ı bulmak için girdiler (testte enjekte edilir).
#[derive(Debug, Clone)]
pub struct Locate {
    /// `COPS_PY`
    pub cops_py: Option<OsString>,
    /// Kendi ikilimizin yolu (`/proc/self/exe`)
    pub self_exe: Option<PathBuf>,
    /// Durum dizini (`paths.CLAUDEOPS_DIR`)
    pub state_dir: Option<PathBuf>,
}

/// Bulunan Python CLI.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PyCli {
    /// Başlatıcının gerçek yolu (`.../py/cops`)
    pub launcher: PathBuf,
    /// Nereden bulunduğu (tanı)
    pub source: &'static str,
}

impl PyCli {
    /// `py/` dizini (başlatıcının dizini; Python `cd` eder).
    pub fn py_dir(&self) -> Option<&Path> {
        self.launcher.parent()
    }
}

/// Bulma hatası.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocateError(pub String);

impl std::fmt::Display for LocateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn same_file(a: &Path, b: &Path) -> bool {
    match (std::fs::metadata(a), std::fs::metadata(b)) {
        (Ok(x), Ok(y)) => x.dev() == y.dev() && x.ino() == y.ino(),
        _ => false,
    }
}

/// Aday başlatıcıyı doğrular; geçerliyse gerçek yolu.
fn validate(cand: &Path, self_exe: Option<&Path>) -> Result<PathBuf, String> {
    let real = std::fs::canonicalize(cand).map_err(|e| format!("{}: {}", cand.display(), e))?;
    let md = std::fs::metadata(&real).map_err(|e| format!("{}: {}", real.display(), e))?;
    if !md.is_file() {
        return Err(format!("{}: düzenli dosya değil", real.display()));
    }
    if md.permissions().mode() & 0o111 == 0 {
        return Err(format!("{}: çalıştırılabilir değil", real.display()));
    }
    if let Some(me) = self_exe {
        let me_real = std::fs::canonicalize(me).unwrap_or_else(|_| me.to_path_buf());
        if real == me_real || same_file(&real, &me_real) {
            return Err(format!(
                "{}: cops-rs'nin kendisi (özyineleme; Python başlatıcısı py/cops olmalı)",
                cand.display()
            ));
        }
    }
    Ok(real)
}

/// Python CLI'ı bulur (bkz. modül belgesi).
pub fn locate(l: &Locate) -> Result<PyCli, LocateError> {
    let me = l.self_exe.as_deref();
    if let Some(p) = l.cops_py.as_ref().filter(|p| !p.is_empty()) {
        return validate(Path::new(p), me)
            .map(|launcher| PyCli {
                launcher,
                source: "COPS_PY",
            })
            .map_err(|e| LocateError(format!("COPS_PY geçersiz: {e}")));
    }
    let mut tried = Vec::new();
    if let Some(exe) = me {
        let real = std::fs::canonicalize(exe).unwrap_or_else(|_| exe.to_path_buf());
        for anc in real.ancestors().skip(1) {
            let cand = anc.join("py").join("cops");
            if cand.is_file() && anc.join("py/claudeops/cli.py").is_file() {
                return validate(&cand, me)
                    .map(|launcher| PyCli {
                        launcher,
                        source: "ikili konumu",
                    })
                    .map_err(LocateError);
            }
        }
        tried.push(format!("{} üst dizinlerinde py/cops yok", real.display()));
    }
    if let Some(sd) = l.state_dir.as_ref() {
        let cand = sd.join("bin").join("cops-py");
        if std::fs::symlink_metadata(&cand).is_ok() {
            return validate(&cand, me)
                .map(|launcher| PyCli {
                    launcher,
                    source: "durum dizini bin/cops-py",
                })
                .map_err(|e| LocateError(format!("{} geçersiz: {e}", cand.display())));
        }
        tried.push(format!("{} yok", cand.display()));
    }
    Err(LocateError(format!(
        "Python CLI bulunamadı: COPS_PY ayarlı değil; {}",
        tried.join("; ")
    )))
}

/// Ortamdaki derinliği okur (bozuk değer = sınırı aşmış say: kapalı yön).
pub fn depth_from(v: Option<&OsStr>) -> u32 {
    match v {
        None => 0,
        Some(s) => s
            .to_str()
            .and_then(|t| t.parse::<u32>().ok())
            .unwrap_or(u32::MAX),
    }
}

/// Devrin hazırlığı: argv ve yeni derinlik. Özyineleme sınırı aşıldıysa hata.
pub fn prepare(py: &PyCli, args: &[OsString], depth: u32) -> Result<(Vec<OsString>, u32), String> {
    if depth >= MAX_DEPTH {
        return Err(format!(
            "devir zinciri çok derin ({DEPTH_ENV}={depth}): {} yine cops-rs'yi çağırıyor olabilir (özyineleme)",
            py.launcher.display()
        ));
    }
    let mut argv = Vec::with_capacity(args.len() + 1);
    argv.push(py.launcher.clone().into_os_string());
    argv.extend(args.iter().cloned());
    Ok((argv, depth + 1))
}

/// `exec`: dönerse hata metnidir.
pub fn exec(py: &PyCli, args: &[OsString], depth: u32) -> String {
    use std::os::unix::process::CommandExt;
    let (argv, next) = match prepare(py, args, depth) {
        Ok(x) => x,
        Err(e) => return e,
    };
    let mut cmd = std::process::Command::new(&py.launcher);
    if let Some(a0) = argv.first() {
        cmd.arg0(a0);
    }
    cmd.args(&argv[1..]).env(DEPTH_ENV, next.to_string());
    let err = cmd.exec();
    format!("{} çalıştırılamadı: {err}", py.launcher.display())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::ffi::OsStringExt;

    fn exe(p: &Path) {
        std::fs::write(p, "#!/bin/sh\n").unwrap();
        std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o755)).unwrap();
    }

    fn repo(root: &Path) -> PathBuf {
        std::fs::create_dir_all(root.join("py/claudeops")).unwrap();
        std::fs::write(root.join("py/claudeops/cli.py"), "").unwrap();
        exe(&root.join("py/cops"));
        root.join("py/cops")
    }

    #[test]
    fn cops_py_wins_and_invalid_is_loud_without_fallback() {
        let t = tempfile::tempdir().unwrap();
        let launcher = repo(t.path());
        let bin = t.path().join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        exe(&bin.join("cops-rs"));
        let l = Locate {
            cops_py: Some(launcher.clone().into()),
            self_exe: Some(bin.join("cops-rs")),
            state_dir: None,
        };
        assert_eq!(locate(&l).unwrap().source, "COPS_PY");
        let l = Locate {
            cops_py: Some(t.path().join("yok").into()),
            ..l
        };
        let e = locate(&l).unwrap_err().0;
        assert!(e.starts_with("COPS_PY geçersiz"), "{e}");
    }

    #[test]
    fn found_next_to_binary_inside_repo() {
        let t = tempfile::tempdir().unwrap();
        let launcher = repo(t.path());
        std::fs::create_dir_all(t.path().join("rust/target")).unwrap();
        exe(&t.path().join("rust/target/cops-rs"));
        let l = Locate {
            cops_py: None,
            self_exe: Some(t.path().join("rust/target/cops-rs")),
            state_dir: None,
        };
        let got = locate(&l).unwrap();
        assert_eq!(got.launcher, std::fs::canonicalize(launcher).unwrap());
        assert_eq!(got.source, "ikili konumu");
    }

    #[test]
    fn py_cops_without_package_marker_is_not_trusted() {
        let t = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(t.path().join("py")).unwrap();
        exe(&t.path().join("py/cops"));
        std::fs::create_dir_all(t.path().join("b")).unwrap();
        exe(&t.path().join("b/cops-rs"));
        let l = Locate {
            cops_py: None,
            self_exe: Some(t.path().join("b/cops-rs")),
            state_dir: Some(t.path().join("state")),
        };
        let e = locate(&l).unwrap_err().0;
        assert!(
            e.contains("bulunamadı") && e.contains("bin/cops-py yok"),
            "{e}"
        );
    }

    #[test]
    fn state_dir_link_and_self_loop_is_refused() {
        let t = tempfile::tempdir().unwrap();
        let launcher = repo(&t.path().join("repo"));
        let sd = t.path().join("state");
        std::fs::create_dir_all(sd.join("bin")).unwrap();
        std::os::unix::fs::symlink(&launcher, sd.join("bin/cops-py")).unwrap();
        let other = t.path().join("x/cops-rs");
        std::fs::create_dir_all(other.parent().unwrap()).unwrap();
        exe(&other);
        let l = Locate {
            cops_py: None,
            self_exe: Some(other.clone()),
            state_dir: Some(sd.clone()),
        };
        assert_eq!(locate(&l).unwrap().source, "durum dizini bin/cops-py");
        // `cops` adlı symlink kendimize dönüyor: hem COPS_PY hem durum dizini yolunda reddedilir.
        let link = t.path().join("cops");
        std::os::unix::fs::symlink(&other, &link).unwrap();
        let l2 = Locate {
            cops_py: Some(link.clone().into()),
            ..l.clone()
        };
        assert!(locate(&l2).unwrap_err().0.contains("özyineleme"));
        std::fs::remove_file(sd.join("bin/cops-py")).unwrap();
        std::os::unix::fs::symlink(&link, sd.join("bin/cops-py")).unwrap();
        assert!(locate(&l).unwrap_err().0.contains("özyineleme"));
        // Sert bağ (farklı yol, aynı inode) da kendimiz sayılır.
        let hard = t.path().join("hard");
        std::fs::hard_link(&other, &hard).unwrap();
        let l3 = Locate {
            cops_py: Some(hard.into()),
            ..l
        };
        assert!(locate(&l3).unwrap_err().0.contains("özyineleme"));
    }

    #[test]
    fn depth_guard_and_argv_are_exact() {
        let py = PyCli {
            launcher: "/r/py/cops".into(),
            source: "COPS_PY",
        };
        let raw = OsString::from_vec(vec![b'-', 0xff, b'x']);
        let args = vec![OsString::from("list"), raw.clone(), OsString::from("a b")];
        let (argv, d) = prepare(&py, &args, 0).unwrap();
        assert_eq!(argv[0], OsString::from("/r/py/cops"));
        assert_eq!(&argv[1..], &args[..]);
        assert_eq!(d, 1);
        assert!(prepare(&py, &args, MAX_DEPTH)
            .unwrap_err()
            .contains("özyineleme"));
        assert_eq!(depth_from(None), 0);
        assert_eq!(depth_from(Some(OsStr::new("2"))), 2);
        assert_eq!(depth_from(Some(OsStr::new("x"))), u32::MAX);
    }
}
