#!/usr/bin/env python3
"""Python steward testlerini koşarken `claudeops.steward` işlevlerinin girdi/çıktısını kaydeder.
Çıktı: `fixtures/vectors/<işlev>.jsonl` (satır = {"args":{..},"ret":..,"now":..,"after":{..}}) ve
`fixtures/test_calls.json` ({test kimliği: [çağrılan işlevler]}). Kullanım: `python3 parity/record.py [işlev...]`."""
import dataclasses, functools, glob, gzip, hashlib, inspect, io, json, math, os, sys, unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
TMP = env.isolate()
sys.path.insert(0, os.path.join(env.PY, "tests"))
sys.argv = ["python3 -m unittest"] + sys.argv[1:]      # claudeops'un test altı korumaları devrede olsun
from claudeops import steward as sw  # noqa: E402

# G/Ç yapan işlevler: bu crate'e taşınmaz (kayıt da alınmaz). Gerekçeler docs/rs-stew.md eşleme tablosunda.
IO = set(json.load(open(os.path.join(env.CRATE, "parity", "io_functions.json"), encoding="utf-8")))
CAP = {"plan_tick": 600, "scan_markers": 500}
DEFAULT_CAP = 250
MAX_BYTES = 80_000

records = {}      # işlev -> {hash: satır}
test_calls = {}
current = [None]


class Skip(Exception):
    pass


def enc(v, fns):
    if v is None or isinstance(v, (bool, str)): return v
    if isinstance(v, int): return v
    if isinstance(v, float):
        if math.isfinite(v): return v
        raise Skip()
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: enc(getattr(v, f.name), fns) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            return {"__pairs__": [[enc(k, fns), enc(x, fns)] for k, x in v.items()]}
        return {k: enc(x, fns) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [enc(x, fns) for x in v]
    if isinstance(v, (set, frozenset)): return sorted((enc(x, fns) for x in v), key=repr)
    raise Skip()


def wrap_cb(fn, log):
    def inner(*a):
        r = fn(*a)
        log.append([enc(list(a), None), enc(r, None)])
        return r
    return inner


def wrap(name, fn):
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def w(*a, **k):
        if current[0] is not None:
            test_calls.setdefault(current[0], set()).add(name)
        try:
            b = sig.bind(*a, **k)
            cbs = {}
            args = {}
            for p, v in list(b.arguments.items()):
                if inspect.isfunction(v) or inspect.ismethod(v) or isinstance(v, functools.partial) or type(v).__name__ in ("MagicMock", "Mock"):
                    cbs[p] = []
                    b.arguments[p] = wrap_cb(v, cbs[p])
                else:
                    args[p] = enc(v, None)
            now = sw._now()
        except Exception:        # noqa: BLE001  kaydedilemeyen çağrı olduğu gibi geçer
            return fn(*a, **k)
        ret = fn(*b.args, **b.kwargs)
        try:
            rec = {"args": args, "ret": enc(ret, None), "now": now}
            after = {}
            for p, v in b.arguments.items():
                if p not in cbs:
                    e = enc(v, None)
                    if e != args.get(p): after[p] = e
            if after: rec["after"] = after
            if cbs: rec["callbacks"] = cbs
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
            if len(line.encode()) <= MAX_BYTES and TMP not in line:
                key = hashlib.sha1(json.dumps([args, cbs, ret if isinstance(ret, str) else rec["ret"]], sort_keys=True).encode()).hexdigest()
                records.setdefault(name, {}).setdefault(key, line)
        except Exception:        # noqa: BLE001
            pass
        return ret
    return w


def install():
    for name, v in list(vars(sw).items()):
        if inspect.isfunction(v) and v.__module__ == sw.__name__ and name not in IO:
            setattr(sw, name, wrap(name, v))
    for cname in ("World", "SessionView"):
        cls = getattr(sw, cname)
        for name, v in list(vars(cls).items()):
            if inspect.isfunction(v) and not name.startswith("__"):
                setattr(cls, name, wrap(f"{cname}.{name}", v))


def install_deps():
    """steward.py'nin dışarıdan çağırdığı SAF yardımcılar (aynı crate'e taşınır)."""
    from claudeops import needs_ho, steward_ask
    rfh = wrap("needs_ho.rfh_marker_in", needs_ho.rfh_marker_in)
    needs_ho.rfh_marker_in = rfh
    sw.rfh_marker_in = rfh
    steward_ask.tour_eligible = wrap("steward_ask.tour_eligible", steward_ask.tour_eligible)


def test_files():
    out = []
    for p in sorted(glob.glob(os.path.join(env.PY, "tests", "test_*.py"))):
        s = open(p, encoding="utf-8").read()
        if os.path.basename(p).startswith("test_steward") or "steward as sw" in s or "import steward" in s:
            out.append(os.path.basename(p)[:-3])
    return out


class Result(unittest.TextTestResult):
    def startTest(self, t):
        current[0] = t.id()
        test_calls.setdefault(t.id(), set())
        super().startTest(t)

    def stopTest(self, t):
        super().stopTest(t)
        current[0] = None


def main():
    install()
    install_deps()
    suite = unittest.defaultTestLoader.loadTestsFromNames(test_files())
    buf = io.StringIO()
    res = unittest.TextTestRunner(stream=buf, resultclass=Result, verbosity=0).run(suite)
    print(f"test: {res.testsRun} koştu, {len(res.failures)} fail, {len(res.errors)} error, {len(res.skipped)} skip")
    for t, tb in (res.failures + res.errors)[:15]:
        print("  ", t.id(), "|", tb.strip().splitlines()[-1][:200])
    out = os.path.join(env.CRATE, "fixtures", "vectors")
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*.jsonl.gz")):
        os.remove(old)
    for name, recs in sorted(records.items()):
        cap = CAP.get(name, DEFAULT_CAP)
        keys = sorted(recs)[:cap]
        keep = set(keys)
        body = "".join(line + "\n" for k, line in recs.items() if k in keep).replace(env.PY, "/repo/py")
        with open(os.path.join(out, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
            f.write(body.encode())
    with open(os.path.join(env.CRATE, "fixtures", "test_calls.json"), "w", encoding="utf-8") as f:
        json.dump({t: sorted(v) for t, v in sorted(test_calls.items())}, f, ensure_ascii=False, indent=0)
    print("işlev:", len(records), "kayıt:", sum(min(len(r), CAP.get(n, DEFAULT_CAP)) for n, r in records.items()))


main()
