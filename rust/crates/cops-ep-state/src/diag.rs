//! `GET /api/diag/log` (web.py `self._json({"lines": diag_log_tail(30)})`, `diaglog.diag_log_tail`). Yalnız okur.
use cops_state::{Json, Map};
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

/// Python `diaglog._TAIL_WINDOW`: kuyruk okuması dosyanın sonundan en çok bu kadar bayt.
pub const TAIL_WINDOW: u64 = 512 * 1024;
/// web.py `diag_log_tail(30)`.
pub const TAIL_LINES: usize = 30;

/// Python `diaglog.diag_log_path()`: boş olmayan `CLAUDEOPS_DIAG_LOG`, yoksa `<durum dizini>/diag.log`. `env` = süreç
/// ortamındaki değer (copsd açılışta bir kez okur; Python her çağrıda okur, ikisi de canlıda tanımsız).
pub fn diag_log_path(state_dir: &Path, env: Option<std::ffi::OsString>) -> PathBuf {
    env.filter(|v| !v.is_empty())
        .map_or_else(|| state_dir.join("diag.log"), PathBuf::from)
}

/// `diag_log_tail(n)`: dosyanın son [`TAIL_WINDOW`] baytı, UTF-8 `replace` çözümü, `str.splitlines()`; pencere dosyanın
/// başından başlamıyorsa ilk (yarım) satır atılır; son `n` satırdan `strip()` sonrası boş olmayanlar. HER hata `[]`.
pub fn diag_log_tail(path: &Path, n: usize) -> Vec<String> {
    let read = || -> std::io::Result<(Vec<u8>, u64)> {
        let mut f = std::fs::File::open(path)?;
        let size = f.seek(SeekFrom::End(0))?;
        f.seek(SeekFrom::Start(size.saturating_sub(TAIL_WINDOW)))?;
        let mut raw = Vec::new();
        f.read_to_end(&mut raw)?;
        Ok((raw, size))
    };
    let Ok((raw, size)) = read() else {
        return Vec::new();
    };
    let text = String::from_utf8_lossy(&raw);
    let mut lines = splitlines(&text);
    if size > TAIL_WINDOW && !lines.is_empty() {
        lines.remove(0);
    }
    let from = lines.len().saturating_sub(n);
    lines[from..]
        .iter()
        .map(|l| cops_state::pycompat::strip(l))
        .filter(|l| !l.is_empty())
        .map(String::from)
        .collect()
}

/// `{"lines": [...]}` (Python yanıt gövdesi; `ok` alanı YOK).
pub fn payload(path: &Path) -> Json {
    let mut m = Map::new();
    m.insert(
        "lines".into(),
        Json::Array(
            diag_log_tail(path, TAIL_LINES)
                .into_iter()
                .map(Json::from)
                .collect(),
        ),
    );
    Json::Object(m)
}

/// Python `str.splitlines()` (satır sonu karakterleri atılır): `\n`, `\r`, `\r\n`, `\v`, `\f`, `\x1c`, `\x1d`, `\x1e`,
/// `\x85`, U+2028, U+2029.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let brk = matches!(
            c,
            '\n' | '\r'
                | '\u{0b}'
                | '\u{0c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if !brk {
            continue;
        }
        out.push(&s[start..i]);
        let mut end = i + c.len_utf8();
        if c == '\r' {
            if let Some((j, '\n')) = it.peek().copied() {
                it.next();
                end = j + 1;
            }
        }
        start = end;
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_like_python() {
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("a\n"), ["a"]);
        assert_eq!(splitlines("a\r\n\rb\n\nc"), ["a", "", "b", "", "c"]);
        assert_eq!(splitlines("\n"), [""]);
    }
}
