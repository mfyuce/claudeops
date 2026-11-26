"""`claudeops.review` işlevlerini sarar: Python sonucu üretilir, aynı girdi Rust sunucusuna sorulur, farklar toplanır.
Dosyaya dokunan işlevler çağrı ANINDA karşılaştırılır (testin geçici dosyaları henüz duruyor). Test sonucunu DEĞİŞTİRMEZ."""
import dataclasses
import inspect
import json
import math
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest

from claudeops import review as rv
from claudeops import statedocs
from claudeops import steward as sw
from claudeops.textutil import collapse_ws

_orig = {}
_calls, _skipped, _mismatches, _by_test = {}, {}, [], {}
_local = threading.local()
_lock = threading.RLock()
_sock = socket.socket(socket.AF_UNIX)
_sock.connect(os.environ["COPS_REV_PARITY_SOCK"])
_io = _sock.makefile("rw", encoding="utf-8", newline="\n")
_current = ["(modül)"]
_run = unittest.TestCase.run


def _tracked_run(self, *a, **kw):
    _current[0] = self.id()
    _local.depth = 0
    try:
        return _run(self, *a, **kw)
    finally:
        _current[0] = "(modül)"


unittest.TestCase.run = _tracked_run


class Skip(Exception):
    pass


def enc(v):
    if isinstance(v, rv.ReviewTarget):
        return {"__t": [v.mode, v.model, v.slug, v.effort, v.lens]}
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            raise Skip("eşlenmemiş vekil")
        return str(v)
    if isinstance(v, os.PathLike):
        return os.fspath(v)
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise Skip("dize olmayan anahtar")
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(enc(x) for x in v)
    raise Skip(f"JSON'a çevrilemeyen tip {type(v).__name__}")


def same(a, b, loose=()):
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        if type(a) is not type(b):
            return False
        return a == b or (math.isnan(a) and math.isnan(b))
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if list(a) != list(b):
            return False
        return all((k in loose and isinstance(a[k], float) and isinstance(b[k], float) and abs(a[k] - b[k]) < 30)
                   or same(a[k], b[k], loose) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y, loose) for x, y in zip(a, b))
    return a == b


def ask(req):
    with _lock:
        _io.write(json.dumps(req, ensure_ascii=False) + "\n")
        _io.flush()
        return json.loads(_io.readline())


def compare(name, req, ok, value, loose=()):
    """`ok`: Python istisnasız döndü mü; `value` kodlanmış sonuç ya da istisna metni."""
    ans = ask(dict(req, fn=name))
    _calls[name] = _calls.get(name, 0) + 1
    _by_test.setdefault(_current[0], set()).add(name)
    good = ("ok" in ans and same(value, ans["ok"], loose)) if ok else ("err" in ans and not ans["err"].startswith(("BİLİNMEYEN", "PANİK")))
    if not good and len(_mismatches) < 200:
        _mismatches.append({"fn": name, "test": _current[0], "req": req, "python": value if ok else f"istisna {value}", "rust": ans})
    return good


def skip(name, why):
    k = f"{name}: {why}"
    _skipped[k] = _skipped.get(k, 0) + 1


def mocked():
    """Test `review`in bir işlevini taklit ettiyse iç çağrılar gerçek davranışı yansıtmaz."""
    return any(rv.__dict__.get(n) is not w for n, w in _wrappers.items())


# ── bağdaştırıcılar: ad -> (bound arguments) -> (istek, sonuç dönüştürücü) ───────────────────

def _texts(a):
    return {"texts": list(a["texts"])}


def _catalog(a):
    return rv.__dict__["claude_catalog"].__wrapped__() if a.get("catalog") is None else a["catalog"]


