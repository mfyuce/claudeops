"""Claude/Anthropic hizmetiyle açılan ucli oturumlarının dolar sayacı ve GÜNLÜK tavan (sahip, 2026-11-01: takım Claude Code
yerine ucli kullanacak, 200 USD API kredisi; tavan settings'ten: `ucli_cost.daily_cap_usd`). Saf-ish yaprak modül: yalnız
oturum başına `--usage-log` dosyalarını okur (`~/.claude/claudeops/ucli_usage/<oturum>.jsonl`). Tavan aşılınca YENİ Claude
oturumu açılmaz (`cap_exceeded`); çalışan oturumlara DOKUNULMAZ (sahibin elindeki karar). Maliyet bir ALT SINIRDIR: fiyat
tablosu `review.ANTHROPIC_PRICES`, 1h yazma çarpanı 1,6 (= 2x / 1,25x), >100K istem kademesi ayrılmaz."""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from . import review as rv
from .settings import ucli_cost_config

USAGE_DIR = os.path.expanduser("~/.claude/claudeops/ucli_usage")
_CACHE: Dict[str, Any] = {"at": 0.0, "usd": 0.0, "day": ""}
_TTL = 30.0
CAP_CODE = "ucli_daily_cap"   # başlatma sonucunda `code` alanı: arayüz "tavanı yükselt ve tekrar dene" sunar


class DailyCapExceeded(ValueError):
    """Günlük USD tavanı aşıldı: yeni Claude oturumu REDDEDİLİR. ValueError alt sınıfıdır (eski yakalayıcılar çalışır)."""

    def __init__(self, today_usd: float, cap_usd: float):
        self.today_usd = float(today_usd)
        self.cap_usd = float(cap_usd)
        super().__init__(f"claude: günlük USD tavanı aşıldı ({self.today_usd:.2f} / {self.cap_usd:.2f}); "
                         "Ayarlar'dan ucli_cost.daily_cap_usd yükselt ya da yarın dene")


def refusal(exc: BaseException) -> Dict[str, Any]:
    """Başlatma reddi -> web sonucu. Tavan reddiyse `code` + tutarlar eklenir (arayüz bunu yakalar)."""
    out: Dict[str, Any] = {"ok": False, "error": str(exc)}
    if isinstance(exc, DailyCapExceeded):
        out.update(code=CAP_CODE, today_usd=round(exc.today_usd, 2), cap_usd=round(exc.cap_usd, 2))
    return out


def log_path(session_name: str, base: str = USAGE_DIR) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(session_name))[:100] or "session"
    return os.path.join(base, f"{safe}.jsonl")


def _day_start_ms(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000.0


def today_usd(now: Optional[float] = None, base: str = USAGE_DIR, write_mult: float = 1.6) -> float:
    """Bugünkü (yerel gün) toplam $ (tüm oturum günlükleri). Dizin yoksa 0."""
    t = time.time() if now is None else now
    since = _day_start_ms(t)
    tot = 0.0
    try:
        names = os.listdir(base)
    except OSError:
        return 0.0
    for n in names:
        p = os.path.join(base, n)
        try:
            if not n.endswith(".jsonl") or os.path.getmtime(p) * 1000.0 < since:
                continue
        except OSError:
            continue
        tot += rv.usage_cost_usd(p, "", since_ms=since, write_mult=write_mult)
    return tot


def state(now: Optional[float] = None, base: str = USAGE_DIR, use_cache: bool = True) -> Dict[str, Any]:
    """{today_usd, cap_usd (0 = yok), pct (tavan yoksa None), cache_ttl}. 30 sn önbellekli (her /api/status'ta disk taraması yok)."""
    t = time.time() if now is None else now
    cfg = ucli_cost_config()
    if not use_cache or t - _CACHE["at"] > _TTL or _CACHE["day"] != time.strftime("%Y-%m-%d", time.localtime(t)):
        mult = 1.6 if cfg["cache_ttl"] == "1h" else 1.0
        _CACHE.update(at=t, usd=today_usd(t, base, mult), day=time.strftime("%Y-%m-%d", time.localtime(t)))
    cap = float(cfg["daily_cap_usd"])
    usd = float(_CACHE["usd"])
    return {"today_usd": round(usd, 4), "cap_usd": cap, "pct": (round(100.0 * usd / cap, 1) if cap > 0 else None),
            "cache_ttl": cfg["cache_ttl"]}


def invalidate() -> None:
    """Önbelleği düşür (ayar kaydedilince: cache_ttl çarpanı değişir, panel yeni değeri hemen görsün)."""
    _CACHE.update(at=0.0, usd=0.0, day="")


def cap_exceeded(now: Optional[float] = None, base: str = USAGE_DIR) -> bool:
    s = state(now, base, use_cache=False)
    return s["cap_usd"] > 0 and s["today_usd"] >= s["cap_usd"]
