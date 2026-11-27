#!/usr/bin/env python3
"""Altın tick girdileri: `py/tests/test_steward_multi.py`deki senaryo (`run_golden`: 3 yapılandırma x 3 tick zinciri)
girdileri `fixtures/golden_tick_input.json`a yazılır; beklenen çıktı Rust testinde doğrudan `py/tests/steward_golden_tick.json`
dosyasından okunur (girdi testin KENDİ üreticilerinden: elle kopya yok). Kullanım: `python3 -I parity/golden.py [--check]`."""
import dataclasses, json, os, site, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
env.isolate()
sys.path.insert(0, os.path.join(env.PY, "tests"))
if sys.flags.isolated:     # `-I` kullanıcı paketlerini dışlar; test kitaplığının bağımlılıkları (websockets) oradadır
    at = next((i for i, p in enumerate(sys.path) if p.endswith("-packages")), len(sys.path))
    sys.path.insert(at, site.getusersitepackages())
CHECK = "--check" in sys.argv
sys.argv = ["python3 -m unittest"]                          # claudeops'un test altı korumaları devrede olsun
from claudeops import steward as sw  # noqa: E402
import test_steward_multi as tm  # noqa: E402


def enc(v):
    if dataclasses.is_dataclass(v):
        return {f.name: enc(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(enc(x) for x in v)
    return v


chains = []
for ck in tm.GOLDEN_CFGS:
    cfg = tm._cfg(**ck)
    steps = []
    for step in range(3):
        projects = tm._golden_projects()
        steps.append({"views": enc(tm._golden_views(step)), "projects": enc(projects), "now": tm.T0 + step * 1200,
                      "questions": enc(tm._golden_questions()), "ideas": enc(tm._golden_ideas()),
                      "world": enc(tm._default_world(projects, cfg))})
    chains.append({"cfg": enc(cfg), "state": {"ho_pending": {"oldgone": tm.T0 - 99999}}, "steps": steps})
out = {"projects_by_sid": {"default": list(tm._golden_projects())}, "chains": chains}
path = os.path.join(env.CRATE, "fixtures", "golden_tick_input.json")
text = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
if CHECK:
    cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if cur != text:
        print("fixtures/golden_tick_input.json güncel değil")
        sys.exit(1)
    print("altın girdi güncel")
else:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("yazıldı:", path)
