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
