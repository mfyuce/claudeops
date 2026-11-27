"""Claude/Anthropic hizmetiyle açılan ucli oturumlarının dolar sayacı ve GÜNLÜK tavan (sahip, 2026-11-01: takım Claude Code
yerine ucli kullanacak, 200 USD API kredisi; tavan settings'ten: `ucli_cost.daily_cap_usd`). Saf-ish yaprak modül: yalnız
oturum başına `--usage-log` dosyalarını okur (`~/.claude/claudeops/ucli_usage/<oturum>.jsonl`). Tavan aşılınca YENİ Claude
oturumu açılmaz (`cap_exceeded`); çalışan oturumlara DOKUNULMAZ (sahibin elindeki karar). Maliyet bir ALT SINIRDIR: fiyat
tablosu `review.ANTHROPIC_PRICES`, 1h yazma çarpanı 1,6 (= 2x / 1,25x), >100K istem kademesi ayrılmaz."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

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
    if getattr(exc, "reason", None) and type(exc).__name__ == "SpawnRefused":     # authz.SpawnRefused (çok kullanıcı: kimliksiz sağlayıcı)
        out.update(code="spawn_refused", reason=exc.reason)
    if isinstance(exc, DailyCapExceeded):
        out.update(code=CAP_CODE, today_usd=round(exc.today_usd, 2), cap_usd=round(exc.cap_usd, 2))
    return out


def log_path(session_name: str, base: str = USAGE_DIR) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(session_name))[:100] or "session"
    return os.path.join(base, f"{safe}.jsonl")


OTHER_DIR = os.path.join(USAGE_DIR, "other")


def other_log_path(session_name: str) -> str:
    """Claude DIŞI hizmetlerin (Evren glm/gemma/qwen, öteki BYOK) oturum günlüğü. `USAGE_DIR` DIŞINDA tutulur: dolar tavanı
    (`per_session_usd`/`today_usd`) yalnız Claude günlüklerini okur, bilinmeyen modeli opus fiyatıyla saymasın (18 Kas Evren dersi:
    etkileşimli REPL oturumları günlük yazmıyordu, kendi sayımımızdan düşüyordu)."""
    return log_path(session_name, OTHER_DIR)


CACHE_1H_WRITE_MULT = 1.6   # 1 saatlik önbellek yazması 5 dk'lıktan pahalı (log'daki maliyet alt sınır); TEK yer


def write_mult(cfg: Optional[Dict[str, Any]] = None) -> float:
    """Ayardaki `cache_ttl`e göre önbellek yazma çarpanı (1h -> `CACHE_1H_WRITE_MULT`, aksi 1.0)."""
    cfg = ucli_cost_config() if cfg is None else cfg
    return CACHE_1H_WRITE_MULT if cfg.get("cache_ttl") == "1h" else 1.0


def _day_start_ms(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000.0


def per_session_usd(now: Optional[float] = None, base: str = USAGE_DIR, write_mult: float = CACHE_1H_WRITE_MULT) -> Dict[str, float]:
    """Bugünkü (yerel gün) $ — OTURUM (kodcu) başına: {oturum günlük adı (.jsonl'siz): usd}. Dizin yoksa {}."""
    t = time.time() if now is None else now
    since = _day_start_ms(t)
    out: Dict[str, float] = {}
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        p = os.path.join(base, n)
        try:
            if not n.endswith(".jsonl") or os.path.getmtime(p) * 1000.0 < since:
                continue
        except OSError:
            continue
        out[n[:-len(".jsonl")]] = rv.usage_cost_usd(p, "", since_ms=since, write_mult=write_mult)
    return out


def rate_by_session(now: Optional[float] = None, window_min: float = 60.0, base: str = USAGE_DIR,
                    write_mult: float = CACHE_1H_WRITE_MULT) -> Dict[str, float]:
    """Son `window_min` dakikadaki harcama HIZI, OTURUM başına: {oturum: USD/saat}. Fiyat mantığı `per_session_usd` ile
    aynı (`rv.usage_cost_usd`, `since_ms` penceresi); dizin yok/pencere <= 0 -> {}. Yalnız hızı > 0 olanlar döner."""
    t = time.time() if now is None else now
    try:
        win = float(window_min)
    except (TypeError, ValueError):
        return {}
    if win <= 0:
        return {}
    since = t * 1000.0 - win * 60_000.0
    out: Dict[str, float] = {}
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        p = os.path.join(base, n)
        try:
            if not n.endswith(".jsonl") or os.path.getmtime(p) * 1000.0 < since:
                continue
        except OSError:
            continue
        usd = rv.usage_cost_usd(p, "", since_ms=since, write_mult=write_mult)
        if usd > 0:
            out[n[:-len(".jsonl")]] = usd * 60.0 / win
    return out


def rate_usd_per_hour(now: Optional[float] = None, window_min: float = 60.0, base: str = USAGE_DIR,
                      write_mult: float = CACHE_1H_WRITE_MULT) -> float:
    """Son `window_min` dakikadaki toplam maliyet / window_min * 60 (USD/saat)."""
    return sum(rate_by_session(now, window_min, base, write_mult).values())


def total_usd(base: str = USAGE_DIR, write_mult: float = CACHE_1H_WRITE_MULT, since_ms: float = 0.0) -> float:
    """BİRİKMİŞ toplam $: tüm oturum günlükleri; `since_ms` > 0 ise yalnız o andan sonrası (kredi dönemi). Dizin yoksa 0."""
    try:
        names = os.listdir(base)
    except OSError:
        return 0.0
    out = 0.0
    for n in names:
        if not n.endswith(".jsonl"):
            continue
        p = os.path.join(base, n)
        try:
            if since_ms > 0 and os.path.getmtime(p) * 1000.0 < since_ms:
                continue        # dönem başlamadan önce son yazılmış günlük: o döneme harcama yazamaz
        except OSError:
            continue
        out += rv.usage_cost_usd(p, "", since_ms=since_ms, write_mult=write_mult)
    return out


def _date_ms(day: str, end: bool = False) -> float:
    """YYYY-MM-DD -> yerel gün başı (ya da `end`: ertesi gün başı) epoch ms; bozuksa 0."""
    try:
        y, m, d = (int(x) for x in day.split("-"))
        t = time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return 0.0
    return (t + (86400 if end else 0)) * 1000.0


def credit_window(cfg: Dict[str, Any], spent: float, now: float) -> Dict[str, Any]:
    """Kredi dönemi özeti (saf): {credit_since, credit_until, days_left, daily_budget_usd}. Bitiş yoksa yalnız since."""
    out: Dict[str, Any] = {}
    if cfg.get("credit_since"):
        out["credit_since"] = cfg["credit_since"]
    until = str(cfg.get("credit_until") or "")
    if until:
        end_ms = _date_ms(until, end=True)
        if end_ms > 0:
            days = max(0.0, (end_ms / 1000.0 - now) / 86400.0)
            out.update(credit_until=until, days_left=round(days, 1))
            credit = float(cfg.get("credit_total_usd") or 0.0)
            if credit > 0 and days > 0:
                out["daily_budget_usd"] = round(max(0.0, credit - spent) / max(days, 1.0), 2)
    return out


def today_usd(now: Optional[float] = None, base: str = USAGE_DIR, write_mult: float = CACHE_1H_WRITE_MULT) -> float:
    """Bugünkü (yerel gün) toplam $ (tüm oturum günlükleri). Dizin yoksa 0."""
    return sum(per_session_usd(now, base, write_mult).values())


BY_SESSION_TOP = 10   # durum yanıtında en çok harcayan N oturum (panel kısa kalsın)


def state(now: Optional[float] = None, base: str = USAGE_DIR, use_cache: bool = True) -> Dict[str, Any]:
    """{today_usd, cap_usd (0 = yok), pct (tavan yoksa None), cache_ttl}. 30 sn önbellekli (her /api/status'ta disk taraması yok)."""
    t = time.time() if now is None else now
    cfg = ucli_cost_config()
    snap = dict(_CACHE)     # yanıt YALNIZ bu kopyadan okunur: arada gelen invalidate() tavan denetimine 0 USD göstermesin
    if not use_cache or t - snap["at"] > _TTL or snap["day"] != time.strftime("%Y-%m-%d", time.localtime(t)):
        mult = write_mult(cfg)
        by = per_session_usd(t, base, mult)
        snap = dict(at=t, total=total_usd(base, mult, _date_ms(cfg.get("credit_since") or "")), usd=sum(by.values()), by=by, day=time.strftime("%Y-%m-%d", time.localtime(t)),
                      rate_1h=rate_by_session(t, 60.0, base, mult), rate_15m=rate_by_session(t, 15.0, base, mult))
        _CACHE.update(snap)
    cap = float(cfg["daily_cap_usd"])
    usd = float(snap["usd"])
    by_all = snap.get("by") or {}
    top = sorted(by_all.items(), key=lambda kv: (-kv[1], kv[0]))[:BY_SESSION_TOP]
    out = {"today_usd": round(usd, 4), "cap_usd": cap, "pct": (round(100.0 * usd / cap, 1) if cap > 0 else None),
           "cache_ttl": cfg["cache_ttl"], "by_session": [{"session": n, "usd": round(v, 4)} for n, v in top if v > 0],
           "rate_1h_usd": round(sum((snap.get("rate_1h") or {}).values()), 4),
           "rate_15m_usd": round(sum((snap.get("rate_15m") or {}).values()), 4)}
    credit = float(cfg.get("credit_total_usd") or 0.0)
    if credit > 0:      # kalan = toplam - birikmiş harcama (alt sınır tahmini; negatife düşmez)
        spent = float(snap.get("total") or 0.0)
        out.update(credit_total_usd=credit, spent_total_usd=round(spent, 4), credit_left_usd=round(max(0.0, credit - spent), 4))
        out.update(credit_window(cfg, spent, t))
    for k in ("credit_since", "credit_until"):      # tarih alanları kredi girilmemişken de panelde görünsün
        if cfg.get(k):
            out[k] = cfg[k]
    return out


def invalidate() -> None:
    """Önbelleği düşür (ayar kaydedilince: cache_ttl çarpanı değişir, panel yeni değeri hemen görsün)."""
    _CACHE.update(at=0.0, usd=0.0, total=0.0, by={}, day="", rate_1h={}, rate_15m={})


def cap_exceeded(now: Optional[float] = None, base: str = USAGE_DIR) -> bool:
    s = state(now, base, use_cache=False)
    return s["cap_usd"] > 0 and s["today_usd"] >= s["cap_usd"]


# Eşanlı başlatma rezervasyonu (P4-VERDICT #34): N oturum aynı anda açılırken hiçbiri henüz günlüğe harcama yazmadığından
# hepsi tavan denetiminden geçerdi. Her başlatma kısa süreli (RESERVE_TTL) bir tahmini pay ayırır; sonraki başlatma
# `bugün + başkalarının ayrılmış payı` ile denetlenir. Süreç içi (web sunucusu tek süreç, istek-başına thread).
RESERVE_USD = 1.0
RESERVE_TTL = 120.0
_RESERVE_LOCK = threading.Lock()
_RESERVED: Dict[str, Tuple[float, float]] = {}      # oturum -> (usd, bitiş zamanı)


def reserve(session_name: str, now: Optional[float] = None, base: str = USAGE_DIR) -> None:
    """Başlatma için RESERVE_USD ayır; tavan (bugün + başkalarının payı + bu pay) aşılıyorsa DailyCapExceeded.
    Tavan yoksa (0) rezervasyon tutulmaz. Aynı ad yeniden ayırırsa öncekinin yerine geçer."""
    t = time.time() if now is None else now
    with _RESERVE_LOCK:
        for k in [k for k, (_, exp) in _RESERVED.items() if exp <= t]:
            del _RESERVED[k]
        s = state(t, base, use_cache=False)
        cap = float(s["cap_usd"])
        if cap <= 0:
            _RESERVED.pop(session_name, None)
            return
        others = sum(u for k, (u, _) in _RESERVED.items() if k != session_name)
        if s["today_usd"] + others >= cap:
            raise DailyCapExceeded(s["today_usd"] + others, cap)
        _RESERVED[session_name] = (RESERVE_USD, t + RESERVE_TTL)


def release(session_name: str) -> None:
    """Başlatma başarısız olduysa payı hemen geri ver (yoksa TTL ile düşer)."""
    with _RESERVE_LOCK:
        _RESERVED.pop(session_name, None)
