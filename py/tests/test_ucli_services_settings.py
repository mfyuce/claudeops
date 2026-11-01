"""ucli hizmet listesi TEK kaynak (settings.ucli_services): doğrulama, yerleşik yedek, modele bağlı effort. python3 tests/test_ucli_services_settings.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings as st  # noqa: E402
from claudeops import ucli_session_opts as so  # noqa: E402
from unittest import mock  # noqa: E402


def with_services(raw):
    return mock.patch.object(st, "load_settings", return_value={"ucli_services": raw})


class ServicesTests(unittest.TestCase):
    def test_defaults_when_empty(self):
        with with_services([]):
            ids = [d["id"] for d in st.ucli_services()]
        self.assertEqual(ids, ["evren", "claude", "grok", "openrouter", "groq"])

    def test_groq_label(self):
        with with_services(None):
            self.assertEqual({d["id"]: d["label"] for d in st.ucli_services()}["groq"], "Groq (groq.com)")

    def test_invalid_dropped_evren_always_present(self):
        raw = [{"id": "Bad Id", "env": "X_KEY", "endpoint": "https://a/v1"},
               {"id": "ok1", "env": "lower", "endpoint": "https://a/v1"},
               {"id": "ok2", "env": "OK2_KEY", "endpoint": "ftp://a"},
               {"id": "ok3", "env": "OK3_KEY", "endpoint": ""},
               {"id": "good", "label": "Good", "env": "GOOD_KEY", "endpoint": "https://g.example/v1/", "models": "a, b,a"}]
        with with_services(raw):
            out = st.ucli_services()
        self.assertEqual([d["id"] for d in out], ["evren", "good"])
        self.assertEqual(out[1]["models"], ["a", "b"])
        self.assertEqual(out[1]["endpoint"], "https://g.example/v1")

    def test_services_map_follows_settings(self):
        raw = [{"id": "evren", "env": "UCLI_API_KEY"}, {"id": "mine", "env": "MINE_KEY", "endpoint": "https://m/v1"}]
        with with_services(raw):
            self.assertEqual(so.services()["mine"], ("", "https://m/v1", "MINE_KEY"))
            self.assertEqual(so.validate_opts({"service": "mine"})[0], {"service": "mine"})
            self.assertTrue(so.validate_opts({"service": "claude"})[1])      # listeden çıkan hizmet seçilemez

    def test_effort_follows_model(self):
        with with_services(None):
            self.assertEqual(so.effort_levels_for("claude", "claude-haiku-5-5"), [])
            self.assertEqual(so.effort_levels_for("claude", "claude-sonnet-5-5"), ["low", "medium", "high"])
            self.assertEqual(so.effort_levels_for("claude", "claude-opus-5-5"), ["low", "medium", "high", "max"])
            self.assertIsNone(so.effort_levels_for("claude", "bilinmeyen"))
            self.assertIsNone(so.effort_levels_for("grok", "grok-4"))


if __name__ == "__main__":
    unittest.main()
