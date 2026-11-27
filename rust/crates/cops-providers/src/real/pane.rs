//! G4 gerçek [`Pane`] uygulayıcısı: [`TmuxPane`] `cops-tmux` üstüne ince sarmalayıcı (Python `tmux_backend`in
//! `tmux_send_keys`, `tmux_send_special_key`, `tmux_capture` işlevleri + `time.monotonic`/`time.sleep`).
//!
//! Sözleşme (`docs/rs-prov.md`, "`Pane` sözleşmesi") ve değişmezler `cops-tmux`tadır, burada YENİDEN yazılmaz:
//! - hedef her zaman TAM ad (`=ad:`); hedeflenemeyen ad hiçbir tmux komutu çalıştırmadan reddedilir;
//! - metin ASLA argv'ye girmez (stdin'den tampona, bracketed paste), NUL içeren metin reddedilir;
//! - otomatik gönderim [`MaskGuard::RefuseMasked`]: pane gizli girdi bekliyorsa YA DA durumu bilinmiyorsa hiçbir şey
//!   yazılmaz (TBD#367). Python `tmux_send_special_key` maske denetlemez; burada tuş da denetlenir (kapalı yön);
//! - her tmux çağrısı zaman aşımlı (5 sn; metin gönderiminde `max(5, 5 + karakter/1500)`);
//! - `capture` `capture-pane -e -p -S -N`: ANSI korunur (temizlik çekirdekte, `tui::strip_ansi`), pane copy-mode'a
//!   SOKULMAZ, çıktı Python `text=True` gibi çözülür (UTF-8 değilse None, `\r\n`/`\r` -> `\n`).
//!
//! Hiçbir yöntem panik atmaz. `settle` NaN, sonsuz ya da `Duration`a sığmazsa gönderim yapılmaz (false; Python NaN/inf'te
//! metni yapıştırıp Enter'sız düşer ya da boş metinde Enter gönderir; çağıranlar yalnız
//! [`crate::Cli::input_settle_delay`] sabitlerini verir).

use crate::real::launch::SystemClock;
use crate::spawn_exec::Clock;
use crate::tui::{Key, Pane};
use cops_tmux::{MaskGuard, Tmux};
use std::time::Duration;

/// Canlı ya da (testte) yalıtılmış tmux sunucusuna bağlı [`Pane`].
#[derive(Debug, Clone)]
pub struct TmuxPane {
    tmux: Tmux,
}

impl TmuxPane {
    /// Canlı filo: `tmux -L cops`.
    pub fn live() -> TmuxPane {
        TmuxPane::new(Tmux::cops())
    }

    /// Verilen istemciyle (testte `Tmux::with_socket(..).tmpdir(..)`).
    pub fn new(tmux: Tmux) -> TmuxPane {
        TmuxPane { tmux }
    }

    pub fn tmux(&self) -> &Tmux {
        &self.tmux
    }
}

/// `settle` saniyesini süreye çevirir. Negatif (ve `-inf`) = 0 (Python `max(settle, 0.15)` / `settle > 0` ile
/// beklemez); NaN, `+inf` ve sığmayan değer = None.
pub fn settle_duration(settle: f64) -> Option<Duration> {
    if settle.is_nan() {
        return None;
    }
    if settle <= 0.0 {
        return Some(Duration::ZERO);
    }
    Duration::try_from_secs_f64(settle).ok()
}

impl Pane for TmuxPane {
    fn send_text(&self, name: &str, text: &str, settle: f64) -> bool {
        let Some(settle) = settle_duration(settle) else {
            return false;
        };
        self.tmux.send_text(name, text, settle, MaskGuard::RefuseMasked).is_ok()
    }

    fn send_key(&self, name: &str, key: Key) -> bool {
        self.tmux.send_special_key(name, key.name(), MaskGuard::RefuseMasked).is_ok()
    }

    fn capture(&self, name: &str, lines: u32) -> Option<String> {
        self.tmux.capture(name, lines).ok()
    }

    fn monotonic(&self) -> f64 {
        SystemClock.monotonic()
    }

    fn sleep(&self, secs: f64) {
        SystemClock.sleep(secs);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settle_maps_python_values_and_never_panics() {
        assert_eq!(settle_duration(0.0), Some(Duration::ZERO));
        assert_eq!(settle_duration(-1.0), Some(Duration::ZERO));
        assert_eq!(settle_duration(f64::NEG_INFINITY), Some(Duration::ZERO));
        assert_eq!(settle_duration(0.15), Some(Duration::from_secs_f64(0.15)));
        assert_eq!(settle_duration(f64::NAN), None);
        assert_eq!(settle_duration(f64::INFINITY), None);
        assert_eq!(settle_duration(1e300), None);
    }

    #[test]
    fn invalid_settle_sends_nothing_and_sleep_ignores_bad_values() {
        // Sunucu yok: geçersiz `settle` tmux'a hiç gitmeden false; geçerli değer de sunucu olmadığı için false.
        let dir = tempfile::tempdir().unwrap();
        let p = TmuxPane::new(Tmux::with_socket("cxpane-yok").tmpdir(dir.path()));
        for s in [f64::NAN, f64::INFINITY, 1e300] {
            assert!(!p.send_text("x", "metin", s));
        }
        let t0 = p.monotonic();
        for s in [f64::NAN, -1.0, f64::NEG_INFINITY, f64::INFINITY, 1e300, 0.0] {
            p.sleep(s);
        }
        p.sleep(0.01);
        let t1 = p.monotonic();
        assert!(t1 - t0 >= 0.01 && t1 - t0 < 2.0, "{}", t1 - t0);
    }
}
