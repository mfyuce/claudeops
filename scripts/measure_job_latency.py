#!/usr/bin/env python3
"""Degnekci is akisi gecikme olcumu: STEWARD-JOB isareti -> job_submit -> done -> job_delivered, son N is, medyan/maks (sn).
Kullanim: measure_job_latency.py [--log YOL ...] [-n N=40] [--since ISO] [--until ISO]
Varsayilan gunluk: ~/.claude/claudeops/steward/log.jsonl + stewards/*/log.jsonl (varaka isleri iso gibi kimliklerin gunlugunde)."""
import argparse, glob, json, os, statistics, sys
from datetime import datetime

def ts(s): return datetime.fromisoformat(s).timestamp()

def default_logs():
    root = os.path.expanduser("~/.claude/claudeops/steward")
    return [p for p in [os.path.join(root, "log.jsonl")] + sorted(glob.glob(os.path.join(root, "stewards", "*", "log.jsonl"))) if os.path.exists(p)]


def load_events(paths, since="", until=""):
    ev = []
    for path in paths:
        for line in open(path, encoding="utf-8", errors="replace"):
            try: e = json.loads(line)
            except ValueError: continue
            if not isinstance(e, dict) or not e.get("ts") or (since and e["ts"] < since) or (until and e["ts"] >= until): continue
            ev.append(e)
    ev.sort(key=lambda e: e["ts"])
    return ev


def measure(ev, n=40):
    """-> {asama: (adet, medyan, en_cok)} (saf; olay listesinden)."""
    marks = {}          # proje -> son isaret zamani (submit'e eslenince tuketilir)
    jobs = {}           # (servis,id) -> {mark,submit,done,deliv}
    for e in ev:
        k = e.get("event"); t = ts(e["ts"]) if e.get("ts") else 0
        if k == "action" and e.get("kind") == "ask_user" and e.get("reason") == "STEWARD-JOB":
            marks[e.get("name")] = t
        elif k == "job_submit":
            key = (e.get("service"), e.get("id"))
            jobs[key] = {"mark": marks.pop(e.get("project"), None), "submit": t}
        elif k == "job_state" and e.get("to") in ("done", "failed", "error", "cancelled"):
            j = jobs.get((e.get("service"), e.get("id")))
            if j and "done" not in j: j["done"] = t
        elif k == "job_delivered" and e.get("stage") == "result":
            j = jobs.get((e.get("service"), e.get("id")))
            if j and "deliv" not in j: j["deliv"] = t
    last = list(jobs.values())[-n:]
    def seg(a, b):
        v = [j[b] - j[a] for j in last if j.get(a) and j.get(b) and j[b] >= j[a]]
        return (len(v), statistics.median(v), max(v)) if v else (0, 0, 0)
    return {"isaret -> submit": seg("mark", "submit"), "submit -> done": seg("submit", "done"),
            "done -> teslim": seg("done", "deliv"), "isaret -> teslim (uctan uca)": seg("mark", "deliv")}


def main(argv):
    ap = argparse.ArgumentParser(description="Degnekci is akisi gecikme olcumu")
    ap.add_argument("--log", action="append", help="gunluk dosyasi (tekrarlanabilir); yoksa tum kimliklerin gunlukleri")
    ap.add_argument("-n", type=int, default=40, help="son N is")
    ap.add_argument("--since", default="", help="ISO zaman (2026-11-13T20:04:00) oncesini atla")
    ap.add_argument("--until", default="", help="ISO zaman: bu andan sonrasini atla (oncesi/sonrasi karsilastirma)")
    a = ap.parse_args(argv)
    res = measure(load_events(a.log or default_logs(), a.since, a.until), a.n)
    print(f"{'asama':32} {'n':>3} {'medyan sn':>10} {'en cok sn':>10}")
    for k, r in res.items(): print(f"{k:32} {r[0]:>3} {r[1]:>10.0f} {r[2]:>10.0f}")


if __name__ == "__main__":
    main(sys.argv[1:])
