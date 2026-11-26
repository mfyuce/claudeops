//! Python `OSError` metinleri: `str(e)`, `repr(e)` ve sınıf adı (günlüğe aynen giderler).

use crate::pyfmt::py_str_repr;
use std::io;

/// `type(e).__name__`.
pub fn class_name(e: &io::Error) -> &'static str {
    match e.raw_os_error() {
        Some(libc::EPERM) | Some(libc::EACCES) => "PermissionError",
        Some(libc::ENOENT) => "FileNotFoundError",
        Some(libc::EEXIST) => "FileExistsError",
        Some(libc::EISDIR) => "IsADirectoryError",
        Some(libc::ENOTDIR) => "NotADirectoryError",
        Some(libc::EINTR) => "InterruptedError",
        Some(libc::EAGAIN) | Some(libc::EALREADY) | Some(libc::EINPROGRESS) => "BlockingIOError",
        Some(libc::ECHILD) => "ChildProcessError",
        Some(libc::ESRCH) => "ProcessLookupError",
        Some(libc::ETIMEDOUT) => "TimeoutError",
        Some(libc::EPIPE) | Some(libc::ESHUTDOWN) => "BrokenPipeError",
        Some(libc::ECONNABORTED) => "ConnectionAbortedError",
        Some(libc::ECONNREFUSED) => "ConnectionRefusedError",
        Some(libc::ECONNRESET) => "ConnectionResetError",
        _ => "OSError",
    }
}

/// `e.strerror` (glibc metni).
fn strerror(e: &io::Error) -> String {
    let text = e.to_string();
    match e.raw_os_error() {
        Some(n) => text.strip_suffix(&format!(" (os error {n})")).unwrap_or(&text).to_string(),
        None => text,
    }
}

/// `repr(e)`: `PermissionError(13, 'Permission denied')`.
pub fn repr(e: &io::Error) -> String {
    match e.raw_os_error() {
        Some(n) => format!("{}({n}, {})", class_name(e), py_str_repr(&strerror(e))),
        None => format!("OSError({})", py_str_repr(&strerror(e))),
    }
}

/// `str(e)`: `[Errno 13] Permission denied: '/yol'`.
pub fn text(e: &io::Error, path: &str) -> String {
    match e.raw_os_error() {
        Some(n) => format!("[Errno {n}] {}: {}", strerror(e), py_str_repr(path)),
        None => strerror(e),
    }
}
