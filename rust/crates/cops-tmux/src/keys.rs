//! Pane'e yazan işlemler: metin, ham tuş, özel tuş, boyut, mesaj.

use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::Duration;

use crate::diag::{swallow, Swallowed};
use crate::runner::{escape_arg, exact_target, Call, Tmux, DEFAULT_TIMEOUT};
use crate::text::py_isspace;
use crate::TmuxError;

/// Literal olmayan `send-keys` yoluna yalnız bu tuş adları girer.
pub const ALLOWED_SPECIAL_KEYS: [&str; 10] = [
    "C-c", "C-d", "Escape", "Up", "Down", "Left", "Right", "Tab", "Enter", "BTab",
];

pub const RESIZE_COLS: (u32, u32) = (20, 500);
pub const RESIZE_ROWS: (u32, u32) = (5, 200);

/// Tek `send-keys -l` çağrısındaki en çok karakter.
pub const RAW_CHUNK_CHARS: usize = 2000;

/// Yapıştırma sonrası TUI'nin metni işlemesi için en az bekleme.
const PASTE_SETTLE: Duration = Duration::from_millis(150);

/// Parola istemine karşı tutum. Her gönderimde AÇIKÇA seçilir.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MaskGuard {
    /// Otomatik enjeksiyon (komut, devir, yönerge): pane gizli girdi bekliyorsa gönderme. Durum bilinmiyorsa
    /// (Python gibi) gönderilir; oturum yoksa gönderim zaten başarısız olur.
    RefuseMasked,
    /// İnsanın panelden kendi yazdığı girdi: parola yazmak meşrudur.
    UserTyped,
}

/// [`Tmux::send_text`] yazma süresi sınırı: uzun metni TUI işlerken tmux 5 sn'yi aşabilir, süre metinle büyür.
pub fn send_text_timeout(chars: usize) -> Duration {
    DEFAULT_TIMEOUT.max(Duration::from_secs_f64(5.0 + chars as f64 / 1500.0))
}

impl Tmux {
    fn guard(&self, name: &str, guard: MaskGuard) -> Result<(), TmuxError> {
        if guard == MaskGuard::RefuseMasked && self.pane_is_masked_input(name) == Some(true) {
            return Err(TmuxError::Masked);
        }
        Ok(())
    }

    fn enter(&self, target: &str) -> Result<(), TmuxError> {
        self.run(&["send-keys", "-t", target, "Enter"]).map(drop)
    }

    /// Metni yazar ve tek Enter gönderir. Çok satırlı metin tek parça bracketed paste ile gider (satır sonu TUI'de
    /// Enter sayılıp mesajı bölerdi). `settle`: metinle Enter arasındaki bekleme (codex ister).
    pub fn send_text(
        &self,
        name: &str,
        text: &str,
        settle: Duration,
        guard: MaskGuard,
    ) -> Result<(), TmuxError> {
        let target = exact_target(name)?;
        self.guard(name, guard)?;
        let timeout = self.timeout.max(send_text_timeout(text.chars().count()));
        if text.contains(['\n', '\r']) {
            static SEQ: AtomicU64 = AtomicU64::new(0);
            let buf = format!(
                "cops-rs-{}-{}",
                std::process::id(),
                SEQ.fetch_add(1, Ordering::Relaxed)
            );
            let load = ["load-buffer", "-b", &buf, "-"];
            self.exec(
                Call {
                    input: Some(text.as_bytes()),
                    ..Call::new(&load)
                },
                timeout,
            )?;
            let paste = ["paste-buffer", "-p", "-d", "-b", &buf, "-t", &target];
            if let Err(e) = self.exec(Call::new(&paste), timeout) {
                // Python gibi yalnız tmux "olmadı" dediyse sil (zaman aşımında tampon kalır).
                if matches!(e, TmuxError::Failed { .. }) {
                    if let Err(del) = self.run(&["delete-buffer", "-b", &buf]) {
                        swallow(Swallowed::DeleteBuffer, &del);
                    }
                }
                return Err(e);
            }
            thread::sleep(settle.max(PASTE_SETTLE));
        } else {
            // `--` ŞART: `-` ile başlayan metin tmux bayrağı sanılır.
            let arg = escape_arg(text);
            let send = ["send-keys", "-t", &target, "-l", "--", &arg];
            self.exec(Call::new(&send), timeout)?;
            thread::sleep(settle);
        }
        self.enter(&target)
    }

