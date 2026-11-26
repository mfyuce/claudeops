//! Sınırlı, bloklamayan dosya okuma ve dizin/`stat` yardımcıları ([`crate::LiveProbe`] sözleşmesi).
//!
//! Yalnız NORMAL dosya okunur: açılış `O_NONBLOCK` ile yapılır (FIFO/aygıt açılışta bloklamaz), tür açılan tanıtıcı
//! üzerinden denetlenir (denetim ile okuma arasında dosya değişemez). Okuma yolunda symlink İZLENİR (Python `open`).

use crate::live::FileStat;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

/// [`read_text`] üst sınırı (Python sınırsız).
pub const TEXT_MAX_BYTES: u64 = 64 << 20;

/// Normal dosyayı okumak için açar; boyutu da döner.
pub fn open_regular(path: &str) -> io::Result<(File, u64)> {
    let file = OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY).open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "normal dosya değil"));
    }
    Ok((file, meta.len()))
}

fn take(file: File, len: u64) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    file.take(len).read_to_end(&mut out).ok()?;
    Some(out)
}

/// Dosyanın tamamı; `max` bayttan büyükse (okuma sırasında büyüse de) None.
pub fn read_bytes(path: &str, max: u64) -> Option<Vec<u8>> {
    let (file, size) = open_regular(path).ok()?;
    if size > max {
        return None;
    }
    let data = take(file, max.saturating_add(1))?;
    (data.len() as u64 <= max).then_some(data)
}

/// Dosyanın son en çok `max` baytı.
pub fn read_tail(path: &str, max: u64) -> Option<Vec<u8>> {
    let (mut file, size) = open_regular(path).ok()?;
    file.seek(SeekFrom::Start(size.saturating_sub(max))).ok()?;
    take(file, max)
}

/// `start`tan başlayan en çok `len` bayt.
pub fn read_range(path: &str, start: u64, len: u64) -> Option<Vec<u8>> {
    let (mut file, _) = open_regular(path).ok()?;
    file.seek(SeekFrom::Start(start)).ok()?;
    take(file, len)
}

/// Python metin kipi: UTF-8, evrensel satır sonu (`\r\n`, `\r` -> `\n`).
pub fn read_text(path: &str) -> Option<String> {
    let text = String::from_utf8(read_bytes(path, TEXT_MAX_BYTES)?).ok()?;
    Some(if text.contains('\r') { text.replace("\r\n", "\n").replace('\r', "\n") } else { text })
}

/// `os.listdir`: okuma sırası korunur; UTF-8 olmayan adlar atlanır; yarıda hata = None.
pub fn list_dir(path: &str) -> Option<Vec<String>> {
    let mut out = Vec::new();
    for entry in fs::read_dir(path).ok()? {
        if let Ok(name) = entry.ok()?.file_name().into_string() {
            out.push(name);
        }
    }
    Some(out)
}

/// `os.stat` (symlink izlenir).
pub fn stat(path: &str) -> Option<FileStat> {
    let m = fs::metadata(path).ok()?;
    Some(FileStat {
        is_file: m.is_file(),
        mtime_ns: m.mtime().saturating_mul(1_000_000_000).saturating_add(m.mtime_nsec()),
        size: m.len(),
    })
}
