"""Sohbet yedeği: uzak arşiv etiketi/günü kabuk satırına girer, sondaki satır sonu komutu bölerdi. Ağ/oturum YOK."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_index, chat_remote as R  # noqa: E402


class _NoSend:
    def __init__(self):
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)

    def idle(self):
        return True

    def root(self):
        return "/live"

    def listing(self, root):
        return []

    def download(self, root, name, dest):
        return 0


class TrailingNewlineChatTest(unittest.TestCase):
    def test_names_reject_newline_tag_and_day(self):
        self.assertTrue(R.names("yuhem", "20261107"))
        for tag, day in (("yuhem\n", "20261107"), ("yuhem", "20261107\n")):
            with self.assertRaises(ValueError, msg=repr((tag, day))):
                R.names(tag, day)

    def test_pull_sends_nothing_for_newline_tag(self):
        tx = _NoSend()
        with tempfile.TemporaryDirectory() as d:
            res = R.pull(tx, "yuhem\n", "20261107", os.path.join(d, "a.tgz"), wait_s=0, sleep=lambda _s: None)
        self.assertFalse(res["ok"])
        self.assertEqual(tx.sent, [])

    def test_index_day_column_rejects_newline(self):
        self.assertEqual(chat_index._valid_day("2026-11-07"), "2026-11-07")
        self.assertEqual(chat_index._valid_day("2026-11-07\n"), "")


if __name__ == "__main__":
    unittest.main()
