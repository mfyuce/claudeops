"""Değnekçi kota bekçisi: Claude plan haftalık kullanımı (`claude -p /usage`) -> karar. SAF çekirdek (süreç, ayar ve
eylem `commands/web_steward.py`'de). TBD#116.

Modlar: `off` (varsayılan), `manual` (`manual_limit`: buna ulaşınca yeni iş alınmaz (drain); `shutdown_limit` (varsayılan final-1): çalışmayanlara devir, bitince kapat; `final_limit`: HARD kapanma), `auto` (günlük tavan
= `final_limit` x geçen gün / 7; tavana ulaşınca yeni iş alınmaz (`drain`), `final_limit`e ulaşınca durur). `day_<mon..sun>`
o haftanın günü için tavanı elle verir (her iki modda geçerli)."""
from __future__ import annotations

import dataclasses
import datetime
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
    mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m.group(1).lower()) + 1
    hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
    year = datetime.datetime.fromtimestamp(now, tz).year
    dt = datetime.datetime(year, mon, int(m.group(2)), hour, int(m.group(4) or 0), tzinfo=tz)
    if dt.timestamp() < now - 86400:
        dt = dt.replace(year=year + 1)
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
        return float(str(cfg.get(key, "")).strip())
    except ValueError:
        return default


def day_label(usage: Usage, now: float, tz: Optional[Any] = None) -> str:
    """Bugünün gün adı (`mon`..`sun`). Haftalık sıfırlanmadan (Pzt 18:00) SONRAKİ 24 saat SALI sayılır (sahip kuralı
    2026-10-25): gün = sıfırlanmadan itibaren geçen 24 saatlik dilim, etiketi sıfırlanma gününün ERTESİ günüdür.
    Sıfırlanma bilinmiyorsa takvim günü."""
    if not usage.reset_ts:
        return DAYS[datetime.datetime.fromtimestamp(now, tz).weekday()]
    start = usage.reset_ts - 7 * 86400
    idx = min(6, max(0, int((now - start) // 86400)))
    return DAYS[(datetime.datetime.fromtimestamp(start, tz).weekday() + 1 + idx) % 7]


def day_cap(cfg: Dict[str, Any], usage: Usage, now: float, tz: Optional[Any] = None) -> Optional[float]:
    """Bugünün tavanı (kullanılan %). Elle `day_<gün>` varsa o; yoksa auto: final x geçen gün / 7 (hafta başı = sıfırlanma
    - 7 gün; gün = 24 saatlik dilim). Sıfırlanma bilinmiyorsa auto için None (tavan hesaplanamaz)."""
    manual = _num(cfg, "day_" + day_label(usage, now, tz), None)
    if manual is not None:
        return manual
    if str(cfg.get("mode")) != "auto" or not usage.reset_ts:
        return None
    final = _num(cfg, "final_limit", DEFAULT_FINAL) or DEFAULT_FINAL
    start = usage.reset_ts - 7 * 86400
    days = min(7, max(1, int((now - start) // 86400) + 1))
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
    final = _num(cfg, "final_limit", DEFAULT_FINAL) or DEFAULT_FINAL
    sd = _num(cfg, "shutdown_limit", None)
    sd = sd if sd is not None else final - 1
    if used >= final:
        return Decision("stop", cap, f"kullanılan %{used:g} >= son limit %{final:g} (hard kapanma)")
    if used >= sd:
        return Decision("shutdown", cap, f"kullanılan %{used:g} >= kapatma limiti %{sd:g} (devirle kapat)")
    if mode == "manual":
        limit = _num(cfg, "manual_limit", None)
        if limit is None:
            return Decision(cap=cap, reason="manual_limit verilmemiş")
        if used >= limit:
            return Decision("drain", cap, f"kullanılan %{used:g} >= yeni-iş-yok limiti %{limit:g}")
    if cap is not None and used >= cap:
        return Decision("drain", cap, f"kullanılan %{used:g} >= bugünün tavanı %{cap:g}")
    return Decision(cap=cap)
