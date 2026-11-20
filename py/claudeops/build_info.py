"""Çalışan sürecin commit'i ve diskteki commit (20 Kas): merge sonrası servis yeniden başlatıldı mı görünsün.

`RUNNING` süreç içe aktarılırken bir kez okunur (o an diskteki kod = çalışan kod); `disk` her çağrıda (30 sn önbellekli) yeniden
okunur. İkisi farklıysa `stale` = diskteki kod daha yeni, süreç eski koda sahip: `restart_drain` gerekir. Yaprak modül; hata = boş."""
from __future__ import annotations

import subprocess
import time
from typing import Any, Dict

from .paths import REPO_DIR

_TTL = 30.0
_cache: Dict[str, Any] = {"at": 0.0, "val": ""}


def _head(repo: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


RUNNING = _head(REPO_DIR)
STARTED_AT = time.time()


def info(repo: str = "") -> Dict[str, Any]:
    now = time.monotonic()
    if repo:
        disk = _head(repo)
    else:
        if now - _cache["at"] > _TTL:
            _cache.update(at=now, val=_head(REPO_DIR))
        disk = _cache["val"]
    return {"running": RUNNING, "disk": disk, "stale": bool(RUNNING and disk and RUNNING != disk), "started_at": STARTED_AT}
