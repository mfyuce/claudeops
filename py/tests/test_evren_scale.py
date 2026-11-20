"""Evren yuva ölçekleyici (evren_scale + web_review._slots_for/_take_slot). Ağ YOK: fetch enjekte edilir."""
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
from claudeops import evren_scale as es  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

T0 = 1_000_000.0
SNAP = {"concurrency_limit": 8, "concurrent_requests": 2, "daily_remaining_tokens": 9_000_000, "daily_limit_tokens": 15_000_000}


class Compute(unittest.TestCase):
    def setUp(self):
        es.reset_for_tests()

    def test_total_is_account_limit_minus_others(self):
        n, why = es.compute_slots(SNAP, manual=1, running=2, now=T0)       # concurrent 2 hepsi bizim: başkası 0
        self.assertEqual(n, 8)
        n, _ = es.compute_slots(dict(SNAP, concurrent_requests=7), manual=1, running=1, now=T0)   # başkaları 6
        self.assertEqual(n, 2)

    def test_config_max_caps(self):
        self.assertEqual(es.compute_slots(SNAP, 1, 0, cfg_max=4, now=T0)[0], 4)

    def test_daily_low_and_stop(self):
        self.assertEqual(es.compute_slots(dict(SNAP, daily_remaining_tokens=1_000_000), 1, 0, now=T0)[0], 1)
        self.assertEqual(es.compute_slots(dict(SNAP, daily_remaining_tokens=100_000), 1, 0, now=T0)[0], 0)

    def test_unreadable_quota_falls_back_to_manual(self):
        n, why = es.compute_slots(None, manual=4, running=0, now=T0)
        self.assertEqual(n, 4)
        self.assertIn("elle", why)

    def test_backoff_halves_then_recovers(self):
        es.note_capacity_error(T0)
        self.assertEqual(es.compute_slots(SNAP, 1, 2, now=T0 + 1)[0], 4)
        es.note_capacity_error(T0 + 2)
        self.assertEqual(es.compute_slots(SNAP, 1, 2, now=T0 + 3)[0], 2)
        self.assertEqual(es.compute_slots(SNAP, 1, 2, now=T0 + es.BACKOFF_SECS + 10)[0], 8)    # 10 dk sessiz: toparlandı
        self.assertEqual(es.compute_slots(None, 4, 0, now=T0 + 3)[0], 1)                      # kota yokken de geri çekilir (min 1)

    def test_backoff_does_not_open_slot_when_account_full(self):
        es.note_capacity_error(T0)
        full = dict(SNAP, concurrent_requests=SNAP["concurrency_limit"])
        self.assertEqual(es.compute_slots(full, 1, 0, now=T0 + 1)[0], 0)

    def test_capacity_text_detection(self):
        self.assertTrue(es.note_if_capacity('HTTP 503 {"error":"model_capacity_exhausted"}', T0))
        self.assertTrue(es.note_if_capacity("429 Too Many Requests", T0 + 700))
        self.assertFalse(es.note_if_capacity("all good", T0))
        self.assertEqual(es.view(T0 + 701)["capacity_errors"], 2)

    def test_fair_share(self):
        self.assertEqual(es.model_cap("glm-5.3"), 2)
        self.assertEqual(es.model_cap("gemma-4-31b"), 2)
        self.assertGreater(es.model_cap("qwen3-coder"), 100)

    def test_snapshot_cache_and_failure_cache(self):
        calls = []
        def ok():
            calls.append(1); return dict(SNAP)
        es.snapshot(lambda: "k", T0, ok); es.snapshot(lambda: "k", T0 + 30, ok)
        self.assertEqual(len(calls), 1)
        es.snapshot(lambda: "k", T0 + 61, ok)
        self.assertEqual(len(calls), 2)
        es.reset_for_tests(); fails = []
        def bad():
            fails.append(1); return None
        self.assertIsNone(es.snapshot(lambda: "k", T0, bad)); self.assertIsNone(es.snapshot(lambda: "k", T0 + 10, bad))
        self.assertEqual(len(fails), 1)          # başarısızlık 30 sn önbellekli


class Wired(unittest.TestCase):
    def setUp(self):
        es.reset_for_tests()
        wr._ACTIVE.clear()

    def tearDown(self):
        wr._ACTIVE.clear()

    def cfg(self, **kw):
        return types.SimpleNamespace(review_slots="agy=2,evren=1", **kw)

    def test_autoscale_off_or_absent_keeps_manual(self):
        self.assertEqual(wr._slots_for(self.cfg())["evren"], 1)
        self.assertEqual(wr._slots_for(self.cfg(review_evren_autoscale="off"))["evren"], 1)

    def test_autoscale_on_overrides_evren_only(self):
        with mock.patch.object(es, "snapshot", return_value=dict(SNAP)):
            s = wr._slots_for(self.cfg(review_evren_autoscale="on"))
        self.assertEqual((s["evren"], s["agy"]), (6, 2))      # SNAP: 2 eşzamanlı istek bizim değil -> 8-2

    def test_zero_evren_is_owner_off_and_empty_spec_stays_single_job(self):
        with mock.patch.object(es, "snapshot", return_value=dict(SNAP)):
            self.assertEqual(wr._slots_for(types.SimpleNamespace(review_slots="evren=0", review_evren_autoscale="on"))["evren"], 0)
            self.assertEqual(wr._slots_for(types.SimpleNamespace(review_slots="", review_evren_autoscale="on")), {})

    def test_scaler_error_falls_back(self):
        with mock.patch.object(es, "snapshot", side_effect=RuntimeError("x")):
            self.assertEqual(wr._slots_for(self.cfg(review_evren_autoscale="on"))["evren"], 1)

    def test_model_slug_and_fair_share_in_take_slot(self):
        self.assertEqual(wr._evren_model_slug("proj|evren/glm-5.3@medium"), "glm-5.3")
        slots = {"evren": 8}
        self.assertGreaterEqual(wr._take_slot("p1|evren/glm-5.3@medium", "p1", "evren", slots)[0], 0)
        self.assertGreaterEqual(wr._take_slot("p2|evren/glm-5.3@high", "p2", "evren", slots)[0], 0)
        idx, why = wr._take_slot("p3|evren/glm-5.3@medium", "p3", "evren", slots)
        self.assertEqual(idx, -1)
        self.assertIn("adil pay", why)
        self.assertGreaterEqual(wr._take_slot("p3|evren/qwen3-coder@medium", "p3", "evren", slots)[0], 0)     # başka model serbest


if __name__ == "__main__":
    unittest.main()
