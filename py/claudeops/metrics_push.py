"""Metrik gönderici (strangler köprüsü): periyodik iş koşusunu copsd `POST /api/metrics/points`e yollar (loopback + `X-Cops-Front`).
Yalnız İNCE gönderici: durum/depo Rust'ta (`metrics.db`), Python'da yeni dosya/tablo YOK. Fire-and-forget (daemon iş parçacığı, 1,5 sn),
her hata yutulur (copsd eski ikiliyse/kapalıysa iş etkilenmez); iş Rust'a taşınınca ilgili çağrı kalkar.
Seri: `job.<ad>` key=`ms` (süre), `ok` (1/0); işin sonucundaki sayısal alanlar `job.<ad>` key=<alan> (en çok 12)."""
from __future__ import annotations

import http.client
import json
import os
import threading
from typing import Any, Dict, List

from . import front

ADDR = os.environ.get("COPSD_METRICS_ADDR", "127.0.0.1:8765")


def build_points(name: str, ms: float, res: Dict[str, Any], ts: float) -> List[Dict[str, Any]]:
    pts = [{"name": f"job.{name}", "key": "ms", "unit": "ms", "ts": ts, "value": round(ms, 1)},
           {"name": f"job.{name}", "key": "ok", "unit": "bool", "ts": ts, "value": 1 if res.get("ok") else 0}]
    n = 0
    for k, v in res.items():
        if k == "ok" or isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
            continue
        pts.append({"name": f"job.{name}", "key": str(k)[:60], "ts": ts, "value": v})
        n += 1
        if n >= 12:
            break
    return pts


def _post(points: List[Dict[str, Any]]) -> None:
    sec = front.read_secret()
    if not sec:
        return
    try:
        host, _, port = ADDR.partition(":")
        c = http.client.HTTPConnection(host, int(port or 8765), timeout=1.5)
        c.request("POST", "/api/metrics/points", body=json.dumps(points), headers={"X-Cops-Front": sec, "Content-Type": "application/json"})
        c.getresponse().read()
        c.close()
    except Exception:  # noqa: BLE001 — metrik iş sonucunu asla bozmaz
        pass


def push_job(name: str, ms: float, res: Dict[str, Any], ts: float) -> None:
    try:
        pts = build_points(name, ms, res if isinstance(res, dict) else {}, ts)
    except Exception:  # noqa: BLE001
        return
    threading.Thread(target=_post, args=(pts,), daemon=True, name="metrics-push").start()
