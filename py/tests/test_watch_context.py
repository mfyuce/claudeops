import unittest

from claudeops.commands import watch


class ContextTextTests(unittest.TestCase):
    def test_with_threshold(self):
        d = {"sessions": {"a": {"context_tokens": 120000, "context_warn": 300000}}}
        self.assertEqual(watch.context_text_from_facts(d, "a"), "ctx 120K/300K %40")

    def test_without_threshold(self):
        d = {"sessions": {"a": {"context_tokens": 120000}}}
        self.assertEqual(watch.context_text_from_facts(d, "a"), "ctx 120K")

    def test_unknown(self):
        for d in ({}, None, {"sessions": {"a": {"context_tokens": None}}}, {"sessions": {}}):
            self.assertEqual(watch.context_text_from_facts(d, "a"), "")

    def test_caps_at_100(self):
        d = {"sessions": {"a": {"context_tokens": 400000, "context_warn": 300000}}}
        self.assertTrue(watch.context_text_from_facts(d, "a").endswith("%100"))


if __name__ == "__main__":
    unittest.main()


class ContextClientKeepsLastGoodTest(unittest.TestCase):
    """Uzak pencerelerde rozet kaybolup duruyordu: boş/başarısız okuma son iyi değeri silmemeli."""

    def _client(self, replies, now):
        import json
        from types import SimpleNamespace as NS
        viewer = NS(context_text="")

        class Resp:
            def __init__(self, d): self.d = d
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.d).encode()

        def urlopen(req, timeout=0):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return Resp(r)

        c = watch.ContextClient(1, "h", "a", viewer, read_token=lambda: "t", urlopen=urlopen, clock=lambda: now[0])
        return c, viewer

    GOOD = {"sessions": {"a": {"running": True, "context_tokens": 120000, "context_warn": 300000}}}

    def test_failure_and_null_keep_last_value_until_stale(self):
        now = [0.0]
        c, v = self._client([self.GOOD, {"ok": False, "error": "h unreachable"}, OSError("x"),
                             {"sessions": {"a": {"running": True, "context_tokens": None}}}], now)
        c.fetch_once()
        self.assertEqual(v.context_text, "ctx 120K/300K %40")
        for t in (20.0, 40.0, 60.0):
            now[0] = t
            c.fetch_once()
            self.assertEqual(v.context_text, "ctx 120K/300K %40", t)

    def test_cleared_when_stale_or_session_closed(self):
        now = [0.0]
        c, v = self._client([self.GOOD, {"ok": False}, self.GOOD, {"sessions": {"a": {"running": False}}}], now)
        c.fetch_once()
        now[0] = watch.ContextClient.STALE_SECONDS + 1
        c.fetch_once()
        self.assertEqual(v.context_text, "")           # uzun süredir okunamıyor: silinir
        c.fetch_once()
        self.assertNotEqual(v.context_text, "")        # tekrar iyi veri: geri gelir
        c.fetch_once()
        self.assertEqual(v.context_text, "")           # oturum kapandı: silinir
