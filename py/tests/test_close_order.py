"""`close.run`: models.tsv ÖNCE yorumlanır, sonra proc öldürülür (guard yeniden açmasın)."""
import argparse
import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import close  # noqa: E402


class CloseOrderTest(unittest.TestCase):
    def test_comment_before_kill(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "models.tsv")
            open(path, "w").write("mkt\tsonnet\tmedium\n")
            seen = []

            def fake_kill(pid, grace, keep, name=None):
                seen.append(open(path).read())
                return "ok"

            sess = types.SimpleNamespace(name="mkt", base="mkt", pid=123)
            args = argparse.Namespace(names=["mkt"], grace=1.0, keep_terminal=True, dry_run=False)
            with mock.patch.object(close, "MODELS_TSV", path), \
                    mock.patch.object(close, "find_sessions", lambda **kw: [sess]), \
                    mock.patch.object(close, "_kill_with_parent", fake_kill), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(close.run(args), 0)
            self.assertEqual(len(seen), 1)
            self.assertTrue(seen[0].startswith("#mkt"))


if __name__ == "__main__":
    unittest.main()
