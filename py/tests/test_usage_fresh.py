"""Oturumsuz kullanım okuması (`claude -p /usage`): ayrıştırma + `_usage_all` önce taze yolu dener, olmazsa oturum yoluna düşer."""
import types
import unittest
from unittest import mock

from claudeops.commands import web
from claudeops.providers import PROVIDERS

SAMPLE = """You are currently using your subscription to power your Claude Code usage

Current week (all models): 48% used · resets Nov 16, 6pm (Europe/Istanbul)
Current week (Fable): 8% used · resets Nov 16, 6pm (Europe/Istanbul)

What's contributing to your usage?
"""


class FreshParse(unittest.TestCase):
    def test_parse_one_line_format(self):
        e = PROVIDERS["claude"].parse_fresh_usage(SAMPLE)
        self.assertEqual([x["percent"] for x in e], ["48", "8"])
        self.assertEqual(e[0]["label"], "Current week (all models)")
        self.assertTrue(e[0]["detail"].startswith("Resets Nov 16"))

    def test_parse_falls_back_to_tui_format(self):
        tui = "Current week (all models)\n██  92% used\nResets Sep 14, 6pm (Europe/Istanbul)\n"
        e = PROVIDERS["claude"].parse_fresh_usage(tui)
        self.assertEqual(e[0]["percent"], "92")

    def test_other_providers_have_no_fresh_path(self):
        for n, p in PROVIDERS.items():
            if n != "claude":
                self.assertIsNone(p.usage_fresh_argv(), n)


class FreshRun(unittest.TestCase):
    def _run(self, rc, out):
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    def test_fresh_ok_without_any_session(self):
        with mock.patch("subprocess.run", return_value=self._run(0, SAMPLE)) as r:
            res = web._usage_fresh(PROVIDERS["claude"])
        self.assertTrue(res["available"])
        self.assertEqual(res["checked_via"], "fresh")
        env = r.call_args.kwargs["env"]
        self.assertFalse(any(k.startswith("CLAUDE_CODE") for k in env))

    def test_fresh_failure_returns_none(self):
        with mock.patch("subprocess.run", return_value=self._run(1, "")):
            self.assertIsNone(web._usage_fresh(PROVIDERS["claude"]))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertIsNone(web._usage_fresh(PROVIDERS["claude"]))

    def test_usage_all_prefers_fresh_and_skips_sessions(self):
        with mock.patch.object(web, "find_sessions", return_value=[]), \
             mock.patch.object(web, "_usage_fresh", side_effect=lambda p: {"available": True, "checked_via": "fresh", "entries": []} if p.name == "claude" else None):
            out = web._usage_all()["providers"]
        self.assertEqual(out["claude"]["checked_via"], "fresh")
        self.assertEqual(out["agy"].get("reason"), "no_running_session")


if __name__ == "__main__":
    unittest.main()