def adapt(name, a):
    """(istek sözlüğü, argümanları değiştiren sözlük, sonuç dönüştürücü(result, a))."""
    extra, post = {}, None
    if name in ("is_capacity_error", "capacity_retry_seconds", "is_daily_limit", "is_quota_exhausted", "is_usage_limit",
                "reset_at", "reset_seconds"):
        return _texts(a), extra, post
    if name in ("quota_block_until", "block_until_for_limit"):
        return {"now": float(a["now"]), "texts": list(a["texts"])}, extra, post
    if name in ("claude_specs", "targets_from_config"):
        req = {k: v for k, v in a.items() if k not in ("cfg", "catalog")}
        req["cfg"] = {f: getattr(a["cfg"], f) for f in dir(a["cfg"]) if f.startswith("review_") and isinstance(getattr(a["cfg"], f), str)}
        req["catalog"] = _catalog(a)
        if name == "targets_from_config":
            req["agy_models"], req["evren_models"] = list(a["agy_models"] or []), list(a["evren_models"] or [])
        return req, extra, post
    if name in ("excluded_keys", "claude_is_subscription"):
        return {"cfg": {f: getattr(a["cfg"], f) for f in dir(a["cfg"]) if f.startswith("review_") and isinstance(getattr(a["cfg"], f), str)}}, extra, post
    if name == "effort_for":
        cfg = {f: getattr(a["cfg"], f) for f in dir(a["cfg"]) if f.startswith("review_") and isinstance(getattr(a["cfg"], f), str)}
        for m in ("claude", "codex", "copilot"):      # Python `getattr(..., "")`: eksik alan boş, Rust varsayılanı değil
            cfg[f"review_{m}_effort"] = getattr(a["cfg"], f"review_{m}_effort", "")
        t = a["target"]
        if t is not None and not isinstance(t, rv.ReviewTarget):
            raise Skip("hedef sahte nesne")
        return {"cfg": cfg, "mode": a["mode"], "target": t}, extra, post
    if name == "claude_catalog":
        from claudeops.paths import CLAUDE_MODELS_JSON
        return {"state": statedocs.read_json("claude_models", CLAUDE_MODELS_JSON, {})}, extra, post
    if name == "project_complete" or name == "model_health":
        return {k: (float(v) if k in ("now", "window", "days", "max_rate") else v) for k, v in a.items()}, extra, post
    if name == "next_review":
        req = {k: a[k] for k in ("pool", "history", "targets", "now", "busy_projects", "window", "skip_pairs")}
        req.update(now=float(a["now"]), window=float(a["window"]), heads=None)
        if a["head_of"] is not None:
            heads = {}
            for p in _orig["pool_enabled"](a["pool"]):
                try:
                    heads[p] = str(a["head_of"](p) or "")
                except Exception:
                    heads[p] = ""
            req["heads"] = heads
        return req, extra, post
    if name == "backlogged_projects":
        counts = {}
        for p in _orig["pool_enabled"](a["pool"]):
            try:
                counts[p] = int(a["count_of"](p))
            except Exception:
                pass
        return {"pool": a["pool"], "counts": counts, "limit": a["limit"]}, extra, post
    if name == "pool_sync":
        names = [n for n in a["owner_names"] if isinstance(n, str)]
        extra["owner_names"] = list(a["owner_names"])
        return {"pool": a["pool"], "owner_names": names, "now": float(a["now"])}, extra, post
    if name == "agy_settings":
        extra["allow"] = list(a["allow"])
        return {"cwd": a["cwd"], "allow": extra["allow"]}, extra, post
    if name == "export_root":
        resolved = {}

        def spy(p, _r=a["resolve"]):
            resolved[p] = _r(p)
            return resolved[p]
        extra["resolve"] = spy
        return {"row": a["row"], "project": a["project"], "cwd": a["cwd"], "resolved": resolved}, extra, post
    if name in ("export_lines", "appended_export", "build_verify_message", "build_self_verify_prompt", "health_digest"):
        extra["rows"] = list(a["rows"])
        req = dict(a, rows=extra["rows"])
        if name == "health_digest":
            req.update(excluded=list(a["excluded"]), days=float(a["days"]))
        return req, extra, post
    if name in ("reconcile_copilot_blocks", "reconcile_agy_blocks"):
        extra["now"] = float(a["now"])      # üretimde `time.time()`: iki tarafa aynı tip
        req = dict(a, hist=json.loads(json.dumps(a["hist"])), now=extra["now"])
        if name == "reconcile_agy_blocks":
            extra["target_keys"] = req["target_keys"] = list(a["target_keys"])
        else:
            req["stop_pct"] = float(a["stop_pct"])
        return req, extra, lambda res, args: [res, args["hist"]]
    if name == "migrate_r10_sub":
        return {"hist": json.loads(json.dumps(a["hist"]))}, extra, lambda res, args: [res, args["hist"]]
    if name in ("apply_verdicts", "requeue_stale_verify"):
        req = dict(a, findings=json.loads(json.dumps(a["findings"])), now=float(a["now"]))
        if name == "apply_verdicts":
            extra["verdicts"] = req["verdicts"] = list(a["verdicts"])
        else:
            req["stale"] = float(a["stale"])
        return req, extra, lambda res, args: [res, args["findings"]]
    if name == "redact_secrets":
        extra["learned"] = list(a["learned"])
        return {"text": a["text"], "learned": extra["learned"]}, extra, post
    for k in ("now", "since_ms", "write_mult", "until", "base"):
        if isinstance(a.get(k), int) and not isinstance(a.get(k), bool):
            a = dict(a, **{k: float(a[k])})
    return dict(a), extra, post


