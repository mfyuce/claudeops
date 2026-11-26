//! `/proc` okuma. Sahiplik kapısı tip düzeyinde: süreç içeriği yalnız [`OwnProc`] ile okunur.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// `/proc/<pid>/stat`in kullanılan alanları.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Stat {
    pub ppid: u32,
    pub utime: u64,
    pub stime: u64,
    pub starttime: u64,
}

/// comm boşluk/parantez içerebilir: SON `)` sonrası ayrıştırılır.
pub fn parse_stat(raw: &str) -> Option<Stat> {
    let rest = &raw[raw.rfind(')')? + 1..];
    let f: Vec<&str> = rest.split_whitespace().collect();
    Some(Stat {
        ppid: f.get(1)?.parse().ok()?,
        utime: f.get(11)?.parse().ok()?,
        stime: f.get(12)?.parse().ok()?,
        starttime: f.get(19)?.parse().ok()?,
    })
}

/// psutil 5.9 `Process.cmdline()` ile aynı bölme (argv'sini boşlukla ezen süreçler dahil).
pub fn split_cmdline(raw: &[u8]) -> Vec<String> {
    if raw.is_empty() {
        return Vec::new();
    }
    let data = String::from_utf8_lossy(raw);
    let sep = if data.ends_with('\0') { '\0' } else { ' ' };
    let data = data.strip_suffix(sep).unwrap_or(&data);
    let parts: Vec<String> = data.split(sep).map(str::to_owned).collect();
    if sep == '\0' && parts.len() == 1 && data.contains(' ') {
        return data.split(' ').map(str::to_owned).collect();
    }
    parts
}

#[derive(Debug, Clone)]
pub struct ProcFs {
    root: PathBuf,
    uid: u32,
}

impl ProcFs {
    pub fn new(root: &Path, uid: u32) -> Self {
        ProcFs {
            root: root.to_path_buf(),
            uid,
        }
    }

    /// Süreç bu kullanıcınınsa (gerçek uid) tutamak; değilse ya da yoksa `None`.
    pub fn own(&self, pid: u32) -> Option<OwnProc> {
        let dir = self.root.join(pid.to_string());
        let status = fs::read(dir.join("status")).ok()?;
        let status = String::from_utf8_lossy(&status);
        let line = status.lines().find_map(|l| l.strip_prefix("Uid:"))?;
        let real: u32 = line.split_whitespace().next()?.parse().ok()?;
        (real == self.uid).then_some(OwnProc { pid, dir })
    }

    /// Bu kullanıcının tüm süreçleri, pid sırasıyla (psutil `process_iter` sırası).
    pub fn own_processes(&self) -> Vec<OwnProc> {
        let Ok(rd) = fs::read_dir(&self.root) else { return Vec::new() };
        let mut pids: Vec<u32> = rd.filter_map(|e| e.ok()?.file_name().to_str()?.parse().ok()).collect();
        pids.sort_unstable();
        pids.into_iter().filter_map(|p| self.own(p)).collect()
    }

    /// Açılış anı (epoch sn), `/proc/stat` `btime`.
    pub fn boot_time(&self) -> Option<u64> {
        let raw = fs::read_to_string(self.root.join("stat")).ok()?;
        raw.lines().find_map(|l| l.strip_prefix("btime "))?.trim().parse().ok()
    }
}

/// Sahipliği doğrulanmış süreç.
#[derive(Debug, Clone)]
pub struct OwnProc {
    pid: u32,
    dir: PathBuf,
}

impl OwnProc {
    pub fn pid(&self) -> u32 {
        self.pid
    }

    pub fn cmdline(&self) -> Vec<String> {
        fs::read(self.dir.join("cmdline"))
            .map(|r| split_cmdline(&r))
            .unwrap_or_default()
    }

    pub fn stat(&self) -> Option<Stat> {
        let raw = fs::read(self.dir.join("stat")).ok()?;
        parse_stat(&String::from_utf8_lossy(&raw))
    }

    pub fn environ(&self) -> Option<HashMap<String, String>> {
        let raw = fs::read(self.dir.join("environ")).ok()?;
        Some(
            raw.split(|b| *b == 0)
                .filter_map(|kv| {
                    let s = String::from_utf8_lossy(kv);
                    let (k, v) = s.split_once('=')?;
                    (!k.is_empty()).then(|| (k.to_owned(), v.to_owned()))
                })
                .collect(),
        )
    }

    /// `readlink(cwd)` olduğu gibi (sessions json kaynağı bunu kullanır).
    pub fn cwd_raw(&self) -> Option<String> {
        fs::read_link(self.dir.join("cwd"))
            .ok()
            .map(|p| p.to_string_lossy().into_owned())
    }

    /// psutil `cwd()`: silinmiş dizinin ` (deleted)` eki atılır.
    pub fn cwd(&self) -> Option<String> {
        let mut c = self.cwd_raw()?;
        if c.ends_with(" (deleted)") && !Path::new(&c).exists() {
            c.truncate(c.len() - " (deleted)".len());
        }
        Some(c)
    }

    /// Terminal gitmiş mi: `fd/0` ` (deleted)` ya da pts/tty'ye bakmıyor. Okunamazsa `false`.
    pub fn terminal_lost(&self) -> bool {
        let Ok(t) = fs::read_link(self.dir.join("fd/0")) else {
            return false;
        };
        let t = t.to_string_lossy();
        t.ends_with(" (deleted)") || !(t.starts_with("/dev/pts/") || t.starts_with("/dev/tty"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stat_with_parens_in_comm() {
        let s = parse_stat("12 (a) b) (x) S 7 1 1 0 -1 0 0 0 0 0 30 40 0 0 20 0 1 0 999 0 0").unwrap();
        assert_eq!(
            s,
            Stat {
                ppid: 7,
                utime: 30,
                stime: 40,
                starttime: 999
            }
        );
        assert!(parse_stat("12 no paren").is_none());
    }

    #[test]
    fn cmdline_like_psutil() {
        assert_eq!(split_cmdline(b"claude\0--model\0x\0"), ["claude", "--model", "x"]);
        assert_eq!(split_cmdline(b"claude --model x"), ["claude", "--model", "x"]);
        assert_eq!(split_cmdline(b"claude --model x\0"), ["claude", "--model", "x"]);
        assert_eq!(split_cmdline(b"claude\0\0"), ["claude", ""]);
        assert!(split_cmdline(b"").is_empty());
    }
}
