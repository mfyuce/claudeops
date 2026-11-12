"""Tek kullanımlık, kısa ömürlü WebSocket bileti (`POST /api/ws-ticket` -> `?ticket=`).

Amaç: kalıcı panel token'ı `/ws`, `/ws/term` sorgu dizesinde dolaşmasın (proxy/erişim logları). Bilet 30 sn geçerli, BİR kez
tüketilir, yalnız bellekte durur (restart'ta tüm biletler düşer; istemci yeniden bilet alır). Eski `?token=` yolu geriye
uyumlu kalır (bir sürüm). `compare_digest` gerekmez: bilet rastgele 192 bit, sözlük araması sabit-zaman değil ama tahmin edilemez
ve tek kullanımlık."""
from __future__ import annotations

import secrets
import threading
import time

TTL_SECONDS = 30.0
MAX_PENDING = 256          # bellek tavanı: bir istemci biletleri yağdırırsa en eskiler atılır

_LOCK = threading.Lock()
_TICKETS: dict = {}        # bilet -> bitiş (monotonic)


def issue(now: float | None = None) -> str:
    now = time.monotonic() if now is None else now
    t = secrets.token_urlsafe(24)
    with _LOCK:
        for k in [k for k, exp in _TICKETS.items() if exp <= now]:
            del _TICKETS[k]
        while len(_TICKETS) >= MAX_PENDING:
            del _TICKETS[min(_TICKETS, key=_TICKETS.get)]
        _TICKETS[t] = now + TTL_SECONDS
    return t


def consume(ticket: str, now: float | None = None) -> bool:
    """Geçerliyse True ve bileti SİLER (ikinci kullanım False)."""
    if not ticket:
        return False
    now = time.monotonic() if now is None else now
    with _LOCK:
        exp = _TICKETS.pop(ticket, None)
    return exp is not None and exp > now
