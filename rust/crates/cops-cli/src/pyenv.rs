//! Python `paths.py` yol kurallarının metin düzeyinde karşılığı (çıktı metinleri Python ile bayt bayt aynı olsun diye).
//!
//! - `HOME`: `os.path.expanduser("~")` (3.10): ortamda `HOME` varsa o (boş dahil), yoksa `pwd` kaydı; sondaki `/` atılır,
//!   sonuç boşsa `/`.
//! - `CLAUDE_DIR = os.path.join(HOME, ".claude")`, `CLAUDEOPS_DIR = $CLAUDEOPS_DIR (boş değilse) ya da join(CLAUDE_DIR, "claudeops")`.
//! - [`join`] `os.path.join`, [`pathlib_str`] `str(pathlib.PurePosixPath(...))`, [`normpath`] `os.path.normpath`.
//!
//! Göreli `CLAUDEOPS_DIR` iki tarafta açık hata (Python `paths.py`, docs/rs-cli.md "Python hatası?" 8; aynı metin). Göreli
//! `HOME` Python'da hâlâ `py/cops`un `cd py/` adımı yüzünden `py/` dizinine göre çözülür; Rust bunu taklit etmez:
//! [`Roots::check_absolute`] açık hata verir (sapma).

use std::ffi::OsString;

/// Ortamdan okunan, Python'un göreceği kökler (metin).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Roots {
    /// `paths.HOME`
    pub home: String,
    /// `paths.CLAUDEOPS_DIR`
    pub claudeops_dir: String,
}

/// Kök çözümünün hatası (UTF-8 olmayan ortam değeri).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RootsError(pub String);

impl std::fmt::Display for RootsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// `os.path.join(a, b)` (iki parça).
pub fn join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        return b.to_string();
    }
    if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

/// `str(PurePosixPath(p))`: tam iki öndeki `/` korunur, boş ve `.` parçalar atılır, `..` korunur; sonuç boşsa `.`.
pub fn pathlib_str(p: &str) -> String {
    let root = if p.starts_with("//") && !p.starts_with("///") {
        "//"
    } else if p.starts_with('/') {
        "/"
    } else {
        ""
    };
    let parts: Vec<&str> = p
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .collect();
    let s = format!("{root}{}", parts.join("/"));
    if s.is_empty() {
        ".".into()
    } else {
        s
    }
}

/// `os.path.normpath` (posix).
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let initial = if p.starts_with("//") && !p.starts_with("///") {
        2
    } else if p.starts_with('/') {
        1
    } else {
        0
    };
    let mut out: Vec<&str> = Vec::new();
    for c in p.split('/') {
        if c.is_empty() || c == "." {
            continue;
        }
        if c != ".." || (initial == 0 && out.is_empty()) || out.last() == Some(&"..") {
            out.push(c);
        } else if !out.is_empty() {
            out.pop();
        }
    }
    let s = format!("{}{}", "/".repeat(initial), out.join("/"));
    if s.is_empty() {
        ".".into()
    } else {
        s
    }
}

/// `expanduser("~")`: `home_env` ortamdaki `HOME` (yoksa `None`), `pw_dir` yedek.
pub fn expand_home(home_env: Option<&str>, pw_dir: impl FnOnce() -> Option<String>) -> String {
    let h = match home_env {
        Some(h) => h.to_string(),
        // Python: pwd kaydı yoksa yol değişmeden ("~") döner.
        None => match pw_dir() {
            Some(d) => d,
            None => return "~".into(),
        },
    };
    let t = h.trim_end_matches('/');
    if t.is_empty() {
        "/".into()
    } else {
        t.to_string()
    }
}

/// Gerçek uid'in `pwd` ev dizini (`getpwuid_r`).
pub fn pw_dir_of_uid() -> Option<String> {
    let mut buf = vec![0 as libc::c_char; 16 * 1024];
    // SAFETY: passwd yapısı sıfırla başlatılır; getpwuid_r yalnız verilen tampona yazar, sonuç işaretçisi o tampona bakar.
    unsafe {
        let mut pw: libc::passwd = std::mem::zeroed();
        let mut res: *mut libc::passwd = std::ptr::null_mut();
        let rc = libc::getpwuid_r(
            libc::getuid(),
            &mut pw,
            buf.as_mut_ptr(),
            buf.len(),
            &mut res,
        );
        if rc != 0 || res.is_null() || pw.pw_dir.is_null() {
            return None;
        }
        std::ffi::CStr::from_ptr(pw.pw_dir)
            .to_str()
            .ok()
            .map(str::to_string)
    }
}

fn utf8(name: &str, v: Option<OsString>) -> Result<Option<String>, RootsError> {
    match v {
        None => Ok(None),
        Some(v) => v
            .into_string()
            .map(Some)
            .map_err(|_| RootsError(format!("{name} UTF-8 değil"))),
    }
}

