"""TBD#375 (b): onay/ret/dışa aktarma önceki doğrulama sonucunu `verdict_state`te saklar.
Geçici dizin; ağ yok.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_review_findings_flow import _Flow, _FakeRemoteDrv  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

class _States(_Flow):
    def change(self, fid, **kw):
        d = self.findings()
        d[fid].update(kw)
        rv.save_findings(self.p, d)

    def kept(self, fid):
        r = self.findings()[fid]
        return r["state"], r.get("verdict_state")


class TestDecisionKeepsVerdict(_States):
    def setUp(self):
        super().setUp()
        self.fids = self.seed()

    def test_approve_and_reject_keep_verdict_state(self):
        f1, f2, f3 = self.fids
        for fid, st, action, to in ((f1, "verified", "approve", "approved"), (f2, "unclear", "approve", "approved"),
                                    (f3, "refuted", "reject", "rejected")):
            self.change(fid, state=st)
            self.assertTrue(self.post("finding", id=fid, action=action)["ok"])
            self.assertEqual(self.kept(fid), (to, st))

    def test_reject_before_verdict_adds_nothing(self):
        f1, f2 = self.fids[:2]
        self.change(f2, state="verify_sent")
        for fid in (f1, f2):
            self.assertTrue(self.post("finding", id=fid, action="reject")["ok"])
            self.assertNotIn("verdict_state", self.findings()[fid])

    def test_refused_decision_changes_nothing(self):
        f1 = self.fids[0]
        self.change(f1, state="refuted")
        self.assertFalse(self.post("finding", id=f1, action="approve")["ok"])
        self.assertNotIn("verdict_state", self.findings()[f1])

    def test_export_after_approve_keeps_verdict_state(self):
        f1 = self.fids[0]
        self.change(f1, state="verified")
        self.assertTrue(self.post("finding", id=f1, action="approve")["ok"])
        self.assertTrue(self.post("export", project="a")["ok"])
        self.assertEqual(self.kept(f1), ("exported", "verified"))

    def test_direct_export_of_verdict_state(self):
        f1 = self.fids[0]
        self.change(f1, state="unclear")
        r = wr.export_findings(self.cfg(), "a", "TOBEDECIDED.md", 5_000.0, by="auto", states=("unclear",))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.kept(f1), ("exported", "unclear"))

    def test_stale_check_reject_keeps_verdict_state(self):
        f1 = self.fids[0]
        self.change(f1, state="unclear", title="`gone_fn` bozuk", where="x.py:1")
        with open(os.path.join(self.proj_dir, "x.py"), "w") as fh:
            fh.write("def live_fn(): pass\n")
        wr.export_findings(self.cfg(), "a", "TOBEDECIDED.md", 5_000.0, by="auto", states=("unclear",))
        self.assertEqual(self.kept(f1), ("rejected", "unclear"))

    def cfg(self):
        return ws.steward_config("rev")


class TestRemoteKeepsVerdict(_States):
    def setUp(self):
        super().setUp()
        self.fids = self.seed(proj="far")
        self.drv = _FakeRemoteDrv({"TODO.md": "# TODO\n", "TOBEDECIDED.md": "# TBD\n"}, [])
        p = mock.patch.object(wr, "_REMOTE_FN", lambda proj, host: self.drv)
        p.start()
        self.addCleanup(p.stop)

    def test_remote_export_and_stale_reject(self):
        f1, f2 = self.fids[:2]
        self.change(f1, state="unclear", title="`old_fn` bozuk")      # where: x.py:10
        self.change(f2, state="unclear", title="`live_fn` bozuk")     # where: y.py:3
        self.drv.src = {"x.py": "def renamed_fn(): pass\n", "y.py": "def live_fn(): pass\n"}
        r = wr.export_findings(ws.steward_config("rev"), "far", "TOBEDECIDED.md", 5_000.0, by="auto",
                               states=("unclear",))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.kept(f1), ("rejected", "unclear"))
        self.assertEqual(self.kept(f2), ("exported", "unclear"))


if __name__ == "__main__":
    unittest.main()
