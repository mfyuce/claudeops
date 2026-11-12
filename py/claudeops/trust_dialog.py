"""Claude "bu klasöre güveniyor musun?" diyaloğu (2026-11-02 dersi: `~/.claude.json`'da olmayan yeni proje klasörü
başlatılınca diyalog çıkar, oturum sessizce ölür/askıda kalır, motor "başladı" sayardı; zlkrnbulent 4 kez).

Yaprak mantık + enjekte edilebilir G/Ç (testler tmux'a dokunmaz):
- `is_trust_dialog(text)`: ANSI'siz pane metninde güven diyaloğu var mı.
- `yes_option(text)`: "Yes" seçeneğinin rakamı ve imlecin zaten üstünde olup olmadığı.
- `handle(name, registered, ...)`: diyalog görülürse YALNIZ KAYITLI klasörde "Yes" seçer; kayıtsızda DOKUNMAZ ("unregistered":
  sahibe sorulur). Dönüş: "none" | "accepted" | "unregistered".
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional, Tuple

_MARKERS = (
    "is this a project you created or one you trust",
    "do you trust the files in this folder",
    "trust this folder",
)
# Claude'un hazır istem ekranında (diyalog artık gelmez) görünen işaretler: yalnız bunlardan biri varken erken çıkılır
_PROMPT_MARKERS = ("? for shortcuts", "shift+tab to cycle", "bypass permissions", "accept edits", "auto mode", "esc to interrupt")
CALM_NO_MARKER_FACTOR = 3     # istem işareti YOKken (açılış başlığı/splash) erken çıkış için gereken sakin yoklama = calm_polls x bu
_YES_RE = re.compile(r"^\s*(?P<ptr>[❯>›]\s*)?(?P<n>\d)\.\s*Yes\b", re.IGNORECASE)


def is_trust_dialog(text: str) -> bool:
    """Diyalog pane'in SONUNDADIR ve hazır-istem altbilgisini kaplar. Konuşma geçmişinde (kaydırma) geçen "trust this folder"
    yazısı diyalog DEĞİL: 7 Kas copsdev oturumu kendi yazısı yüzünden 6 saat mesaj alamadı (`send_blocked_trust_dialog`)."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    low = "\n".join(lines[-30:]).lower()
    if not any(m in low for m in _MARKERS):
        return False
    tail = "\n".join(lines[-6:]).lower()
    return not any(m in tail for m in _PROMPT_MARKERS)


def yes_option(text: str) -> Optional[Tuple[str, bool]]:
    """(rakam, imleç zaten üstünde mi) ya da None. Numarasız menüde rakam "" (bkz. `yes_moves`)."""
    for line in (text or "").splitlines():
        m = _YES_RE.match(line)
        if m:
            return m.group("n"), bool(m.group("ptr"))
    moves = yes_moves(text)
    if moves is not None:
        return "", moves == 0
    return None


# Numarasız menü (Claude Code 12 Kas 2026: "❯ No, exit" / "  Yes, I trust this folder", imleç VARSAYILAN No'da):
# eski `1. Yes` kalıbı tutmadığı için runikppr açılışta diyalogda kaldı (`trust_dialog_no_yes_option`).
_OPT_RE = re.compile(r"^\s*(?P<ptr>[❯>›]\s*)?(?P<label>(?:Yes|No)\b.*)$", re.IGNORECASE)


