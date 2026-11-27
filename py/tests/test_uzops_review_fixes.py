"""uzops incelemesi (26 Kas) geçerli kalan bulgular: R-8 (maliyet önbelleği),
R-15 (bozuk draft.json yedeği), R-17 (claude ikili yolu)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import model_freshness, orch_store, ucli_cost  # noqa: E402


class CostCacheRace(unittest.TestCase):
    def test_invalidate_between_scan_and_read_keeps_cap_closed(self):
        class Racy(dict):
            def update(self, *a, **k):
                super().update(*a, **k)
                if self.get("usd"):      # yazım biter bitmez başka iş parçacığı invalidate() çağırıyor
                    super().update(at=0.0, usd=0.0, total=0.0, by={}, day="", rate_1h={}, rate_15m={})

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ucli_cost, "_CACHE", Racy(at=0.0, usd=0.0, day="")), \
                mock.patch.object(ucli_cost, "ucli_cost_config", lambda: {"daily_cap_usd": 5, "cache_ttl": "5m"}), \
                mock.patch.object(ucli_cost, "per_session_usd", return_value={"a": 9.0}):
            self.assertTrue(ucli_cost.cap_exceeded(base=d))


class CorruptDraft(unittest.TestCase):
    def test_corrupt_draft_is_copied_before_next_save_overwrites_it(self):
        from claudeops import statedocs
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "draft.json")
            with open(p, "w") as f:
                f.write('{"participants": [')
            with mock.patch.object(orch_store, "DRAFT_JSON", p), mock.patch.object(statedocs, "_db_ok", lambda _p: False):
                with self.assertLogs(orch_store.__name__, "WARNING"):
                    self.assertEqual(orch_store.load_draft(), [])
                orch_store.save_draft([])
            kept = [n for n in os.listdir(d) if n.startswith("draft.json.corrupt")]
            self.assertEqual(len(kept), 1, os.listdir(d))
            with open(os.path.join(d, kept[0])) as f:
                self.assertEqual(f.read(), '{"participants": [')
            self.assertEqual(os.stat(os.path.join(d, kept[0])).st_mode & 0o777, 0o600)


class ModelCheckBinary(unittest.TestCase):
    def test_uses_resolved_claude_binary(self):
        done = subprocess.CompletedProcess([], 1, stdout="")
        with mock.patch.object(model_freshness, "resolved_binary", return_value="/opt/x/claude", create=True), \
                mock.patch.object(model_freshness.subprocess, "run", return_value=done) as run:
            model_freshness._fetch_live_models()
        self.assertEqual(run.call_args[0][0][0], "/opt/x/claude")


if __name__ == "__main__":
    unittest.main()
