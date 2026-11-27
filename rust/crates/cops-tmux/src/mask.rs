use std::fs::OpenOptions;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;

/// Pane'in pty'si parola istemi durumunda mı (ICANON açık + ECHO kapalı). Etkileşimli kabuk/readline ECHO'yu zaten
/// kapalı tutar (`-icanon -echo`); ayırt edici olan kombinasyondur. Yol boş / açılamaz / tty değil -> `None`.
///
/// `O_NOCTTY` ŞART: yoksa ctty'siz bir servis süreci bu pty'yi denetim terminali edinir ve oturum kapanınca
/// SIGHUP alır (TODO.md K-02).
pub fn tty_is_masked(pty_path: &str) -> Option<bool> {
    if pty_path.is_empty() {
        return None;
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOCTTY | libc::O_NONBLOCK)
        .open(pty_path)
        .ok()?;
    let mut attrs = std::mem::MaybeUninit::<libc::termios>::uninit();
    // SAFETY: fd `file` yaşadıkça geçerli; `tcgetattr` başarıda yapının tamamını doldurur.
    let attrs = unsafe {
        if libc::tcgetattr(file.as_raw_fd(), attrs.as_mut_ptr()) != 0 {
            return None;
        }
        attrs.assume_init()
    };
    Some(attrs.c_lflag & libc::ICANON != 0 && attrs.c_lflag & libc::ECHO == 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_for_empty_missing_and_non_tty() {
        assert_eq!(tty_is_masked(""), None);
        assert_eq!(tty_is_masked("/nonexistent/pts"), None);
        assert_eq!(tty_is_masked("/dev/null"), None);
    }
}
