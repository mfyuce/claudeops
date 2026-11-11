"""claude_models belgesi DB-doğruluk kaynağı (SQL göçü Adım B): yazım DB+ayna, db kipinde okuma DB'den, dosya bozulsa/yok olsa DB kazanır,
model_choices yedeği (hardcoded) korunur."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import model_freshness as mf, statedocs as sd, store as S  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402


class ClaudeModelsStoreTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-cm-")
        self.p = os.path.join(self.d, "claude_models.json")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.ps = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                   mock.patch.object(mf, "CLAUDE_MODELS_JSON", self.p), mock.patch.object(cp, "CLAUDE_MODELS_JSON", self.p),
                   mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db", "CLAUDEOPS_DIAG_LOG": os.path.join(self.d, "diag.log")})]
        [p.start() for p in self.ps]
        sd._SYNCED.clear()
        sd._DIRTY.clear()

    def tearDown(self):
        [p.stop() for p in self.ps]
        self.st.close()

    def test_is_db_ready(self):
        self.assertTrue(sd.db_ready("claude_models"))

    def test_write_goes_to_db_and_mirror_and_reads_from_db(self):
        sd.write_json("claude_models", self.p, {"checked_at": "2026-11-12T00:00:00", "models": {"claude-sonnet-5-5": "enabled", "claude-x-1": "disabled"}})
        self.assertEqual(self.st.get_doc("claude_models")["models"]["claude-sonnet-5-5"], "enabled")
        self.assertTrue(os.path.exists(self.p))                                  # ayna
        self.assertEqual(cp.ClaudeProvider().model_choices(), ["claude-sonnet-5-5"])
        self.assertEqual(mf._read_state()["checked_at"], "2026-11-12T00:00:00")

    def test_db_wins_over_corrupt_or_missing_file(self):
        sd.write_json("claude_models", self.p, {"models": {"claude-opus-5-5": "enabled"}})
        with open(self.p, "w") as f:
            f.write("{bozuk")
        self.assertEqual(cp.ClaudeProvider().model_choices(), ["claude-opus-5-5"])    # db kipinde dosyaya bakılmaz
        os.remove(self.p)
        self.assertEqual(cp.ClaudeProvider().model_choices(), ["claude-opus-5-5"])

    def test_fallback_to_hardcoded_when_empty(self):
        self.assertEqual(cp.ClaudeProvider().model_choices(), cp.MODEL_CHOICES)
        self.assertEqual(mf._read_state(), {})
        sd.write_json("claude_models", self.p, {"models": {"claude-x": "disabled"}})
        self.assertEqual(cp.ClaudeProvider().model_choices(), cp.MODEL_CHOICES)


if __name__ == "__main__":
    unittest.main()
