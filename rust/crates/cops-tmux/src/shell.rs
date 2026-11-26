//! Oturum yaşam döngüsü: kabuk komut parçaları, doğrudan açma, hayalet tespiti, kapatma.

use std::env;
use std::ffi::OsString;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::proc::pid_childless;
use crate::runner::{exact_target, Call, Tmux};
use crate::TmuxError;

/// Python `_GHOST_SHELLS`.
pub const GHOST_SHELLS: [&str; 4] = ["bash", "sh", "zsh", "dash"];
/// Python `GHOST_MIN_AGE_SECONDS`.
pub const GHOST_MIN_AGE_SECONDS: f64 = 30.0;

/// Python `shlex.quote`.
pub fn shell_quote(s: &str) -> String {
    let safe = |c: char| c.is_ascii_alphanumeric() || "_@%+=:,./-".contains(c);
    if !s.is_empty() && s.chars().all(safe) {
        s.to_string()
    } else {
        format!("'{}'", s.replace('\'', "'\"'\"'"))
    }
}

/// Python `tmux_available`: `PATH`te çalıştırılabilir `tmux` var mı.
pub fn tmux_available() -> bool {
    let path = env::var_os("PATH").unwrap_or_else(|| "/bin:/usr/bin".into());
    env::split_paths(&path).any(|dir| {
        // Boş `PATH` elemanı çalışma dizinidir.
        let dir = if dir.as_os_str().is_empty() {
            PathBuf::from(".")
        } else {
            dir
        };
        dir.join("tmux")
            .metadata()
            .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    })
}

/// Python `tmux_conf_path`: çekirdek `py/` dizinindeki paketli yapılandırma. Dosya orada KALMALI
/// (`tmux-strip.conf` başlatıcıyı ona göre bulur).
pub fn tmux_conf_path(core_py_dir: &Path) -> PathBuf {
    let path = core_py_dir.join("claudeops/data/tmux.conf");
    path.canonicalize().unwrap_or(path)
}

impl Tmux {
    fn shell_base(&self) -> String {
        self.base_argv()
            .iter()
            .map(|a| shell_quote(a))
            .collect::<Vec<_>>()
            .join(" ")
    }

    /// gnome-terminal komutuna eklenen bash parçası (burada ÇALIŞTIRILMAZ): varsa bağlan, yoksa oluştur (`-A`).
    pub fn new_session_shell_fragment(
        &self,
        conf: &str,
        name: &str,
        cwd: &str,
        inner: &str,
    ) -> String {
        format!(
            "{} -f {} new-session -A -s {} -c {} -x 100 -y 30 {}",
            self.shell_base(),
            shell_quote(conf),
            shell_quote(name),
            shell_quote(cwd),
            shell_quote(inner)
        )
    }

    /// VAR OLAN oturuma yeni pencere bağlayan bash parçası.
    pub fn attach_shell_fragment(&self, conf: &str, name: &str) -> String {
        format!(
            "{} -f {} attach-session -t {}",
            self.shell_base(),
            shell_quote(conf),
            shell_quote(&exact_target(name))
        )
    }

    /// Penceresiz doğrudan açma (Python `tmux_spawn_direct`). `envs` sürecin TÜM çevresidir (miras yok). `inner` tek
    /// argv elemanıdır (tmux kabukta çalıştırır); CLI çıkınca `exec bash` oturumu açık tutar.
    pub fn spawn_direct<I, K, V>(
        &self,
        conf: &Path,
        name: &str,
        cwd: &str,
        inner: &str,
        envs: I,
    ) -> Result<(), TmuxError>
    where
        I: IntoIterator<Item = (K, V)>,
        K: Into<OsString>,
        V: Into<OsString>,
    {
        let envs: Vec<(OsString, OsString)> = envs
            .into_iter()
            .map(|(k, v)| (k.into(), v.into()))
            .collect();
        let conf = conf.to_str().ok_or(TmuxError::BadArgument("conf"))?;
        let command = format!("{inner}; exec bash");
        let args = [
            "-f",
            conf,
            "new-session",
            "-d",
            "-A",
            "-s",
            name,
            "-c",
            cwd,
            "-x",
            "100",
            "-y",
            "30",
            &command,
        ];
        self.exec(
            Call {
                env: Some(&envs),
                ..Call::new(&args)
            },
            self.timeout,
        )
        .map(drop)
    }

