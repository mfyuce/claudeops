import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import ucli_agents as ua  # noqa: E402


class PreviewOnlyTest(unittest.TestCase):
    def test_preview_does_not_issue_token(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ua, "TOKEN_DIR", d), \
                mock.patch.object(ua, "_save") as save:
            with ua.preview_only():
                p = ua.issue_token("sess1")
            self.assertEqual(p, os.path.join(d, "sess1"))
            self.assertFalse(os.path.exists(p))
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
