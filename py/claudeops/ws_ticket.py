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
_BOUND: dict = {}          # bilet -> Principal (çok kullanıcı modu: bileti kimin aldığı; yoksa kimliksiz bilet)


def issue(now: float | None = None, principal: object = None) -> str:
    """`principal` verilirse (çok kullanıcı) bilet o kimliğe bağlanır; `consume_principal` onu geri verir."""
    now = time.monotonic() if now is None else now
    t = secrets.token_urlsafe(24)
    with _LOCK:
        for k in [k for k, exp in _TICKETS.items() if exp <= now]:
            del _TICKETS[k]
            _BOUND.pop(k, None)
        while len(_TICKETS) >= MAX_PENDING:
            k = min(_TICKETS, key=_TICKETS.get)
            del _TICKETS[k]
            _BOUND.pop(k, None)
        _TICKETS[t] = now + TTL_SECONDS
        if principal is not None:
            _BOUND[t] = principal
    return t


def consume_principal(ticket: str, now: float | None = None):
    """Geçerli ve BİR kimliğe bağlıysa o kimliği döner (bileti siler); aksi None (bilet yine tüketilir)."""
    if not ticket:
        return None
    now = time.monotonic() if now is None else now
    with _LOCK:
        exp = _TICKETS.pop(ticket, None)
        p = _BOUND.pop(ticket, None)
    return p if exp is not None and exp > now else None


def consume(ticket: str, now: float | None = None) -> bool:
    """Geçerliyse True ve bileti SİLER (ikinci kullanım False)."""
    if not ticket:
        return False
    now = time.monotonic() if now is None else now
    with _LOCK:
        exp = _TICKETS.pop(ticket, None)
        _BOUND.pop(ticket, None)
    return exp is not None and exp > now


def consume_full(ticket: str, now: float | None = None):
    """(geçerli mi, bağlı kimlik ya da None); bileti her durumda SİLER. Rust ön kapı el sıkışması için (tek atomik çağrı)."""
    if not ticket:
        return False, None
    now = time.monotonic() if now is None else now
    with _LOCK:
        exp = _TICKETS.pop(ticket, None)
        p = _BOUND.pop(ticket, None)
    ok = exp is not None and exp > now
    return ok, (p if ok else None)
