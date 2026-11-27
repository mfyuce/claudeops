"""ucli tarafındaki ad/kimlik doğrulamaları sondaki satır sonunu kabul etmesin. Gerçek süreç/ağ/durum dizini YOK."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval as ua, ucli_ask, ucli_checks, ucli_client, ucli_session_opts  # noqa: E402


class _Roots(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.td = d.name
        for mod, name, sub in ((ua, "ROOT", "approval"), (ucli_ask, "ROOT", "ask"), (ucli_checks, "ROOT", "checks"),
                               (ucli_checks, "AUDIT", "checks/audit.jsonl")):
            p = mock.patch.object(mod, name, os.path.join(self.td, sub))
            p.start()
            self.addCleanup(p.stop)


class AskTest(_Roots):
    def test_session_name_with_newline_rejected(self):
        with self.assertRaises(ValueError):
            ucli_ask.dir_for("s1\n")
        d = os.path.join(ucli_ask.ROOT, "s1\n")
        os.makedirs(d)
        with open(os.path.join(d, "question.json"), "w", encoding="utf-8") as f:
            json.dump({"id": 1, "question": "?"}, f)
        self.assertIsNone(ucli_ask.pending("s1\n"))
        self.assertEqual(ucli_ask.answer("s1\n", 1, "x"), (False, "no pending question"))
        self.assertFalse(os.path.exists(os.path.join(d, "answer.json")))


class ApprovalIdTest(_Roots):
    def setUp(self):
        super().setUp()
        ua.register("run1", "/w", "s1", [], owner="a")

    def test_suspended_id_with_newline_ignored(self):
        self.assertIsNone(ua.parse_suspended(json.dumps({"suspended": {"id": "ab-1\n"}})))

    def test_pending_file_id_with_newline_ignored_and_not_answerable(self):
        with open(os.path.join(ua.dir_for("run1"), "pending", "a.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "a1\n", "expires_at": time.time() + 100}, f)
        self.assertEqual(ua.pending("run1"), [])
        self.assertEqual(ua.answer("run1", "a1\n", "approve"), (False, "invalid id"))
        self.assertEqual(os.listdir(os.path.join(ua.dir_for("run1"), "answers")), [])


class CheckNameTest(_Roots):
    def test_check_name_with_newline_rejected_and_not_written(self):
        checks = [{"name": "unittest", "argv": ["true"]}, {"name": "unittest\n", "argv": ["false"]}]
        ok, why = ucli_checks.replace_checks(checks)
        self.assertFalse(ok)
        self.assertIn("adı", why)
        self.assertFalse(os.path.exists(ucli_checks.registry_path()))


class EnvNameTest(unittest.TestCase):
    def test_api_key_env_with_newline_rejected(self):
        self.assertIn("X_API_KEY", ucli_client._subprocess_env("X_API_KEY", "k"))
        with self.assertRaises(ucli_client.UcliError):
            ucli_client._subprocess_env("X_API_KEY\n", "k")


class PathNameTest(unittest.TestCase):
    def test_executable_with_newline_in_name_not_listed(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("tool", "other\n"):
                p = os.path.join(d, n)
                with open(p, "w", encoding="utf-8") as f:
                    f.write("#!/bin/true\n")
                os.chmod(p, 0o700)
            self.assertEqual(ucli_session_opts.path_executables(d), ["tool"])


if __name__ == "__main__":
    unittest.main()
