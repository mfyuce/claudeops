"""Claude/Anthropic hizmetiyle açılan ucli oturumlarının dolar sayacı ve GÜNLÜK tavan (sahip, 2026-11-01: takım Claude Code
yerine ucli kullanacak, 200 USD API kredisi; tavan settings'ten: `ucli_cost.daily_cap_usd`). Saf-ish yaprak modül: yalnız
oturum başına `--usage-log` dosyalarını okur (`~/.claude/claudeops/ucli_usage/<oturum>.jsonl`). Tavan aşılınca YENİ Claude
oturumu açılmaz (`cap_exceeded`); çalışan oturumlara DOKUNULMAZ (sahibin elindeki karar). Maliyet bir ALT SINIRDIR: fiyat
tablosu `review.ANTHROPIC_PRICES`, 1h yazma çarpanı 1,6 (= 2x / 1,25x), >100K istem kademesi ayrılmaz."""
from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import paths
from . import review as rv
from .settings import _ucli_cap_problem, ucli_cost_config

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


def write_dir(base: Optional[str] = None) -> str:
    """Günlüğün YAZILACAĞI dizin: ortak dizin salt okunursa (TBD#412 b, ikinci örnek) `<CLAUDEOPS_DIR>` altındaki eşi."""
    base = USAGE_DIR if base is None else base
    if paths.shared_write_allowed(base):
        return base
    return os.path.join(paths.CLAUDEOPS_DIR, os.path.relpath(base, os.path.dirname(USAGE_DIR)))


def read_dirs(base: str) -> List[str]:
    """Okunacak dizinler: ortak dizin, yazma başka yere gidiyorsa o da (ikinci örnekte tavan ikisinin toplamını görür)."""
    own = write_dir(base)
    return [base] if own == base else [base, own]


def _logs(base: str):
    """`(oturum adı, yol)`: `read_dirs(base)` altındaki tüm `.jsonl` günlükleri."""
    for d in read_dirs(base):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.endswith(".jsonl"):
                yield n[:-len(".jsonl")], os.path.join(d, n)


def log_path(session_name: str, base: Optional[str] = None) -> str:
    base = write_dir() if base is None else base
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(session_name))[:100] or "session"
    return os.path.join(base, f"{safe}.jsonl")


OTHER_DIR = os.path.join(USAGE_DIR, "other")


def other_log_path(session_name: str) -> str:
    """Claude DIŞI hizmetlerin (Evren glm/gemma/qwen, öteki BYOK) oturum günlüğü. `USAGE_DIR` DIŞINDA tutulur: dolar tavanı
    (`per_session_usd`/`today_usd`) yalnız Claude günlüklerini okur, bilinmeyen modeli opus fiyatıyla saymasın (18 Kas Evren dersi:
    etkileşimli REPL oturumları günlük yazmıyordu, kendi sayımımızdan düşüyordu)."""
    return log_path(session_name, write_dir(OTHER_DIR))


CACHE_1H_WRITE_MULT = 1.6   # 1 saatlik önbellek yazması 5 dk'lıktan pahalı (log'daki maliyet alt sınır); TEK yer


def write_mult(cfg: Optional[Dict[str, Any]] = None) -> float:
    """Ayardaki `cache_ttl`e göre önbellek yazma çarpanı (1h -> `CACHE_1H_WRITE_MULT`, aksi 1.0)."""
    cfg = ucli_cost_config() if cfg is None else cfg
    return CACHE_1H_WRITE_MULT if cfg.get("cache_ttl") == "1h" else 1.0


