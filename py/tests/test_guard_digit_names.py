"""guard: adı rakam/_N ile biten roster kaydı çalışıyorsa her geçişte yeniden AÇILMAZ (review cliops 17 Kas)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import guard  # noqa: E402
from claudeops.roster import RosterEntry  # noqa: E402


class GuardDigitNames(unittest.TestCase):
    def _run(self, running_names):
        roster = [RosterEntry("ysf2", "/x", "m"), RosterEntry("hc", "/y", "m"), RosterEntry("gone", "/z", "m")]
        models = {"ysf2": "m", "hc": "m", "gone": "m"}
        import re
        sess = [SimpleNamespace(name=n, base=re.sub(r"\d+$", "", n)) for n in running_names]   # Session.base gibi sondaki rakamlar atılır
        with mock.patch.object(guard, "find_sessions", return_value=sess), mock.patch.object(guard, "read_roster", return_value=roster), \
                mock.patch.object(guard, "read_models", return_value=models), mock.patch.object(guard, "duplicates", return_value=[]), \
                mock.patch.object(guard, "spawn_session", return_value="spawned") as sp, mock.patch.object(guard, "detect_display", return_value=":0"):
            res = guard.guard_once(dry_run=True, spawn_delay=0)
        return res, sp

    def test_running_digit_named_entry_not_missing(self):
        res, _ = self._run(["ysf2", "hc"])
        self.assertEqual([e.name for e in res.missing], ["gone"])        # ysf2 çalışıyor: eksik DEĞİL

    def test_really_missing_still_reported(self):
        res, _ = self._run(["hc"])
        self.assertEqual(sorted(e.name for e in res.missing), ["gone", "ysf2"])


if __name__ == "__main__":
    unittest.main()
