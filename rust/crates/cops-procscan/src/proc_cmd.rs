//! Zaman aşımlı alt süreç (`subprocess.run(..., capture_output=True, timeout=)`).

use std::io::Read;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// Çıkış durumu ve stdout; başlatılamazsa ya da süre dolarsa (süreç öldürülür) `None`.
pub(crate) fn run(mut cmd: Command, timeout: Duration) -> Option<(ExitStatus, Vec<u8>)> {
    let deadline = Instant::now() + timeout;
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let mut pipe = child.stdout.take()?;
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut buf = Vec::new();
        let ok = pipe.read_to_end(&mut buf).is_ok();
        let _ = tx.send(ok.then_some(buf));
    });
    let out = rx.recv_timeout(timeout).ok().flatten();
    while out.is_some() {
        match child.try_wait() {
            Ok(Some(status)) => return out.map(|o| (status, o)),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(2)),
            _ => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_status_and_timeout() {
        let sh = |s: &str| {
            let mut c = Command::new("sh");
            c.args(["-c", s]);
            c
        };
        let (st, out) = run(sh("echo hi; exit 3"), Duration::from_secs(5)).unwrap();
        assert_eq!((st.code(), out.as_slice()), (Some(3), b"hi\n".as_slice()));
        let t = Instant::now();
        assert!(run(sh("exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(run(sh("exec >&-; exec sleep 5"), Duration::from_millis(100)).is_none());
        assert!(t.elapsed() < Duration::from_secs(3));
        assert!(run(Command::new("/nonexistent/x"), Duration::from_secs(1)).is_none());
    }
}
