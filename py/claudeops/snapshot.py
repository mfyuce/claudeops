"""Fleet snapshot — çalışan session'ların anlık görüntüsünü kaydet/geri-yükle.

TODO.md 2026-09-16 maddesi (kullanıcı: "last running snapshot gibi bisi olmali.
makineyi kapatinca kaldigi yerden devam etmesi icin"): guard kasıtlı kapalı
([[feedback-manual-fleet-control]]), bu yüzden reboot sonrası fleet'i geri açmak
[[reboot-recovery]]'nin otomatik jsonl-resume mekanizmasından FARKLI — açıkça
kullanıcı-tetiklemeli üç adım (kaydet → görüntüle → geri-yükle).

Leaf modül (sadece atomic_json/paths'e bağımlı) — settings.py ile aynı disiplin,
commands/ paketine bağımlı olmayan modüller de sorunsuz import edebilsin.
"""
from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, List

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

SNAPSHOT_JSON = os.path.join(CLAUDEOPS_DIR, "last_snapshot.json")


def save_snapshot(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`sessions`: [{"name","cwd","model","permission_mode","effort","cli"}] —
    çağıran (web.py) canlı Session listesinden bu şekli üretir; burası sadece
    diske yazar (discovery'ye bağımlı DEĞİL, leaf disiplini)."""
    data = {"saved_at": time.time(), "sessions": sessions}
    atomic_write_json(SNAPSHOT_JSON, data)
    return data


def load_snapshot() -> Dict[str, Any]:
    """Eksik/bozuk dosyaya toleranslı — hiç kayıt yoksa boş şekil döner
    (settings.py'nin load_settings()'iyle aynı tolerans deseni)."""
    try:
        with open(SNAPSHOT_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sessions"), list):
            return {"saved_at": data.get("saved_at"), "sessions": data["sessions"]}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"saved_at": None, "sessions": []}
