"""Çok satırlı mesaj tek parça bracketed paste ile gider (load-buffer + paste-buffer -p + tek Enter); tek satır eski yolda. tmux'a DOKUNMAZ."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402


def _run(text, fail_on=None):
    calls = []

    def fake_run(argv, capture_output=True, timeout=None, input=None):
        sub = next((a for a in argv if a in ("load-buffer", "paste-buffer", "send-keys", "delete-buffer")), "")
        calls.append((sub, argv, input))
        return subprocess.CompletedProcess(argv, 1 if sub == fail_on else 0)

    with mock.patch.object(tmux_backend.subprocess, "run", fake_run), \
            mock.patch.object(tmux_backend, "_exact", lambda n: n), \
            mock.patch.object(tmux_backend.time, "sleep", lambda s: None):
        ok = tmux_backend.tmux_send_keys("x", text)
    return ok, calls


class MultilineSendTest(unittest.TestCase):
    def test_multiline_uses_bracketed_paste_then_single_enter(self):
        ok, calls = _run("satır1\nsatır2\n- madde")
        self.assertTrue(ok)
        self.assertEqual([c[0] for c in calls], ["load-buffer", "paste-buffer", "send-keys"])
        self.assertEqual(calls[0][2], "satır1\nsatır2\n- madde".encode("utf-8"))
        self.assertIn("-p", calls[1][1])
        self.assertIn("Enter", calls[2][1])
        self.assertNotIn("-l", calls[2][1])

    def test_single_line_keeps_literal_path(self):
        ok, calls = _run("merhaba")
        self.assertTrue(ok)
        self.assertEqual([c[0] for c in calls], ["send-keys", "send-keys"])
        self.assertIn("-l", calls[0][1])

    def test_paste_failure_returns_false_and_cleans_buffer(self):
        ok, calls = _run("a\nb", fail_on="paste-buffer")
        self.assertFalse(ok)
        self.assertEqual(calls[-1][0], "delete-buffer")
        self.assertNotIn("send-keys", [c[0] for c in calls])


if __name__ == "__main__":
    unittest.main()
