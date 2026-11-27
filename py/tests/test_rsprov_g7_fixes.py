"""rs/prov G7 (model kaynakları) Python hataları: iki tarafta düzeldi (Rust `cops-providers`, `parity_model_sources`).

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_g7_fixes.py
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_session_opts as uso  # noqa: E402
from claudeops.providers import agy_provider as ap  # noqa: E402
from claudeops.providers import codex_provider as xp  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BootTest(unittest.TestCase):
    """Aday 1: `_cache_ts = 0.0` + `time.monotonic()` açılıştan sonraki ilk 300 sn hiç çekmiyordu."""

    def test_agy_fetches_right_after_boot(self):
        out = types.SimpleNamespace(stdout="Fetching...\nm1\tM1\n")
        with mock.patch.object(ap.time, "monotonic", lambda: 5.0), \
                mock.patch.object(ap.subprocess, "run", lambda *a, **k: out), \
                mock.patch.object(ap, "resolved_binary", lambda n: n):
            self.assertEqual(ap.AgyProvider().model_choices(), ["m1"])

    def test_codex_reads_right_after_boot(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "models_cache.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"models": [{"slug": "g1", "visibility": "list"}]}, f)
            with mock.patch.object(xp.time, "monotonic", lambda: 5.0), mock.patch.object(xp, "MODELS_CACHE", p):
                self.assertEqual(xp.CodexProvider().model_choices(), ["g1"])


class CodexDocTest(unittest.TestCase):
    def test_non_utf8_document_keeps_the_old_list(self):                  # aday 2
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "models_cache.json")
            with open(p, "wb") as f:
                f.write(b'{"models": \xff}')
            with mock.patch.object(xp, "MODELS_CACHE", p):
                prov = xp.CodexProvider()
                self.assertEqual(prov.model_choices(), xp.FALLBACK_MODELS)
                self.assertIsNone(prov.model_effort_levels("x"))


class UcliLiveTest(unittest.TestCase):
    def fetch(self, payload):
        with mock.patch.object(up, "byok_env_for", lambda cli: {"UCLI_API_KEY": "k"}), \
                mock.patch.object(up, "_open_no_redirect", lambda *a, **k: _R(payload)), \
                mock.patch.object(up, "diag_log", lambda ev, **kw: self.diags.append((ev, kw))):
            return up._fetch_live_models()

    def setUp(self):
        self.diags = []
        self.addCleanup(setattr, up, "_LIVE_CAPS", {})

    def test_deep_body_is_a_failed_fetch(self):                            # aday 3
        self.assertIsNone(self.fetch(b"[" * 100000))
        self.assertEqual(self.diags, [("models_fetch_failed", {"source": "ucli"})])

    def test_non_text_ids_are_skipped(self):                               # aday 8 + liste kimlik TypeError
        body = json.dumps({"data": [{"id": 5, "task": "chat"}, {"id": ["x"], "task": "chat", "capabilities": {}},
                                    {"id": "g", "task": "chat"}]}).encode()
        self.assertEqual(self.fetch(body), ["g"])
        self.assertEqual(self.diags, [])


class ServiceModelsTest(unittest.TestCase):
    def setUp(self):
        uso._MODELS_CACHE.clear()
        self.addCleanup(uso._MODELS_CACHE.clear)
        self.diags = []
        p = mock.patch("claudeops.diaglog.diag_log", lambda ev, **kw: self.diags.append((ev, kw)))
        p.start()
        self.addCleanup(p.stop)
        self.svc = next(s for s in ("grok", "openrouter") if s in uso.services())

    def get(self, opener, t, key="K"):
        return uso.service_models(self.svc, key, opener=opener, now=lambda: t)

    def test_failed_refresh_keeps_the_good_list(self):                    # aday 4
        ok = lambda req, timeout=0: _R(json.dumps({"data": [{"id": "m1"}]}).encode())   # noqa: E731

        def bad(req, timeout=0):
            raise OSError("ağ yok")
        self.assertEqual(self.get(ok, 0.0), ["m1"])
        self.assertEqual(self.get(bad, 90000.0), ["m1"])
        self.assertEqual(self.diags, [("models_fetch_failed", {"source": self.svc})])
        calls = []

        def counted(req, timeout=0):
            calls.append(1)
            raise OSError("ağ yok")
        self.assertEqual(self.get(counted, 90030.0), ["m1"])          # 60 sn dolmadan yeniden denenmez
        self.assertEqual(calls, [])
        self.assertEqual(self.get(counted, 90061.0), ["m1"])
        self.assertEqual(calls, [1])

    def test_unparsable_body_is_a_failure_not_an_empty_list(self):
        ok = lambda req, timeout=0: _R(json.dumps({"data": [{"id": "m1"}]}).encode())   # noqa: E731
        self.assertEqual(self.get(ok, 0.0), ["m1"])
        for body in (b"{bozuk", b'{"data": 5}'):
            with self.subTest(body=body):
                self.assertEqual(self.get(lambda req, timeout=0: _R(body), 90000.0 + len(self.diags) * 100), ["m1"])

    def test_cache_follows_the_key(self):                                 # aday 5
        seen = []

        def opener(req, timeout=0):
            seen.append(req.get_header("Authorization") or req.get_header("X-api-key"))
            return _R(json.dumps({"data": [{"id": "m-" + str(len(seen))}]}).encode())
        self.assertEqual(self.get(opener, 0.0, "K1"), ["m-1"])
        self.assertEqual(self.get(opener, 10.0, "K1"), ["m-1"])
        self.assertEqual(self.get(opener, 20.0, "K2"), ["m-2"])
        self.assertEqual(len(seen), 2)
        self.assertFalse(any("K1" in k or "K2" in k for k in uso._MODELS_CACHE))     # anahtar saklanmaz


class AgyColdTest(unittest.TestCase):
    def test_second_caller_waits_for_the_cold_fetch(self):                # aday 7
        started, release = threading.Event(), threading.Event()

        def slow_run(*a, **k):
            started.set()
            release.wait(5)
            return types.SimpleNamespace(stdout="m1\tM1\n")
        prov = ap.AgyProvider()
        got = {}
        with mock.patch.object(ap.subprocess, "run", slow_run), mock.patch.object(ap, "resolved_binary", lambda n: n):
            t1 = threading.Thread(target=lambda: got.setdefault("a", prov.model_choices()))
            t1.start()
            self.assertTrue(started.wait(5))
            t2 = threading.Thread(target=lambda: got.setdefault("b", prov.model_choices()))
            t2.start()
            time.sleep(0.2)
            self.assertNotIn("b", got)          # boş listeyle dönmedi, bekliyor
            release.set()
            t1.join(5)
            t2.join(5)
        self.assertEqual(got, {"a": ["m1"], "b": ["m1"]})

    def test_failed_fetch_is_logged(self):
        def boom(*a, **k):
            raise FileNotFoundError("agy")
        diags = []
        with mock.patch.object(ap.subprocess, "run", boom), mock.patch.object(ap, "resolved_binary", lambda n: n), \
                mock.patch.object(ap, "diag_log", lambda ev, **kw: diags.append((ev, kw))):
            self.assertEqual(ap.AgyProvider().model_choices(), [])
        self.assertEqual(diags, [("models_fetch_failed", {"source": "agy"})])


if __name__ == "__main__":
    unittest.main()
