//! G4: canlı pane'e yazan sağlayıcı davranışı (girdi hazırlama, mod kalıpları, devir kancaları, canlı model/effort
//! geçişi, başıboş diyalog). Python `providers/{base,claude_provider,codex_provider,copilot_provider,shell_provider,
//! ucli_provider}.py` karşılığı.
//!
//! Çekirdek SAF: tmux, saat, uyku ve günlük [`Pane`] arkasındadır; gerçek uygulayıcı `real/pane.rs`. Sözleşme
//! `docs/rs-prov.md` G4 bölümünde. Kural (TBD#399): EMİN OLUNAMAYAN EKRANDA TUŞ GÖNDERİLMEZ. Komut yalnız boş ve
//! boşta giriş kutusuna yazılır; tuş yalnız ekranın SONUNDA açık duran beklenen diyaloğa gider (kör Enter yok);
//! sonuç tipli döner.

use crate::pyfmt::py_isspace;
use crate::{claude, copilot, Cli, Diag};
use regex::Regex;
use serde_json::json;
use std::borrow::Cow;
use std::sync::LazyLock;

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
    /// `diag_log` (en iyi çaba).
    fn diag(&self, diag: &Diag);
}

use cops_tmux::input_box;
/// Python `tmux_backend.strip_ansi` (SGR + BEL ya da ST ile biten OSC): tek kaynak `cops-tmux`.
pub use cops_tmux::strip_ansi;

/// Canlı geçişte yakalanan geçmiş satırı: komuttan ÖNCEKİ sonuç satırları sayılıp yeni sayılmasın.
pub const SWITCH_CAPTURE_LINES: u32 = 200;
/// Başıboş diyalog taramasında yakalanan geçmiş satırı.
pub const DIALOG_CAPTURE_LINES: u32 = 20;
pub const MODEL_SWITCH_TIMEOUT_SECONDS: f64 = 20.0;
pub const MODEL_SWITCH_POLL_SECONDS: f64 = 0.3;
pub const EFFORT_SWITCH_TIMEOUT_SECONDS: f64 = 8.0;
pub const EFFORT_SWITCH_POLL_SECONDS: f64 = 0.3;
pub const STRAY_DIALOG_TIMEOUT_SECONDS: f64 = 6.0;
pub const STRAY_DIALOG_POLL_SECONDS: f64 = 0.5;
/// `Down` ile ekranın yeniden okunması arasındaki bekleme.
pub const STRAY_DIALOG_KEY_GAP_SECONDS: f64 = 0.2;

pub const MODEL_SWITCH_DIALOG: &str = "Switch model?";
pub const MODEL_SWITCH_DONE_MARKERS: [&str; 2] = ["Set model to", "Kept model as"];
pub const EFFORT_SWITCH_DIALOG: &str = "Change effort level?";
pub const EFFORT_SWITCH_DONE_MARKERS: [&str; 4] = [
    "Set effort level to",
    "Not applied:",
    "exceeds the cap",
    "Failed to set effort level",
];

const SWITCH_GUIDE_MAX: usize = 2;
const SWITCH_TITLE_WINDOW: usize = 15;
const BOX_FOOTER_MAX: usize = 12;
const BUSY_TAIL_LINES: usize = 12;
const BOX_RULE: &str = "────";

/// Sabit desen. `\s` yerine `[\s\x1c-\x1f]`: Python `\s` U+001C..U+001F'i de boşluk sayar.
fn pattern(p: &str) -> Regex {
    Regex::new(p).expect("sabit desen")
}

static SWITCH_YES_RE: LazyLock<Regex> = LazyLock::new(|| {
    pattern(
        r"^(?P<ptr>❯[\s\x1c-\x1f]*)?1\.[\s\x1c-\x1f]*Yes, switch to (?P<label>[^\s\x1c-\x1f].*)$",
    )
});
static SWITCH_NO_RE: LazyLock<Regex> =
    LazyLock::new(|| pattern(r"^(?P<ptr>❯[\s\x1c-\x1f]*)?2\.[\s\x1c-\x1f]*No, go back$"));
