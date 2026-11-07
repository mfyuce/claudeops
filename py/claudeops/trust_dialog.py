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
    """(rakam, imleç zaten üstünde mi) ya da None."""
    for line in (text or "").splitlines():
        m = _YES_RE.match(line)
        if m:
            return m.group("n"), bool(m.group("ptr"))
    return None


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
            if not on_it:
                send_raw(name, digit)
                sleep(0.3)
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
