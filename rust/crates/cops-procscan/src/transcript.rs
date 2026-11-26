//! Claude transkript yolu.

use crate::Config;
use std::path::PathBuf;

/// Transkript satırı üst sınırı (bayt, satır sonu hariç). Ölçüm (26 Kas, bu kullanıcının `~/.claude/projects`,
/// 11.252 dosya, 2,38 milyon satır): en uzun satır 13.234.801 bayt; sınır ~5 kat pay. Python karşılığı
/// `needs_ho._MAX_LINE_BYTES` / `session_usage._MAX_LINE_BYTES` (aynı değer).
pub const MAX_LINE_BYTES: usize = 64 * 1024 * 1024;

#[cfg(test)]
thread_local! {
    /// Testler sınırı yalnız kendi iş parçacığında küçültür.
    pub(crate) static TEST_MAX_LINE: std::cell::Cell<Option<usize>> = const { std::cell::Cell::new(None) };
}

/// [`read_line`] sonucu (bayt sayıları satır sonu dahil, okuyucudan tüketilen).
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum Line {
    /// `\\n` ile biten, sınır içinde satır (tamponda).
    Full(usize),
    /// Dosya sonunda `\\n`siz, sınır içinde kalan (tamponda; yazımı sürüyor olabilir).
    Partial(usize),
    /// İçeriği sınırı aşan satır: tampona alınmadan tüketildi. `complete` = satır sonuna ulaşıldı (yoksa dosya bitti).
    TooLong {
        consumed: usize,
        complete: bool,
    },
    Eof,
}

/// Bir satır okur; tampon hiçbir zaman `max + 1` baytı aşmaz (aşan satır önce tümüyle okunmaz, parça parça atılır).
/// Satır içeriği (satır sonu hariç) `max`ı aşıyorsa [`Line::TooLong`] (Python `readline(max + 1)` kuralıyla aynı).
pub(crate) fn read_line(r: &mut impl std::io::BufRead, buf: &mut Vec<u8>, max: usize) -> std::io::Result<Line> {
    buf.clear();
    let (mut consumed, mut too_long) = (0, false);
    loop {
        let avail = match r.fill_buf() {
            Ok(a) => a,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        if avail.is_empty() {
            return Ok(match (too_long, consumed) {
                (true, _) => Line::TooLong {
                    consumed,
                    complete: false,
                },
                (false, 0) => Line::Eof,
                (false, n) => Line::Partial(n),
            });
        }
        let nl = avail.iter().position(|&b| b == b'\n');
        let take = nl.map_or(avail.len(), |i| i + 1);
        if !too_long {
            let content = buf.len() + take - usize::from(nl.is_some());
            if content > max {
                too_long = true;
                buf.clear();
            } else {
                buf.extend_from_slice(&avail[..take]);
            }
        }
        r.consume(take);
        consumed += take;
        if nl.is_some() {
            return Ok(if too_long {
                Line::TooLong {
                    consumed,
                    complete: true,
                }
            } else {
                Line::Full(consumed)
            });
        }
    }
}

/// Geçerli satır sınırı (üretimde [`MAX_LINE_BYTES`]).
pub(crate) fn max_line() -> usize {
    #[cfg(test)]
    if let Some(n) = TEST_MAX_LINE.with(std::cell::Cell::get) {
        return n;
    }
    MAX_LINE_BYTES
}

/// claude'un `projects/` altı adlandırması: harf/rakam olmayan her karakter `-`.
pub fn encode_cwd(cwd: &str) -> String {
    cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect()
}

/// `<projects>/<cwd>/<sid>.jsonl`, yalnız TAM eşleşme.
///
/// **Tüketici sözleşmesi: `None` = transkript yok.** Sid yok, geçersiz (`/` ya da NUL içerir, tek yol parçası değil)
/// ya da dosyası yoksa `None`; çağıran bunu "bilinmiyor" olarak ele alır (usage gösterilmez, needs_ho transkript
/// sinyalini atlar), başka bir dosyayla DOLDURMAZ.
///
/// Python'dan KASITLI fark (docs/rs-proc.md sapma 1; parite koşucusu `KNOWN_DEVIATIONS`): Python `jsonl_path_for`
/// sid hiç YOKKEN cwd'deki en yeni transkripte düşer (tahmin); Rust düşmez, çünkü ortak cwd'de başka oturumun
/// transkriptini verir. Sid VARKEN iki dil aynı: yalnız `<sid>.jsonl`, yoksa ya da sid geçersizse `None` (TBD#365
/// birleştirme kapısı; Python önceden bu durumda da tahmine düşüyordu).
pub fn jsonl_path_for(cfg: &Config, cwd: &str, sid: Option<&str>) -> Option<PathBuf> {
    let sid = sid.filter(|s| !s.is_empty() && !s.contains(['/', '\0']))?;
    let path = cfg
        .claude_dir
        .join("projects")
        .join(encode_cwd(cwd))
        .join(format!("{sid}.jsonl"));
    path.is_file().then_some(path)
}

#[cfg(test)]
mod tests {
    #[test]
    fn encodes_non_ascii_per_char() {
        assert_eq!(super::encode_cwd("/a_b/veri_madenciliği.x"), "-a-b-veri-madencili-i-x");
    }
}
