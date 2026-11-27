//! Süreç ağacı sorguları: `tmux_backend.py`nin psutil kullanan yarısı, doğrudan `/proc` üzerinden (psutil 5.9
//! davranışıyla: ad 15 karakterde kesilirse argv[0]dan tamamlanır, pid yeniden kullanımı ebeveynlikte elenir).

use std::collections::HashMap;
use std::fs;
use std::sync::Mutex;

use crate::runner::{escape_arg, exact_target, Tmux};
use crate::shell::shell_quote;
use crate::text::py_split;

/// Python `_ANCESTOR_WALK_LIMIT`.
pub const ANCESTOR_WALK_LIMIT: usize = 6;

/// Süreç kimliği: pid + başlangıç anı (pid yeniden kullanılırsa an değişir). psutil `create_time` ile aynı değer.
pub type OuterBash = (u32, f64);

#[derive(Debug, Clone)]
struct Stat {
    comm: String,
    ppid: u32,
    /// Açılıştan beri saat tiki.
    start: u64,
}

fn parse_stat(raw: &str) -> Option<Stat> {
    // `pid (comm) state ppid ...`: comm boşluk ve parantez içerebilir, SON `)` ayırır.
    let open = raw.find('(')?;
    let close = raw.rfind(')')?;
    let comm = raw.get(open + 1..close)?.to_string();
    let rest: Vec<&str> = raw.get(close + 1..)?.split_whitespace().collect();
    Some(Stat {
        comm,
        ppid: rest.get(1)?.parse().ok()?,
        start: rest.get(19)?.parse().ok()?,
    })
}

fn stat(pid: u32) -> Option<Stat> {
    let raw = fs::read(format!("/proc/{pid}/stat")).ok()?;
    parse_stat(&String::from_utf8_lossy(&raw))
}

fn split_cmdline(data: &str) -> Vec<String> {
    if data.is_empty() {
        return Vec::new();
    }
    // setproctitle kullanan süreçler NUL yerine boşluk yazar (psutil #1179).
    let sep = if data.ends_with('\0') { '\0' } else { ' ' };
    let data = data.strip_suffix(sep).unwrap_or(data);
    let sep = if sep == '\0' && !data.contains('\0') && data.contains(' ') {
        ' '
    } else {
        sep
    };
    data.split(sep).map(str::to_string).collect()
}

/// `None` = süreç yok ya da okunamıyor; zombide boş liste.
fn cmdline(pid: u32) -> Option<Vec<String>> {
    let raw = fs::read(format!("/proc/{pid}/cmdline")).ok()?;
    Some(split_cmdline(&String::from_utf8_lossy(&raw)))
}

fn basename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

fn name(pid: u32, st: &Stat) -> String {
    if st.comm.len() >= 15 {
        if let Some(full) = cmdline(pid).as_ref().and_then(|c| c.first()) {
            let full = basename(full);
            if full.starts_with(&st.comm) {
                return full.to_string();
            }
        }
    }
    st.comm.clone()
}

fn boot_time() -> Option<f64> {
    let raw = fs::read_to_string("/proc/stat").ok()?;
    raw.lines()
        .find_map(|l| l.strip_prefix("btime "))?
        .trim()
        .parse()
        .ok()
}

fn create_time(st: &Stat) -> Option<f64> {
    // SAFETY: yan etkisiz sistem sorgusu.
    let ticks = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
    if ticks <= 0 {
        return None;
    }
    Some(st.start as f64 / ticks as f64 + boot_time()?)
}

/// psutil `Process.parent()`: pid 1'in ve ebeveyni (çekirdek) 0 olanın ebeveyni yoktur.
fn parent(pid: u32) -> Option<(u32, Stat)> {
    if pid <= 1 {
        return None;
    }
    let child = stat(pid)?;
    let up = stat(child.ppid)?;
    (up.start <= child.start).then_some((child.ppid, up))
}

fn all_pids() -> Vec<u32> {
    let Ok(dir) = fs::read_dir("/proc") else {
        return Vec::new();
    };
    let mut pids: Vec<u32> = dir
        .filter_map(|e| e.ok()?.file_name().to_str()?.parse().ok())
        .collect();
    pids.sort_unstable();
    pids
}

/// Pane kabuğunun HİÇ alt süreci yok mu (Python `_pid_childless`; okunamazsa `false` = hayalet sayma).
pub fn pid_childless(pid: &str) -> bool {
    // Python `int(pid)` baştaki/sondaki Unicode boşluğu atar (`str.strip`ten farklı: U+001C..U+001F atılmaz).
    let Ok(pid) = pid.trim().parse::<u32>() else {
        return false;
    };
    let Some(me) = stat(pid) else {
        return false;
    };
    !all_pids()
        .into_iter()
        .filter_map(stat)
        .any(|c| c.ppid == pid && c.start >= me.start)
}

