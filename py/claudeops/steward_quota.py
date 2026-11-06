"""Değnekçi kota bekçisi: Claude plan haftalık kullanımı (`claude -p /usage`) -> karar. SAF çekirdek (süreç, ayar ve
eylem `commands/web_steward.py`'de). TBD#116.

Modlar: `off` (varsayılan), `manual` (`manual_limit`: buna ulaşınca yeni iş alınmaz (drain); `shutdown_limit` (varsayılan final-1): çalışmayanlara devir, bitince kapat; `final_limit`: HARD kapanma), `auto` (günlük tavan
= `final_limit` x geçen gün / 7; tavana ulaşınca yeni iş alınmaz (`drain`), `final_limit`e ulaşınca durur). `day_<mon..sun>`
o haftanın günü için tavanı elle verir (her iki modda geçerli)."""
from __future__ import annotations

import dataclasses
import datetime
import math
import re
from typing import Any, Dict, Optional

MODES = ("off", "manual", "auto")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_FINAL = 95.0
DEFAULT_POLL_MINUTES = 10

_WEEK_RE = re.compile(r"Current week \(all models\):\s*(\d+(?:\.\d+)?)%\s*used(?:\s*·\s*resets\s+([^(\n]+?)\s*\(([^)]+)\))?")
_FABLE_RE = re.compile(r"Current week \(Fable\):\s*(\d+(?:\.\d+)?)%\s*used")
_SESSION_RE = re.compile(r"Current session:\s*(\d+(?:\.\d+)?)%\s*used")


@dataclasses.dataclass
class Usage:
    week_pct: Optional[float] = None
    fable_pct: Optional[float] = None
    session_pct: Optional[float] = None
    reset_ts: Optional[float] = None        # haftalık sıfırlanma (epoch)


@dataclasses.dataclass
class Decision:
    action: str = "ok"                      # ok | drain | shutdown (devirle kapat) | stop (HARD)
    cap: Optional[float] = None             # bugünün tavanı (kullanılan %)
    reason: str = ""


