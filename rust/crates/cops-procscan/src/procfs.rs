//! `/proc` okuma. Sahiplik kapısı tip düzeyinde: süreç içeriği yalnız [`OwnProc`] ile okunur.

use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Süreç kimliği: pid yeniden kullanılabildiği için `starttime` (açılıştan beri saat tıkı) ile birlikte.
/// Bir sürece eylem (sinyal vb.) uygulamadan önce [`ProcFs::verify`] `Liveness::Same` dönmelidir.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub struct ProcId {
    pub pid: u32,
    pub start_time: u64,
}

/// [`ProcFs::verify`] sonucu.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Liveness {
    /// Aynı süreç, bu kullanıcının.
    Same,
    /// Pid yaşıyor ama başka süreç (başlangıç zamanı farklı).
    Replaced,
    /// Pid yok.
    Gone,
    /// Başka kullanıcının süreci: içerik okunmaz, eylem yapılmaz.
    NotOwn,
    /// Okunamadı (izin, bozuk `status`/`stat`): "yok" ya da "aynı" SAYILMAZ.
    Unknown,
}

/// [`ProcFs::access`] sonucu: "yok", "başkasının" ve "okunamadı" ayrı.
#[derive(Debug, Clone)]
pub enum Access {
    Own(OwnProc),
    NotOwn,
    Gone,
    /// `status` okunamadı ya da `Uid:` satırı ayrıştırılamadı.
    Unreadable,
}

/// [`ProcFs::own_processes_checked`]in atladığı süreç sayıları (tarama sırasında çıkan ya da okunamayan).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct ListCounts {
    pub vanished: u32,
    pub unreadable: u32,
}

/// Kaybolan süreç (`ENOENT`/`ESRCH`) ile okunamayan süreci ayırır.
fn is_gone(e: &io::Error) -> bool {
    e.kind() == io::ErrorKind::NotFound || e.raw_os_error() == Some(libc::ESRCH)
}

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

    /// Sahiplik sınıflaması; yalnız `status` okunur.
    pub fn access(&self, pid: u32) -> Access {
        let dir = self.root.join(pid.to_string());
        let status = match fs::read(dir.join("status")) {
            Ok(s) => s,
            Err(e) if is_gone(&e) => return Access::Gone,
            Err(_) => return Access::Unreadable,
        };
        let status = String::from_utf8_lossy(&status);
        let real = status
            .lines()
            .find_map(|l| l.strip_prefix("Uid:"))
            .and_then(|l| l.split_whitespace().next()?.parse::<u32>().ok());
        match real {
            Some(r) if r == self.uid => Access::Own(OwnProc { pid, dir }),
            Some(_) => Access::NotOwn,
            None => Access::Unreadable,
        }
    }

    /// Süreç bu kullanıcınınsa (gerçek uid) tutamak; değilse, yoksa ya da okunamıyorsa `None`
    /// (ayrım gerekiyorsa [`ProcFs::access`]).
    pub fn own(&self, pid: u32) -> Option<OwnProc> {
        match self.access(pid) {
            Access::Own(p) => Some(p),
            _ => None,
        }
    }

    /// Bu kullanıcının tüm süreçleri, pid sırasıyla (psutil `process_iter` sırası). Kök okunamazsa boş
    /// (ayrım gerekiyorsa [`ProcFs::own_processes_checked`]).
    pub fn own_processes(&self) -> Vec<OwnProc> {
        self.own_processes_checked().map(|(v, _)| v).unwrap_or_default()
    }

    /// Kök listelenemezse hata ("süreç yok" ile karışmasın); atlanan süreçler sayılır.
    pub fn own_processes_checked(&self) -> io::Result<(Vec<OwnProc>, ListCounts)> {
        let mut pids: Vec<u32> = fs::read_dir(&self.root)?
            .filter_map(|e| e.ok()?.file_name().to_str()?.parse().ok())
            .collect();
        pids.sort_unstable();
        let mut counts = ListCounts::default();
        let mut out = Vec::new();
        for pid in pids {
            match self.access(pid) {
                Access::Own(p) => out.push(p),
                Access::NotOwn => {}
                Access::Gone => counts.vanished += 1,
                Access::Unreadable => counts.unreadable += 1,
            }
        }
        Ok((out, counts))
    }

    /// Kimliği taşıyan süreç hâlâ aynı mı. Sinyal/eylem öncesi zorunlu denetim (`eacd56c` dersi).
    pub fn verify(&self, id: &ProcId) -> Liveness {
        match self.access(id.pid) {
            Access::Own(p) => match p.try_stat() {
                Ok(Some(st)) if st.starttime == id.start_time => Liveness::Same,
                Ok(Some(_)) => Liveness::Replaced,
                Err(e) if is_gone(&e) => Liveness::Gone,
                _ => Liveness::Unknown,
            },
            Access::NotOwn => Liveness::NotOwn,
            Access::Gone => Liveness::Gone,
            Access::Unreadable => Liveness::Unknown,
        }
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

    /// Okunamazsa boş (psutil `process_iter` `cmdline` özniteliği gibi); ayrım için [`OwnProc::try_cmdline`].
    pub fn cmdline(&self) -> Vec<String> {
        self.try_cmdline().unwrap_or_default()
    }

    pub fn try_cmdline(&self) -> io::Result<Vec<String>> {
        fs::read(self.dir.join("cmdline")).map(|r| split_cmdline(&r))
    }

    /// Okunamaz ya da ayrıştırılamazsa `None`; ayrım için [`OwnProc::try_stat`].
    pub fn stat(&self) -> Option<Stat> {
        self.try_stat().ok().flatten()
    }

    /// Okuma hatası `Err`, okunan ama ayrıştırılamayan içerik `Ok(None)`.
    pub fn try_stat(&self) -> io::Result<Option<Stat>> {
        let raw = fs::read(self.dir.join("stat"))?;
        Ok(parse_stat(&String::from_utf8_lossy(&raw)))
    }

    /// Kimlik (`starttime` okunabiliyorsa).
    pub fn id(&self) -> Option<ProcId> {
        self.stat().map(|s| ProcId {
            pid: self.pid,
            start_time: s.starttime,
        })
    }

    pub fn environ(&self) -> Option<HashMap<String, String>> {
        self.try_environ().ok()
    }

    pub fn try_environ(&self) -> io::Result<HashMap<String, String>> {
        let raw = fs::read(self.dir.join("environ"))?;
        Ok(raw
            .split(|b| *b == 0)
            .filter_map(|kv| {
                let s = String::from_utf8_lossy(kv);
                let (k, v) = s.split_once('=')?;
                (!k.is_empty()).then(|| (k.to_owned(), v.to_owned()))
            })
            .collect())
    }

    /// `readlink(cwd)` olduğu gibi (sessions json kaynağı bunu kullanır).
    pub fn cwd_raw(&self) -> Option<String> {
        self.try_cwd_raw().ok()
    }

    pub fn try_cwd_raw(&self) -> io::Result<String> {
        fs::read_link(self.dir.join("cwd")).map(|p| p.to_string_lossy().into_owned())
    }

    /// psutil `cwd()`: silinmiş dizinin ` (deleted)` eki atılır.
    pub fn cwd(&self) -> Option<String> {
        self.try_cwd().ok()
    }

    pub fn try_cwd(&self) -> io::Result<String> {
        let mut c = self.try_cwd_raw()?;
        if c.ends_with(" (deleted)") && !Path::new(&c).exists() {
            c.truncate(c.len() - " (deleted)".len());
        }
        Ok(c)
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
