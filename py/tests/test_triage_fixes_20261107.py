"""7 Kas triyaj düzeltmeleri: orch_store.run_dir path traversal, needs_ho kullanıcı mesajındaki RFH, hosts db kipi liste dışı değer.

Gerçek ~/.claude'a dokunmaz (geçici dosyalar, statedocs sahte)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts, needs_ho, orch_store  # noqa: E402


class RunDirTest(unittest.TestCase):
    def test_rejects_traversal(self):
        for bad in ("", "../x", "a/b", "a\\b", "..", "a\0b"):
            with self.assertRaises(ValueError):
                orch_store.run_dir(bad)

    def test_normal_id_ok(self):
        self.assertTrue(orch_store.run_dir("20261107_120000_ab12").endswith("20261107_120000_ab12"))


class HandoverDoneUserMessageTest(unittest.TestCase):
    def _write(self, rows):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        self.addCleanup(os.unlink, f.name)
        for t, text in rows:
            f.write(json.dumps({"type": t, "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
        f.close()
        return f.name

    def test_user_message_with_rfh_text_does_not_count(self):
        p = self._write([("user", "Devir yaz, bitince 'READY FOR HANDOVER' de"), ("assistant", "tamam")])
        self.assertFalse(needs_ho.handover_done(p))

    def test_assistant_rfh_counts(self):
        p = self._write([("user", "ho"), ("assistant", "READY FOR HANDOVER (tarih)")])
        self.assertTrue(needs_ho.handover_done(p))


class HostsDbNonListTest(unittest.TestCase):
    def test_db_mode_non_list_is_corrupt(self):
        from claudeops import statedocs
        with mock.patch.object(statedocs, "backend", return_value="db"), \
                mock.patch.object(statedocs, "_db_ok", return_value=True), \
                mock.patch.object(statedocs, "read_json", return_value={"x": 1}):
            self.assertEqual(hosts._read_checked(), ([], True))
        with mock.patch.object(statedocs, "backend", return_value="db"), \
                mock.patch.object(statedocs, "_db_ok", return_value=True), \
                mock.patch.object(statedocs, "read_json", return_value=[{"name": "a"}, 3]):
            self.assertEqual(hosts._read_checked(), ([{"name": "a"}], False))


if __name__ == "__main__":
    unittest.main()
