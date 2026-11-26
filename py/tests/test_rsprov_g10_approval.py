"""rs/prov G10: onay kaydı belirsizlikte REDDEDER (yalnız geçici dizin; süreç yalnız sahte betik)."""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval as ua  # noqa: E402
from claudeops import ucli_client  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="cops-g10-appr-")
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.root = os.path.join(self.d, "ucli_approval")
        self.index = os.path.join(self.root, "index.json")
        p = mock.patch.object(ua, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def write_index(self, data: bytes):
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        with open(self.index, "wb") as f:
            f.write(data)

    def copies(self):
        return sorted(n for n in os.listdir(self.root) if n.startswith("index.json.corrupt-"))


class Names(_Base):
    def test_trailing_newline_run_key_refused(self):
        with self.assertRaises(ValueError):
            ua.dir_for("run1\n", create=True)

    def test_trailing_newline_approval_id_ignored(self):
        self.assertIsNone(ua.parse_suspended('{"suspended":{"id":"ab\\n"}}'))

    def test_deep_line_is_skipped(self):
        out = '{"suspended":{"id":"iyi"}}\n' + '{"a":' * 100000
        self.assertEqual(ua.parse_suspended(out), {"id": "iyi"})


class Index(_Base):
    def test_corrupt_index_is_copied_before_overwrite(self):
        for bad in (b"{", b"[1]", b"\xff", b"[" * 100000):
            self.write_index(bad)
            ua.register("r1", "/w", "", ["x"])
            copies = self.copies()
            self.assertTrue(copies, bad[:8])
            contents = []
            for n in copies:
                path = os.path.join(self.root, n)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
                with open(path, "rb") as f:
                    contents.append(f.read())
            self.assertIn(bad, contents)
            self.assertEqual(ua.get("r1")["state"], "running")

    def test_deep_index_reads_as_empty(self):
        self.write_index(b"[" * 100000)
        self.assertIsNone(ua.get("r1"))
        self.assertFalse(ua.set_state("r1", "done"))

    @unittest.skipIf(os.geteuid() == 0, "root izinleri yok sayar")
    def test_unreadable_index_is_not_overwritten(self):
        self.write_index(b'{"eski": {"state": "suspended"}}')
        os.chmod(self.index, 0)
        with self.assertRaises(OSError):
            ua.register("r1", "/w", "", ["x"])
        os.chmod(self.index, 0o600)
        with open(self.index, "rb") as f:
            self.assertEqual(f.read(), b'{"eski": {"state": "suspended"}}')

    def test_fifo_index_does_not_block(self):
        os.makedirs(self.root, mode=0o700)
        os.mkfifo(self.index)
        got = []

        def run():
            got.append(ua.get("r1"))
            try:
                ua.register("r1", "/w", "", ["x"])
            except OSError:
                got.append("ret")
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(5)
        blocked = t.is_alive()
        if blocked:
            os.close(os.open(self.index, os.O_WRONLY | os.O_NONBLOCK))
        self.assertFalse(blocked)
        self.assertEqual(got, [None, "ret"])
        self.assertTrue(stat.S_ISFIFO(os.lstat(self.index).st_mode))

    def test_live_run_key_is_not_replaced(self):
        ua.register("r1", "/w", "s", ["eski"], owner="ali")
        for state in ("running", "suspended", "resuming"):
            ua.set_state("r1", state)
            with self.assertRaises(OSError):
                ua.register("r1", "/x", "t", ["yeni"], owner="vera")
            self.assertEqual((ua.get("r1")["argv_resume"], ua.get("r1")["owner"]), (["eski"], "ali"), state)
        for state in ("done", "expired"):
            ua.set_state("r1", state)
            ua.register("r1", "/x", "t", [state])
            self.assertEqual(ua.get("r1")["argv_resume"], [state])

    def test_unrecognised_record_is_not_replaced(self):
        for rec in (5, {"state": "garip"}, {}):
            self.write_index(json.dumps({"r1": rec}).encode())
            with self.assertRaises(OSError):
                ua.register("r1", "/w", "", ["x"])

    def test_chat_once_refuses_live_key_before_spawn(self):
        ua.register("r1", "/w", "s", ["eski"])
        ua.set_state("r1", "suspended")
        mark = os.path.join(self.d, "calisti")
        fake = os.path.join(self.d, "ucli")
        with open(fake, "w") as f:
            f.write(f"#!/bin/sh\ntouch {mark}\necho '{{}}'\n")
        os.chmod(fake, 0o755)
        with mock.patch.object(ucli_client, "binary_supports_flag", lambda *a: True):
            with self.assertRaises(ucli_client.UcliError):
                ucli_client.ucli_chat_once(self.d, "p", binary=fake, approval_run_key="r1", timeout=10)
        self.assertFalse(os.path.exists(mark))


class Dirs(_Base):
    def test_symlinked_run_dir_or_sub_dir_refused(self):
        out = os.path.join(self.d, "disari")
        os.makedirs(out, mode=0o755)
        os.makedirs(self.root)
        os.symlink(out, os.path.join(self.root, "r1"))
        with self.assertRaises(OSError):
            ua.dir_for("r1", create=True)
        os.makedirs(os.path.join(self.root, "r2"))
        os.symlink(out, os.path.join(self.root, "r2", "answers"))
        with self.assertRaises(OSError):
            ua.dir_for("r2", create=True)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o755)
        self.assertEqual(os.listdir(out), [])


if __name__ == "__main__":
    unittest.main()