static SWITCH_GUIDE_RE: LazyLock<Regex> =
    LazyLock::new(|| pattern(r"(?i)enter to confirm|esc to cancel"));
static FOOTER_MENU_RE: LazyLock<Regex> =
    LazyLock::new(|| pattern(r"^(?:❯|[>›]?[\s\x1c-\x1f]*\d\.[\s\x1c-\x1f])"));

/// Canlı geçişin nasıl bittiği (Python `_Switch`; `Unsupported` = Python None).
#[must_use]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwitchOutcome {
    /// Bu CLI canlı geçiş yapmaz: hiçbir şey gönderilmedi.
    Unsupported,
    /// claude sonucu yazdı (uyguladı ya da reddetti) ve giriş kutusu hazır. `confirmed`: diyaloğa Enter basıldı.
    Done { confirmed: bool },
    /// Tur sürüyor: komut GÖNDERİLMEDİ.
    Busy,
    /// Giriş kutusunda yazılı metin: gönderilmedi.
    Draft,
    /// Geçiş diyaloğu zaten açık: gönderilmedi.
    DialogOpen,
    /// Ekran okunamadı ya da boş giriş kutusu görülmedi: gönderilmedi.
    Unreadable,
    /// Komut gönderilemedi (metin kutuda kalmış olabilir): bekleme yok, tuş yok.
    SendFailed,
    /// Gönderildi ama sonuç doğrulanamadı ya da diyalog açık kaldı.
    Unconfirmed { confirmed: bool },
}

impl SwitchOutcome {
    /// Bundan sonra pane'e başka metin yazılabilir mi (Python `handover._SWITCH_SAFE`).
    pub fn safe_to_type(self) -> bool {
        matches!(
            self,
            SwitchOutcome::Unsupported | SwitchOutcome::Done { .. } | SwitchOutcome::Busy
        )
    }

    /// Python değeri (`Unsupported` = None).
    pub fn as_str(self) -> Option<&'static str> {
        Some(match self {
            SwitchOutcome::Unsupported => return None,
            SwitchOutcome::Done { .. } => "done",
            SwitchOutcome::Busy => "busy",
            SwitchOutcome::Draft => "draft",
            SwitchOutcome::DialogOpen => "dialog",
            SwitchOutcome::Unreadable => "unreadable",
            SwitchOutcome::SendFailed => "send_failed",
            SwitchOutcome::Unconfirmed { .. } => "unconfirmed",
        })
    }
}

/// [`Cli::dismiss_stray_dialog`] sonucu (Python None / `DONE` / `UNCONFIRMED`).
#[must_use]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DismissOutcome {
    /// Geçiş diyaloğu görülmedi (ya da bu CLI'da yok).
    NotSeen,
    /// Reddedildi ve kapandığı doğrulandı.
    Closed,
    /// Açık kalmış olabilir (günlüğe yazılır).
    LeftOpen,
}

