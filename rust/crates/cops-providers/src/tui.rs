//! G4: canlı pane'e yazan sağlayıcı davranışı (girdi hazırlama, mod kalıpları, devir kancaları, canlı model/effort
//! geçişi, başıboş diyalog). Python `providers/{base,claude_provider,codex_provider,copilot_provider,shell_provider,
//! ucli_provider}.py` karşılığı.
//!
//! Çekirdek SAF: tmux, saat ve uyku [`Pane`] arkasındadır; gerçek uygulayıcı G9'dadır. Sözleşme `docs/rs-prov.md` G4
//! bölümünde. Kurallar: yakalanan metin eşleştirilmeden önce [`strip_ansi`] uygulanır; onay tuşu yalnız ilgili diyalog
//! metni yakalamada görülünce gider (kör Enter yok).

use crate::pyfmt::py_isspace;
use crate::{claude, copilot, Cli};
use std::borrow::Cow;

/// Literal olmayan yoldan gönderilen tuşlar (bu grubun bastıkları; serbest metin tuş adı olamaz).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    Enter,
    Down,
}

impl Key {
    /// tmux tuş adı.
    pub fn name(self) -> &'static str {
        match self {
            Key::Enter => "Enter",
            Key::Down => "Down",
        }
    }
}

/// Canlı pane ve saat. Hiçbir yöntem panik atmaz; her biri sınırlı sürede döner.
pub trait Pane {
    /// Python `tmux_send_keys(name, text, settle_delay)`: metni TAM adlı oturuma yazar, `settle` saniye bekler, tek
    /// Enter gönderir. true = hepsi başarılı. Metin argv'ye girmez; gizli girdi bekleyen ya da durumu bilinmeyen
    /// pane'e hiçbir şey yazılmaz (false).
    fn send_text(&self, name: &str, text: &str, settle: f64) -> bool;
    /// Python `tmux_send_special_key`: TAM adlı oturuma tek tuş. true = tmux kabul etti.
    fn send_key(&self, name: &str, key: Key) -> bool;
    /// Python `tmux_capture(name, lines=)`: görünür alan + `lines` satır geçmiş, ANSI KORUNMUŞ. Hata, zaman aşımı,
    /// oturum yok ya da UTF-8 olmayan çıktı = None.
    fn capture(&self, name: &str, lines: u32) -> Option<String>;
    /// `time.monotonic()` (saniye, geri gitmez).
    fn monotonic(&self) -> f64;
    /// `time.sleep(secs)`: [`Pane::monotonic`] en az `secs` ilerler (bekleme döngüleri buna dayanır).
    fn sleep(&self, secs: f64);
}

/// Python `tmux_backend.strip_ansi` (SGR + BEL ya da ST ile biten OSC): tek kaynak `cops-tmux`.
pub use cops_tmux::strip_ansi;

/// Canlı geçişte yakalanan geçmiş satırı sayısı.
pub const DIALOG_CAPTURE_LINES: u32 = 20;
pub const MODEL_SWITCH_TIMEOUT_SECONDS: f64 = 20.0;
pub const MODEL_SWITCH_POLL_SECONDS: f64 = 0.3;
pub const EFFORT_SWITCH_TIMEOUT_SECONDS: f64 = 8.0;
pub const EFFORT_SWITCH_POLL_SECONDS: f64 = 0.3;
pub const STRAY_DIALOG_TIMEOUT_SECONDS: f64 = 6.0;
pub const STRAY_DIALOG_POLL_SECONDS: f64 = 0.5;
/// `Down` ile `Enter` arasındaki bekleme.
pub const STRAY_DIALOG_KEY_GAP_SECONDS: f64 = 0.2;

pub const MODEL_SWITCH_DIALOG: &str = "Switch model?";
pub const MODEL_SWITCH_DONE_MARKERS: [&str; 2] = ["Set model to", "Kept model as"];
pub const EFFORT_SWITCH_DIALOG: &str = "Change effort level?";
pub const EFFORT_SWITCH_DONE_MARKERS: [&str; 4] =
    ["Set effort level to", "Not applied:", "exceeds the cap", "Failed to set effort level"];

