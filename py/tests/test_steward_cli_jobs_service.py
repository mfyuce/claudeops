"""D10: `steward jobs show/ack --service` aynı kimlikli iki servis kaydını ayırır (sj sahte; disk YOK)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import steward as st  # noqa: E402

JOBS = [
    {"id": 7, "service": "varaka", "state": "done", "project": "a"},
    {"id": 7, "service": "other", "state": "failed", "project": "b"},
]


class JobsServiceTest(unittest.TestCase):
    def _run(self, act, service):
        out = []
        args = SimpleNamespace(jobs_action=act, id="7", service=service, sid="default")
        with mock.patch.object(st, "_sid", return_value="default"), \
                mock.patch.object(st.sj, "load_jobs", return_value=JOBS), \
                mock.patch.object(st.sj, "mark_delivered") as md, \
                mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
            rc = st.cmd_jobs(args)
        return rc, out, md

    def test_show_picks_named_service(self):
        rc, out, _ = self._run("show", "other")
        self.assertEqual(rc, 0)
        self.assertIn('"failed"', "\n".join(out))

    def test_show_unknown_service_errors(self):
        rc, out, _ = self._run("show", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("nope", "\n".join(out))

    def test_ack_marks_named_service(self):
        rc, _, md = self._run("ack", "other")
        self.assertEqual(rc, 0)
        self.assertEqual(md.call_args[0][:3], (7, "other", "result"))


if __name__ == "__main__":
    unittest.main()
