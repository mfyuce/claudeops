"""Panel: beyin modeli/effort ayarı (`/api/steward/config` brain_model/brain_effort). Yalnız insan; değer doğrulanır. Gerçek oturum YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TestBrainModelConfig(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        self.addCleanup(ws._reset_contexts)

    def test_set_and_clear(self):
        r = ws.http_config({"key": "brain_model", "value": "claude-sonnet-5-5"})
        self.assertEqual((r["ok"], r["value"]), (True, "claude-sonnet-5-5"))
        self.assertTrue(ws.http_config({"key": "brain_effort", "value": "High"})["ok"])
        self.assertEqual(ws.steward_config("default").brain_effort, "high")
        ws.http_config({"key": "brain_model", "value": ""})        # boş = otomatik
        self.assertEqual(ws.steward_config("default").brain_model, "")

    def test_rejects_bad_values_and_brain_actor(self):
        self.assertFalse(ws.http_config({"key": "brain_model", "value": "x; rm -rf /"})["ok"])
        self.assertFalse(ws.http_config({"key": "brain_effort", "value": "ultra"})["ok"])
        self.assertFalse(ws.http_config({"key": "brain_model", "value": "m", "actor": "brain"})["ok"])


if __name__ == "__main__":
    unittest.main()
