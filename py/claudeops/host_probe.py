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
MIN_GAIN_SECONDS = 0.05       # terfi için en az bu kadar kazanç...
MIN_GAIN_RATIO = 0.6          # ...ve mevcut ortalamanın en çok %60'ı (gürültüyle ileri geri gitmesin)
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


def record(rec: Optional[Dict[str, Any]], ms: Optional[float], err: str, now: float) -> Dict[str, Any]:
    """Bir adresin kaydına tek yoklama sonucunu işler (saf). `ms` None = başarısız."""
    r = dict(rec or {})
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
    """Tüm host'ların adreslerini paralel yoklar, depoyu günceller. Yalnız `extra_urls`ı olan host'lar yoklanır (tek adreste seçim yok)
    ama base_url da metrik için dahildir. Döner: {"hosts": n, "urls": n, "ok": n}."""
    from . import hosts as hosts_mod
    now = time.time() if now is None else now
    recs = hosts_mod.load_hosts() if hosts is None else hosts
    jobs: List[Tuple[str, str, str]] = []
    for h in recs:
        urls = candidates(h)
        if len(urls) >= 2:
            jobs += [(h["name"], u, h["token"]) for u in urls]
    results: Dict[Tuple[str, str], Tuple[Optional[float], str]] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
            futs = {(n, u): ex.submit(probe, u, t) for n, u, t in jobs}
            for k, f in futs.items():
                try:
                    results[k] = f.result()
                except Exception as e:      # noqa: BLE001
                    results[k] = (None, f"{type(e).__name__}")
    data = load_store()
    store = {"hosts": json.loads(json.dumps(data.get("hosts") or {})), "updated_at": now}
    names = {h["name"] for h in recs}
    for gone in [n for n in store["hosts"] if n not in names]:
        del store["hosts"][gone]
    ok = 0
    for (n, u), (ms, err) in results.items():
        urls = store["hosts"].setdefault(n, {"urls": {}})["urls"]
        urls[u] = record(urls.get(u), ms, err, now)
        ok += ms is not None
    for h in recs:                                    # artık aday olmayan adresleri depodan düş
        ent = store["hosts"].get(h["name"])
        if ent is not None:
            keep = set(candidates(h))
            ent["urls"] = {u: r for u, r in ent["urls"].items() if u in keep}
    save_store(store)
    return {"hosts": len({n for n, _u, _t in jobs}), "urls": len(jobs), "ok": ok}


def healthy(rec: Optional[Dict[str, Any]], now: float) -> bool:
    return bool(rec and rec.get("ok") and int(rec.get("fails") or 0) == 0 and now - float(rec.get("at") or 0) <= STALE_SECONDS
                and rec.get("avg_ms") is not None)


def choose_for(host_record: Dict[str, Any], now: Optional[float] = None,
               store: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Poller için: depodan (AĞA GİTMEDEN) en hızlı SAĞLIKLI adres; `base_url`ten farklıysa onu, değilse None.
    base sağlıklı değilse en hızlı sağlıklı aday; base sağlıklıysa kazanç eşikleri (`MIN_GAIN_*`) aranır."""
    now = time.time() if now is None else now
    base = str(host_record.get("base_url") or "").rstrip("/")
    ent = ((store if store is not None else load_store()).get("hosts") or {}).get(host_record.get("name"))
    if not ent or not base:
        return None
    from .commands import web_hosts as wh
    urls = ent.get("urls") or {}
    cand = {u: r for u, r in urls.items() if u != base and healthy(r, now) and wh._candidate_allowed(base, u)}
    if not cand:
        return None
    best = min(cand, key=lambda u: cand[u]["avg_ms"])
    brec = urls.get(base)
    if healthy(brec, now):
        b, c = brec["avg_ms"] / 1000.0, cand[best]["avg_ms"] / 1000.0
        if not (b - c >= MIN_GAIN_SECONDS and c <= b * MIN_GAIN_RATIO):
            return None
    elif brec is not None and now - float(brec.get("at") or 0) > STALE_SECONDS:
        return None             # base'in durumu bilinmiyor (yoklayıcı bayat): kararsız, elleme
    return best


def public_view(name: str) -> List[Dict[str, Any]]:
    """Panel için bir host'un adres metrikleri (salt okur): [{url, ok, ms, avg_ms, fails, total, total_fail, err, at}] hızlıdan yavaşa."""
    ent = (load_store().get("hosts") or {}).get(name) or {}
    rows = [{"url": u, **{k: r.get(k) for k in ("ok", "ms", "avg_ms", "fails", "total", "total_fail", "err", "at")}}
            for u, r in (ent.get("urls") or {}).items()]
    rows.sort(key=lambda r: (not r["ok"], r["avg_ms"] if r["avg_ms"] is not None else 10 ** 9))
    return rows