STORE = {"load_pool": "review_pool", "save_pool": "review_pool", "load_history": "review_history",
         "save_history": "review_history", "set_block": "review_history", "update_pair": "review_history",
         "load_findings": "findings", "save_findings": "findings", "add_findings": "findings",
         "mark_verify_sent": "findings", "decide_finding": "findings"}


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def call_store(name, fn, bound):
    a = bound.arguments
    p = sw._pp(a["paths"])
    if statedocs.backend() != "files":
        raise Skip("DB kipi")
    path = getattr(p, STORE[name])
    scratch = tempfile.mkdtemp(prefix="cops-rev-par-")
    try:
        mine = os.path.join(scratch, os.path.basename(path))
        before = _read(path)
        if before is not None:
            with open(mine, "wb") as f:
                f.write(before)
        req = {k: v for k, v in a.items() if k != "paths"}
        for k in ("fids", "parsed"):
            if k in req:
                req[k] = a[k] = list(req[k])
        if name == "update_pair":
            req.update(req.pop("fields", {}))
            req = {"proj": a["proj"], "t": a["t"], "fields": dict(a.get("fields", {}))}
        for k in ("now", "until"):
            if k in req:
                req[k] = float(req[k])
        req = enc(req)
        req.update(root=scratch, reviews=p.reviews)
        ok, value, exc = True, None, None
        try:
            result = fn(*bound.args, **bound.kwargs)
        except Exception as e:
            ok, exc = False, e
        loose = ("set_at", "created_at", "started_at")
        if ok:
            value = enc(result)
        if compare(name, req, ok, value if ok else repr(exc), loose):
            after, theirs = _read(path), _read(mine)
            if name.startswith("load_") and theirs == before and after is not None and after != before:
                skip(name, "okuma sırasında başka iş parçacığı yazdı (dosya karşılaştırılmadı)")
            elif after != theirs:
                try:
                    equal = after is not None and theirs is not None and same(json.loads(after), json.loads(theirs), loose)
                except ValueError:
                    equal = False
                time_only = equal and len(after.splitlines()) == len(theirs.splitlines())
                if not time_only:
                    _mismatches.append({"fn": name, "test": _current[0], "dosya": True,
                                        "python": (after or b"<yok>")[:600].decode("utf-8", "replace"),
                                        "rust": (theirs or b"<yok>")[:600].decode("utf-8", "replace")})
        if not ok:
            raise exc
        return result
    finally:
        shutil.rmtree(scratch, True)


def wrap(name, fn):
    sig = inspect.signature(fn)

    def wrapper(*args, **kwargs):
        depth = getattr(_local, "depth", 0)
        if depth or mocked():           # iç çağrılar dış karşılaştırmanın parçası
            if not depth:
                skip(name, "review işlevi taklit edilmiş")
            return fn(*args, **kwargs)
        _local.depth = 1
        try:
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
            except TypeError:
                return fn(*args, **kwargs)
            if name in STORE:
                try:
                    return call_store(name, fn, bound)
                except Skip as s:
                    skip(name, str(s))
                    return fn(*args, **kwargs)
            try:
                req, extra, post = adapt(name, dict(bound.arguments))
                bound.arguments.update(extra)
                if name == "export_root":
                    pass                 # `resolved` çağrı SIRASINDA dolar: kodlama sonra
                elif post is None:
                    req = enc(req)       # girdi çağrıdan ÖNCE sabitlenir
                else:
                    req = json.loads(json.dumps(enc(req)))
            except Skip as s:
                skip(name, str(s))
                return fn(*args, **kwargs)
            except Exception as e:
                skip(name, f"girdi hazırlanamadı {type(e).__name__}")
                return fn(*args, **kwargs)
            try:
                result = fn(*bound.args, **bound.kwargs)
            except Exception as e:
                try:
                    compare(name, enc(req), False, repr(e))
                except Skip as s:
                    skip(name, str(s))
                raise
            try:
                value = enc(post(result, bound.arguments) if post else result)
                if name == "excluded_keys":
                    value = sorted(value)
                compare(name, enc(req), True, value)
            except Skip as s:
                skip(name, str(s))
            return result
        finally:
            _local.depth = depth

    wrapper.__wrapped__ = fn
    wrapper.__doc__ = fn.__doc__
    return wrapper


