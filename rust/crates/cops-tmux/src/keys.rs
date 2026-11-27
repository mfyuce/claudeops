//! Pane'e yazan işlemler: metin, ham tuş, özel tuş, boyut, mesaj.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::PoisonError;
use std::thread;
use std::time::{Duration, Instant};

use crate::diag::{swallow, Swallowed};
use crate::runner::{exact_target, Call, Tmux, DEFAULT_TIMEOUT};
use crate::text::{py_isspace, py_strip};
use crate::TmuxError;

/// Literal olmayan `send-keys` yoluna yalnız bu tuş adları girer.
pub const ALLOWED_SPECIAL_KEYS: [&str; 10] = [
    "C-c", "C-d", "Escape", "Up", "Down", "Left", "Right", "Tab", "Enter", "BTab",
];

pub const RESIZE_COLS: (u32, u32) = (20, 500);
pub const RESIZE_ROWS: (u32, u32) = (5, 200);

/// Ham yapıştırma sürüm yoklamasının ömrü (Python `_RAW_PROBE_TTL`): sunucu yenilenirse yanlış bayrakla en çok bu
/// kadar gönderilir.
pub const RAW_PROBE_TTL: Duration = Duration::from_secs(60);

/// Yapıştırma sonrası TUI'nin metni işlemesi için en az bekleme.
const PASTE_SETTLE: Duration = Duration::from_millis(150);

fn next_buffer() -> String {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    format!(
        "cops-rs-{}-{}",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    )
}

