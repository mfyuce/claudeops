"""API yasağı kapısı: ucli+Anthropic kayıtlı proje, yasak tarihi gelmeden açılmaz (stdlib unittest; gerçek ayar/oturum yok)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_steward as ws  # noqa: E402

UCLI_CLAUDE = {"cli": "ucli", "cli_opts": {"service": "claude"}}


class ApiBlockTest(unittest.TestCase):
    def gate(self, until, rec, today="2026-11-06"):
        with mock.patch.object(ws.settings_mod, "load_settings", return_value={"anthropic_api_block_until": until}), \
             mock.patch.object(ws, "_last_launch", return_value=rec):
            return ws._api_blocked("cli", today=today)

    def test_blocks_ucli_anthropic_before_date(self):
        r = self.gate("2026-11-09", UCLI_CLAUDE)
        self.assertEqual(r["code"], "anthropic_api_blocked")
        self.assertFalse(r["ok"])

    def test_endpoint_anthropic_blocked(self):
        self.assertIsNotNone(self.gate("2026-11-09", {"cli": "ucli", "cli_opts": {"endpoint": "https://api.anthropic.com"}}))

    def test_empty_opts_claude_model_blocked(self):
        self.assertIsNotNone(self.gate("2026-11-09", {"cli": "ucli", "model": "claude-sonnet-5-5", "cli_opts": None}))
        self.assertIsNone(self.gate("2026-11-09", {"cli": "ucli", "model": "glm-5.3", "cli_opts": None}))

    def test_open_after_date_or_empty(self):
        self.assertIsNone(self.gate("2026-11-09", UCLI_CLAUDE, today="2026-11-09"))
        self.assertIsNone(self.gate("", UCLI_CLAUDE))

    def test_other_records_pass(self):
        self.assertIsNone(self.gate("2026-11-09", {"cli": "claude"}))
        self.assertIsNone(self.gate("2026-11-09", {"cli": "ucli", "cli_opts": {"service": "evren"}}))
        self.assertIsNone(self.gate("2026-11-09", None))


if __name__ == "__main__":
    unittest.main()