def _parse_reset(text: str, tz_name: str, now: float) -> Optional[float]:
    """'Oct 26, 5:59pm' (+ dilimi) -> epoch. Yıl metinde yok: bugünün yılı, geçmişe düşerse +1."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name.strip())
    except Exception:
        return None
    m = re.match(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)", text.strip(), re.I)
    if not m:
        return None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    if m.group(1).lower() not in months:     # "Foo 26, 5pm": bilinmeyen ay adı istisna değil None
        return None
    mon = months.index(m.group(1).lower()) + 1
    hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
    year = datetime.datetime.fromtimestamp(now, tz).year
    try:
        dt = datetime.datetime(year, mon, int(m.group(2)), hour, int(m.group(4) or 0), tzinfo=tz)
        if dt.timestamp() < now - 86400:
            dt = dt.replace(year=year + 1)
    except (ValueError, OverflowError):      # geçersiz gün/saat ya da 29 Şubat'ın ertesi yıl karşılığı yok
        return None
    return dt.timestamp()


def parse_usage(text: str, now: float) -> Optional[Usage]:
    """`claude -p /usage` çıktısı -> Usage; haftalık satır yoksa None (biçim değişti / abonelik dışı)."""
    m = _WEEK_RE.search(text or "")
    if not m:
        return None
    u = Usage(week_pct=float(m.group(1)))
    if m.group(2) and m.group(3):
        u.reset_ts = _parse_reset(m.group(2), m.group(3), now)
    f = _FABLE_RE.search(text)
    s = _SESSION_RE.search(text)
    u.fable_pct = float(f.group(1)) if f else None
    u.session_pct = float(s.group(1)) if s else None
    return u


def _num(cfg: Dict[str, Any], key: str, default: Optional[float]) -> Optional[float]:
    try:
        v = float(str(cfg.get(key, "")).strip())
    except ValueError:
        return default
    return v if math.isfinite(v) else default      # "nan"/"inf" geçerli float'tır ama karşılaştırmalar hep yanlış olur


def limits(cfg: Dict[str, Any]) -> "tuple[Optional[float], float, float]":
    """(manual, shutdown, final) kademeleri. `budget_pct` (X, 1..100) doluysa TEK ayar: manual=X-2, shutdown=X-1, final=X
    (sahip TBD#163 d); tek tek limitler yalnız budget_pct YOKKEN okunur. Yoksa eski davranış (final varsayılan 95,
    shutdown varsayılan final-1, manual verilmemişse None)."""
    b = _num(cfg, "budget_pct", None)
    if b is not None and b > 0:
        return max(b - 2, 0.0), max(b - 1, 0.0), b
    final = _num(cfg, "final_limit", DEFAULT_FINAL) or DEFAULT_FINAL
    sd = _num(cfg, "shutdown_limit", None)
    return _num(cfg, "manual_limit", None), (sd if sd is not None else final - 1), final


def _week_day_index(usage: Usage, now: float, tz: Optional[Any] = None) -> "tuple[datetime.datetime, int]":
    """(hafta başı, 0..6 gün indeksi). Sınırlar DUVAR SAATİYLE (sıfırlanma - 7 takvim günü, +k takvim günü); sabit 86400 sn
    DST haftasında sınırı 1 saat kaydırıp gün etiketini/tavanı yanlış günde değiştirirdi. `reset_ts` bilinmeli."""
    start = datetime.datetime.fromtimestamp(float(usage.reset_ts or 0), tz) - datetime.timedelta(days=7)
    idx = 0
    for k in range(1, 7):
        if now >= (start + datetime.timedelta(days=k)).timestamp():
            idx = k
    return start, idx


def day_label(usage: Usage, now: float, tz: Optional[Any] = None) -> str:
    """Bugünün gün adı (`mon`..`sun`). Haftalık sıfırlanmadan (Pzt 18:00) SONRAKİ 24 saat SALI sayılır (sahip kuralı
    2026-10-25): gün = sıfırlanmadan itibaren geçen 24 saatlik dilim, etiketi sıfırlanma gününün ERTESİ günüdür.
    Sıfırlanma bilinmiyorsa takvim günü."""
    if not usage.reset_ts:
        return DAYS[datetime.datetime.fromtimestamp(now, tz).weekday()]
    start, idx = _week_day_index(usage, now, tz)
    return DAYS[(start.weekday() + 1 + idx) % 7]


def day_cap(cfg: Dict[str, Any], usage: Usage, now: float, tz: Optional[Any] = None) -> Optional[float]:
    """Bugünün tavanı (kullanılan %). Elle `day_<gün>` varsa o; yoksa auto: final x geçen gün / 7 (hafta başı = sıfırlanma
    - 7 gün; gün = 24 saatlik dilim). Sıfırlanma bilinmiyorsa auto için None (tavan hesaplanamaz)."""
    manual = _num(cfg, "day_" + day_label(usage, now, tz), None)
    if manual is not None:
        return manual
    if str(cfg.get("mode")) != "auto" or not usage.reset_ts:
        return None
    final = limits(cfg)[2]
    days = _week_day_index(usage, now, tz)[1] + 1
    return round(final * days / 7, 1)


def decide(cfg: Dict[str, Any], usage: Optional[Usage], now: float, tz: Optional[Any] = None) -> Decision:
    """Kota kararı. Bilinmeyen kullanım (okuma başarısız) HİÇBİR ŞEYİ durdurmaz: yanlış alarm tüm sistemi kapatırdı."""
    mode = str(cfg.get("mode") or "off")
    if mode not in MODES or mode == "off":
        return Decision()
    if usage is None or usage.week_pct is None:
        return Decision(reason="kullanım okunamadı")
    used = usage.week_pct
    cap = day_cap(cfg, usage, now, tz)
    limit, sd, final = limits(cfg)
    if used >= final:
        return Decision("stop", cap, f"kullanılan %{used:g} >= son limit %{final:g} (hard kapanma)")
    if used >= sd:
        return Decision("shutdown", cap, f"kullanılan %{used:g} >= kapatma limiti %{sd:g} (devirle kapat)")
    if mode == "manual":
        if limit is None and cap is None:
            return Decision(cap=cap, reason="manual_limit verilmemiş")
        if limit is not None and used >= limit:
            return Decision("drain", cap, f"kullanılan %{used:g} >= yeni-iş-yok limiti %{limit:g}")
    if cap is not None and used >= cap:
        return Decision("drain", cap, f"kullanılan %{used:g} >= bugünün tavanı %{cap:g}")
    if cap is None and mode == "auto":     # sessizce devre dışı kalmasın: neden görünür olsun (stop/shutdown yine yukarıda çalışır)
        return Decision(reason="sıfırlanma zamanı çözülemedi: günlük tavan uygulanamıyor")
    return Decision(cap=cap)