/// Parola istemine karşı tutum. Her gönderimde AÇIKÇA seçilir.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MaskGuard {
    /// Otomatik enjeksiyon (komut, devir, yönerge): pane gizli girdi bekliyorsa ([`TmuxError::Masked`]) YA DA durum
    /// bilinmiyorsa ([`TmuxError::MaskUnknown`]: pty okunamadı, tmux cevap vermedi, oturum yok/pane ölü) gönderme
    /// (TBD#367, sahip kararı: kapalı yön).
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
        if guard == MaskGuard::UserTyped {
            return Ok(());
        }
        match self.pane_is_masked_input(name) {
            Some(false) => Ok(()),
            Some(true) => Err(TmuxError::Masked),
            None => Err(TmuxError::MaskUnknown),
        }
    }

    fn enter(&self, target: &str) -> Result<(), TmuxError> {
        self.run(&["send-keys", "-t", target, "Enter"]).map(drop)
    }

    /// Metni yazar ve tek Enter gönderir. Metin ASLA argv'ye girmez (TBD#369: `/proc/<pid>/cmdline`ı başka kullanıcı
    /// okuyabilir): stdin'den tampona yüklenir, tek parça bracketed paste ile yapıştırılır (satır sonu TUI'de Enter
    /// sayılıp mesajı bölmez). Yapıştırma olmazsa (hata, zaman aşımı) tampon silinir. `settle`: metinle Enter arasındaki
    /// bekleme (codex ister). NUL içeren metin `BadArgument("text")`. Diğer denetim karakterleri (sekme ve satır sonu
    /// dışında) ATILIR; boş olmayan metinden yalnız boşluk/satır sonu kalıyorsa hiçbir şey gönderilmez (yalın Enter
    /// seçili düğmeyi onaylardı): `BadArgument("text")`. Bilerek yalın Enter isteyen çağıran `""` verir.
    ///
    /// YARIŞ (kapatılamaz): `guard` denetimi ile yapıştırma AYRI tmux çağrılarıdır; arada açılan bir parola istemi
    /// yakalanmaz. Pencere, yoklama + iki tmux süreci kadardır.
    pub fn send_text(
        &self,
        name: &str,
        text: &str,
        settle: Duration,
        guard: MaskGuard,
    ) -> Result<(), TmuxError> {
        let target = exact_target(name)?;
        if text.contains('\0') {
            return Err(TmuxError::BadArgument("text"));
        }
        // Python `_TEXT_CONTROL_RE` (C0 sekme/satır sonu hariç, DEL, C1) = `char::is_control` eksi `\t \n \r`.
        let clean: String = text
            .chars()
            .filter(|c| !c.is_control() || matches!(c, '\t' | '\n' | '\r'))
            .collect();
        if !text.is_empty() && py_strip(&clean).is_empty() {
            return Err(TmuxError::BadArgument("text"));
        }
        let text = clean.as_str();
        self.guard(name, guard)?;
        if text.is_empty() {
            thread::sleep(settle);
        } else {
            let timeout = self.timeout.max(send_text_timeout(text.chars().count()));
            self.paste_text(&target, text, timeout)?;
            thread::sleep(settle.max(PASTE_SETTLE));
        }
        self.enter(&target)
    }

    fn paste_text(&self, target: &str, text: &str, timeout: Duration) -> Result<(), TmuxError> {
        let buf = next_buffer();
        let load = ["load-buffer", "-b", &buf, "-"];
        let paste = ["paste-buffer", "-p", "-d", "-b", &buf, "-t", target];
        self.paste_buffered(&buf, &[&load, &paste], text.as_bytes(), timeout)
    }

    /// tmux komutlarını sırayla koşar; `payload` İLKİNİN stdin'ine verilir. Yapıştırma olmazsa tampon silinir.
    fn paste_buffered(
        &self,
        buf: &str,
        commands: &[&[&str]],
        payload: &[u8],
        timeout: Duration,
    ) -> Result<(), TmuxError> {
        let result = commands.iter().enumerate().try_for_each(|(i, args)| {
            let call = Call {
                input: (i == 0).then_some(payload),
                ..Call::new(args)
            };
            self.exec(call, timeout).map(drop)
        });
        if let Err(e) = result {
            // Zaman aşımında da sil: metin (parola olabilir) sunucuda okunabilir kalmasın (TBD#369 P9).
            if let Err(del) = self.run(&["delete-buffer", "-b", buf]) {
                swallow(Swallowed::DeleteBuffer, &del);
            }
            return Err(e);
        }
        Ok(())
    }

    /// Ham yapıştırma için `-S` gerekli mi (Python `_raw_paste_flags`). tmux 3.7+ `paste-buffer`, `-S` verilmezse
    /// kontrol karakterlerini görünür metne çevirir; eski sürümler `-S`i tanımaz. Sunucunun `list-commands` çıktısından
    /// okunur; `paste-buffer` satırı yoksa [`TmuxError::BadOutput`] (hiçbir şey gönderilmez).
    fn raw_needs_no_vis(&self) -> Result<bool, TmuxError> {
        let cached = *self
            .raw_probe
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if let Some((at, flag)) = cached {
            if at.elapsed() < RAW_PROBE_TTL {
                return Ok(flag);
            }
        }
        let now = Instant::now();
        let out = self.run(&["list-commands"])?;
        let text = String::from_utf8_lossy(&out.stdout);
        let line = text
            .split('\n')
            .find(|l| l.starts_with("paste-buffer "))
            .ok_or(TmuxError::BadOutput)?;
        let flags = line.split_once("[-").map_or("", |(_, rest)| rest);
        let flag = flags.split(']').next().is_some_and(|f| f.contains('S'));
        self.set_raw_probe(Some((now, flag)));
        Ok(flag)
    }

    fn set_raw_probe(&self, value: Option<(Instant, bool)>) {
        *self
            .raw_probe
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = value;
    }

    /// Sürüm yoklaması önbelleğini boşaltır (Python `_reset_raw_paste_probe`).
    pub fn reset_raw_paste_probe(&self) {
        self.set_raw_probe(None);
    }

    /// Ham tuş verisi (xterm.js `onData`): Enter EKLEMEZ. Veri (parola olabilir) ASLA argv'ye girmez (TBD#385): stdin'den
    /// tampona yüklenir ve AYNI tmux sürecinde `paste-buffer -r` ile olduğu gibi yazılır (`-p` YOK; `-d` tamponu siler).
    /// NUL dahil her bayt geçer. `send-keys`ten farkı: pane copy-mode'dayken de veri uygulamaya gider.
    pub fn send_raw(&self, name: &str, data: &str, guard: MaskGuard) -> Result<(), TmuxError> {
        if data.is_empty() {
            return Ok(());
        }
        let target = exact_target(name)?;
        self.guard(name, guard)?;
        let keep = self.raw_needs_no_vis()?;
        let buf = next_buffer();
        let mut args = vec!["load-buffer", "-b", &buf, "-", ";", "paste-buffer", "-r"];
        if keep {
            args.push("-S");
        }
        args.extend(["-d", "-b", &buf, "-t", &target]);
        let timeout = self.timeout.max(send_text_timeout(data.chars().count()));
        let result = self.paste_buffered(&buf, &[&args], data.as_bytes(), timeout);
        if result.is_err() {
            self.reset_raw_paste_probe();
        }
        result
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
