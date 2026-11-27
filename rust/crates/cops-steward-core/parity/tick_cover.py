#!/usr/bin/env python3
"""`plan_tick` satır kapsamı: kayıtlı (`fixtures/vectors`) ve elle (`fixtures/hand`) vektörler Python'da yeniden oynatılır,
`sys.settrace` ile `plan_tick` ve iç işlevlerinin koşan satırları toplanır; hiç koşmayan satırlar yazılır (coverage paketi
gerekmez). Kullanım: `python3 -I parity/tick_cover.py [--quiet]`."""
import dataclasses, gzip, inspect, json, os, sys, types

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
from claudeops import steward as sw  # noqa: E402

FN = sw.plan_tick
SRC, START = inspect.getsourcelines(FN)
CODES = set()


def collect(code):
    CODES.add(code)
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            collect(c)


collect(FN.__code__)
EXEC = {ln for c in CODES for _, _, ln in c.co_lines() if ln is not None}
HIT = set()


def tracer(frame, event, arg):
    if frame.f_code in CODES:
        HIT.add(frame.f_lineno)
        return local
    return None


def local(frame, event, arg):
    if event == "line":
        HIT.add(frame.f_lineno)
    return local


def dc(cls, d):
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def world(d):
    if d is None:
        return None
    d = dict(d)
    for k in ("conflicts", "unavailable", "quota_held"):
        if k in d:
            d[k] = frozenset(d[k] or [])
    return dc(sw.World, d)


def callbacks(rec):
    out = {}
    for name, pairs in (rec.get("callbacks") or {}).items():
        table = {json.dumps(a, ensure_ascii=False): r for a, r in pairs}

        def fn(*a, table=table, name=name):
            key = json.dumps(list(a), ensure_ascii=False)
            if key not in table or (name == "todo_sha" and table[key] is None):
                raise RuntimeError("kayıtsız çağrı")
            return table[key]
        out[name] = fn
    return out


def replay(path):
    n = 0
    if not os.path.exists(path):
        return 0
    for line in gzip.open(path, "rt", encoding="utf-8"):
        rec = json.loads(line)
        a = rec["args"]
        args = dict(views=[dc(sw.SessionView, v) for v in a["views"]], projects={k: dc(sw.Project, p) for k, p in a["projects"].items()},
                    state=a.get("state") or {}, cfg=dc(sw.Config, a["cfg"]), now=a["now"], questions=[dc(sw.Question, q) for q in a["questions"]],
                    ideas=[dc(sw.Idea, i) for i in a["ideas"]], world=world(a.get("world")))
        args.update(callbacks(rec))
        sys.settrace(tracer)
        try:
            FN(**args)
        except Exception:        # noqa: BLE001  hata vektörü
            pass
        finally:
            sys.settrace(None)
        n += 1
    return n


def main():
    total = 0
    for sub in ("vectors", "hand"):
        before = set(HIT)
        n = replay(os.path.join(env.CRATE, "fixtures", sub, "plan_tick.jsonl.gz"))
        total += n
        print(f"{sub}: {n} çağrı, yeni satır {len(HIT - before)}")
    missed = sorted(EXEC - HIT)
    print(f"plan_tick: {len(EXEC)} çalıştırılabilir satır, {len(EXEC & HIT)} koştu, {len(missed)} hiç koşmadı ({total} çağrı)")
    if "--quiet" not in sys.argv:
        for ln in missed:
            print(f"  {ln}: {SRC[ln - START].rstrip()}")


main()
