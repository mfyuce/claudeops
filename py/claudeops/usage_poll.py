"""Değnekçi tick'inde kullanım okuması (`usage_mode`: "tek" varsayılan | "tick"). Sahip kararı (13 Kas, TBD#203):
- `tek`: otomatik okuma YOK; yalnız panelde "Kullanımı kontrol et" basılınca.
- `tick`: oturumsuz yolu olanlar (claude `claude -p /usage`, API anahtarlı sağlayıcılar) her tick; açık oturuma `/usage` yazdıran
  (agy, copilot) en fazla `SESSION_MIN_GAP` (30 dk) aralıkla, çünkü canlı oturumu rahatsız eder.
Okuma arka plan thread'inde (tick bekletilmez); sonuç `last()` ile panele (`POST /api/usage {"cached":true}`). Saf mantık: toplayıcı ve
sağlayıcı sınıflandırması dışarıdan verilir (test edilebilir)."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Set

MODES = ("tek", "tick")
DEFAULT_MODE = "tek"
SESSION_MIN_GAP = 1800.0

_lock = threading.Lock()
_STATE: Dict[str, Any] = {"at": 0.0, "providers": {}, "per_at": {}, "busy": False}


def normalize_mode(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in MODES else DEFAULT_MODE


def due(kinds: Dict[str, bool], now: float, per_at: Dict[str, float]) -> Set[str]:
    """kinds: ad -> oturum ister mi. Oturumsuz olanlar hep; oturum isteyenler son okumadan `SESSION_MIN_GAP` sonra."""
    return {n for n, needs in kinds.items() if (not needs) or n not in per_at or now - float(per_at[n]) >= SESSION_MIN_GAP}


def tick(mode: object, collect: Callable[..., Dict[str, Any]], kinds: Dict[str, bool], now: Optional[float] = None,
         spawn: Callable[[Callable[[], None]], None] = lambda fn: threading.Thread(target=fn, name="usage-poll", daemon=True).start()) -> bool:
    """True = bir okuma başlatıldı. `tek` modunda hiçbir şey yapmaz."""
    if normalize_mode(mode) != "tick":
        return False
    t = time.time() if now is None else now
    with _lock:
        if _STATE["busy"]:
            return False
        names = due(kinds, t, _STATE["per_at"])
        if not names:
            return False
        _STATE["busy"] = True
        for n in names:
            _STATE["per_at"][n] = t

    def run() -> None:
        try:
            res = collect(only=names)
            provs = (res or {}).get("providers") or {}
            with _lock:
                _STATE["providers"].update(provs)
                _STATE["at"] = t
        except Exception:
            pass        # sessizce bir sonraki aralığa; tick'i/paneli düşürme
        finally:
            with _lock:
                _STATE["busy"] = False

    spawn(run)
    return True


def last() -> Dict[str, Any]:
    with _lock:
        return {"ok": True, "cached": True, "at": _STATE["at"], "providers": dict(_STATE["providers"]),
                "per_at": dict(_STATE["per_at"])}


def reset() -> None:
    with _lock:
        _STATE.update(at=0.0, providers={}, per_at={}, busy=False)
