//! `/proc` okuma. Sahiplik kapısı tip düzeyinde: süreç içeriği yalnız [`OwnProc`] ile okunur.

use serde::Serialize;
use std::collections::HashMap;
use std::ffi::{CStr, CString, OsString};
use std::fs::{self, File};
use std::io::{self, Read};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
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

/// `/proc/<pid>` dizinini fd olarak açar: bu fd üzerinden yapılan okumalar hep AYNI sürece aittir (gerçek `/proc`ta
/// süreç çıkarsa ya da pid yeniden kullanılırsa eski fd yeni süreci göstermez, `ESRCH`/`ENOENT` döner).
fn open_dir(path: &Path) -> io::Result<OwnedFd> {
    let c = CString::new(path.as_os_str().as_bytes()).map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
    // SAFETY: geçerli NUL sonlu yol; dönen fd yalnız burada sahiplenilir.
    let fd = unsafe { libc::open(c.as_ptr(), libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: `fd` az önce açıldı ve başka sahibi yok.
    Ok(unsafe { OwnedFd::from_raw_fd(fd) })
}

/// Dizin fd'sine göreli dosyayı okur (sembolik bağ izlenmez).
fn read_at(dir: &OwnedFd, name: &CStr) -> io::Result<Vec<u8>> {
    // SAFETY: geçerli dizin fd'si ve NUL sonlu ad.
    let fd = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: `fd` az önce açıldı ve başka sahibi yok.
    let mut f = File::from(unsafe { OwnedFd::from_raw_fd(fd) });
    let mut buf = Vec::new();
    f.read_to_end(&mut buf)?;
    Ok(buf)
}

/// Dizin fd'sine göreli sembolik bağın hedefi.
fn readlink_at(dir: &OwnedFd, name: &CStr) -> io::Result<PathBuf> {
    let mut buf = vec![0u8; 4096];
    loop {
        // SAFETY: tampon uzunluğu doğru verildi; readlinkat NUL eklemez.
        let n = unsafe { libc::readlinkat(dir.as_raw_fd(), name.as_ptr(), buf.as_mut_ptr().cast(), buf.len()) };
        let n = usize::try_from(n).map_err(|_| io::Error::last_os_error())?;
        if n < buf.len() {
            buf.truncate(n);
            return Ok(PathBuf::from(OsString::from_vec(buf)));
        }
        if buf.len() >= 1 << 20 {
            return Err(io::Error::from(io::ErrorKind::InvalidData));
        }
        buf.resize(buf.len() * 2, 0);
    }
}

/// `status`taki gerçek uid; satır yoksa ya da ayrıştırılamazsa `None`.
fn real_uid(status: &[u8]) -> Option<u32> {
    String::from_utf8_lossy(status)
        .lines()
        .find_map(|l| l.strip_prefix("Uid:"))
        .and_then(|l| l.split_whitespace().next()?.parse::<u32>().ok())
}

fn stat_at(dir: &OwnedFd) -> io::Result<Option<Stat>> {
    Ok(parse_stat(&String::from_utf8_lossy(&read_at(dir, c"stat")?)))
}

/// Değiştirilmiş ya da başkasına geçmiş süreç: `ESRCH` ("yok" sayılır, içerik dönmez).
fn replaced() -> io::Error {
    io::Error::from_raw_os_error(libc::ESRCH)
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

    /// Sahiplik sınıflaması; dizin fd üzerinden yalnız `status` (ve kendi sürecimizde kimlik için `stat`) okunur.
    pub fn access(&self, pid: u32) -> Access {
        let dir = self.root.join(pid.to_string());
        let classify = |e: io::Error| if is_gone(&e) { Access::Gone } else { Access::Unreadable };
        let fd = match open_dir(&dir) {
            Ok(fd) => fd,
            Err(e) => return classify(e),
        };
        let status = match read_at(&fd, c"status") {
            Ok(s) => s,
            Err(e) => return classify(e),
        };
        match real_uid(&status) {
            Some(r) if r == self.uid => Access::Own(OwnProc {
                pid,
                dir,
                uid: self.uid,
                start_time: stat_at(&fd).ok().flatten().map(|s| s.starttime),
            }),
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
///
/// TOCTOU (birleştirme kapısı): sahiplik oluşturulduğu an doğrulanır, ama pid sonra yeniden kullanılabilir ya da sürecin
/// uid'i değişebilir. Bu yüzden HER içerik okuması `/proc/<pid>` dizinini yeniden fd olarak açar, AYNI fd üzerinden
/// gerçek uid'i ve (biliniyorsa) `starttime`ı okumadan ÖNCE ve SONRA doğrular, içeriği `openat`/`readlinkat` ile okur.
/// Doğrulama tutmazsa içerik atılır ve `ESRCH` (değişmiş süreç) döner: başka kullanıcının içeriği hiçbir durumda dönmez.
#[derive(Debug, Clone)]
pub struct OwnProc {
    pid: u32,
    dir: PathBuf,
    uid: u32,
    /// Oluşturulduğu andaki `starttime` (okunamadıysa `None`: yalnız uid denetlenir).
    start_time: Option<u64>,
}

impl OwnProc {
    pub fn pid(&self) -> u32 {
        self.pid
    }

    /// Fd hâlâ bu sürece mi ait: gerçek uid bizim ve `starttime` aynı.
    fn check(&self, fd: &OwnedFd) -> io::Result<Option<Stat>> {
        if real_uid(&read_at(fd, c"status")?) != Some(self.uid) {
            return Err(replaced());
        }
        let st = stat_at(fd)?;
        match (self.start_time, st) {
            (Some(want), Some(s)) if s.starttime != want => Err(replaced()),
            (Some(_), None) => Err(io::Error::from(io::ErrorKind::InvalidData)),
            _ => Ok(st),
        }
    }

    /// İçeriği doğrulanmış dizin fd'si üzerinden okur; okumadan sonra da doğrular.
    fn read<T>(&self, f: impl FnOnce(&OwnedFd) -> io::Result<T>) -> io::Result<T> {
        let fd = open_dir(&self.dir)?;
        self.check(&fd)?;
        let out = f(&fd)?;
        self.check(&fd)?;
        Ok(out)
    }

    /// Okunamazsa boş (psutil `process_iter` `cmdline` özniteliği gibi); ayrım için [`OwnProc::try_cmdline`].
    pub fn cmdline(&self) -> Vec<String> {
        self.try_cmdline().unwrap_or_default()
    }

    pub fn try_cmdline(&self) -> io::Result<Vec<String>> {
        self.read(|fd| read_at(fd, c"cmdline")).map(|r| split_cmdline(&r))
    }

    /// Okunamaz ya da ayrıştırılamazsa `None`; ayrım için [`OwnProc::try_stat`].
    pub fn stat(&self) -> Option<Stat> {
        self.try_stat().ok().flatten()
    }

    /// Okuma hatası `Err`, okunan ama ayrıştırılamayan içerik `Ok(None)`.
    pub fn try_stat(&self) -> io::Result<Option<Stat>> {
        self.read(stat_at)
    }

    /// Kimlik (`starttime` okunabildiyse; oluşturulduğu anki değer).
    pub fn id(&self) -> Option<ProcId> {
        self.start_time.map(|start_time| ProcId {
            pid: self.pid,
            start_time,
        })
    }

    pub fn environ(&self) -> Option<HashMap<String, String>> {
        self.try_environ().ok()
    }

    pub fn try_environ(&self) -> io::Result<HashMap<String, String>> {
        let raw = self.read(|fd| read_at(fd, c"environ"))?;
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
        self.read(|fd| readlink_at(fd, c"cwd"))
            .map(|p| p.to_string_lossy().into_owned())
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
        let Ok(t) = self.read(|fd| readlink_at(fd, c"fd/0")) else {
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
