"""ucli live_context: durum dosyası context_bytes/4 kaba token; yoksa None (satır yedeği). Gerçek spawn/dosya YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402


class LiveContext(unittest.TestCase):
    def ctx(self, status, sid="cops"):
        with mock.patch.object(up, "read_status_file", lambda cwd, s: status):
            return up.UcliProvider().live_context("/w", sid)

    def test_bytes_over_four(self):
        self.assertEqual(self.ctx({"context_bytes": 1_200_000}), 300_000)

    def test_zero_is_zero(self):
        self.assertEqual(self.ctx({"context_bytes": 0}), 0)

    def test_unknown_cases_are_none(self):
        self.assertIsNone(self.ctx(None))
        self.assertIsNone(self.ctx({}))
        self.assertIsNone(self.ctx({"context_bytes": "12"}))
        self.assertIsNone(self.ctx({"context_bytes": -5}))
        self.assertIsNone(self.ctx({"context_bytes": True}))
        self.assertIsNone(self.ctx({"context_bytes": 100}, sid=None))

    def test_reader_error_is_none(self):
        def boom(cwd, s):
            raise OSError("x")
        with mock.patch.object(up, "read_status_file", boom):
            self.assertIsNone(up.UcliProvider().live_context("/w", "cops"))


if __name__ == "__main__":
    unittest.main()
