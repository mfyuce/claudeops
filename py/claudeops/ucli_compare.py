"""ucli oturumları arası MALİYET + KAYNAK karşılaştırma tablosu (TODO 30 (d), 22 Kas). Yaprak modül, yalnız dosya okur (ağ/süreç yok):
  - `ucli_usage/<oturum>.jsonl`        Claude hizmeti: USD HESAPLANIR (`review.usage_cost_usd`, alt sınır; fiyat tablosu tek yerde).
  - `ucli_usage/other/<oturum>.jsonl`  Claude DIŞI (Evren glm/gemma..., BYOK): token VAR, USD YOK (bilinmeyen modeli opus fiyatıyla
                                       saymamak için; bkz. `ucli_cost.other_log_path`).
  - `ucli_metrics.db`                  RSS/CPU/IO örnekleri (`ucli_metrics.query`); oturum adı = günlük dosya adı. Örnek yoksa `res: None`.
Claude Code (claude CLI) oturumları BU tabloda YOK: onlarda süreç örnekleyici yok (yalnız token, bkz. `commands/usage`); kaynak ayağı
yoksa karşılaştırma yanıltıcı olurdu. Maliyet tablodaki rakamlar ALT SINIRDIR."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import review as rv
from . import ucli_cost
from . import ucli_metrics as um

MIN_RATE_SPAN_S = 60.0   # bundan kısa aralıkta USD/saat anlamsız (ekstrapolasyon): None


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _scan(path: str) -> Dict[str, Any]:
    """Tek geçişte: model (son task_start), istek sayısı, ilk/son istek zamanı, token toplamları, model bekleme süresi."""
    model, req, wait = "", 0, 0.0
    first: Optional[float] = None
    last: Optional[float] = None
    tasks = 0
    tok = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ev = rec.get("event")
                if ev == "task_start":
                    tasks += 1
                    if rec.get("model"):
                        model = str(rec["model"])
                elif ev == "request":
                    req += 1
                    wait += _num(rec.get("seconds"))
                    t = _num(rec.get("t"))
                    if t:
                        first = t if first is None else min(first, t)
                        last = t if last is None else max(last, t)
                    u = rec.get("usage")
                    if isinstance(u, dict):
                        tok["in"] += int(_num(u.get("prompt_tokens") or u.get("input_tokens")))
                        tok["out"] += int(_num(u.get("completion_tokens") or u.get("output_tokens")))
                        tok["cache_read"] += int(_num(u.get("cache_read_input_tokens") or u.get("cached_tokens")))
                        tok["cache_write"] += int(_num(u.get("cache_creation_input_tokens") or u.get("cache_write_tokens")))
    except OSError:
        pass
    span = ((last - first) / 1000.0) if first is not None and last is not None else 0.0
    return {"model": model, "tasks": tasks, "requests": req, "wait_s": round(wait, 3), "span_s": round(span, 3), "tokens": tok}


def _res(name: str, db: str) -> Optional[Dict[str, Any]]:
    s = um.query(name, 0.0, um.MAX_LIMIT, db).get("summary") or {}
    if not s.get("n"):
        return None
    return {k: s[k] for k in ("rss_max_kib", "cpu_avg", "io_r", "io_w", "n")}


def _rows(base: str, source: str, db: str, since: float, wm: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for n in names:
        p = os.path.join(base, n)
        if not n.endswith(".jsonl") or not os.path.isfile(p):
            continue
        try:
            if since and os.path.getmtime(p) < since:
                continue
        except OSError:
            continue
        s = _scan(p)
        name = n[:-len(".jsonl")]
        usd = rv.usage_cost_usd(p, "", write_mult=wm) if source == "claude" else None
        out.append({"session": name, "source": source, **s, "usd": usd,
                    "usd_per_hour": (usd * 3600.0 / s["span_s"]) if usd is not None and s["span_s"] >= MIN_RATE_SPAN_S else None,
                    "usd_per_request": (usd / s["requests"]) if usd is not None and s["requests"] else None,
                    "res": _res(name, db)})
    return out


def _resource_only_rows(seen: set, db: str, since: float) -> List[Dict[str, Any]]:
    """Token günlüğü olmayan ama örneklenen oturumlar (claude CLI): yalnız kaynak sütunları; USD/istek yok. source="cli"."""
    out: List[Dict[str, Any]] = []
    for s in um.list_sessions(db):
        if s["name"] in seen or (since and s["last_ts"] < since):
            continue
        res = _res(s["name"], db)
        if not res:
            continue
        out.append({"session": s["name"], "source": "cli", "model": "", "tasks": 0, "requests": 0, "wait_s": 0.0, "span_s": 0.0,
                    "tokens": {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}, "usd": None, "usd_per_hour": None,
                    "usd_per_request": None, "res": res})
    return out


def compare(usage_dir: str = ucli_cost.USAGE_DIR, other_dir: str = ucli_cost.OTHER_DIR, db: Optional[str] = None,
            since: float = 0.0, write_mult: float = ucli_cost.CACHE_1H_WRITE_MULT) -> Dict[str, Any]:
    """{rows: oturum başına satır, by_model: model başına toplam}. `since`: unix saniye, yalnız bu andan sonra güncellenen günlükler.
    Eksik dizin/DB ve bozuk satır FIRLATMAZ (boş sonuç)."""
    db = db or um.db_path()
    rows = _rows(usage_dir, "claude", db, since, write_mult) + _rows(other_dir, "other", db, since, write_mult)
    rows += _resource_only_rows({r["session"] for r in rows}, db, since)
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m = agg.setdefault((r["model"] or "?", r["source"]), {"model": r["model"] or "?", "source": r["source"], "sessions": 0, "requests": 0, "usd": None,
                                               "tokens": {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}, "_rss": [], "_cpu": []})
        m["sessions"] += 1
        m["requests"] += r["requests"]
        for k in m["tokens"]:
            m["tokens"][k] += r["tokens"][k]
        if r["usd"] is not None:
            m["usd"] = (m["usd"] or 0.0) + r["usd"]
        if r["res"]:
            m["_rss"].append(r["res"]["rss_max_kib"])
            m["_cpu"].append(r["res"]["cpu_avg"])
    by_model = []
    for m in agg.values():
        rss, cpu = m.pop("_rss"), m.pop("_cpu")
        m["usd_per_request"] = (m["usd"] / m["requests"]) if m["usd"] is not None and m["requests"] else None
        m["rss_max_kib_avg"] = int(sum(rss) / len(rss)) if rss else None
        m["cpu_avg"] = round(sum(cpu) / len(cpu), 2) if cpu else None
        by_model.append(m)
    by_model.sort(key=lambda m: (m["usd"] is None, -(m["usd"] or 0.0), m["model"]))
    return {"ok": True, "rows": rows, "by_model": by_model}


def api_get(path: str, qs: Dict[str, List[str]], usage_dir: str = ucli_cost.USAGE_DIR, other_dir: str = ucli_cost.OTHER_DIR,
            db: Optional[str] = None) -> Dict[str, Any]:
    """GET /api/ucli/compare?since=<unix sn>."""
    try:
        since = float((qs.get("since") or ["0"])[0] or 0)
    except ValueError:
        return {"ok": False, "error": "since sayı olmalı"}
    return compare(usage_dir, other_dir, db, since)
