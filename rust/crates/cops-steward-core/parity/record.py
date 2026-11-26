#!/usr/bin/env python3
"""Python steward testlerini koşarken `claudeops.steward` işlevlerinin girdi/çıktısını kaydeder.
Çıktı: `fixtures/vectors/<işlev>.jsonl` (satır = {"args":{..},"ret":..,"now":..,"after":{..}}) ve
`fixtures/test_calls.json` ({test kimliği: [çağrılan işlevler]}). Kullanım: `python3 parity/record.py [işlev...]`
(ad verilirse yalnız o vektör dosyaları yazılır, diğerlerine dokunulmaz; testlerin tümü yine koşar).
Depo okuyup yazan işlevler (`STATEFUL`) saat dondurularak kaydedilir: args = Python argümanları + çağrı ÖNCESİ belge +
üretilen kimlikler (`_ids`, `_keys`) + dış dünyadan okunanlar; after = çağrı sonrası belge. İstisna da kaydedilir."""
import dataclasses, functools, glob, gzip, hashlib, inspect, io, json, math, os, site, sys, threading, unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
TMP = env.isolate()
ONLY = set(sys.argv[1:])
sys.path.insert(0, os.path.join(env.PY, "tests"))
if sys.flags.isolated:     # `-I` kullanıcı paketlerini dışlar; testlerin bağımlılıkları (websockets) oradadır
    at = next((i for i, p in enumerate(sys.path) if p.endswith("-packages")), len(sys.path))
    sys.path.insert(at, site.getusersitepackages())     # normal sıradaki gibi: sistem paketlerinden önce
sys.argv = ["python3 -m unittest"]                          # claudeops'un test altı korumaları devrede olsun
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


# ── durumlu işlevler ──────────────────────────────────────────────────────────

def questions_doc(paths, args):
    if args.get("questions") is not None:
        return args["questions"]
    return enc([q for q in sw.load_questions(paths)], None)


def ideas_doc(paths, args):
    return enc(sw.load_ideas(paths), None)


def projects_doc(paths, args):
    return enc(sw.load_projects(paths), None)


def state_doc(paths, args):
    return enc(sw.load_state(paths), None)


def card_doc(paths, args):
    return enc(sw.load_card(args["name"], paths), None)


QUESTION_FNS = ("add_question_ex add_question set_question_detail answer_question set_answered_by mark_notified "
                "escalate_routine mark_delivered mark_undeliverable open_questions undelivered_answers find_question "
                "recent_answers").split()
STATEFUL = {**{n: ("questions", questions_doc) for n in QUESTION_FNS},
            **{n: ("ideas", ideas_doc) for n in ("add_idea", "update_idea", "record_idea_export")},
            "upsert_project": ("projects", projects_doc), "_clear_project_state": ("state", state_doc),
            "mark_card_stale": ("card", card_doc), "note_card_failure": ("card", card_doc), "make_card": (None, None)}


def keep(name, rec, key_obj):
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    if len(line.encode()) <= MAX_BYTES and TMP not in line:
        key = hashlib.sha1(json.dumps(key_obj, sort_keys=True).encode()).hexdigest()
        records.setdefault(name, {}).setdefault(key, line)


def spy(saved, attr, make):
    saved.append((attr, getattr(sw, attr)))
    setattr(sw, attr, make(getattr(sw, attr)))


def logged(log):
    def make(orig):
        def inner(*a, **k):
            r = orig(*a, **k)
            log.append(r)
            return r
        return inner
    return make