    /// Oturumu kapatır. Yalnız kapatma modülü (Python `kill.py` karşılığı) ve hayalet temizliği çağırır: süreç/pencere
    /// temizliği ve devir kuralları ORADADIR.
    pub fn kill_session(&self, name: &str) -> Result<(), TmuxError> {
        self.run(&["kill-session", "-t", &exact_target(name)])
            .map(drop)
    }

    /// CLI'si çıkmış, `exec bash` ile canlı kalan oturum mu: TÜM pane'ler çıplak (alt süreçsiz) kabuk VE oturum
    /// [`GHOST_MIN_AGE_SECONDS`]ten eski. Her belirsizlik `false` (dokunma). `now` verilmezse şimdi.
    pub fn ghost_session(&self, name: &str, now: Option<f64>) -> bool {
        let target = exact_target(name);
        let Ok(out) = self.text(&[
            "list-panes",
            "-s",
            "-t",
            &target,
            "-F",
            "#{pane_current_command}\t#{session_created}\t#{pane_pid}",
        ]) else {
            return false;
        };
        let now = now.unwrap_or_else(|| {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(0.0, |d| d.as_secs_f64())
        });
        ghost_rows(&out, now, pid_childless)
    }
}

/// `komut\toluşma\tpid` satırlarından hayalet kararı.
fn ghost_rows(out: &str, now: f64, childless: impl Fn(&str) -> bool) -> bool {
    let rows: Vec<Vec<&str>> = out
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| l.split('\t').collect())
        .collect();
    if rows.is_empty() || rows.iter().any(|r| r.len() != 3) {
        return false;
    }
    let mut oldest = f64::INFINITY;
    for (i, row) in rows.iter().enumerate() {
        let Ok(created) = row[1].trim().parse::<f64>() else {
            return false;
        };
        // Python `min`: ilk değerle başlar (NaN davranışı aynı kalsın).
        if i == 0 || created < oldest {
            oldest = created;
        }
    }
    if !rows.iter().all(|r| GHOST_SHELLS.contains(&r[0])) || (now - oldest) < GHOST_MIN_AGE_SECONDS
    {
        return false;
    }
    rows.iter().all(|r| childless(r[2]))
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW: f64 = 1_000_000.0;

    fn ghost(out: &str, childless: bool) -> bool {
        ghost_rows(out, NOW, |_| childless)
    }

    #[test]
    fn old_bare_bash_is_ghost() {
        assert!(ghost("bash\t999900\t42\n", true));
    }

    #[test]
    fn live_cli_is_not_ghost() {
        assert!(!ghost("claude\t999900\t42\n", true));
    }

    #[test]
    fn young_session_is_not_ghost() {
        assert!(!ghost("bash\t999995\t42\n", true));
    }

    #[test]
    fn bash_with_child_is_not_ghost() {
        assert!(!ghost("bash\t999900\t42\n", false));
    }

    #[test]
    fn empty_or_garbage_is_not_ghost() {
        for out in ["", "bash\n", "bash\tx\t42\n", "bash\t999900\t42\textra\n"] {
            assert!(!ghost(out, true), "{out:?}");
        }
    }

    #[test]
    fn mixed_panes_are_not_ghost() {
        assert!(!ghost("bash\t999900\t42\nnode\t999900\t43\n", true));
    }

    #[test]
    fn quoting() {
        assert_eq!(shell_quote("abc_1-./:=@%+,"), "abc_1-./:=@%+,");
        assert_eq!(shell_quote(""), "''");
        assert_eq!(shell_quote("a b"), "'a b'");
        assert_eq!(shell_quote("we'ird"), "'we'\"'\"'ird'");
        assert_eq!(shell_quote("ş"), "'ş'");
    }
}