/// Canlı geçişin nasıl bittiği (Python None döner; çağıran günlük ve karar için kullanır). `MarkerSeen` sonucu
/// DOĞRULAMAZ: sonuç metni yakalamadaki eski bir satır da olabilir.
#[must_use]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwitchOutcome {
    /// Bu CLI canlı geçiş yapmaz: hiçbir şey gönderilmedi.
    Unsupported,
    /// Komut gönderilemedi: bekleme yok, başka tuş yok.
    SendFailed,
    /// Sonuç metni görüldü. `confirmed`: onay diyaloğuna Enter basıldı.
    MarkerSeen { confirmed: bool },
    /// Süre doldu. `confirmed`: onay diyaloğuna (döngüde ya da son bakışta) Enter basıldı.
    TimedOut { confirmed: bool },
}

struct Switch {
    command: String,
    dialog: &'static str,
    done: &'static [&'static str],
    timeout: f64,
    poll: f64,
}

fn screen(pane: &dyn Pane, name: &str) -> String {
    strip_ansi(&pane.capture(name, DIALOG_CAPTURE_LINES).unwrap_or_default())
}

fn run_switch(pane: &dyn Pane, name: &str, s: &Switch) -> SwitchOutcome {
    if !pane.send_text(name, &s.command, 0.0) {
        return SwitchOutcome::SendFailed;
    }
    let deadline = pane.monotonic() + s.timeout;
    let mut confirmed = false;
    while pane.monotonic() < deadline {
        pane.sleep(s.poll);
        let text = screen(pane, name);
        if !confirmed && text.contains(s.dialog) {
            // Python gibi: Enter sonucu bakılmaz, ikinci kez basılmaz.
            pane.send_key(name, Key::Enter);
            confirmed = true;
            continue;
        }
        if s.done.iter().any(|m| text.contains(m)) {
            return SwitchOutcome::MarkerSeen { confirmed };
        }
    }
    // Son bakış: diyalog tam şimdi açıldıysa onayla; görünmüyorsa Enter YOK.
    if !confirmed && screen(pane, name).contains(s.dialog) {
        pane.send_key(name, Key::Enter);
        confirmed = true;
    }
    SwitchOutcome::TimedOut { confirmed }
}

impl Cli {
    /// Konuşma sürdürür mü (devir ve takılma kurtarma hedefi olabilir mi).
    pub fn has_conversation(self) -> bool {
        self != Cli::Shell
    }

    /// Devir Faz1 (kapanış mesajı + kapat/aç) uygulanır mı.
    pub fn wants_handover_wrapup(self) -> bool {
        match self {
            Cli::Ucli => false,
            _ => self.has_conversation(),
        }
    }

    pub fn wants_stuck_recovery(self) -> bool {
        self.has_conversation()
    }

