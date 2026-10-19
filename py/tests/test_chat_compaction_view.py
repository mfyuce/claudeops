"""Sohbet geçmişi: compaction sınırı + özet işareti (TBD#89, yalnız görünüm)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402


def _msg(t, text, **kw):
    return dict({"type": t, "message": {"content": text}}, **kw)


class CompactionViewTests(unittest.TestCase):
    def _history(self, lines):
        p = ClaudeProvider()
        p._transcript_lines = lambda cwd, sid: lines
        return p.full_history("x", None)

    def test_boundary_and_summary_roles_keep_pre_compaction_messages(self):
        h = self._history([
            _msg("user", "eski soru"),
            _msg("assistant", "eski cevap"),
            {"type": "system", "subtype": "compact_boundary",
             "compactMetadata": {"trigger": "auto", "preTokens": 261105}},
            _msg("user", "This session is being continued...", isCompactSummary=True),
            _msg("user", "yeni soru"),
        ])
        self.assertEqual([m["role"] for m in h], ["user", "assistant", "boundary", "summary", "user"])
        self.assertEqual(h[2]["text"], "auto, 261105")
        self.assertEqual(h[0]["text"], "eski soru")

    def test_no_boundary_unchanged(self):
        h = self._history([_msg("user", "a"), _msg("assistant", "b")])
        self.assertEqual([m["role"] for m in h], ["user", "assistant"])

    def test_sidechain_summary_ignored(self):
        h = self._history([_msg("user", "özet", isCompactSummary=True, isSidechain=True)])
        self.assertEqual(h, [])


if __name__ == "__main__":
    unittest.main()
