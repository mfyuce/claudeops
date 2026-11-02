import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_session_opts as so  # noqa: E402


class ForbiddenCmds(unittest.TestCase):
    def test_interpreters_rejected_by_name(self):
        for c in ("python", "python3", "python3.12", "pypy3", "perl", "node", "Ruby", "awk", "sed", "curl", "vim"):
            out, err = so.validate_opts({"exec_cmds": [c]})
            self.assertTrue(err, c)
            self.assertEqual(out, {})

    def test_is_forbidden_cmd(self):
        self.assertTrue(so.is_forbidden_cmd("python3.11"))
        self.assertTrue(so.is_forbidden_cmd("BASH"))
        for ok in ("cargo", "git", "ls", "pytest", "pythonista-tool"):
            self.assertFalse(so.is_forbidden_cmd(ok), ok)


if __name__ == "__main__":
    unittest.main()
