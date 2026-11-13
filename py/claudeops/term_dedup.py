"""Terminal girdisi için tekrar-teslim koruması (`input_id`).

Uzak host yolu (devtunnel) bazen 15-40 sn yanıtsız kalır; proxy aynı isteği `input_id` ile yeniden dener. İlk istek aslında
uzağa ulaşıp yazılmış olabilir: uzak taraf son `TTL_SECONDS` içinde gördüğü `(yol, ad, input_id)` üçlüsünü YAZMADAN `ok:true`
döndürür (çift yazma yok). `input_id` yoksa (eski istemci) hiçbir şey değişmez. Leaf modül, yalnız stdlib."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

TTL_SECONDS = 300.0
MAX_ENTRIES = 4096
MAX_ID_LEN = 64

_lock = threading.Lock()
_seen: Dict[tuple, float] = {}


def valid_id(value: Any) -> Optional[str]:
    if isinstance(value, str) and 0 < len(value) <= MAX_ID_LEN and value.isprintable() and " " not in value:
        return value
    return None


def claim(path: str, name: str, input_id: str, now: Optional[float] = None) -> bool:
    """True = yeni (işle), False = yakın zamanda görülmüş tekrar (yazma)."""
    t = time.monotonic() if now is None else now
    key = (path, name, input_id)
    with _lock:
        if len(_seen) >= MAX_ENTRIES or (_seen and len(_seen) % 64 == 0):
            for k in [k for k, ts in _seen.items() if t - ts > TTL_SECONDS]:
                del _seen[k]
            if len(_seen) >= MAX_ENTRIES:
                _seen.pop(next(iter(_seen)))
        ts = _seen.get(key)
        if ts is not None and t - ts <= TTL_SECONDS:
            return False
        _seen[key] = t
        return True


def release(path: str, name: str, input_id: str) -> None:
    """Yazım başarısız olduysa kaydı sil: yeniden deneme gerçekten yazabilsin."""
    with _lock:
        _seen.pop((path, name, input_id), None)
