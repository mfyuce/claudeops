"""Evren reviewer yuva ölçekleyici (sahip 18 Kas, "Evren dersi"). Elle `review_slots evren=N` yerine, Evren `GET /v1/quota` (hesap
eşzamanlılığı, günlük kalan token) ve hata geri çekilmesinden eşzamanlı Evren koşu sayısını hesaplar.

Kurallar: toplam <= hesap eşzamanlılık sınırı (8) - başkalarının kullandığı; glm/gemma model başına en çok 2 (adil pay; qwen vb. sınırsız);
günlük kalan token az ise 1 ya da 0; `503 model_capacity_exhausted` / `429` görülünce yuva yarıya iner (10 dk sessizlikle toparlanır).
Kota okunamazsa ELLE ayar (`review_slots evren=N`, yoksa 1) aynen geçer: ölçekleyici asla koşuyu kendi başına düşürmez/büyütmez.
Anahtar loga/argv'ye girmez; tek istek önbelleklenir (TTL 60 sn)."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

DEFAULT_ENDPOINT = "https://evren-llmapi.ssyz.org.tr/v1"
TTL = 60.0
BACKOFF_SECS = 600.0
FAIR_SHARE = 2                       # glm/gemma yoğunken model başına adil pay (18 Kas ölçüm)
FAIR_RE = re.compile(r"glm|gemma", re.I)
DAILY_STOP = 300_000                 # kalan günlük token bunun altında: yeni Evren koşusu açılmaz
DAILY_LOW = 1_500_000                # bunun altında: tek yuva
CAPACITY_RE = re.compile(r"model_capacity_exhausted|\b429\b|rate.?limit|too many requests", re.I)
MAX_DEFAULT = 8

_LOCK = threading.Lock()
_ST: Dict[str, Any] = {"snap": None, "at": 0.0, "fail_at": 0.0, "level": 0, "last_err": 0.0, "errors": 0}


def model_cap(model_slug: str) -> int:
    """Bu modelin eşzamanlı koşu üst sınırı (adil pay: glm/gemma 2, öteki sınırsız=hesap sınırı)."""
    return FAIR_SHARE if FAIR_RE.search(model_slug or "") else 10 ** 6


def fetch_quota(key: str, endpoint: str = DEFAULT_ENDPOINT, opener: Optional[Callable] = None, timeout: float = 15.0) -> Optional[dict]:
    if not key:
        return None
    req = urllib.request.Request(endpoint.rstrip("/") + "/quota", headers={"X-API-Key": key})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            d = json.load(r)
        return d if isinstance(d, dict) else None
    except Exception:       # noqa: BLE001  ağ/JSON hatası: ölçekleyici devre dışı kalır, elle ayar geçer
        return None


def snapshot(key_fn: Callable[[], str], now: Optional[float] = None, fetch: Optional[Callable] = None) -> Optional[dict]:
    """Önbellekli kota görüntüsü; okunamazsa SON bilinen (en çok 10 dk bayat) ya da None."""
    t = time.time() if now is None else now
    with _LOCK:
        if _ST["snap"] is not None and t - _ST["at"] < TTL:
            return _ST["snap"]
        if t - _ST["fail_at"] < 30.0:         # son deneme başarısızdı: panel yoklaması her seferinde ağa çıkmasın
            return _ST["snap"]
    d = (fetch or (lambda: fetch_quota(key_fn())))()
    with _LOCK:
        if d is not None:
            _ST["snap"], _ST["at"] = d, t
        else:
            _ST["fail_at"] = t
            if _ST["snap"] is not None and t - _ST["at"] > 600:
                _ST["snap"] = None
        return _ST["snap"]


def note_capacity_error(now: Optional[float] = None) -> None:
    t = time.time() if now is None else now
    with _LOCK:
        if t - _ST["last_err"] > BACKOFF_SECS:
            _ST["level"] = 0
        _ST["level"] = min(3, _ST["level"] + 1)
        _ST["last_err"] = t
        _ST["errors"] += 1


def note_if_capacity(text: str, now: Optional[float] = None) -> bool:
    """Koşu çıktısında 503 model_capacity_exhausted / 429 varsa geri çekilmeyi tetikler."""
    if text and CAPACITY_RE.search(text[-20000:]):
        note_capacity_error(now)
        return True
    return False


def _level(now: float) -> int:
    with _LOCK:
        if now - _ST["last_err"] > BACKOFF_SECS:
            return 0
        return int(_ST["level"])


def compute_slots(snap: Optional[dict], manual: int, running: int, cfg_max: int = MAX_DEFAULT, now: Optional[float] = None) -> Tuple[int, str]:
    """(evren yuva sayısı, neden). `running` = şu an çalışan kendi Evren koşularımız (hesap eşzamanlılığından başkalarınınkini ayırmak için)."""
    t = time.time() if now is None else now
    lvl = _level(t)
    if snap is None:
        n = max(1, manual)
        return (max(1, n >> lvl) if lvl else n), "kota okunamadı: elle ayar" + (f", geri çekilme {lvl}" if lvl else "")
    limit = int(snap.get("concurrency_limit") or cfg_max)
    used = int(snap.get("concurrent_requests") or 0)
    others = max(0, used - running)
    n = max(0, min(cfg_max, limit - others))
    why = [f"hesap {limit}, başkaları {others}"]
    rem = snap.get("daily_remaining_tokens")
    if isinstance(rem, (int, float)):
        if rem < DAILY_STOP:
            return 0, f"günlük kalan {int(rem)} token (< {DAILY_STOP}): yeni koşu yok"
        if rem < DAILY_LOW:
            n = min(n, 1)
            why.append(f"günlük kalan {int(rem)}: tek yuva")
    if lvl:
        n = max(1, n >> lvl) if n > 0 else 0  # doluyken (n=0) geri çekilme yuva AÇMAZ
        why.append(f"geri çekilme {lvl}")
    return n, ", ".join(why)


def view(now: Optional[float] = None) -> Dict[str, Any]:
    """Panel için özet (anahtarsız)."""
    t = time.time() if now is None else now
    with _LOCK:
        s = dict(_ST["snap"] or {})
        age = t - _ST["at"] if _ST["snap"] is not None else None
        errs, lvl = _ST["errors"], (int(_ST["level"]) if t - _ST["last_err"] <= BACKOFF_SECS else 0)
    return {"daily_remaining_tokens": s.get("daily_remaining_tokens"), "daily_limit_tokens": s.get("daily_limit_tokens"),
            "concurrent_requests": s.get("concurrent_requests"), "concurrency_limit": s.get("concurrency_limit"),
            "age_secs": None if age is None else int(age), "backoff_level": lvl, "capacity_errors": errs}


def reset_for_tests() -> None:
    with _LOCK:
        _ST.update({"snap": None, "at": 0.0, "fail_at": 0.0, "level": 0, "last_err": 0.0, "errors": 0})
