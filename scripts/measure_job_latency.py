#!/usr/bin/env python3
"""Degnekci is akisi gecikme olcumu (log.jsonl): STEWARD-JOB isareti -> job_submit -> done -> job_delivered, son N is, medyan/maks (sn).
Kullanim: measure_job_latency.py [log.jsonl] [N=40] [--since ISO]"""
import json, os, statistics, sys
from datetime import datetime

def ts(s): return datetime.fromisoformat(s).timestamp()

def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    since = argv[argv.index("--since") + 1] if "--since" in argv else ""
    path = args[0] if args else os.path.expanduser("~/.claude/claudeops/steward/log.jsonl")
    n = int(args[1]) if len(args) > 1 else 40
    ev = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try: e = json.loads(line)
        except ValueError: continue
        if since and e.get("ts", "") < since: continue
        ev.append(e)
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
    rows = [("isaret -> submit", *seg("mark", "submit")), ("submit -> done", *seg("submit", "done")),
            ("done -> teslim", *seg("done", "deliv")),
            ("isaret -> teslim (uctan uca)", *seg("mark", "deliv"))]
    print(f"{'asama':32} {'n':>3} {'medyan sn':>10} {'en cok sn':>10}")
    for r in rows: print(f"{r[0]:32} {r[1]:>3} {r[2]:>10.0f} {r[3]:>10.0f}")

if __name__ == "__main__":
    main(sys.argv[1:])
