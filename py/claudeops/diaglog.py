"""Diag-log — sessiz spawn-başarısızlıklarının kalıcı izi.

[[spawn-zombie-child-degrades-web-server]] / [[resume-deferred-tool-marker]]:
panel/tarayıcı sekmesi kapansa da geçmiş kalsın diye append-only JSONL. spawn.py
(fallback tetiklenince) ve commands/web.py (diag test/restart/ask) buraya yazar.
Leaf modül (sadece paths'e bağımlı) — spawn.py'nin commands/ paketine bağımlı
OLMAMASI için (yön: commands → spawn, tersi değil) bilerek ayrı dosyada.

Best-effort: log yazımı/okuması ASLA çağıran akışı (spawn/diag) kesmemeli.
"""
from __future__ import annotations
import datetime
import json
import os

from .paths import CLAUDEOPS_DIR

DIAG_LOG = os.path.join(CLAUDEOPS_DIR, "diag.log")


def diag_log(event: str, **data) -> None:
    try:
        entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "event": event, **data}
        with open(DIAG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def diag_log_tail(n: int = 20) -> list:
    try:
        with open(DIAG_LOG, encoding="utf-8") as f:
            lines = f.readlines()
        return [ln.strip() for ln in lines[-n:] if ln.strip()]
    except Exception:
        return []


def diag_log_recent_fallback_count(window_minutes: float = 15.0) -> int:
    """Son `window_minutes` içinde kaç `spawn_fallback_used` oldu (spawn.py'nin
    gnome-terminal'i TÜM retry'larıyla denedikten SONRA headless'e düştüğü olay).

    2026-08-28 canlı bulundu: TEK bir fallback normal/ara-sıra bir flake sayılır
    (spawn.py'nin retry'ı çoğunu zaten sessizce yutar) — ama KISA sürede ARKA ARKAYA
    birden fazlası gnome-terminal-server'ın o an gerçekten sorunlu olduğuna işaret
    eder. Bu sayı UI'de eşiği aşınca kullanıcıya restart öner (asla OTOMATİK
    restart etme — [[layout-needs-unlocked-screen]]'deki gibi TÜM açık pencereleri
    kapatan yıkıcı bir işlem, kullanıcı onayı şart).
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(minutes=window_minutes)
    count = 0
    for ln in diag_log_tail(500):
        try:
            entry = json.loads(ln)
            if entry.get("event") != "spawn_fallback_used":
                continue
            if datetime.datetime.fromisoformat(entry["ts"]) >= cutoff:
                count += 1
        except Exception:
            continue
    return count
