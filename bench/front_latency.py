#!/usr/bin/env python3
"""Rust ön kapı (copsd) gecikme ölçümü: aynı uca doğrudan Python iç portu ile vekil üzerinden ardışık N istek.
  python3 bench/front_latency.py [--n 300] [--path /api/instances] [--front 127.0.0.1:8765] [--direct 127.0.0.1:28765]
Çıktı: p50/p95/p99/max ms ve vekil farkı. Token ~/.claude/claudeops/web.token. Yalnız GET, salt-okunur (canlı panelde güvenli)."""
import argparse
import http.client
import os
import statistics
import time


def measure(hostport: str, path: str, n: int, tok: str):
    host, _, port = hostport.rpartition(":")
    ts, bad = [], 0
    for _ in range(n):
        t = time.perf_counter()
        c = http.client.HTTPConnection(host, int(port), timeout=10)      # yeni bağlantı: vekil havuzsuz, adil karşılaştırma
        try:
            c.request("GET", path, headers={"Authorization": "Bearer " + tok})
            r = c.getresponse(); r.read()
            bad += r.status != 200
        except OSError:
            bad += 1
        finally:
            c.close()
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    q = lambda p: ts[min(len(ts) - 1, int(len(ts) * p))]
    return {"p50": q(.5), "p95": q(.95), "p99": q(.99), "max": ts[-1], "mean": statistics.mean(ts), "bad": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--path", default="/api/instances")
    ap.add_argument("--front", default="127.0.0.1:8765")
    ap.add_argument("--direct", default="127.0.0.1:28765")
    a = ap.parse_args()
    tok = open(os.path.expanduser("~/.claude/claudeops/web.token")).read().strip()
    measure(a.direct, a.path, 20, tok)           # ısınma
    d = measure(a.direct, a.path, a.n, tok)
    f = measure(a.front, a.path, a.n, tok)
    print(f"{'':8}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}{'bad':>5}")
    for name, r in (("direct", d), ("front", f)):
        print(f"{name:8}{r['p50']:8.2f}{r['p95']:8.2f}{r['p99']:8.2f}{r['max']:8.2f}{r['bad']:5d}")
    print(f"fark p50 {f['p50'] - d['p50']:+.2f} ms, p95 {f['p95'] - d['p95']:+.2f} ms")


if __name__ == "__main__":
    main()
