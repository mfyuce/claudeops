//! Zaman aşımlı alt süreç (`subprocess.run(..., capture_output=True, timeout=)`).
//!
//! Sahiplik: başlatılan her çocuk [`ChildGuard`] içindedir; hangi yoldan çıkılırsa çıkılsın (zaman aşımı, hata, panik)
//! `Drop` öldürür ve `wait` ile biçer (zombi kalmaz). Crate'te süreç öldürmenin TEK yeri burasıdır ve yalnız kendi
//! başlattığı çocuğa uygulanır (`clippy.toml` `disallowed-methods`).
//!
//! Bilinen sınır (Python `subprocess.run` ile aynı): çocuğun çocuğu (torun) stdout borusunu açık tutarsa okuyucu
//! iş parçacığı torun çıkana dek yaşar; çağrı yine zaman aşımında döner, torun öldürülmez.

use std::io::Read;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// Kendi başlattığımız çocuk: düşerken kill+wait.
pub(crate) struct ChildGuard {
    child: Child,
    reaped: bool,
}

impl ChildGuard {
    pub(crate) fn spawn(cmd: &mut Command) -> std::io::Result<Self> {
        Ok(ChildGuard {
            child: cmd.spawn()?,
            reaped: false,
        })
    }

    pub(crate) fn id(&self) -> u32 {
        self.child.id()
    }

    fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> {
        let st = self.child.try_wait()?;
        self.reaped |= st.is_some();
        Ok(st)
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if !self.reaped {
            // Yalnız kendi çocuğumuz; zaten çıkmışsa kill hata döner, wait yine biçer.
            #[allow(clippy::disallowed_methods)]
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

/// Çıkış durumu ve stdout; başlatılamazsa ya da süre dolarsa (süreç öldürülür) `None`.
pub(crate) fn run(cmd: Command, timeout: Duration) -> Option<(ExitStatus, Vec<u8>)> {
    run_observed(cmd, timeout, |_| {})
}

/// [`run`]; `spawned` çocuğun pid'iyle çağrılır (testler biçildiğini doğrular).
#[doc(hidden)]
pub fn run_observed(mut cmd: Command, timeout: Duration, spawned: impl FnOnce(u32)) -> Option<(ExitStatus, Vec<u8>)> {
    let deadline = Instant::now() + timeout;
    let mut child = ChildGuard::spawn(cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null())).ok()?;
    spawned(child.id());
    let mut pipe = child.child.stdout.take()?;
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        let ok = pipe.read_to_end(&mut buf).is_ok();
        let _ = tx.send(ok.then_some(buf));
    });
    let out = rx.recv_timeout(timeout).ok().flatten()?;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some((status, out)),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(2)),
            _ => return None, // `child` düşer: kill+wait
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sh(s: &str) -> Command {
        let mut c = Command::new("sh");
        c.args(["-c", s]);
        c
    }

    #[test]
    fn output_status_and_timeout() {
        let (st, out) = run(sh("echo hi; exit 3"), Duration::from_secs(5)).unwrap();
        assert_eq!((st.code(), out.as_slice()), (Some(3), b"hi\n".as_slice()));
        let t = Instant::now();
        assert!(run(sh("exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(run(sh("exec >&-; exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(t.elapsed() < Duration::from_secs(3));
        assert!(run(Command::new("/nonexistent/x"), Duration::from_secs(1)).is_none());
    }

    #[test]
    fn guard_reaps_on_drop() {
        let mut c = sh("exec sleep 30");
        let g = ChildGuard::spawn(c.stdin(Stdio::null())).unwrap();
        let pid = g.id();
        let start = |pid: u32| {
            let raw = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
            crate::procfs::parse_stat(&raw).map(|s| s.starttime)
        };
        let before = start(pid).unwrap();
        drop(g);
        // biçilmiş çocuğun /proc girdisi kalmaz (zombi olsaydı `State: Z` ile dururdu); pid yeniden kullanıldıysa başka süreç
        assert_ne!(start(pid), Some(before));
    }
}