def _day_start_ms(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000.0


class _ReadPass:
    """Tek bir açılış denetimi boyunca okunan günlükler: her dosya bir kez açılır, bütün pencereler o geçişte toplanır."""

    def __init__(self) -> None:
        self.at: Optional[float] = None          # pencerelerin saati: denetimin ilk taraması
        self.windows: Tuple[float, ...] = ()
        self.files: Dict[Tuple[str, float], Dict[float, Tuple[float, str, List[str]]]] = {}


_PASS = threading.local()      # `.cur`: bu iş parçacığında süren açılış denetimi


@contextlib.contextmanager
def _one_read():
    """İçindeki `cap_exceeded`/`state`/`reserve` çağrıları harcama dosyalarını bir kez okur. Blok bitince hiçbir şey
    saklanmaz; başka iş parçacığını etkilemez."""
    prev = getattr(_PASS, "cur", None)
    _PASS.cur = _ReadPass()
    try:
        yield
    finally:
        _PASS.cur = prev


def _rate_since(now: float, window_min: float) -> float:
    return now * 1000.0 - window_min * 60_000.0


def _window_clock(now: float, credit_since: str) -> float:
    """`state`in taramada kullanacağı saat. Açılış denetiminde ilk taramanın saatidir (gün değişmedikçe): sonraki çağrılar
    aynı pencereleri ister ve dosya yeniden okunmaz. Denetim dışında `now`."""
    cur = getattr(_PASS, "cur", None)
    if cur is None:
        return now
    if cur.at is None or _day_start_ms(cur.at) != _day_start_ms(now):
        cur.at = now
    cur.windows = (_day_start_ms(cur.at), _date_ms(credit_since), _rate_since(cur.at, 60.0), _rate_since(cur.at, 15.0))
    return cur.at


def _scan(path: str, since_ms: float, write_mult: float) -> Tuple[float, str]:
    """`rv._scan_usage(path, "", ..)`; açılış denetiminde dosyanın tek okumasından (günlük olayları her çağrıda aynen)."""
    cur = getattr(_PASS, "cur", None)
    if cur is None:
        return rv._scan_usage(path, "", since_ms, write_mult)
    got = cur.files.get((path, write_mult))
    if got is None or since_ms not in got:
        got = cur.files[(path, write_mult)] = rv._scan_usage_windows(path, "", (since_ms, *cur.windows), write_mult)
    usd, problem, skipped = got[since_ms]
    for what in skipped:
        rv._log_bad(what, path)
    return usd, problem


def _usd(path: str, since_ms: float, write_mult: float) -> float:
    if getattr(_PASS, "cur", None) is None:
        return rv.usage_cost_usd(path, "", since_ms=since_ms, write_mult=write_mult)
    return _scan(path, since_ms, write_mult)[0]


def per_session_usd(now: Optional[float] = None, base: str = USAGE_DIR, write_mult: float = CACHE_1H_WRITE_MULT) -> Dict[str, float]:
    """Bugünkü (yerel gün) $ — OTURUM (kodcu) başına: {oturum günlük adı (.jsonl'siz): usd}. Dizin yoksa {}."""
    t = time.time() if now is None else now
    since = _day_start_ms(t)
    out: Dict[str, float] = {}
    for name, p in _logs(base):
        try:
            if os.path.getmtime(p) * 1000.0 < since:
                continue
        except OSError:
            continue
        out[name] = out.get(name, 0.0) + _usd(p, since, write_mult)
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
    since = _rate_since(t, win)
    out: Dict[str, float] = {}
    for name, p in _logs(base):
        try:
            if os.path.getmtime(p) * 1000.0 < since:
                continue
        except OSError:
            continue
        usd = _usd(p, since, write_mult)
        if usd > 0:
            out[name] = out.get(name, 0.0) + usd * 60.0 / win
    return out


def rate_usd_per_hour(now: Optional[float] = None, window_min: float = 60.0, base: str = USAGE_DIR,
                      write_mult: float = CACHE_1H_WRITE_MULT) -> float:
    """Son `window_min` dakikadaki toplam maliyet / window_min * 60 (USD/saat)."""
    return sum(rate_by_session(now, window_min, base, write_mult).values())


def total_usd(base: str = USAGE_DIR, write_mult: float = CACHE_1H_WRITE_MULT, since_ms: float = 0.0) -> float:
    """BİRİKMİŞ toplam $: tüm oturum günlükleri; `since_ms` > 0 ise yalnız o andan sonrası (kredi dönemi). Dizin yoksa 0."""
    out = 0.0
    for _, p in _logs(base):
        try:
            if since_ms > 0 and os.path.getmtime(p) * 1000.0 < since_ms:
                continue        # dönem başlamadan önce son yazılmış günlük: o döneme harcama yazamaz
        except OSError:
            continue
        out += _usd(p, since_ms, write_mult)
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
        st = _window_clock(t, cfg.get("credit_since") or "")
        by = per_session_usd(st, base, mult)
        snap = dict(at=t, total=total_usd(base, mult, _date_ms(cfg.get("credit_since") or "")), usd=sum(by.values()), by=by, day=time.strftime("%Y-%m-%d", time.localtime(t)),
                      rate_1h=rate_by_session(st, 60.0, base, mult), rate_15m=rate_by_session(st, 15.0, base, mult))
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


def _ledger_problem(now: float, base: str, write_mult: float) -> str:
    """Bugünün harcaması güvenilir biçimde sayılamıyorsa nedeni (dosya adıyla), aksi "". Okunamayan dizin/dosya ve geçersiz
    sayaç 0 harcama gibi görünür; açık tavan buna güvenip geçirmesin. Dizin ya da dosyanın OLMAMASI sorun değildir.
    Toplamın okuduğu BÜTÜN dizinler denetlenir (`read_dirs`: ikinci örnekte kendi dizini de)."""
    since = _day_start_ms(now)
    for d in read_dirs(base):
        try:
            names = os.listdir(d)
        except FileNotFoundError:
            continue
        except OSError:
            return "günlük dizini okunamadı"
        for n in names:
            p = os.path.join(d, n)
            if not n.endswith(".jsonl"):
                continue
            try:
                if os.path.getmtime(p) * 1000.0 < since:
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                return f"{n}: okunamadı"
            why = _scan(p, since, write_mult)[1]
            if why:
                return f"{n}: {why}"
    return ""


def reserve(session_name: str, now: Optional[float] = None, base: str = USAGE_DIR) -> None:
    """Başlatma için RESERVE_USD ayır; tavan (bugün + başkalarının payı + bu pay) aşılıyorsa DailyCapExceeded; tavan
    açıkken günlükler okunamıyor/bozuksa, ya da `settings.json`/tavan değeri bozuksa ValueError. Tavan yoksa (0) rezervasyon
    tutulmaz. Aynı ad yeniden ayırırsa öncekinin yerine geçer."""
    t = time.time() if now is None else now
    with _RESERVE_LOCK:
        for k in [k for k, (_, exp) in _RESERVED.items() if exp <= t]:
            del _RESERVED[k]
        s = state(t, base, use_cache=False)
        why = _ucli_cap_problem()
        if why:      # bilinemeyen tavan "tavan yok" DEĞİLDİR: kapalı yön
            raise ValueError(f"claude: günlük USD tavanı denetlenemiyor ({why}); settings.json'ı düzelt "
                             "(ucli_cost.daily_cap_usd: 0 = tavan yok ya da pozitif sayı)")
        cap = float(s["cap_usd"])
        if cap <= 0:
            _RESERVED.pop(session_name, None)
            return
        why = _ledger_problem(t, base, write_mult(ucli_cost_config()))
        if why:      # sayılamayan harcama "tavanın altında" DEĞİLDİR: kapalı yön
            raise ValueError(f"claude: günlük USD tavanı denetlenemiyor ({why}); ucli_usage günlüklerini düzelt ya da "
                             "Ayarlar'dan ucli_cost.daily_cap_usd'yi kapat")
        others = sum(u for k, (u, _) in _RESERVED.items() if k != session_name)
        if s["today_usd"] + others >= cap:
            raise DailyCapExceeded(s["today_usd"] + others, cap)
        _RESERVED[session_name] = (RESERVE_USD, t + RESERVE_TTL)


def release(session_name: str) -> None:
    """Başlatma başarısız olduysa payı hemen geri ver (yoksa TTL ile düşer)."""
    with _RESERVE_LOCK:
        _RESERVED.pop(session_name, None)
