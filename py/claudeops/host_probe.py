"""Uzak host adres yoklaması (periodic iş `host_probe`): her host'un `base_url` + `extra_urls` adreslerini birkaç dakikada bir yoklar
(erişilebilirlik, gecikme ms, son N ortalaması, hata sayısı), sonucu `CLAUDEOPS_DIR/host_probe.json` durum deposuna yazar.
Host istemcisi (`web_hosts._poll_once`) en hızlı SAĞLIKLI adresi buradan OKUR; istek anında ölçmez (sahip 19 Kas, ulak_31 maddesi:
devtunnels ~300-420 ms, LAN ~3 ms). Panelde Hostlar sekmesi aynı depoyu gösterir.

Güvenlik: https `base_url` varken http aday yalnız özel-ağ (RFC1918) IP literaliyse yoklanır/seçilir (`web_hosts._candidate_allowed`)."""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

STORE_JSON = os.path.join(CLAUDEOPS_DIR, "host_probe.json")
SAMPLES = 10                  # ortalama için son N başarılı ölçüm
PROBE_TIMEOUT_SECONDS = 3.0
MAX_URLS = 6                  # host başına en çok bu kadar adres (base + extra_urls)
STALE_SECONDS = 900.0         # bu kadar süredir yoklanmayan adres "sağlıklı" sayılmaz (yoklayıcı ölü/takılı olabilir)
ATTEMPTS = 4                  # tur başına adres başına deneme (tek ölçüm gürültülü: menzil ilk ölçüm 1902 ms, 6'lı ölçüm ~400 ms)
WINDOW = 40                   # puan penceresi: son N DENEME (başarılı + başarısız)
WARMUP = 12                   # puanlı sayılmak için en az deneme (ısınma tek ölçümüyle geçiş YOK)
FAIL_PENALTY_MS = 6000.0      # puan = gecikme + hata_oranı x bu (zaman aşımı/hata puanı belirgin düşürür)
MAX_FAIL_RATE = 0.3           # aday için en çok hata oranı
SWITCH_RATIO = 0.7            # geçiş: aday puanı <= mevcut puanın %70'i...
SWITCH_MIN_GAIN_MS = 100.0    # ...ve en az bu kadar ms kazanç
DWELL_SECONDS = 600.0         # histerezis: bir geçişten sonra en az bu kadar süre yeniden geçiş yok (salınım yok)
_last_switch: Dict[str, float] = {}
_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": None, "data": {}}


def _empty() -> Dict[str, Any]:
    return {"hosts": {}, "updated_at": 0.0}


def load_store() -> Dict[str, Any]:
    """Depoyu okur (dosya mtime'ına göre bellekte önbellekli: poller'ın her 3 sn'lik turunda ucuz). Bozuk/eksik = boş."""
    try:
        mt = os.stat(STORE_JSON).st_mtime_ns
    except OSError:
        return _empty()
    with _lock:
        if _cache["mtime"] == mt:
            return _cache["data"]
    try:
        with open(STORE_JSON, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("hosts"), dict):
            data = _empty()
    except (OSError, ValueError):
        data = _empty()
    with _lock:
        _cache["mtime"], _cache["data"] = mt, data
    return data


def save_store(data: Dict[str, Any]) -> None:
    atomic_write_json(STORE_JSON, data)