impl DismissOutcome {
    pub fn as_str(self) -> Option<&'static str> {
        match self {
            DismissOutcome::NotSeen => None,
            DismissOutcome::Closed => Some("done"),
            DismissOutcome::LeftOpen => Some("unconfirmed"),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
struct SwitchDialog {
    title: &'static str,
    label: String,
    on_no: bool,
}

fn trim(s: &str) -> &str {
    s.trim_matches(py_isspace)
}

/// ANSI'siz ekranın dolu satırları: kenar çizgisi atılmış; yalnız çerçeveden oluşan satır sayılmaz.
fn screen_rows(text: &str) -> Vec<&str> {
    text.split('\n')
        .map(|l| trim(trim(l).trim_matches('│')))
        .filter(|r| {
            !r.trim_matches(['│', '╭', '╮', '╰', '╯', '─', ' '])
                .is_empty()
        })
        .collect()
}

/// ANSI'siz ekranın SONUNDA açık duran geçiş diyaloğu: iki seçenek ardışık, tam olarak birinde imleç, altlarında
/// yalnız yardım satırı; konuşmada geçen aynı yazı diyalog değildir.
fn open_switch_dialog(text: &str) -> Option<SwitchDialog> {
    let mut rows = screen_rows(text);
    for _ in 0..SWITCH_GUIDE_MAX {
        match rows.last() {
            Some(r) if SWITCH_GUIDE_RE.is_match(r) && !FOOTER_MENU_RE.is_match(r) => rows.pop(),
            _ => break,
        };
    }
    let [.., yes, no] = rows.as_slice() else {
        return None;
    };
    if rows.len() < 3 {
        return None;
    }
    let (yes, no) = (SWITCH_YES_RE.captures(yes)?, SWITCH_NO_RE.captures(no)?);
    let on_no = no.name("ptr").is_some();
    if yes.name("ptr").is_some() == on_no {
        return None;
    }
    for row in rows[..rows.len() - 2]
        .iter()
        .rev()
        .take(SWITCH_TITLE_WINDOW)
    {
        if let Some(title) = [MODEL_SWITCH_DIALOG, EFFORT_SWITCH_DIALOG]
            .into_iter()
            .find(|t| t == row)
        {
            return Some(SwitchDialog {
                title,
                label: yes["label"].to_string(),
                on_no,
            });
        }
        if row.starts_with('❯') {
            break;
        }
    }
    None
}

/// Diyaloğun adı istenen hedef mi ("Sonnet 5.5" ~ `sonnet`, "high" ~ `high`; "xhigh" `high` DEĞİL).
fn label_matches(label: &str, target: &str) -> bool {
    let norm = |x: &str| {
        let s: String = x
            .to_lowercase()
            .chars()
            .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
            .collect();
        s.strip_prefix("claude").map(String::from).unwrap_or(s)
    };
    let (a, b) = (norm(label), norm(target));
    !a.is_empty() && !b.is_empty() && (a.starts_with(&b) || b.ends_with(&a))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PaneState {
    Ready,
    Busy,
    Draft,
    Dialog,
    Unreadable,
}

/// `capture-pane -e` ekranının durumu. Soluk/gri öneri yazılı metin sayılmaz (`cops_tmux::input_box`).
fn pane_state(raw: Option<&str>) -> PaneState {
    let Some(raw) = raw.filter(|r| !r.is_empty()) else {
        return PaneState::Unreadable;
    };
    let text = strip_ansi(raw);
    if open_switch_dialog(&text).is_some() {
        return PaneState::Dialog;
    }
    let Some(input) = input_box(raw) else {
        return PaneState::Unreadable;
    };
    let lines: Vec<&str> = text.split('\n').collect();
    let Some(last_rule) = lines.iter().rposition(|l| l.contains(BOX_RULE)) else {
        return PaneState::Unreadable;
    };
    let below = lines[last_rule + 1..].join("\n");
    let footer = screen_rows(&below);
    if footer.len() > BOX_FOOTER_MAX
        || footer
            .iter()
            .any(|r| FOOTER_MENU_RE.is_match(r) || SWITCH_GUIDE_RE.is_match(r))
    {
        // kutu eski bir kare: altında başka bir menü/diyalog var
        return PaneState::Unreadable;
    }
    if !trim(&input.typed.replace(['❯', '│'], "")).is_empty() {
        return PaneState::Draft;
    }
    let rows = screen_rows(&text);
    let tail = &rows[rows.len().saturating_sub(BUSY_TAIL_LINES)..];
    if tail.iter().any(|r| r.contains(claude::BUSY_STATUS_PATTERN)) {
        return PaneState::Busy;
    }
    PaneState::Ready
}

struct Switch<'a> {
    target: &'a str,
    command: String,
    dialog: &'static str,
    done: &'static [&'static str],
    timeout: f64,
    poll: f64,
}

struct Run<'a> {
    pane: &'a dyn Pane,
    name: &'a str,
    switch: Switch<'a>,
    /// Komuttan önceki ekrandaki sonuç satırı sayısı.
    seen: usize,
    confirmed: bool,
}

