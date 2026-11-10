"""Sahip kurali (2026-11-05, TBD#162): durmus projeyi acarken resume edilecek konusma devirsiz bitmisse once onunla ac,
devir gonder, `ho_pending` yaz (motor READY'de taze yeniden acar); direktif o tur GITMEZ. Gercek tmux/spawn yok.
Calistirma: python3 -m unittest discover -s py/tests"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


def _jsonl(lines):
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for o in lines:
            f.write(json.dumps(o) + "\n")
    return p


USER = {"type": "user", "message": {"role": "user", "content": "isi ilerlet"}}
ASSIST = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "tamam"}]}}
RFH = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "READY FOR HANDOVER"}]}}


class ResumeLacksHoTest(unittest.TestCase):
    def _run(self, path, cfg_val="act", cli="claude", launch=None):
        cfg = sw.Config(ho_on_open=cfg_val)
        prov = mock.MagicMock()
        prov.resolve_resume_id.return_value = "sid1"
        with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: "/x")), \
                mock.patch.object(ws, "_project_cli", lambda n: cli), \
                mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: launch or {}), \
                mock.patch.object(ws, "get_provider", lambda c: prov), \
                mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: path):
            return ws._resume_lacks_ho("p", cfg)

    def tearDown(self):
        for p in getattr(self, "_paths", []):
            os.unlink(p)

    def _p(self, lines):
        p = _jsonl(lines)
        self._paths = getattr(self, "_paths", []) + [p]
        return p

    def test_work_without_ho_is_detected(self):
        p = self._p([USER, ASSIST])
        self.assertEqual(self._run(p), p)

    def test_ho_done_is_clean(self):
        self.assertEqual(self._run(self._p([USER, ASSIST, RFH])), "")

    def test_new_request_after_ho_needs_ho_again(self):
        p = self._p([USER, RFH, USER, ASSIST])
        self.assertEqual(self._run(p), p)

    def test_empty_conversation_is_clean(self):
        self.assertEqual(self._run(self._p([ASSIST])), "")

    def test_off_and_non_claude_and_ucli_record(self):
        p = self._p([USER, ASSIST])
        self.assertEqual(self._run(p, cfg_val="off"), "")
        self.assertEqual(self._run(p, cli="agy"), "")
        self.assertEqual(self._run(p, launch={"cli": "ucli"}), "")

    def test_missing_jsonl(self):
        self.assertEqual(self._run("/nonexistent/x.jsonl"), "")


class EnsureRunningHoOnOpenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.paths = sw.paths_for("default")
        self.state = {}

    def _ensure(self, lacks, handover_ok=True):
        started, handed = [], []
        ws.configure(start=lambda *a, **k: started.append(k) or {"ok": True})
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []), \
                mock.patch.object(ws, "_resume_lacks_ho", lambda n, c: "/t/a.jsonl" if lacks else ""), \
                mock.patch.object(ws, "_oversized_resume", lambda n, c: self.fail("ho first, oversized skipped") if lacks else 0), \
                mock.patch.object(ws, "_closed_in_models", lambda n: False), \
                mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: {}), \
                mock.patch.object(ws, "steward_config", lambda sid="default": sw.Config()), \
                mock.patch.object(ws, "_start_appeared", lambda n, s="default": True), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: True), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"), \
                mock.patch.object(ws, "_resolved_local_name", lambda n, s: n + "20261105"), \
                mock.patch.object(ws, "_local_handover", lambda n, s, l: handed.append(n) or {"ok": handover_ok}), \
                mock.patch.object(sw, "load_state", lambda p=None: dict(self.state)), \
                mock.patch.object(sw, "save_state", lambda st, p=None: self.state.update(st)), \
                mock.patch.object(sw, "steward_lock", mock.MagicMock()), \
                mock.patch.object(sw, "log_event", lambda *a, **k: None):
            res = ws._ensure_running("p")
        return res, started, handed

    def test_lacking_ho_resumes_then_hands_over(self):
        res, started, handed = self._ensure(True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["ho_on_open"])
        self.assertFalse(started[0].get("fresh"))      # eski konusmayla (resume) acilir
        self.assertEqual(handed, ["p"])
        self.assertIn("p20261105", self.state.get("ho_pending", {}))

    def test_clean_open_no_handover(self):
        res, _started, handed = self._ensure(False)
        self.assertNotIn("ho_on_open", res)
        self.assertEqual(handed, [])
        self.assertEqual({k: v for k, v in self.state.items() if k != "owned"}, {})   # L2 kaydı meşru ek

    def test_handover_failure_no_pending(self):
        res, _s, _h = self._ensure(True, handover_ok=False)
        self.assertTrue(res["ok"])
        self.assertFalse(res["ho_on_open"])
        self.assertEqual({k: v for k, v in self.state.items() if k != "owned"}, {})   # L2 kaydı meşru ek


if __name__ == "__main__":
    unittest.main()
