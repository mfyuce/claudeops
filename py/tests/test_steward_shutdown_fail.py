import unittest

from claudeops import steward as sw


class ShutdownNoteResultTests(unittest.TestCase):
    def test_failure_rolls_back_then_gives_up(self):
        it = {"stage": "ho", "at": 1.0}
        for i in range(sw.SHUTDOWN_ACTION_FAIL_MAX - 1):
            self.assertTrue(sw.shutdown_note_result(it, "handover", {"ok": False, "error": "not running"}, 2.0))
            self.assertEqual(it["stage"], "wait")
            it["stage"] = "ho"
        self.assertFalse(sw.shutdown_note_result(it, "handover", {"ok": False, "error": "not running"}, 3.0))
        self.assertEqual(it["stage"], "ho_failed")
        self.assertIn("ho_failed", sw._SD_TERMINAL)
        self.assertEqual(it["fail_error"], "not running")

    def test_stop_failure_goes_back_to_ho(self):
        it = {"stage": "closed", "at": 1.0}
        self.assertTrue(sw.shutdown_note_result(it, "stop", {"ok": False}, 2.0))
        self.assertEqual(it["stage"], "ho")

    def test_failed_stop_is_retried_end_to_end(self):
        # TODO 2026-10-28 (21): stop başarısız -> `at` yenilenince `last_activity >= at` bir daha tutmuyor, oturum açık kalıyordu
        cfg = sw.Config()
        projects = {"ncs": sw.Project(name="ncs")}
        v = sw.SessionView(name="ncs", running=True, cwd="/x", cli="claude", last_activity=100.0)
        _, sd, _ = sw.plan_shutdown([v], projects, {}, cfg, 1000.0)
        v2 = sw.SessionView(name="ncs", running=True, cwd="/x", cli="claude", last_activity=1500.0,
                            last_assistant=sw.READY_FOR_HANDOVER)
        acts, sd, _ = sw.plan_shutdown([v2], projects, sd, cfg, 1600.0)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "ncs")])
        self.assertTrue(sw.shutdown_note_result(sd["items"]["ncs"], "stop", {"ok": False, "error": "lock"}, 1601.0))
        acts, sd, done = sw.plan_shutdown([v2], projects, sd, cfg, 1700.0)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "ncs")])      # yeniden denendi
        self.assertNotEqual(sd["items"]["ncs"]["stage"], "ho_timeout")

    def test_success_resets_counter(self):
        it = {"stage": "ho", "fails": 3}
        self.assertFalse(sw.shutdown_note_result(it, "handover", {"ok": True}, 2.0))
        self.assertNotIn("fails", it)

    def test_terminal_plan_finishes(self):
        cfg = sw.Config()
        sd = {"init": True, "started": 0.0, "items": {"x": {"stage": "ho_failed", "at": 1.0}}}
        _, _, done = sw.plan_shutdown([], {}, sd, cfg, 10.0)
        self.assertTrue(done)


if __name__ == "__main__":
    unittest.main()