impl Roots {
    /// Verilen ortam değerlerinden (Python kuralı).
    pub fn from_values(
        home_env: Option<OsString>,
        claudeops_env: Option<OsString>,
        pw_dir: impl FnOnce() -> Option<String>,
    ) -> Result<Roots, RootsError> {
        let home = expand_home(utf8("HOME", home_env)?.as_deref(), pw_dir);
        let claude_dir = join(&home, ".claude");
        let claudeops_dir = match utf8("CLAUDEOPS_DIR", claudeops_env)? {
            Some(d) if !d.is_empty() => d,
            _ => join(&claude_dir, "claudeops"),
        };
        Ok(Roots {
            home,
            claudeops_dir,
        })
    }

    /// Süreç ortamından.
    pub fn from_env() -> Result<Roots, RootsError> {
        Roots::from_values(
            std::env::var_os("HOME"),
            std::env::var_os("CLAUDEOPS_DIR"),
            pw_dir_of_uid,
        )
    }

    /// `~/.claude` (`paths.CLAUDE_DIR`).
    pub fn claude_dir(&self) -> String {
        join(&self.home, ".claude")
    }

    /// Yazma/okuma yapan komutlar için: iki kök de mutlak olmalı (göreli kök Python'da `py/`ye göre çözülür).
    pub fn check_absolute(&self) -> Result<(), RootsError> {
        if !self.home.starts_with('/') {
            return Err(RootsError(format!(
                "HOME göreli ({}): Python bunu py/ dizinine göre çözer, cops-rs çözmez; mutlak yol verin",
                self.home
            )));
        }
        if !self.claudeops_dir.starts_with('/') {
            // Python `paths.py` ile aynı metin.
            return Err(RootsError(format!(
                "CLAUDEOPS_DIR göreli ({}): mutlak yol verin",
                self.claudeops_dir
            )));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn join_matches_os_path_join() {
        assert_eq!(join("/a", "b"), "/a/b");
        assert_eq!(join("/a/", "b"), "/a/b");
        assert_eq!(join("", "b"), "b");
        assert_eq!(join("/a", "/b"), "/b");
    }

    #[test]
    fn pathlib_and_normpath_match_python() {
        assert_eq!(pathlib_str("/a//b/./c/"), "/a/b/c");
        assert_eq!(pathlib_str("//a/b"), "//a/b");
        assert_eq!(pathlib_str("///a"), "/a");
        assert_eq!(pathlib_str("a/../b"), "a/../b");
        assert_eq!(pathlib_str(""), ".");
        assert_eq!(normpath("/a/b/../c/./"), "/a/c");
        assert_eq!(normpath("//a/../.."), "//");
        assert_eq!(normpath("/.."), "/");
        assert_eq!(normpath("///x"), "/x");
    }

    #[test]
    fn home_rules_match_expanduser() {
        assert_eq!(expand_home(Some("/home/x/"), || None), "/home/x");
        assert_eq!(expand_home(Some(""), || None), "/");
        assert_eq!(expand_home(Some("/"), || None), "/");
        assert_eq!(expand_home(None, || Some("/pw".into())), "/pw");
        assert_eq!(expand_home(None, || None), "~");
    }

    #[test]
    fn roots_follow_paths_py() {
        let r = Roots::from_values(Some("/h".into()), None, || None).unwrap();
        assert_eq!(r.claudeops_dir, "/h/.claude/claudeops");
        let r = Roots::from_values(Some("/h".into()), Some("".into()), || None).unwrap();
        assert_eq!(r.claudeops_dir, "/h/.claude/claudeops");
        let r = Roots::from_values(Some("/".into()), Some("/s/".into()), || None).unwrap();
        assert_eq!((r.home.as_str(), r.claudeops_dir.as_str()), ("/", "/s/"));
        assert_eq!(r.claude_dir(), "/.claude");
        assert!(r.check_absolute().is_ok());
        let r = Roots::from_values(Some("/h".into()), Some("rel".into()), || None).unwrap();
        assert_eq!(
            r.check_absolute().unwrap_err().0,
            "CLAUDEOPS_DIR göreli (rel): mutlak yol verin"
        );
        let r = Roots::from_values(Some("h".into()), None, || None).unwrap();
        assert!(r.check_absolute().unwrap_err().0.starts_with("HOME göreli (h)"));
    }

    #[test]
    fn non_utf8_env_is_an_error() {
        use std::os::unix::ffi::OsStringExt;
        let bad = OsString::from_vec(vec![0xff]);
        assert!(Roots::from_values(Some(bad), None, || None).is_err());
    }
}