impl Run<'_> {
    fn count(&self, raw: &str) -> usize {
        let text = strip_ansi(raw);
        self.switch
            .done
            .iter()
            .map(|m| text.matches(m).count())
            .sum()
    }

    fn give_up(&self, result: SwitchOutcome, stage: &str) -> SwitchOutcome {
        self.pane.diag(&Diag {
            event: "live_switch_not_done",
            fields: vec![
                ("name", json!(self.name)),
                ("command", json!(&self.switch.command)),
                ("result", json!(result.as_str())),
                ("stage", json!(stage)),
            ],
        });
        result
    }

    /// Bir yoklama: beklenen diyaloğu BİR kez onaylar ya da yeni sonuç satırı + hazır kutu görür.
    fn look(&mut self) -> Option<SwitchOutcome> {
        let raw = self.pane.capture(self.name, SWITCH_CAPTURE_LINES)?;
        if let Some(d) = open_switch_dialog(&strip_ansi(&raw)) {
            if !self.confirmed
                && d.title == self.switch.dialog
                && !d.on_no
                && label_matches(&d.label, self.switch.target)
            {
                self.confirmed = true;
                if !self.pane.send_key(self.name, Key::Enter) {
                    let out = SwitchOutcome::Unconfirmed { confirmed: true };
                    return Some(self.give_up(out, "confirm_key"));
                }
            }
            return None;
        }
        (self.count(&raw) > self.seen
            && matches!(pane_state(Some(&raw)), PaneState::Ready | PaneState::Busy))
        .then_some(SwitchOutcome::Done {
            confirmed: self.confirmed,
        })
    }
}

fn run_switch(pane: &dyn Pane, name: &str, switch: Switch<'_>) -> SwitchOutcome {
    let mut run = Run {
        pane,
        name,
        switch,
        seen: 0,
        confirmed: false,
    };
    let before = pane.capture(name, SWITCH_CAPTURE_LINES);
    let refused = match pane_state(before.as_deref()) {
        PaneState::Ready => None,
        PaneState::Busy => Some(SwitchOutcome::Busy),
        PaneState::Draft => Some(SwitchOutcome::Draft),
        PaneState::Dialog => Some(SwitchOutcome::DialogOpen),
        PaneState::Unreadable => Some(SwitchOutcome::Unreadable),
    };
    if let Some(out) = refused {
        return run.give_up(out, "precheck");
    }
    run.seen = before.as_deref().map_or(0, |raw| run.count(raw));
    if !pane.send_text(name, &run.switch.command, 0.0) {
        return run.give_up(SwitchOutcome::SendFailed, "command");
    }
    let deadline = pane.monotonic() + run.switch.timeout;
    while pane.monotonic() < deadline {
        pane.sleep(run.switch.poll);
        if let Some(out) = run.look() {
            return out;
        }
    }
    // Son bakış: diyalog tam şimdi açıldıysa onayla ve sonucunu bir kez daha oku.
    let was_confirmed = run.confirmed;
    let mut out = run.look();
    if out.is_none() && run.confirmed && !was_confirmed {
        pane.sleep(run.switch.poll);
        out = run.look();
    }
    out.unwrap_or_else(|| {
        let failed = SwitchOutcome::Unconfirmed {
            confirmed: run.confirmed,
        };
        run.give_up(failed, "timeout")
    })
}

