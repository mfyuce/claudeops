"""Panel Reviewer formu: `/api/steward/config` review_slots + agy/Evren model listeleri (metin ayarları). Gerçek oturum YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TestReviewFormConfig(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        self.addCleanup(ws._reset_contexts)

    def test_slots_normalized_and_cleared(self):
        r = ws.http_config({"key": "review_slots", "value": " AGY=2, evren=1 ,codex=0"}, sid="reviewer")
        self.assertEqual((r["ok"], r["value"]), (True, "agy=2,evren=1,codex=0"))
        self.assertTrue(ws.http_config({"key": "review_slots", "value": "off"}, sid="reviewer")["ok"])
        self.assertEqual(ws.steward_config("reviewer").review_slots, "off")
        ws.http_config({"key": "review_slots", "value": ""}, sid="reviewer")
        self.assertEqual(ws.steward_config("reviewer").review_slots, "")

    def test_slots_rejects_bad(self):
        for bad in ("agy", "foo=1", "agy=x", "agy=11", "agy=1;rm"):
            self.assertFalse(ws.http_config({"key": "review_slots", "value": bad}, sid="reviewer")["ok"], bad)

    def test_model_lists(self):
        r = ws.http_config({"key": "review_agy_models", "value": "gemini-4-argon-medium, gemini-3.8-flash-high,gemini-4-argon-medium"},
                           sid="reviewer")
        self.assertEqual(r["value"], "gemini-4-argon-medium,gemini-3.8-flash-high")
        self.assertTrue(ws.http_config({"key": "review_evren_models", "value": "glm-5.3,qwen3.8-flash-next"}, sid="reviewer")["ok"])
        self.assertFalse(ws.http_config({"key": "review_evren_models", "value": "a b"}, sid="reviewer")["ok"])
        self.assertFalse(ws.http_config({"key": "review_agy_models", "value": "x;y"}, sid="reviewer")["ok"])
        self.assertFalse(ws.http_config({"key": "review_agy_models", "value": "m", "actor": "brain"}, sid="reviewer")["ok"])


if __name__ == "__main__":
    unittest.main()