def stateful(name, fn):
    sig = inspect.signature(fn)
    doc_name, doc = STATEFUL[name]

    @functools.wraps(fn)
    def w(*a, **k):
        if current[0] is None:
            return fn(*a, **k)
        test_calls.setdefault(current[0], set()).add(name)
        if threading.current_thread() is not threading.main_thread():    # yamalar modül geneli: eşzamanlı kayıt karışır
            return fn(*a, **k)
        saved, ids, keys, extra, mid = [], [], [], {}, []
        try:
            b = sig.bind(*a, **k)
            paths = b.arguments.get("paths")
            if name == "upsert_project":
                fields = b.arguments.get("fields", {})
                args = {"name": b.arguments["name"], "force": b.arguments.get("force", False), "fields": enc(fields, None)}
            else:
                args = {p: enc(v, None) for p, v in b.arguments.items() if p not in ("paths", "projects")}
            if name == "_clear_project_state":
                args["projects"] = enc(b.arguments["projects"], None)
            now = sw._now()
            before = doc(paths, args) if doc else None
            if doc: args[doc_name] = before
        except Exception:        # noqa: BLE001
            return fn(*a, **k)
        spy(saved, "_now", lambda orig: lambda: now)
        spy(saved, "_new_id", logged(ids))
        spy(saved, "_unique_question_key", logged(keys))
        if name == "upsert_project":
            sid = sw._pp(paths).sid
            args["sid"] = sid
            args["reviewer"] = bool(sw.is_reviewer(sid))
            owners, hosts, index, busy, cleared, labels = [], [], [], [], [], []
            spy(saved, "project_owner", logged(owners))
            spy(saved, "ownership_index", logged(index))
            spy(saved, "_clear_project_state", logged(cleared))
            real_get = sw.hosts_mod.get_host
            sw.hosts_mod.get_host = logged(hosts)(real_get)
            saved.append(("hosts_mod.get_host", real_get))

            def labels_spy(orig):
                def inner(project, paths=None, *, via=""):
                    labels.append(via)
                    return orig(project, paths, via=via)
                return inner
            spy(saved, "auto_remove_labels", labels_spy)
            running = b.arguments.get("running")
            if callable(running):
                b.arguments["running"] = logged(busy)(running)
        if name == "answer_question":
            def hook(orig):
                def inner(*x, **y):
                    mid.append(doc(paths, {}))
                    return orig(*x, **y)
                return inner
            spy(saved, "apply_review_where_answer", hook)
        err = ret = None
        try:
            ret = fn(*b.args, **b.kwargs)
        except Exception as e:        # noqa: BLE001  istisna da vektördür
            err = e
        finally:
            for attr, orig in reversed(saved):
                if attr == "hosts_mod.get_host": sw.hosts_mod.get_host = orig
                else: setattr(sw, attr, orig)
        if err and not isinstance(err, (ValueError, TypeError)):     # ortam hatası (kilit zaman aşımı, disk): karar değil
            raise err
        try:
            if name == "upsert_project":
                args["owner_elsewhere"] = enc(owners[-1], None) if owners else None
                args["host_known"] = bool(hosts[-1] is not None) if hosts else True
                args["index"] = enc(index[-1], None) if index else None
                args["running_given"] = callable(running)
                args["running"] = busy[-1] if busy else None
                extra = {"cleared": bool(cleared), "auto_label_via": labels[-1] if labels else None}
            args["_ids"], args["_keys"] = ids, keys
            out = {"__error__": type(err).__name__, "msg": str(err)} if err else enc(ret, None)
            rec = {"args": args, "ret": out, "now": now}
            after = dict(extra)
            if doc: after[doc_name] = mid[-1] if mid else doc(paths, {})
            if after: rec["after"] = after
            keep(name, rec, [args, out, after])
        except Exception:        # noqa: BLE001
            pass
        if err: raise err
        return ret
    return w


def log_dedup_wrapper(fn):
    """`_log_dedup` modül durumuna (`_LOG_SEEN`) bakar: ilgili konunun önceki/sonraki kaydı da vektöre girer. Python'un içerik
    özeti Rust'a taşınmaz; yalnız "önceki kayıt bu içerikle aynı mı" (`same`) kaydedilir."""
    @functools.wraps(fn)
    def w(log, event, data, now):
        if current[0] is None:
            return fn(log, event, data, now)
        test_calls.setdefault(current[0], set()).add("_log_dedup")
        if threading.current_thread() is not threading.main_thread():
            return fn(log, event, data, now)
        try:
            key = (log, event, str(data.get("name") or data.get("project") or ""))
            prev = sw._LOG_SEEN.get(key)
            prev = list(prev) if prev else None
            digest = hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]
        except Exception:        # noqa: BLE001
            return fn(log, event, data, now)
        ret = fn(log, event, data, now)
        try:
            post = sw._LOG_SEEN.get(key)
            args = {"log": "<log>", "event": event, "data": enc(data, None), "now": now,
                    "seen": None if prev is None else {"same": prev[0] == digest, "at": prev[1], "suppressed": prev[2]}}
            after = {"seen": None if post is None else {"at": post[1], "suppressed": post[2]}}
            keep("_log_dedup", {"args": args, "ret": enc(ret, None), "now": now, "after": after}, [args, ret, after])
        except Exception:        # noqa: BLE001
            pass
        return ret
    return w


def install():
    for name in STATEFUL:
        setattr(sw, name, stateful(name, getattr(sw, name)))
    sw._log_dedup = log_dedup_wrapper(sw._log_dedup)
    for name, v in list(vars(sw).items()):
        if name in STATEFUL or name == "_log_dedup":
            continue
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
    if not ONLY:
        for old in glob.glob(os.path.join(out, "*.jsonl.gz")):
            os.remove(old)
    elif ONLY - set(records):
        print("kayıt yok:", ", ".join(sorted(ONLY - set(records))))
    for name, recs in sorted(records.items()):
        if ONLY and name not in ONLY:
            continue
        cap = CAP.get(name, DEFAULT_CAP)
        keys = sorted(recs)[:cap]
        keep = set(keys)
        body = "".join(line + "\n" for k, line in recs.items() if k in keep).replace(env.PY, "/repo/py").replace(os.getcwd(), "/repo/cwd")
        with open(os.path.join(out, name + ".jsonl.gz"), "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
            f.write(body.encode())
    with open(os.path.join(env.CRATE, "fixtures", "test_calls.json"), "w", encoding="utf-8") as f:
        json.dump({t: sorted(v) for t, v in sorted(test_calls.items())}, f, ensure_ascii=False, indent=0)
    print("işlev:", len(records), "kayıt:", sum(min(len(r), CAP.get(n, DEFAULT_CAP)) for n, r in records.items()))


main()