/// `bash -c <betik>` ise betik.
fn bash_script(pid: u32) -> Option<String> {
    let cmd = cmdline(pid)?;
    (cmd.len() >= 3 && cmd[1] == "-c").then(|| cmd[2].clone())
}

impl Tmux {
    /// Pid'in ata zincirinde (sınırlı) bu soketin tmux sunucusu var mı. Her belirsizlik `false` (tmux'suz say).
    pub fn is_tmux_backed(&self, pid: u32) -> bool {
        // SAFETY: yan etkisiz sistem sorgusu.
        self.tmux_ancestor_of(pid, unsafe { libc::getuid() })
    }

    /// Yalnız `uid` kullanıcısının ataları: başkasınınki yürüyüşü bitirir, içeriği okunmaz (TBD#365).
    fn tmux_ancestor_of(&self, pid: u32, uid: u32) -> bool {
        if stat(pid).is_none() {
            return false;
        }
        let mut current = pid;
        for _ in 0..ANCESTOR_WALK_LIMIT {
            let Some((up, _)) = parent(current) else {
                return false;
            };
            current = up;
            if real_uid(current) != Some(uid) {
                return false;
            }
            let Some(cmd) = cmdline(current) else {
                return false;
            };
            if cmd.len() >= 3
                && basename(&cmd[0]) == "tmux"
                && cmd[1] == "-L"
                && cmd[2] == self.socket()
            {
                return true;
            }
        }
        false
    }

    /// `list-clients`: her istemcinin ebeveyni `bash -c ...` ise o bash. Hata -> boş (Python
    /// `_outer_bash_via_list_clients`).
    pub fn outer_bash_via_list_clients(&self, session: &str) -> Vec<OuterBash> {
        let Ok(out) = exact_target(session)
            .and_then(|target| self.text(&["list-clients", "-t", &target, "-F", "#{client_pid}"]))
        else {
            return Vec::new();
        };
        let mut found = Vec::new();
        // Python `stdout.split()`.
        for token in py_split(&out) {
            let Some((pid, st)) = token.parse().ok().and_then(parent) else {
                continue;
            };
            if name(pid, &st) != "bash" || bash_script(pid).is_none() {
                continue;
            }
            let Some(created) = create_time(&st) else {
                continue;
            };
            if !found.contains(&(pid, created)) {
                found.push((pid, created));
            }
        }
        found
    }

    /// Oturuma bağlı pencerelerin dış `bash -c` süreçleri. Pane süreci / oturum öldürülmeden ÖNCE çağrılmalı: istemci
    /// dönünce `exec bash` argv'yi siler. Önce tmux'un istemci listesi, boşsa tüm süreçlerin komut satırı.
    pub fn find_outer_bash_pids(&self, session: &str) -> Vec<OuterBash> {
        // Hedeflenemeyen ad (TBD#366): `=ad:` iğnesi başka oturumun penceresini de bulurdu.
        let Ok(exact) = exact_target(session) else {
            return Vec::new();
        };
        let native = self.outer_bash_via_list_clients(session);
        if !native.is_empty() {
            return native;
        }
        let needles = [
            format!("-s {} -c ", shell_quote(session)),
            // Güncel parça sondaki `;`i kaçışlı yazar.
            format!("-s {} -c ", shell_quote(&escape_arg(session))),
            format!("attach-session -t {};", shell_quote(session)),
            format!("attach-session -t {};", shell_quote(&exact)),
        ];
        // SAFETY: yan etkisiz sistem sorgusu.
        scan_outer_bash(&needles, unsafe { libc::getuid() })
    }
}

/// Süreçin GERÇEK kullanıcısı (`/proc/<pid>/status` `Uid:` ilk alanı; psutil `uids().real`). `None` = okunamadı.
fn real_uid(pid: u32) -> Option<u32> {
    let raw = fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
    raw.lines()
        .find_map(|l| l.strip_prefix("Uid:"))?
        .split_whitespace()
        .next()?
        .parse()
        .ok()
}

/// Yedek tarama: `uid` kullanıcısının, betiği iğnelerden birini içeren `bash -c` süreçleri. Başka kullanıcının aynı
/// adlı penceresi sayılmaz (TBD#366 P7; çok kullanıcılı makine).
fn scan_outer_bash(needles: &[String], uid: u32) -> Vec<OuterBash> {
    all_pids()
        .into_iter()
        .filter_map(|pid| {
            let st = stat(pid)?;
            if name(pid, &st) != "bash" || real_uid(pid)? != uid {
                return None;
            }
            let script = bash_script(pid)?;
            needles
                .iter()
                .any(|n| script.contains(n.as_str()))
                .then(|| create_time(&st))?
                .map(|created| (pid, created))
        })
        .collect()
}