    /// Ham tuş verisi (xterm.js `onData`): Enter EKLEMEZ. NUL argv'den geçemez, atılır.
    pub fn send_raw(&self, name: &str, data: &str, guard: MaskGuard) -> Result<(), TmuxError> {
        let data: Vec<char> = data.chars().filter(|&c| c != '\0').collect();
        if data.is_empty() {
            return Ok(());
        }
        let target = exact_target(name)?;
        self.guard(name, guard)?;
        for chunk in data.chunks(RAW_CHUNK_CHARS) {
            let arg = escape_arg(&chunk.iter().collect::<String>());
            self.run(&["send-keys", "-t", &target, "-l", "--", &arg])?;
        }
        Ok(())
    }

    /// [`ALLOWED_SPECIAL_KEYS`] içindeki tek tuş.
    pub fn send_special_key(
        &self,
        name: &str,
        key: &str,
        guard: MaskGuard,
    ) -> Result<(), TmuxError> {
        if !ALLOWED_SPECIAL_KEYS.contains(&key) {
            return Err(TmuxError::BadArgument("key"));
        }
        let target = exact_target(name)?;
        self.guard(name, guard)?;
        self.run(&["send-keys", "-t", &target, key]).map(drop)
    }

    /// Pencere boyutunu uygular (`window-size manual` olur: iş bitince [`Tmux::release_size`] ŞART). Bağlı istemcisi
    /// olan oturumda ÇAĞIRMA (çağıran [`Tmux::client_count`] ile eler).
    pub fn resize_window(&self, name: &str, cols: u32, rows: u32) -> Result<(), TmuxError> {
        if !(RESIZE_COLS.0..=RESIZE_COLS.1).contains(&cols)
            || !(RESIZE_ROWS.0..=RESIZE_ROWS.1).contains(&rows)
        {
            return Err(TmuxError::BadArgument("size"));
        }
        let (cols, rows) = (cols.to_string(), rows.to_string());
        self.run(&[
            "resize-window",
            "-t",
            &exact_target(name)?,
            "-x",
            &cols,
            "-y",
            &rows,
        ])
        .map(drop)
    }

    /// Elle boyutu geri alır. tmux 3.0a'da seçenek yoktur: `Failed` zararsızdır.
    pub fn release_size(&self, name: &str) -> Result<(), TmuxError> {
        self.run(&[
            "set-option",
            "-wu",
            "-t",
            &exact_target(name)?,
            "window-size",
        ])
        .map(drop)
    }

    /// `client`ın oturumunda `ms` süreli tek satırlık mesaj. Metin güvenli hale getirilir ([`safe_message`]).
    pub fn message(&self, client: &str, text: &str, ms: u32) -> Result<(), TmuxError> {
        let session = self
            .client_session(client)?
            .ok_or(TmuxError::BadArgument("client"))?;
        // `-c <istemci>` DEĞİL: tmux 3.2a'da `display-message -c` hiç çalışmaz.
        let target = exact_target(&session)?;
        let safe = safe_message(text);
        let ms = ms.to_string();
        match self.run(&["display-message", "-d", &ms, "-t", &target, &safe]) {
            // `-d` tmux 3.2+; eskisinde süresiz. Başlatılamayan / askıda kalan tmux yeniden denenmez.
            Err(TmuxError::Failed { .. }) => self
                .run(&["display-message", "-t", &target, &safe])
                .map(drop),
            other => other.map(drop),
        }
    }
}

/// `#` ikilenir (biçim genişletmesi: `#(komut)` kabukta koşardı), boşluklar tekleşir, sondaki `;` atılır (komut
/// ayıracı), baştaki `-` bayrak olmasın. Python ile aynı sıra (`"a; ;"` -> `"a;"`, tmux bunu `a` gösterir).
fn safe_message(text: &str) -> String {
    let doubled = text.replace('#', "##");
    let joined = doubled
        .split(py_isspace)
        .filter(|w| !w.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let trimmed = joined.trim_end_matches(';').trim_end_matches(py_isspace);
    let safe = if trimmed.is_empty() { "…" } else { trimmed };
    if safe.starts_with('-') {
        format!(" {safe}")
    } else {
        safe.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timeout_grows_with_text() {
        assert_eq!(send_text_timeout(0), Duration::from_secs(5));
        assert_eq!(send_text_timeout(24_000), Duration::from_secs(21));
    }

    #[test]
    fn message_is_neutralised() {
        assert_eq!(safe_message("a #(rm -rf)\n b;"), "a ##(rm -rf) b");
        assert_eq!(safe_message("a; ;"), "a;");
        assert_eq!(safe_message("-x"), " -x");
        assert_eq!(safe_message(" ;; "), "…");
        assert_eq!(safe_message("foo ;;"), "foo");
        assert_eq!(safe_message("a ; b"), "a ; b");
    }
}
