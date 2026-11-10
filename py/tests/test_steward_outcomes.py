"""L5 (10 Kas 2026): başarılı dönen eylemin sonucu doğrulanır (oturum açıldı mı / hedefte yeni cevap ya da etkinlik var mı)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402

T0 = 100000.0


def v(name, text="x", act=T0 - 600, started=T0 - 3600, running=True, bp=None):
    return sw.SessionView(name=name, running=running, last_assistant=text, last_activity=act, started_at=started, blueprint=bp)


class OutcomeTest(unittest.TestCase):
    def _pend(self, kind, name, views):
        r = sw.outcome_baseline(kind, name, views, T0)
        return {f"{kind}|{name}": r}

    def test_start_opened_under_dated_name(self):
        pend = self._pend("start", "cops", [])
        done, rest = sw.check_outcomes(pend, [v("cops20261110_1", started=T0 + 20)], T0 + 60)
        self.assertEqual([(d["kind"], d["result"]) for d in done], [("start", "changed")])
        self.assertEqual(rest, {})

    def test_start_never_opened_is_none_after_window(self):
        pend = self._pend("start", "danisppr", [])
        done, rest = sw.check_outcomes(pend, [], T0 + 60)
        self.assertEqual((done, len(rest)), ([], 1))                      # pencere dolmadı: bekler
        done, rest = sw.check_outcomes(rest, [], T0 + sw.VERIFY_WINDOW_SECONDS + 1)
        self.assertEqual([d["result"] for d in done], ["none"])

    def test_directive_with_new_activity_or_reply(self):
        before = [v("p20261110", text="eski")]
        pend = self._pend("directive", "p", before)
        done, _ = sw.check_outcomes(pend, [v("p20261110", text="yeni cevap")], T0 + 120)
        self.assertEqual(done[0]["result"], "changed")
        done, _ = sw.check_outcomes(pend, [v("p20261110", text="eski", act=T0 + 30)], T0 + 120)
        self.assertEqual(done[0]["result"], "changed")
        done, _ = sw.check_outcomes(pend, [v("p20261110", text="eski")], T0 + sw.VERIFY_WINDOW_SECONDS + 1)
        self.assertEqual(done[0]["result"], "none")                       # keepwarm/dürtme işe yaramadı

    def test_other_project_with_same_prefix_does_not_count(self):
        pend = self._pend("start", "hc", [])
        done, rest = sw.check_outcomes(pend, [v("hcr20261110", started=T0 + 20)], T0 + 60)
        self.assertEqual((done, len(rest)), ([], 1))

    def test_pending_is_capped(self):
        pend = {f"k{i}": {"kind": "directive", "name": f"n{i}", "at": T0 + i, "sigs": {}} for i in range(sw.VERIFY_MAX_PENDING + 50)}
        _, rest = sw.check_outcomes(pend, [], T0 + 1)
        self.assertEqual(len(rest), sw.VERIFY_MAX_PENDING)

    def test_via_passes_through(self):
        pend = {"k": {"kind": "directive", "name": "p", "at": T0, "sigs": {}, "via": "brain"}}
        done, _ = sw.check_outcomes(pend, [v("p20261110", act=T0 + 30)], T0 + 60)
        self.assertEqual((done[0]["result"], done[0]["via"]), ("changed", "brain"))
        done, _ = sw.check_outcomes({"k": dict(pend["k"], via="")}, [v("p", act=T0 + 30)], T0 + 60)
        self.assertNotIn("via", done[0])


class BrainDirectiveOutcomeTest(unittest.TestCase):
    """L2 kalan (b): beynin MCP direktifi doğrulama kuyruğuna girer; atlanan/kuru/başarısız girmez."""

    def test_register_only_real_sends(self):
        from unittest import mock
        from claudeops.commands import web_steward as ws
        with mock.patch.object(ws, "_register_outcomes") as reg:
            for res in ({"ok": False}, {"ok": True, "skipped": "wake_repeat"}, {"ok": True, "dry": True}, None):
                ws._register_brain_outcome(res, "p", "iso")
            reg.assert_not_called()
            ws._register_brain_outcome({"ok": True, "name": "p20261110", "chars": 9}, "p", "iso")
            recs = reg.call_args[0][0]
            self.assertEqual((recs[0]["kind"], recs[0]["name"], recs[0]["via"], recs[0]["sigs"]),
                             ("directive", "p20261110", "brain", {}))


if __name__ == "__main__":
    unittest.main()