NAMES = """is_capacity_error capacity_retry_seconds counts_as_attempt max_attempts parse_slots slug_model split_spec
excluded_keys toggle_excluded claude_catalog claude_specs claude_is_subscription targets_from_config review_title pair_key
window_seconds project_complete pool_enabled pool_focus agy_pool model_family next_review open_review_lines
backlogged_projects pool_sync build_review_prompt parse_findings dsn_passwords redact_secrets agy_allow_list agy_settings
agy_label_ok effort_for review_path draft_path partial_path error_path finding_path finding_paths draft_prompt_suffix
is_daily_limit next_utc_midnight next_utc_month_start block_until_for_limit limit_scan_texts is_short_banner
is_quota_exhausted is_usage_limit reset_at reset_seconds quota_block_until set_block parse_copilot_entries
reconcile_copilot_blocks parse_agy_entries parse_agy_usage agy_pool_blocked_until reconcile_agy_blocks blocked_modes
load_pool save_pool migrate_r10_sub load_history save_history update_pair load_findings save_findings finding_key
add_findings scan_verdicts text_hash reviewer_slug_of apply_verdicts requeue_stale_verify usage_summary model_health
health_digest duration_summary build_verify_message build_self_verify_prompt mark_verify_sent decide_finding is_decision
where_text where_relpath has_quoted_names stale_reason_text stale_reason changed_after_review _worktree_main row_in_repo
export_root export_lines appended_export report_incomplete report_bodyless anthropic_price usage_cost_usd
anthropic_spent_usd register_lens lenses""".split()

_wrappers = {}
for _n in NAMES:
    _orig[_n] = rv.__dict__[_n]
for _n in NAMES:
    if _n in ("register_lens", "lenses"):
        continue
    _wrappers[_n] = wrap(_n, _orig[_n])
    setattr(rv, _n, _wrappers[_n])


def lens_state():
    """Rust kaydını Python'un şu anki mercek tablosuna eşitler (testler genel tabloyu değiştirip geri alıyor)."""
    ask({"fn": "reset_lenses"})
    for n in rv.LENSES:
        if n != "dry":
            ask({"fn": "register_lens", "name": n, "tr": rv._LENS_TEXT[(n, "tr")], "en": rv._LENS_TEXT[(n, "en")],
                 "format_tr": rv._LENS_FORMAT_EXTRA.get((n, "tr"), ""), "format_en": rv._LENS_FORMAT_EXTRA.get((n, "en"), "")})


def _register(name, tr, en, format_tr="", format_en=""):
    lens_state()
    req = {"name": name, "tr": tr, "en": en, "format_tr": format_tr, "format_en": format_en}
    if not all(isinstance(v, str) for v in req.values()):
        skip("register_lens", "dize olmayan girdi (Rust tip sistemi)")
        return _orig["register_lens"](name, tr, en, format_tr, format_en)
    try:
        _orig["register_lens"](name, tr, en, format_tr, format_en)
    except Exception as e:
        compare("register_lens", req, False, repr(e))
        raise
    compare("register_lens", req, True, None)


def _lenses():
    out = _orig["lenses"]()
    lens_state()
    compare("lenses", {}, True, list(out))
    return out


def _prompt(proj, cwd, lang="tr", lens=""):
    lens_state()
    return _wrappers_prompt(proj, cwd, lang, lens)


_wrappers_prompt = _wrappers["build_review_prompt"]
_wrappers.update(register_lens=_register, lenses=_lenses, build_review_prompt=_prompt)
rv.register_lens, rv.lenses, rv.build_review_prompt = _register, _lenses, _prompt


def check_collapse(text):
    compare("collapse_ws", {"text": text}, True, collapse_ws(text))


def check_target(t):
    compare("target_props", {"t": enc(t)}, True, [t.pslug, t.key, t.spec])


def write_report():
    with open(os.environ["COPS_REV_PARITY_REPORT"], "w", encoding="utf-8") as f:
        json.dump({"calls": _calls, "skipped": _skipped, "mismatches": _mismatches, "wrapped": NAMES,
                   "by_test": {k: sorted(v) for k, v in sorted(_by_test.items())}}, f, ensure_ascii=False, indent=1)
