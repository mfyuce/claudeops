"""Proje oturumları düşük öncelikle başlar (spawn_nice, 21 Kas): nice 10 + ionice best-effort 7; değnekçi beyni muaf; off kapatır."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn  # noqa: E402


def _with(value):
    return mock.patch("claudeops.settings.load_settings", lambda: {"spawn_nice": value} if value is not None else {})


class SpawnPriority(unittest.TestCase):
    def test_default_and_exempt_and_off(self):
        with _with(None):
            self.assertIn("renice -n 10", spawn.spawn_priority_prefix("proj1"))
            self.assertEqual(spawn.spawn_priority_prefix("degnekci_iso"), "")
        for v in ("off", "0", "", "abc", "25"):
            with _with(v):
                self.assertEqual(spawn.spawn_priority_prefix("proj1"), "", v)
        with _with("5"):
            self.assertIn("renice -n 5", spawn.spawn_priority_prefix("proj1"))

    def test_child_inherits_nice(self):
        with _with("10"):
            pre = spawn.spawn_priority_prefix("p")
        out = subprocess.run(["sh", "-c", f"cd /tmp && {pre}bash -c 'cut -d\" \" -f19 /proc/$$/stat'"], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "10")


if __name__ == "__main__":
    unittest.main()