fn read_dialog(pane: &dyn Pane, name: &str) -> (bool, Option<SwitchDialog>) {
    let raw = pane.capture(name, DIALOG_CAPTURE_LINES);
    let dialog = raw
        .as_deref()
        .and_then(|r| open_switch_dialog(&strip_ansi(r)));
    (raw.is_some(), dialog)
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

    /// `/model <target>` gönderir; beklenen "Switch model?" diyaloğu görülürse onaylar. Çağıran `target`ı
    /// [`Cli::handover_model_downgrade`]den alır (serbest metin verme: komut satırına aynen girer). Sonuç
    /// [`SwitchOutcome::safe_to_type`] değilse pane'e başka metin yazma.
    pub fn apply_live_model_switch(
        self,
        pane: &dyn Pane,
        name: &str,
        target: &str,
    ) -> SwitchOutcome {
        if self != Cli::Claude {
            return SwitchOutcome::Unsupported;
        }
        let s = Switch {
            target,
            command: format!("/model {target}"),
            dialog: MODEL_SWITCH_DIALOG,
            done: &MODEL_SWITCH_DONE_MARKERS,
            timeout: MODEL_SWITCH_TIMEOUT_SECONDS,
            poll: MODEL_SWITCH_POLL_SECONDS,
        };
        run_switch(pane, name, s)
    }

    /// `/effort <target>` gönderir; beklenen "Change effort level?" diyaloğu görülürse onaylar. `target` ve sonuç
    /// için [`Cli::apply_live_model_switch`] notu geçerli.
    pub fn apply_live_effort_switch(
        self,
        pane: &dyn Pane,
        name: &str,
        target: &str,
    ) -> SwitchOutcome {
        if self != Cli::Claude {
            return SwitchOutcome::Unsupported;
        }
        let s = Switch {
            target,
            command: format!("/effort {target}"),
            dialog: EFFORT_SWITCH_DIALOG,
            done: &EFFORT_SWITCH_DONE_MARKERS,
            timeout: EFFORT_SWITCH_TIMEOUT_SECONDS,
            poll: EFFORT_SWITCH_POLL_SECONDS,
        };
        run_switch(pane, name, s)
    }

    /// Devir mesajından sonra (ya da geçiş güvenli bitmediğinde) kısa süre bekler; açık duran geçiş diyaloğunu
    /// (model ya da effort) REDDEDER: `Down`, ekranı yeniden oku, imleç "No"daysa `Enter`, kapandığını doğrula.
    /// Herhangi bir adım doğrulanamazsa başka tuş yok.
    pub fn dismiss_stray_dialog(self, pane: &dyn Pane, name: &str) -> DismissOutcome {
        if self != Cli::Claude {
            return DismissOutcome::NotSeen;
        }
        let stuck = |stage: &str| {
            pane.diag(&Diag {
                event: "stray_dialog_left_open",
                fields: vec![("name", json!(name)), ("stage", json!(stage))],
            });
            DismissOutcome::LeftOpen
        };
        let deadline = pane.monotonic() + STRAY_DIALOG_TIMEOUT_SECONDS;
        while pane.monotonic() < deadline {
            if let (_, Some(dialog)) = read_dialog(pane, name) {
                if !dialog.on_no {
                    if !pane.send_key(name, Key::Down) {
                        return stuck("down_key");
                    }
                    pane.sleep(STRAY_DIALOG_KEY_GAP_SECONDS);
                    match read_dialog(pane, name).1 {
                        Some(m) if m.title == dialog.title && m.on_no => {}
                        _ => return stuck("cursor"),
                    }
                }
                if !pane.send_key(name, Key::Enter) {
                    return stuck("enter_key");
                }
                pane.sleep(STRAY_DIALOG_POLL_SECONDS);
                return match read_dialog(pane, name) {
                    (true, None) => DismissOutcome::Closed,
                    _ => stuck("still_open"),
                };
            }
            pane.sleep(STRAY_DIALOG_POLL_SECONDS);
        }
        DismissOutcome::NotSeen
    }

    /// Metin yazımı ile Enter arasındaki bekleme (saniye).
    pub fn input_settle_delay(self) -> f64 {
        match self {
            Cli::Codex => 0.15,
            _ => 0.0,
        }
    }

    /// Pane'e gönderilmeden önce metin. ucli her satırı ayrı tur sayar (sekme tamamlamayı tetikler): satır sonu ya da
    /// sekme varsa tüm boşluklar tek boşluğa iner, KESME YOK. Diğerleri ve tek satır: aynen. Geriye hiçbir şey
    /// kalmıyorsa metin AYNEN döner (boş metne inerse yalın Enter olurdu; [`Pane::send_text`] onu reddeder).
    pub fn prepare_input(self, text: &str) -> Cow<'_, str> {
        if self != Cli::Ucli || !text.contains(['\n', '\r', '\t']) {
            return Cow::Borrowed(text);
        }
        let folded = text
            .split(py_isspace)
            .filter(|w| !w.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        if folded.is_empty() {
            return Cow::Borrowed(text);
        }
        Cow::Owned(folded)
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