    /// Devrin kapanış turu için geçici ucuz model (yalnız claude: opus/fable -> sonnet).
    pub fn handover_model_downgrade(self, current_model: &str) -> Option<&'static str> {
        if self != Cli::Claude || current_model.is_empty() {
            return None;
        }
        let low = current_model.to_lowercase();
        (low.contains("opus") || low.contains("fable")).then_some("sonnet")
    }

    /// Devrin kapanış turu için effort: yalnız `current` `target`ın ÜSTÜNDEYSE `target`.
    pub fn handover_effort_downgrade<'a>(self, current: &str, target: &'a str) -> Option<&'a str> {
        if self != Cli::Claude {
            return None;
        }
        let levels = self.effort_levels();
        let at = |e: &str| levels.iter().position(|l| *l == e);
        (at(current)? > at(target)?).then_some(target)
    }

    /// `/model <target>` gönderir; "Switch model?" görülürse onaylar. Çağıran `target`ı
    /// [`Cli::handover_model_downgrade`]den alır (serbest metin verme: komut satırına aynen girer).
    pub fn apply_live_model_switch(self, pane: &dyn Pane, name: &str, target: &str) -> SwitchOutcome {
        if self != Cli::Claude {
            return SwitchOutcome::Unsupported;
        }
        let s = Switch {
            command: format!("/model {target}"),
            dialog: MODEL_SWITCH_DIALOG,
            done: &MODEL_SWITCH_DONE_MARKERS,
            timeout: MODEL_SWITCH_TIMEOUT_SECONDS,
            poll: MODEL_SWITCH_POLL_SECONDS,
        };
        run_switch(pane, name, &s)
    }

    /// `/effort <target>` gönderir; "Change effort level?" görülürse onaylar. `target` için
    /// [`Cli::apply_live_model_switch`] notu geçerli.
    pub fn apply_live_effort_switch(self, pane: &dyn Pane, name: &str, target: &str) -> SwitchOutcome {
        if self != Cli::Claude {
            return SwitchOutcome::Unsupported;
        }
        let s = Switch {
            command: format!("/effort {target}"),
            dialog: EFFORT_SWITCH_DIALOG,
            done: &EFFORT_SWITCH_DONE_MARKERS,
            timeout: EFFORT_SWITCH_TIMEOUT_SECONDS,
            poll: EFFORT_SWITCH_POLL_SECONDS,
        };
        run_switch(pane, name, &s)
    }

    /// Devir mesajından sonra kısa süre bekler; "Switch model?" görülürse REDDEDER (`Down`, `Enter`). `Down`
    /// gönderilemezse Enter yok (seçili düğme "Yes").
    pub fn dismiss_stray_dialog(self, pane: &dyn Pane, name: &str) {
        if self != Cli::Claude {
            return;
        }
        let deadline = pane.monotonic() + STRAY_DIALOG_TIMEOUT_SECONDS;
        while pane.monotonic() < deadline {
            if screen(pane, name).contains(MODEL_SWITCH_DIALOG) {
                if pane.send_key(name, Key::Down) {
                    pane.sleep(STRAY_DIALOG_KEY_GAP_SECONDS);
                    pane.send_key(name, Key::Enter);
                }
                return;
            }
            pane.sleep(STRAY_DIALOG_POLL_SECONDS);
        }
    }

    /// Metin yazımı ile Enter arasındaki bekleme (saniye).
    pub fn input_settle_delay(self) -> f64 {
        match self {
            Cli::Codex => 0.15,
            _ => 0.0,
        }
    }

    /// Pane'e gönderilmeden önce metin. ucli her satırı ayrı tur sayar (sekme tamamlamayı tetikler): satır sonu ya da
    /// sekme varsa tüm boşluklar tek boşluğa iner, KESME YOK. Diğerleri ve tek satır: aynen.
    pub fn prepare_input(self, text: &str) -> Cow<'_, str> {
        if self != Cli::Ucli || !text.contains(['\n', '\r', '\t']) {
            return Cow::Borrowed(text);
        }
        Cow::Owned(text.split(py_isspace).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" "))
    }

    /// Konuşma özetleme komutu (yoksa None).
    pub fn compact_command(self) -> Option<&'static str> {
        match self {
            Cli::Claude => Some("/compact"),
            _ => None,
        }
    }

    /// (mod, desen) çiftleri, eşleştirme sırasıyla; boş = bu CLI'da canlı mod okuma yok. Desenler Python `re`
    /// metnidir ve büyük/küçük harf duyarsız kullanılır (tüketici notu: `docs/rs-prov.md` G4).
    pub fn mode_status_patterns(self) -> &'static [(&'static str, &'static str)] {
        match self {
            Cli::Claude => &claude::MODE_STATUS_PATTERNS,
            Cli::Copilot => &copilot::MODE_STATUS_PATTERNS,
            _ => &[],
        }
    }

    /// Shift+Tab döngüsüyle canlıyken hedeflenebilen modlar; boş = canlı mod değiştirme yok.
    pub fn cyclable_modes(self) -> &'static [&'static str] {
        match self {
            Cli::Claude => &claude::CYCLABLE_MODES,
            _ => &[],
        }
    }
}
