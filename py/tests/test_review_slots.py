"""reviewer mod başına eşzamanlı koşu yuvaları (`review_slots`): yuva sayıları, aynı-proje yasağı, varsayılan tek iş,
uzak proje yalnız evren, kota engelli hedefin atlanması, 0 yuvalı mod, boşalan yuvanın dolması. Sahte run_job (gerçek
Popen/agy/Evren YOK), `settings.SETTINGS_JSON` geçici dosyada (`_Engine`)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_web_review_tick import _Tick, NOW, T1, T2  # noqa: E402
from claudeops import review as rv, settings, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

T3 = rv.ReviewTarget("agy", "m3", "m3")
CX = rv.ReviewTarget("codex", "c1", "c1")


class TestParseSlots(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(rv.parse_slots(""), {})
        self.assertEqual(rv.parse_slots("off"), {})
        self.assertEqual(rv.parse_slots("bozuk"), {})
        s = rv.parse_slots("agy=5, evren=1,codex=1,copilot=0,xx=9,claude=a")
        self.assertEqual(s, {"agy": 5, "evren": 1, "claude": 1, "codex": 1, "copilot": 0, "anthropic": 1})


class TestTakeSlot(unittest.TestCase):
    def setUp(self):
        wr._ACTIVE.clear()
        self.addCleanup(wr._ACTIVE.clear)

    def test_single_mode_one_job(self):
        self.assertEqual(wr._take_slot("a|evren/m1", "a", "evren", {})[0], 0)
        self.assertLess(wr._take_slot("b|agy/m2", "b", "agy", {})[0], 0)

    def test_slots(self):
        s = rv.parse_slots("agy=2,evren=1,copilot=0")
        self.assertEqual(wr._take_slot("a|agy/m2", "a", "agy", s)[0], 0)
        self.assertEqual(wr._take_slot("b|agy/m2", "b", "agy", s)[0], 1)      # ayrı agy HOME numarası
        self.assertLess(wr._take_slot("c|agy/m2", "c", "agy", s)[0], 0)       # agy dolu
        self.assertLess(wr._take_slot("a|evren/m1", "a", "evren", s)[0], 0)   # aynı proje başka koşuda
        self.assertEqual(wr._take_slot("c|evren/m1", "c", "evren", s)[0], 0)
        self.assertIn("0", wr._take_slot("d|copilot/x", "d", "copilot", s)[1])
        wr._release_slot("a|agy/m2")
        self.assertEqual(wr._take_slot("d|agy/m2", "d", "agy", s)[0], 0)      # boşalan en küçük numara yeniden

    def test_agy_home_per_slot(self):
        with tempfile.TemporaryDirectory() as d:
            h0 = wr.agy_home(d, "/x", ["ls"], real_home=d)
            h2 = wr.agy_home(d, "/y", ["ls"], real_home=d, slot=2)
            self.assertEqual(os.path.basename(h0), "agy_home")
            self.assertEqual(os.path.basename(h2), "agy_home_2")
            self.assertTrue(os.path.isdir(os.path.join(h2, "tmp")))


class TestSlotsTick(_Tick):
    def setUp(self):
        super().setUp()
        self.hold = True
        wr._ACTIVE.clear()
        self.addCleanup(wr._ACTIVE.clear)

    def slots(self, spec, gap="0"):
        settings.save_settings({"stewards": {"rev": {"review_slots": spec, "review_min_gap_minutes": gap}}})

    def modes(self):
        return sorted(k.split("/")[0] for _p, k in self.started)

    def test_default_single_job(self):
        self.own("a", "b", "c")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)

    def test_slot_counts_per_mode(self):
        self.own("a", "b", "c", "e")
        self.targets = [T1, T2, CX]
        self.slots("agy=2,evren=1,codex=0")
        res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(res["started"], 3)
        self.assertEqual(self.modes(), ["agy", "agy", "evren"])
        self.assertEqual(len({p for p, _k in self.started}), 3)              # her koşu ayrı proje
        wr.review_tick(self.cfg(), now=NOW + 60)                             # yuvalar dolu: yeni başlatma yok
        self.assertEqual(len(self.started), 3)

    def test_same_project_never_twice(self):
        self.own("a")
        self.slots("agy=5,evren=1")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)

    def test_zero_slot_mode_never_starts_and_running_survives(self):
        self.own("a", "b")
        self.targets = [T2]
        wr.review_tick(self.cfg(), now=NOW)                                  # tek iş kipinde agy koşusu başladı
        self.assertEqual(len(self.started), 1)
        self.slots("agy=0,evren=1")
        res = wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(res["started"], 0)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(wr.running_keys()), 1)                          # 0'a çekmek çalışanı öldürmez
        self.assertFalse(any(a.get("kind") == "cancel" for a in res["actions"]))
        st = wr.review_state(self.cfg(), now=NOW + 60)
        self.assertEqual(st["slots"]["agy"]["slots"], 0)
        self.assertEqual(len(st["slots"]["agy"]["running"]), 1)
        self.assertFalse(wr.manual_run(self.cfg(), "b", "agy", "m2")["ok"])  # elle de başlamaz

    def test_remote_project_only_evren(self):
        self.own("far", "loc")
        self.targets = [T2, T1]
        self.slots("agy=5,evren=1")
        with mock.patch.object(wr, "remote_host", lambda n, idx=None: "h" if n == "far" else ""), \
                mock.patch.object(wr, "remote_ready", lambda n, idx=None: (True, "")):
            wr.review_tick(self.cfg(), now=NOW)
        far = [k for p, k in self.started if p == "far"]
        self.assertTrue(far)
        self.assertTrue(all(k.startswith("evren/") for k in far))
        self.assertIn("loc", [p for p, _k in self.started])

    def test_quota_blocked_target_skipped(self):
        self.own("a", "b")
        self.targets = [T2, T3]
        rv.set_block(sw.paths_for("rev"), T2.key, NOW + 3600, "kota")
        self.slots("agy=2")
        res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(res["started"], 2)
        self.assertEqual({k for _p, k in self.started}, {T3.key})

    def test_freed_slot_refilled_next_tick(self):
        self.own("a", "b")
        self.targets = [T1]
        self.slots("evren=1")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)
        proj = self.started[0][0]
        wr._JOBS.clear()                                                     # koşu bitti
        rv.update_pair(sw.paths_for("rev"), proj, T1, status="done", finished_at=NOW + 90)
        wr.review_tick(self.cfg(), now=NOW + 120)
        self.assertEqual(len(self.started), 2)
        self.assertNotEqual(self.started[1][0], proj)

    def test_min_gap_one_start_per_tick(self):
        self.own("a", "b", "c")
        self.targets = [T2]
        self.slots("agy=5", gap="10")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(len(self.started), 1)
        wr.review_tick(self.cfg(), now=NOW + 60)                             # aralık dolmadı
        self.assertEqual(len(self.started), 1)
        wr.review_tick(self.cfg(), now=NOW + 11 * 60)
        self.assertEqual(len(self.started), 2)


if __name__ == "__main__":
    unittest.main()
