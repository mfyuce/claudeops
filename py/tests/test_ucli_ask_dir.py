"""ucli `--ask-dir` (cli_opts `ask_dir`) + `ucli_ask.py` dosya kanalı. Gerçek Popen/ağ yok."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import ucli_ask  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.ucli_session_opts import validate_opts  # noqa: E402


class AskDirTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        p = mock.patch.object(ucli_ask, "ROOT", os.path.join(self.root, "ucli_ask"))
        p.start()
        self.addCleanup(p.stop)

    def apply(self, opts, name="s1", supports=lambda b, f: True):
        with mock.patch.object(up, "binary_supports_flag", supports), mock.patch.object(up, "_default_session_cap", return_value=0):
            return up._apply_cli_opts(["ucli", "chat"], opts, name)[0]

    def test_opts_default_off_and_ambiguous(self):
        self.assertNotIn("ask_dir", validate_opts({})[0])
        self.assertNotIn("ask_dir", validate_opts({"ask_dir": "off"})[0])
        self.assertIs(validate_opts({"ask_dir": True})[0]["ask_dir"], True)
        self.assertTrue(validate_opts({"ask_dir": "maybe"})[1])

    def test_argv_has_private_dir_outside_workspace(self):
        argv = self.apply({"ask_dir": True})
        d = argv[argv.index("--ask-dir") + 1]
        self.assertEqual(d, os.path.join(self.root, "ucli_ask", "s1"))
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        self.assertNotIn("--ask-dir", self.apply({}))

    def test_unsupported_binary_or_no_name_is_error(self):
        with self.assertRaises(ValueError):
            self.apply({"ask_dir": True}, supports=lambda b, f: False)
        with self.assertRaises(ValueError):
            self.apply({"ask_dir": True}, name="")

    def test_pending_and_answer_roundtrip_and_stale_id(self):
        d = ucli_ask.dir_for("s1", create=True)
        self.assertIsNone(ucli_ask.pending("s1"))
        self.assertEqual(ucli_ask.answer("s1", 7, "x"), (False, "no pending question"))
        with open(os.path.join(d, "question.json"), "w") as f:
            json.dump({"id": 7, "header": "H", "question": "Q?", "options": ["a", "b"]}, f)
        self.assertEqual(ucli_ask.pending("s1"), {"id": 7, "header": "H", "question": "Q?", "options": ["a", "b"]})
        self.assertEqual(ucli_ask.answer("s1", 6, "x"), (False, "stale question id"))
        self.assertEqual(ucli_ask.answer("s1", 7, "x" * 70000), (False, "answer too large"))
        self.assertEqual(ucli_ask.answer("s1", 7, "evet"), (True, ""))
        self.assertEqual(json.load(open(os.path.join(d, "answer.json"))), {"id": 7, "text": "evet"})

    def test_bad_names_rejected(self):
        for n in ("", "../x", "a/b", ".hidden"):
            with self.assertRaises(ValueError):
                ucli_ask.dir_for(n)

    def test_broken_question_file_is_none(self):
        d = ucli_ask.dir_for("s1", create=True)
        open(os.path.join(d, "question.json"), "w").write("{trunc")
        self.assertIsNone(ucli_ask.pending("s1"))


if __name__ == "__main__":
    unittest.main()
