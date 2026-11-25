"""Python `authz` ile Rust (`cops-auth` eylem tablosu, `cops-proxy` kaynak çıkarımı) eşitlik vektörleri.
Dosya Python davranışını izler; Python değişirse AYNI commit'te yenile: `UPDATE_AUTHZ_VECTORS=1 python3 -m unittest discover -s py/tests -p test_authz_vectors.py`.
`rust_rejects` işaretli girdileri Rust bilerek REDDEDER (daha sıkı: metin olmayan dolu kaynak alanı, nesne olmayan gövde)."""
import json
import os
import sys
import unittest
from urllib.parse import parse_qs
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from claudeops import authz, ucli_approval  # noqa: E402

PATH = os.path.join(HERE, "..", "..", "rust", "crates", "cops-auth", "tests", "data", "authz_vectors.json")
APPROVALS = {"k1": "s-onay", "bos": ""}      # run_key -> oturum

EXTRA_PATHS = ["/", "", "//", "/x", "/api", "/api/", "/api/brand-new", "/API/status", "/api/ucli/approvals", "/api/ucli/approvals/",
               "/api/ucli/checks-modex", "/api/session", "/api/session/", "/assets/a.js", "/readfile/x", "/v1", "/v1x", "/q", "/qx",
               "/ws", "/wsx", "/ws/", "/ws/term/", "/api/term", "/api/files", "/api/filesx", "/api/enterprise/x", "/api/%73tatus"]

# (yol, ham sorgu, gövde metni | None)
RES = [
    ("/api/status", "", None), ("/api/start", "name=a", None), ("/api/start", "name=a&host=h1", None),
    ("/api/start", "name=a&name=b", None), ("/api/start", "name=&name=b", None), ("/api/start", "name", None),
    ("/api/start", "n%61me=a+b%20c&host=h%C3%BC", None), ("/api/start", "name=%zz%4", None), ("/api/start", "name=%FF", None),
    ("/api/start", "name=+++", None), ("/api/start", "host=h1", None), ("/api/start", "name=a;host=b", None),
    ("/api/start", "name=a=b&&=x", None), ("/api/start", "name=%1Ca%1F", None), ("/api/start", "name=%C2%A0a%E2%80%83", None),
    ("/api/start", "name=q", '{"name": " g ", "host": "h2"}'), ("/api/start", "name=q&host=qh", '{"name": "", "host": ""}'),
    ("/api/start", "name=q", '{"name": null}'), ("/api/start", "name=q", '{"name": 0}'), ("/api/start", "name=q", '{"name": false}'),
    ("/api/start", "name=q", '{"name": []}'), ("/api/start", "name=q", '{"name": {}}'), ("/api/start", "name=q", '{"name": 0.0}'),
    ("/api/start", "", '{"name": "a", "name": "b"}'), ("/api/start", "", '{}'),
    ("/v1/chat/completions", "", '{"model": "m1"}'), ("/v1/chat/completions", "name=m1", '{"model": "m1"}'),
    ("/v1/chat/completions", "host=h", '{"model": "m1", "name": "m1"}'), ("/v1/models", "model=q", None),
    ("/api/start", "", '{"model": "m1"}'),
    ("/api/orch/run", "", '{"participants": [{"host": "h", "name": "a"}, {"name": "b"}, 5, "c", {"host": "h", "name": "a"}]}'),
    ("/api/orch/run", "host=h", '{"participants": "a", "names": "b"}'),
    ("/api/handover", "host=h&names=a,b&names=c", '{"names": ["d", " a ", "", null]}'),
    ("/api/handover", "names=,,%2C", None), ("/api/handover", "", '{"host": "h", "names": ["a", "a"]}'),
    ("/api/steward/status", "", None), ("/api/steward/status", "steward=bo&name=proje", None),
    ("/api/steward/status", "steward=bo", '{"steward": "ayse", "name": "p"}'), ("/api/steward/status", "", '{"steward": "  "}'),
    ("/api/steward/status", "steward=+", None), ("/api/stewardx", "name=a", None),
    ("/api/ucli/approvals", "run_key=k1", None), ("/api/ucli/approvals", "run_key=yok", None),
    ("/api/ucli/approvals", "", '{"run_key": "k1", "name": "baska"}'), ("/api/ucli/approvals", "run_key=bos", None),
    ("/api/ucli/approvals", "", None),
]
RUST_REJECTS = [
    ("/api/start", "", '{"name": 5}'), ("/api/start", "", '{"name": true}'), ("/api/start", "", '{"name": ["a"]}'),
    ("/api/start", "", '{"name": "a", "host": 1}'), ("/api/orch/run", "", '{"participants": [{"name": 7}]}'),
    ("/api/orch/run", "", '{"participants": [{"host": ["h"], "name": "a"}]}'), ("/api/handover", "", '{"names": [1]}'),
    ("/v1/chat/completions", "", '{"model": {"a": 1}}'), ("/api/steward/status", "", '{"steward": 3}'),
    ("/api/ucli/approvals", "", '{"run_key": 1}'), ("/api/start", "", '[1]'), ("/api/start", "", 'null'),
    ("/api/start", "", '{bozuk'), ("/api/start", "", '{"name": NaN}'),
]


def _paths():
    out = list(EXTRA_PATHS)
    for prefix, _ in authz._ACTION_TABLE:
        base = prefix.rstrip("/")
        out += [prefix, base, base + "x", prefix + "x", base + "/alt"]
    return sorted(set(out))


def build():
    actions = [[m, p, authz.action_for(m, p)] for p in _paths() for m in ("GET", "POST", "get")]
    res = []
    with mock.patch.object(ucli_approval, "get", lambda k: {"session": APPROVALS[k]} if k in APPROVALS else None):
        for path, query, body in RES:
            data = json.loads(body) if body is not None else None
            got = authz.resources_from(path, parse_qs(query), data)
            res.append({"path": path, "query": query, "body": body,
                        "expect": [{"kind": r.kind, "host": r.host, "name": r.name, "cwd": r.cwd, "steward": r.steward} for r in got]})
    res += [{"path": p, "query": q, "body": b, "rust_rejects": True} for p, q, b in RUST_REJECTS]
    legacy = authz.LEGACY
    return {"unmapped": authz.UNMAPPED, "table": [list(t) for t in authz._ACTION_TABLE],
            "legacy": {"uid": legacy.uid, "roles": list(legacy.roles), "kind": legacy.kind},
            "approvals": APPROVALS, "actions": actions, "resources": res}


class AuthzVectorsTest(unittest.TestCase):
    def setUp(self):
        authz.reset()                # eklenti eylem kaydı vektörlere karışmasın
        self.addCleanup(authz.reset)

    def test_vectors_match_python(self):
        text = json.dumps(build(), ensure_ascii=True, indent=1, sort_keys=True) + "\n"
        if os.environ.get("UPDATE_AUTHZ_VECTORS"):
            with open(PATH, "w", encoding="ascii") as fh:
                fh.write(text)
        with open(PATH, encoding="ascii") as fh:
            self.assertEqual(json.loads(fh.read()), json.loads(text), "authz değişti: vektörleri yenile ve Rust'ı eşitle")


if __name__ == "__main__":
    unittest.main()