def yes_moves(text: str) -> Optional[int]:
    """Numarasız menüde imleçten "Yes" satırına ok tuşu sayısı (+ aşağı, - yukarı); menü/imleç/Yes yoksa None.
    Yalnız pane SONUNDAKİ ardışık seçenek bloğu okunur (geçmişte geçen "Yes" satırları sayılmaz)."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    opts: list = []
    for line in reversed(lines[-12:]):
        m = _OPT_RE.match(line)
        if m:
            opts.insert(0, (bool(m.group("ptr")), m.group("label").lower().startswith("yes")))
        elif opts:
            break
    ptr = [i for i, (p, _) in enumerate(opts) if p]
    yes = [i for i, (_, y) in enumerate(opts) if y]
    if len(ptr) != 1 or len(yes) != 1:
        return None
    return yes[0] - ptr[0]


def handle(name: str, registered: bool, capture: Callable[[str], Optional[str]], send_key: Callable[[str, str], bool],
           send_raw: Callable[[str, str], bool], strip: Callable[[str], str], log: Callable[..., None],
           wait: float = 20.0, step: float = 1.0, calm_polls: int = 3,
           alive: Optional[Callable[[], bool]] = None, sleep: Callable[[float], None] = time.sleep) -> str:
    """Pane'i `wait` sn izler. Diyalog çıkarsa kayıtlıda Yes seçer ("accepted"), kayıtsızda bırakır ("unregistered").
    Erken çıkış ("none") YALNIZ hazır-istem işareti (`_PROMPT_MARKERS`) görünürken `calm_polls` kez art arda diyalogsuzsa; işaret yoksa
    (splash/başlık: diyalog geç gelebilir, 7 Kas animallangppr/vesuviusppr) `calm_polls x CALM_NO_MARKER_FACTOR` sakin yoklama ya da `wait` dolana dek yoklar. Oturum ölürse çıkar."""
    waited, calm = 0.0, 0
    while waited <= wait:
        if alive is not None and not alive():
            return "none"
        text = strip(capture(name) or "")
        if is_trust_dialog(text):
            if not registered:
                log("trust_dialog_unregistered", name=name)
                return "unregistered"
            opt = yes_option(text)
            if opt is None:
                log("trust_dialog_no_yes_option", name=name)
                return "unregistered"
            digit, on_it = opt
            if not on_it and digit:
                send_raw(name, digit)
                sleep(0.3)
            elif not on_it:
                moves = yes_moves(text) or 0
                for _ in range(abs(moves)):
                    send_key(name, "Down" if moves > 0 else "Up")
                    sleep(0.15)
                if yes_moves(strip(capture(name) or "")) != 0:      # imleç Yes'e gelmedi: Enter basma ("No, exit" oturumu kapatır)
                    log("trust_dialog_cursor_not_on_yes", name=name)
                    return "unregistered"
            send_key(name, "Enter")
            log("trust_dialog_accepted", name=name, option=digit)
            return "accepted"
        calm = calm + 1 if text.strip() else 0
        has_prompt = any(m in text.lower() for m in _PROMPT_MARKERS)
        if calm >= (calm_polls if has_prompt else calm_polls * CALM_NO_MARKER_FACTOR):
            return "none"
        sleep(step)
        waited += step
    return "none"


# ── tanı: bilinen / bilinmeyen diyaloglar (11 Kas 2026, dalgicppr 12 saat güven diyaloğunda kaldı) ──────────────────────────────
_RESUME_MARKERS = ("resume a conversation", "select a conversation to resume", "resume session", "choose a conversation")
_LOGIN_MARKERS = ("select login method", "paste code here", "choose the text style", "let's get started")
_MENU_RE = re.compile(r"^\s*[❯>›]?\s*\d\.\s+\S")


def dialog_head(text: str, n: int = 2) -> str:
    """Pane SONUNDAKİ diyalog bloğunun ilk `n` dolu satırı (tek satıra katlı): bildirim/panel 'diyalogda takılı: ...' için."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    tail = lines[-14:]
    for i, l in enumerate(tail):        # blok başı: ilk soru/başlık satırı (menü satırından önceki)
        if _MENU_RE.match(l):
            tail = tail[max(0, i - 2):]
            break
    return " | ".join(tail[:n])[:240]


def classify(text: str) -> Optional[Tuple[str, str]]:
    """Pane'de kullanıcı girişi bekleyen bir DİYALOG var mı: (tür, ilk 2 satır) | None.
    Türler: trust (güven klasörü), resume_picker, login, unknown_dialog (hazır-istem altbilgisi YOK + numaralı menü/`Enter to confirm`).
    Hazır-istem altbilgisi görünüyorsa hiçbiri değildir (konuşma geçmişinde geçen yazı diyalog sayılmaz). SAF."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return None
    if is_trust_dialog(text):
        return "trust", dialog_head(text)
    tail = "\n".join(lines[-8:]).lower()
    if any(m in tail for m in _PROMPT_MARKERS):
        return None
    low30 = "\n".join(lines[-30:]).lower()
    if any(m in low30 for m in _RESUME_MARKERS):
        return "resume_picker", dialog_head(text)
    if any(m in low30 for m in _LOGIN_MARKERS):
        return "login", dialog_head(text)
    menu = sum(1 for l in lines[-10:] if _MENU_RE.match(l))
    if menu >= 2 and ("enter to confirm" in tail or "esc to cancel" in tail or "to select" in tail or "use arrow" in tail):
        return "unknown_dialog", dialog_head(text)
    return None