def _pct(vals: List[float], q: float) -> float:
    v = sorted(vals)
    if not v:
        return 0.0
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def score_of(rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pencereden (son WINDOW deneme) puan bileşenleri (saf): {n, ok_n, fail_rate, med, p90, score, warm}. `score` ms cinsinden,
    DÜŞÜK iyi: 0,5 x medyan + 0,5 x p90 + hata_oranı x FAIL_PENALTY_MS; hiç başarı yoksa None. `warm` = n >= WARMUP."""
    win = list((rec or {}).get("window") or [])
    n = len(win)
    oks = [float(x) for x in win if x is not None]
    out: Dict[str, Any] = {"n": n, "ok_n": len(oks), "fail_rate": (1 - len(oks) / n) if n else 1.0, "med": None, "p90": None,
                           "score": None, "warm": n >= WARMUP}
    if oks:
        out["med"], out["p90"] = round(_pct(oks, 0.5)), round(_pct(oks, 0.9))
        out["score"] = round(0.5 * out["med"] + 0.5 * out["p90"] + out["fail_rate"] * FAIL_PENALTY_MS)
    return out


def record(rec: Optional[Dict[str, Any]], ms: Optional[float], err: str, now: float) -> Dict[str, Any]:
    """Bir adresin kaydına tek yoklama sonucunu işler (saf). `ms` None = başarısız. Her deneme `window`a da girer (puan için)."""
    r = dict(rec or {})
    win: List[Optional[int]] = list(r.get("window") or [])
    win.append(int(round(ms * 1000)) if ms is not None else None)
    r["window"] = win[-WINDOW:]
    samples: List[int] = list(r.get("samples") or [])
    r["total"] = int(r.get("total") or 0) + 1
    r["at"] = now
    if ms is not None:
        r["ok"], r["ms"], r["err"], r["fails"] = True, int(round(ms * 1000)), "", 0
        samples.append(r["ms"])
        samples = samples[-SAMPLES:]
    else:
        r["ok"], r["ms"], r["err"] = False, None, str(err or "")[:120]
        r["fails"] = int(r.get("fails") or 0) + 1
        r["total_fail"] = int(r.get("total_fail") or 0) + 1
    r.setdefault("total_fail", 0)
    r["samples"] = samples
    r["avg_ms"] = int(round(sum(samples) / len(samples))) if samples else None
    return r


def probe_url(url: str, token: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> Tuple[Optional[float], str]:
    """Adrese hafif bir yoklama; (süre sn | None, hata). Önce küçük `/api/session/facts?names=` (eski host 404 verir), olmazsa `/api/status`."""
    from .commands import web_hosts as wh
    t0 = time.monotonic()
    status, parsed, err = wh._http_json("GET", f"{url}/api/session/facts?names=&token={token}", None, timeout, dedup=False)
    if err is None and parsed is not None and "sessions" in parsed:
        return time.monotonic() - t0, ""
    if err is None and status == 404:         # eski host: facts yok
        t0 = time.monotonic()
        parsed, err2 = wh._fetch_status_from(url, token, timeout, dedup=False)
        if err2 is None and parsed is not None:
            return time.monotonic() - t0, ""
        return None, err2 or "no status"
    return None, err or (f"http {status}" if status else "unreachable")


def candidates(host_record: Dict[str, Any]) -> List[str]:
    """Yoklanacak adresler: base_url + extra_urls (tekrarsız, https→http özel-ağ kuralına uyan, en çok MAX_URLS)."""
    from .commands import web_hosts as wh
    base = str(host_record.get("base_url") or "").rstrip("/")
    out: List[str] = [base] if base else []
    for u in host_record.get("extra_urls") or []:
        u = str(u).rstrip("/")
        if u and u not in out and wh._candidate_allowed(base, u):
            out.append(u)
    return out[:MAX_URLS]


def run_probe(hosts: Optional[List[Dict[str, Any]]] = None,
              probe: Callable[[str, str], Tuple[Optional[float], str]] = probe_url,
              now: Optional[float] = None) -> Dict[str, Any]:
    """Host'ları paralel, bir host'un adreslerini SIRALI yoklar, depoyu günceller. Yalnız `extra_urls`ı olan host'lar yoklanır (tek adreste seçim yok)
    ama base_url da metrik için dahildir. Döner: {"hosts": n, "urls": n, "ok": n}."""
    from . import hosts as hosts_mod
    now = time.time() if now is None else now
    recs = hosts_mod.load_hosts() if hosts is None else hosts
    jobs: List[Tuple[str, str, str]] = []
    for h in recs:
        urls = candidates(h)
        if len(urls) >= 2:
            jobs += [(h["name"], u, h["token"]) for u in urls]
    results: Dict[Tuple[str, str], List[Tuple[Optional[float], str]]] = {}

    def _attempts(u: str, t: str) -> List[Tuple[Optional[float], str]]:
        out: List[Tuple[Optional[float], str]] = []
        for _ in range(ATTEMPTS):
            try:
                out.append(probe(u, t))
            except Exception as e:      # noqa: BLE001
                out.append((None, f"{type(e).__name__}"))
        return out
    # Aynı host'un adresleri SIRALI yoklanır (uzak panel eşzamanlı isteği kötü işliyor: 2 eşzamanlı istek 6-10 sn, sıralı 0,4-1,7 sn,
    # cops ölçümü 19 Kas): yoklayıcı kendi yükünü ölçmesin. Farklı host'lar birbirinden bağımsız, paralel.
    by_host: Dict[str, List[Tuple[str, str]]] = {}
    for n, u, t in jobs:
        by_host.setdefault(n, []).append((u, t))

    def _host_round(n: str) -> None:
        for u, t in by_host[n]:
            results[(n, u)] = _attempts(u, t)
    if by_host:
        with ThreadPoolExecutor(max_workers=min(8, len(by_host))) as ex:
            for f in [ex.submit(_host_round, n) for n in by_host]:
                f.result()
    data = load_store()
    store = {"hosts": json.loads(json.dumps(data.get("hosts") or {})), "updated_at": now}
    names = {h["name"] for h in recs}
    for gone in [n for n in store["hosts"] if n not in names]:
        del store["hosts"][gone]
    ok = 0
    for (n, u), outs in results.items():
        urls = store["hosts"].setdefault(n, {"urls": {}})["urls"]
        rec_u = urls.get(u)
        for ms, err in outs:
            rec_u = record(rec_u, ms, err, now)
        urls[u] = rec_u
        ok += any(ms is not None for ms, _e in outs)
    for h in recs:                                    # artık aday olmayan adresleri depodan düş
        ent = store["hosts"].get(h["name"])
        if ent is not None:
            keep = set(candidates(h))
            ent["urls"] = {u: r for u, r in ent["urls"].items() if u in keep}
    save_store(store)
    return {"hosts": len({n for n, _u, _t in jobs}), "urls": len(jobs), "ok": ok}


def healthy(rec: Optional[Dict[str, Any]], now: float) -> bool:
    """Aday olabilir: taze (yoklayıcı ölü değil), ISINMIŞ pencere, hata oranı sınırın altında ve puanı var."""
    if not rec or now - float(rec.get("at") or 0) > STALE_SECONDS:
        return False
    sc = score_of(rec)
    return bool(sc["warm"] and sc["score"] is not None and sc["fail_rate"] <= MAX_FAIL_RATE)


def note_switch(name: str, now: Optional[float] = None) -> None:
    """Poller bir geçiş yaptı: histerezis süresi başlar."""
    _last_switch[name] = time.time() if now is None else now


def choose_for(host_record: Dict[str, Any], now: Optional[float] = None,
               store: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Poller için: depodan (AĞA GİTMEDEN) PUANI en iyi aday; `base_url`ten farklıysa onu, değilse None.
    Kurallar: aday ısınmış (WARMUP deneme), taze, hata oranı <= MAX_FAIL_RATE; base da sağlıklıysa geçiş için aday puanı mevcut
    puanın SWITCH_RATIO'sunu geçmemeli VE en az SWITCH_MIN_GAIN_MS kazandırmalı; son geçişten DWELL_SECONDS dolmadan yeniden
    geçiş yok (salınım yok). Base çöktüyse (hata oranı > MAX_FAIL_RATE ya da başarısız) eşikler aranmaz (dwell yine uygulanır)."""
    now = time.time() if now is None else now
    base = str(host_record.get("base_url") or "").rstrip("/")
    name = host_record.get("name")
    ent = ((store if store is not None else load_store()).get("hosts") or {}).get(name)
    if not ent or not base:
        return None
    from .commands import web_hosts as wh
    urls = ent.get("urls") or {}
    cand = {u: score_of(r)["score"] for u, r in urls.items() if u != base and healthy(r, now) and wh._candidate_allowed(base, u)}
    if not cand:
        return None
    best = min(cand, key=lambda u: cand[u])
    if now - _last_switch.get(str(name), -1e12) < DWELL_SECONDS:
        return None
    brec = urls.get(base)
    if brec is not None and now - float(brec.get("at") or 0) > STALE_SECONDS:
        return None             # base'in durumu bilinmiyor (yoklayıcı bayat): kararsız, elleme
    bsc = score_of(brec)
    if brec is not None and bsc["warm"] and bsc["score"] is not None and bsc["fail_rate"] <= MAX_FAIL_RATE:
        b, c = float(bsc["score"]), float(cand[best])
        if not (c <= b * SWITCH_RATIO and b - c >= SWITCH_MIN_GAIN_MS):
            return None
    elif brec is not None and not bsc["warm"]:
        return None             # base henüz ısınmadı (örn. yeni kayıt): ısınma verisiyle geçiş yok
    return best


def public_view(name: str) -> List[Dict[str, Any]]:
    """Panel için bir host'un adres metrikleri (salt okur), puanlı olandan başlayarak: [{url, ok, ms, avg_ms, fails, total, total_fail,
    err, at, n, ok_n, fail_rate, med, p90, score, warm}]."""
    ent = (load_store().get("hosts") or {}).get(name) or {}
    rows = []
    for u, r in (ent.get("urls") or {}).items():
        sc = score_of(r)
        rows.append({"url": u, **{k: r.get(k) for k in ("ok", "ms", "avg_ms", "fails", "total", "total_fail", "err", "at")},
                     **{k: sc[k] for k in ("n", "ok_n", "fail_rate", "med", "p90", "score", "warm")}})
    rows.sort(key=lambda r: (r["score"] is None, r["score"] if r["score"] is not None else 0, not r["ok"]))
    return rows
