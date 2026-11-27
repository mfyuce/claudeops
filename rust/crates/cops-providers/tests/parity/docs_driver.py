"""`tests/parity_docs.rs` koşucusu: gerçek `statedocs` + `agy_provider` üstünde tek vaka. Yalnız argümandaki GEÇİCİ durum
dizinine dokunur (ortam testte kurulur; dizin eşleşmezse hiçbir şey yapmaz).

  docs_driver.py seed|run|dump <vaka json>
"""
import json
import os
import sqlite3
import sys

mode, case = sys.argv[1], json.loads(sys.argv[2])
root = case["root"]
assert os.environ["CLAUDEOPS_DIR"] == root and os.environ["HOME"] != os.path.expanduser("~root")

from claudeops import paths, statedocs, store                     # noqa: E402
from claudeops.providers import agy_provider as agy               # noqa: E402

assert paths.CLAUDEOPS_DIR == root and agy.AGY_SIDS_JSON.startswith(root + os.sep)
FILES = {"agy_sids": agy.AGY_SIDS_JSON, "claude_models": paths.CLAUDE_MODELS_JSON}


def seed():
    if case.get("db", True):
        st = store.default_store()
        for name, body in (case.get("rows") or {}).items():
            st.set_doc(name, json.loads(body))
    for name, body in (case.get("files") or {}).items():
        if body is None:
            os.mkdir(FILES[name])
        else:
            with open(FILES[name], "w", encoding="utf-8") as f:
                f.write(body)


def run():
    out = []
    for op in case["ops"]:
        try:
            if op[0] == "load":
                out.append(agy._load_agy_sids())
            elif op[0] == "remember":
                out.append(agy._remember_agy_sid(op[1], op[2]))
            elif op[0] == "claude":
                out.append(statedocs.read_json("claude_models", paths.CLAUDE_MODELS_JSON, {}))
            else:                                                   # elle düzenleme (dosya imzası değişsin)
                with open(FILES[op[1]], "w", encoding="utf-8") as f:
                    f.write(op[2])
                out.append(None)
        except Exception as e:
            out.append({"exception": type(e).__name__})
    return out


def _clean(v):
    """Eşlenmemiş vekil Rust tarafında U+FFFD olarak okunur; çıktı da öyle yazılır."""
    if isinstance(v, str):
        return "".join("\ufffd" if "\ud800" <= c <= "\udfff" else c for c in v)
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {_clean(k): _clean(x) for k, x in v.items()}
    return v


def _event(e):
    text = e["event"]
    if text.startswith("statedocs ") and ("-> dosya" in text or text.startswith(("statedocs write ", "statedocs mirror "))):
        text = text.split(":", 1)[0]                                 # istisna metni dile özgü
    return [text, e.get("name")]


def dump():
    res = {"files": {}, "rows": {}, "diag": [], "mirror": []}
    for name, path in FILES.items():
        if os.path.isdir(path):
            res["files"][name] = "<dizin>"
        elif os.path.exists(path):
            with open(path, "rb") as f:
                res["files"][name] = f.read().decode("utf-8", "replace")
    db = os.path.join(root, "claudeops.db")
    res["has_db"] = os.path.exists(db)
    if res["has_db"]:
        c = sqlite3.connect(db)
        for name, body, version in c.execute("SELECT name, body, version FROM docs ORDER BY name"):
            res["rows"][name] = [body, version]
        res["mirror"] = [_event(json.loads(b)) for (b,) in c.execute("SELECT body FROM log WHERE stream='diag' ORDER BY id")]
        c.close()
    log = os.path.join(root, "diag.log")
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            res["diag"] = [_event(json.loads(ln)) for ln in f if ln.strip()]
    return res


if mode == "seed":
    seed()
    print(json.dumps({}))
elif mode == "run":
    seed()
    returns = run()
    print(json.dumps(_clean({"returns": returns, "state": dump()})))
else:
    print(json.dumps(dump()))
