import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import steward as cs  # noqa: E402


class AppendNote(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(cs.merge_note("a\n", " b "), "a\nb")
        self.assertEqual(cs.merge_note("", "b"), "b")
        self.assertEqual(cs.merge_note("a", ""), "a")

    def args(self, **kw):
        base = dict(name="p", append_note="yeni", note=None, host=None, phase=None, kind=None, goal=None, priority=None,
                    cadence=None, model=None, effort=None, port=0)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_appends_to_existing_and_does_not_overwrite(self):
        seen = {}

        def up(name, paths=None, **f):
            seen.update(f)
            raise ValueError("stop")
        with mock.patch.object(cs.sw, "load_projects", return_value={"p": SimpleNamespace(notes="eski")}), \
                mock.patch.object(cs.sw, "upsert_project", side_effect=up), mock.patch.object(cs, "_sid", return_value=None):
            cs.cmd_set(self.args())
        self.assertEqual(seen["notes"], "eski\nyeni")

    def test_conflicts_refused(self):
        self.assertEqual(cs.cmd_set(self.args(note="x")), 1)
        self.assertEqual(cs.cmd_set(self.args(host="yuhem")), 1)


if __name__ == "__main__":
    unittest.main()
