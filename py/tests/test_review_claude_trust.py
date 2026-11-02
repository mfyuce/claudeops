import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class ClaudeTrust(unittest.TestCase):
    def test_second_project_is_trusted_too(self):
        with tempfile.TemporaryDirectory() as d:
            cj = os.path.join(d, ".claude.json")
            wr._ensure_claude_trust(cj, "/a")
            wr._ensure_claude_trust(cj, "/b")
            wr._ensure_claude_trust(cj, "/b")
            data = json.load(open(cj))
            self.assertTrue(data["hasCompletedOnboarding"])
            self.assertTrue(data["projects"]["/a"]["hasTrustDialogAccepted"])
            self.assertTrue(data["projects"]["/b"]["hasTrustDialogAccepted"])

    def test_corrupt_file_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            cj = os.path.join(d, ".claude.json")
            open(cj, "w").write("{bozuk")
            wr._ensure_claude_trust(cj, "/a")
            self.assertTrue(json.load(open(cj))["projects"]["/a"]["hasTrustDialogAccepted"])


if __name__ == "__main__":
    unittest.main()
