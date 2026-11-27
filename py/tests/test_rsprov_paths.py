"""rs/prov: yola denetimsiz eklenen oturum adı/kimlik (ders tablosu §3.14). İki tarafta düzeldi (Rust `pyfmt::is_path_part`).

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_paths.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_client  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers.base import _path_part_ok  # noqa: E402

VALID = ("abc", "copsdev", "rs-prov", "ppr20261118_1", "a.b", "x_aj2", "ağaç", "...", "-n", "Q20261127")


class PathPartTest(unittest.TestCase):
    def test_valid_names_are_accepted(self):
        for n in VALID:
            with self.subTest(n=n):
                self.assertTrue(_path_part_ok(n))
        for n in ("", "/abs", "a/b", "../x", "a\0b", None, 5):
            with self.subTest(n=n):
                self.assertFalse(_path_part_ok(n))


class ClaudeRequestTest(unittest.TestCase):
    def test_absolute_sid_never_reads_outside_the_project(self):
        with tempfile.TemporaryDirectory() as d:
            projects = os.path.join(d, "projects")
            cwd = os.path.join(d, "w")
            pdir = Path(projects, cp._encode_cwd(cwd))
            pdir.mkdir(parents=True)
            row = json.dumps({"type": "assistant", "timestamp": "2026-11-27T10:00:00Z",
                              "message": {"model": "claude-x", "usage": {"input_tokens": 5}}}) + "\n"
            Path(d, "dis.jsonl").write_text(row)
            for n in VALID:
                (pdir / f"{n}.jsonl").write_text(row)
            with mock.patch.object(cp, "PROJECTS_DIR", projects):
                p = cp.ClaudeProvider()
                self.assertIsNone(p.last_request_epoch(cwd, os.path.join(d, "dis")))
                for n in VALID:
                    with self.subTest(n=n):
                        self.assertIsNotNone(p.last_request_epoch(cwd, n))


class UcliFilesTest(unittest.TestCase):
    def test_slash_in_session_name_reads_nothing_outside(self):
        with tempfile.TemporaryDirectory() as d:
            chat = Path(d, ".ucli", "chat")
            chat.mkdir(parents=True)
            Path(d, "dis.status.json").write_text('{"activity": "x"}')
            Path(d, "dis.jsonl").write_text('{"role": "user", "content": "x"}\n')
            with mock.patch.object(ucli_client, "chat_session_dirs", lambda cwd: [str(chat)]):
                self.assertIsNone(ucli_client.read_status_file(d, "../../dis"))
                self.assertIsNone(ucli_client.read_chat_history(d, "../../dis"))
                for n in VALID:
                    with self.subTest(n=n):
                        (chat / f"{n}.status.json").write_text('{"activity": "x"}')
                        (chat / f"{n}.jsonl").write_text('{"role": "user", "content": "x"}\n')
                        self.assertEqual(ucli_client.read_status_file(d, n), {"activity": "x"})
                        self.assertEqual(ucli_client.read_chat_history(d, n), [{"role": "user", "text": "x"}])


if __name__ == "__main__":
    unittest.main()