/// Python `push_ctx` / `_CTX_PUSHED`: değişmeyen etiketi yeniden yazmaz. Yeni pid (oturum yeniden başladı) seçeneği
/// kaybetmiştir: yeniden yazılır. Başarısız yazım not edilmez.
#[derive(Debug, Default)]
pub struct CtxPusher {
    pushed: Mutex<HashMap<(String, u32), String>>,
}

/// Not sayısı bunu aşınca tablo boşaltılır.
const CTX_CACHE_LIMIT: usize = 512;

impl CtxPusher {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&self, tmux: &Tmux, name: &str, pid: u32, label: &str) -> bool {
        let key = (name.to_string(), pid);
        // Kilit tmux çağrısı boyunca TUTULMAZ (askıda tmux diğer oturumları bekletmesin).
        {
            let mut map = self.lock();
            if map.get(&key).is_some_and(|v| v == label) {
                return true;
            }
            if map.len() > CTX_CACHE_LIMIT {
                map.clear();
            }
        }
        let ok = tmux.set_ctx(name, label).is_ok();
        if ok {
            self.lock().insert(key, label.to_string());
        }
        ok
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<(String, u32), String>> {
        // Zehirli kilit: tablo yalnız bir önbellek, içeriği yine kullanılabilir.
        self.pushed.lock().unwrap_or_else(|e| e.into_inner())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stat_line_with_spaces_and_parens_in_name() {
        let raw = "42 (a) b (c)) S 7 1 1 0 -1 4 0 0 0 0 0 0 0 0 20 0 1 0 12345 0 0";
        let st = parse_stat(raw).unwrap();
        assert_eq!(
            (st.comm.as_str(), st.ppid, st.start),
            ("a) b (c)", 7, 12345)
        );
        assert!(parse_stat("bozuk").is_none());
    }

    #[test]
    fn cmdline_split_like_psutil() {
        assert!(split_cmdline("").is_empty());
        assert_eq!(split_cmdline("bash\0-c\0a b\0"), ["bash", "-c", "a b"]);
        assert_eq!(split_cmdline("a\0\0"), ["a", ""]);
        assert_eq!(split_cmdline("chrome --x y"), ["chrome", "--x", "y"]);
        assert_eq!(split_cmdline("chrome --x\0"), ["chrome", "--x"]);
    }

    #[test]
    fn fallback_scan_counts_only_this_users_windows() {
        let needle = format!("cxrs-p7-{} -c ", std::process::id());
        let mut child = std::process::Command::new("bash")
            .args(["-c", &format!("cat # -s {needle}/x\ntrue")])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::null())
            .spawn()
            .unwrap();
        // SAFETY: yan etkisiz sistem sorgusu.
        let me = unsafe { libc::getuid() };
        let needles = [format!("-s {needle}")];
        let mut found = Vec::new();
        for _ in 0..200 {
            found = scan_outer_bash(&needles, me);
            if !found.is_empty() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        let other = scan_outer_bash(&needles, me.wrapping_add(4242));
        drop(child.stdin.take());
        child.wait().unwrap();
        assert_eq!(
            found.iter().map(|(p, _)| *p).collect::<Vec<_>>(),
            [child.id()]
        );
        assert!(other.is_empty(), "{other:?}");
        assert_eq!(real_uid(child.id()), None, "süreç bitti");
    }

    #[test]
    fn another_users_tmux_ancestor_does_not_count() {
        let dir = tempfile::tempdir().unwrap();
        let socket = format!("cxrs-uid-{}", std::process::id());
        let tmux = |args: &[&str]| {
            std::process::Command::new("tmux")
                .args(["-L", &socket, "-f", "/dev/null"])
                .args(args)
                .env("TMUX_TMPDIR", dir.path())
                .env_remove("TMUX")
                .output()
                .unwrap()
        };
        let out = tmux(&[
            "new-session",
            "-d",
            "-P",
            "-F",
            "#{pane_pid}",
            "exec sleep 900",
        ]);
        let pid: u32 = String::from_utf8_lossy(&out.stdout).trim().parse().unwrap();
        let t = Tmux::with_socket(&socket);
        // SAFETY: yan etkisiz sistem sorgusu.
        let me = unsafe { libc::getuid() };
        let (own, foreign) = (
            t.tmux_ancestor_of(pid, me),
            t.tmux_ancestor_of(pid, me.wrapping_add(4242)),
        );
        tmux(&["kill-server"]);
        assert!(own);
        assert!(!foreign);
    }

    #[test]
    fn unknown_pids_are_conservative() {
        assert!(!pid_childless("x"));
        assert!(!pid_childless("4294967294"));
        let t = Tmux::with_socket("cxrs-yok");
        assert!(!t.is_tmux_backed(4_294_967_294));
        assert!(!t.is_tmux_backed(0));
        assert!(!t.is_tmux_backed(1));
    }
}
