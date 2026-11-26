//! Çalışan `cops watch` pencereleri (`mirrors.py`).

use crate::proc_cmd;
use crate::procfs::ProcFs;
use crate::Config;
use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::process::Command;
use std::time::Duration;

const LOCAL_HOST: &str = "local";
/// Değer alan bayraklar: hedef bunların değeri değildir.
const VALUE_FLAGS: [&str; 2] = ["--port", "--transport"];

/// `python3 -m claudeops watch <hedef> [bayraklar]` komut satırından `host:ad`.
pub fn spec_from_cmdline(cmd: &[String]) -> Option<String> {
    let at = (1..cmd.len().saturating_sub(1)).find(|&i| cmd[i - 1] == "claudeops" && cmd[i] == "watch")?;
    let rest = &cmd[at + 1..];
    if rest.iter().any(|t| t == "--once") {
        return None;
    }
    let mut skip = false;
    let target = rest.iter().find(|tok| {
        if skip {
            skip = false;
            false
        } else if VALUE_FLAGS.contains(&tok.as_str()) {
            skip = true;
            false
        } else {
            !tok.starts_with('-')
        }
    })?;
    let (host, name) = target.split_once(':').unwrap_or((LOCAL_HOST, target));
    let (host, name) = (crate::py::strip(host), crate::py::strip(name));
    (!host.is_empty() && !name.is_empty()).then(|| format!("{host}:{name}"))
}

/// Komut satırı bir görüntüleyiciyse `found["host:ad"]`e pid ekler.
pub fn note_mirror(found: &mut BTreeMap<String, Vec<u32>>, pid: u32, cmd: &[String]) {
    if let Some(spec) = spec_from_cmdline(cmd) {
        found.entry(spec).or_default().push(pid);
    }
}

/// Bu kullanıcının çalışan görüntüleyicileri.
pub fn running_mirrors(cfg: &Config) -> BTreeMap<String, Vec<u32>> {
    let mut found = BTreeMap::new();
    for p in ProcFs::new(&cfg.proc_root, cfg.uid).own_processes() {
        note_mirror(&mut found, p.pid(), &p.cmdline());
    }
    found
}

/// Pencereyi öne getirir (`wmctrl -F -a`, başlık TAM eşleşir). Başarısızlık `false`.
pub fn focus_window(spec: &str, display: &str) -> bool {
    focus_with(OsStr::new("wmctrl"), spec, display)
}

fn focus_with(program: &OsStr, spec: &str, display: &str) -> bool {
    let mut cmd = Command::new(program);
    cmd.args(["-F", "-a", spec]).env("DISPLAY", display);
    proc_cmd::run(cmd, Duration::from_secs(3)).is_some_and(|(st, _)| st.success())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(s: &str) -> Option<String> {
        spec_from_cmdline(&s.split(' ').map(str::to_owned).collect::<Vec<_>>())
    }

    #[test]
    fn specs() {
        assert_eq!(spec("python3 -m claudeops watch yuhem:a").as_deref(), Some("yuhem:a"));
        assert_eq!(spec("python3 -m claudeops watch a").as_deref(), Some("local:a"));
        assert_eq!(spec("python3 -m claudeops watch --port 1 a").as_deref(), Some("local:a"));
        assert_eq!(
            spec("python3 -m claudeops watch h:a --transport ws --follow").as_deref(),
            Some("h:a")
        );
        for none in [
            "python3 -m claudeops watch a --once",
            "python3 -m claudeops watch :a",
            "python3 -m claudeops watch h:",
            "python3 -m claudeops watch",
            "python3 -m claudeops watch --port 1",
            "python3 -m claudeops list x",
            "watch claudeops x",
            "claudeops list x",
        ] {
            assert_eq!(spec(none), None, "{none}");
        }
        assert_eq!(spec_from_cmdline(&[]), None);
    }

    #[test]
    fn notes_accumulate() {
        let mut found = BTreeMap::new();
        let cmd: Vec<String> = ["py", "-m", "claudeops", "watch", "a"].map(String::from).to_vec();
        note_mirror(&mut found, 1, &cmd);
        note_mirror(&mut found, 2, &cmd);
        note_mirror(&mut found, 3, &cmd[..3]);
        assert_eq!(found, BTreeMap::from([("local:a".to_owned(), vec![1, 2])]));
    }

    #[test]
    fn focus_reports_exit_status_and_passes_exact_args() {
        let tmp = tempfile::tempdir().unwrap();
        let script = tmp.path().join("wm");
        let log = tmp.path().join("log");
        std::fs::write(
            &script,
            format!("#!/bin/sh\necho \"$DISPLAY $*\" > {}\n[ \"$3\" = ok ]\n", log.display()),
        )
        .unwrap();
        std::fs::set_permissions(&script, std::os::unix::fs::PermissionsExt::from_mode(0o700)).unwrap();
        // ETXTBSY: paralel testin fork'u yazma tutamağını kısa süre taşıyabilir
        let ok = (0..50).any(|_| focus_with(script.as_os_str(), "ok", ":7"));
        assert!(ok);
        assert_eq!(std::fs::read_to_string(&log).unwrap(), ":7 -F -a ok\n");
        assert!(!focus_with(script.as_os_str(), "no", ":7"));
        assert!(!focus_with(OsStr::new("/nonexistent/wmctrl"), "ok", ":7"));
    }
}
