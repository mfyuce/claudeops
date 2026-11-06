"""TBD#163 (c): model/mod sağlığı (limit koşuları sayılmaz), sahip onaylı çıkarma (`review_excluded`). Gerçek koşu/ağ YOK."""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import review as rv, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 10_000_000.0


def run(target, status, age_days=1.0, proj="p"):
    return {"pair": f"{proj}|{target}", "status": status, "at": NOW - age_days * 86400}


class TestHealth(unittest.TestCase):
    def test_limit_runs_do_not_count_and_candidates_need_min_runs(self):
        runs = [run("evren/a", "error")] * 5 + [run("evren/a", "limit")] * 20 + [run("evren/b", "error")] * 4 \
            + [run("evren/c", "done")] * 3 + [run("evren/c", "error")] * 2
        rows = {r["target"]: r for r in rv.model_health({"runs": runs}, NOW)}
        self.assertEqual(rows["evren/a"]["runs"], 5)           # limit sayılmadı
        self.assertTrue(rows["evren/a"]["candidate"])
        self.assertFalse(rows["evren/b"]["candidate"])          # 4 koşu < 5
        self.assertFalse(rows["evren/c"]["candidate"])          # oran 0.6
        self.assertEqual(rv.model_health({"runs": runs}, NOW)[0]["target"], "evren/a")   # en kötü önce

    def test_old_runs_are_outside_the_window(self):
        rows = rv.model_health({"runs": [run("evren/a", "error", age_days=9)] * 6}, NOW)
        self.assertEqual(rows, [])

    def test_digest_lists_only_non_excluded_candidates(self):
        rows = rv.model_health({"runs": [run("evren/a", "error")] * 5 + [run("evren/b", "error")] * 5}, NOW)
        d = rv.health_digest(rows, ["evren/b"])
        self.assertIn("evren/a", d)
        self.assertNotIn("evren/b:", d)
        self.assertEqual(rv.health_digest(rows, ["evren/a", "evren/b"]), "")


class TestExclusion(unittest.TestCase):
    def test_toggle_and_targets_filter(self):
        self.assertEqual(rv.toggle_excluded("", "evren/a", True), "evren/a")
        self.assertEqual(rv.toggle_excluded("evren/a", "evren/a", True), "evren/a")
        self.assertEqual(rv.toggle_excluded("evren/a,evren/b", "evren/a", False), "evren/b")
        cfg = NS(review_agy_models="", review_evren_models="", review_excluded="evren/a")
        keys = [t.key for t in rv.targets_from_config(cfg, [], ["a", "b"])]
        self.assertEqual(keys, ["evren/b"])


class TestHttp(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        self.addCleanup(ws._reset_contexts)

    def test_human_only_and_validation(self):
        r = ws.http_review_exclude({"actor": "brain", "target": "evren/a"}, "reviewer")
        self.assertFalse(r["ok"])
        with mock.patch.object(ws, "_reviewer_cfg", lambda sid: (NS(review_excluded=""), None)):
            self.assertFalse(ws.http_review_exclude({"target": "yok"}, "reviewer")["ok"])
            self.assertFalse(ws.http_review_exclude({"target": "evren/a", "action": "zap"}, "reviewer")["ok"])


if __name__ == "__main__":
    unittest.main()
