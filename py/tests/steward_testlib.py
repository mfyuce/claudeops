"""Değnekçi testlerinin ortak yardımcısı (adı `test_` ile başlamaz: keşfe girmez).

`_Tmp`: her test için geçici bir `CLAUDEOPS_DIR` benzeri dizin; `settings.SETTINGS_JSON` ve değnekçi modül sabitleri
oraya yönlendirilir, gerçek `~/.claude/claudeops/` ve `settings.json`'a dokunulmaz."""
import atexit
import os
import shutil
import sys
import tempfile
import threading
import traceback
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if not os.environ.get("CLAUDEOPS_DIAG_LOG"):
    _diag = tempfile.mkdtemp(prefix="cops-test-diag-")
    atexit.register(shutil.rmtree, _diag, True)
    os.environ["CLAUDEOPS_DIAG_LOG"] = os.path.join(_diag, "diag.log")
from claudeops import question_detail, settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward  # noqa: E402


class _Tmp(unittest.TestCase):
    def _cleanup_dir(self):
        """Geçici dizini siler; silinemezse (tam pakette bir kez `Directory not empty`, yazan bulunamadı) kalan dosyaları
        ve canlı iş parçacıklarının yığınını hataya ekler: bir sonraki tekrarda yazan belli olsun."""
        try:
            self.dir.cleanup()
        except OSError as e:
            left = [os.path.relpath(os.path.join(r, f), self.dir.name) for r, _d, fs in os.walk(self.dir.name) for f in fs]
            frames = sys._current_frames()
            stacks = "\n".join(f"[{t.name}]\n" + "".join(traceback.format_stack(frames[t.ident], limit=8))
                               for t in threading.enumerate() if t is not threading.current_thread() and t.ident in frames)
            raise AssertionError(f"geçici dizin silinemedi: {e}; kalan: {left[:20]}\n{stacks}") from e

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._cleanup_dir)
        d = self.dir.name
        # Soru açınca arka plan thread'i gerçek `claude -p` çağırır ve geçici dizine yazar (temizlikle yarışır).
        qd_off = mock.patch.object(question_detail, "ensure_async", lambda *a, **k: None)
        qd_off.start()
        self.addCleanup(qd_off.stop)
        sd = os.path.join(d, "steward")
        patches = [
            mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d, "settings.json")),
            mock.patch.object(sw, "STEWARD_DIR", sd),
            mock.patch.object(sw, "PROJECTS_JSON", os.path.join(sd, "projects.json")),
            mock.patch.object(sw, "IDEAS_JSON", os.path.join(sd, "ideas.json")),
            mock.patch.object(sw, "QUESTIONS_JSON", os.path.join(sd, "questions.json")),
            mock.patch.object(sw, "STATE_JSON", os.path.join(sd, "state.json")),
            mock.patch.object(sw, "LOG_JSONL", os.path.join(sd, "log.jsonl")),
            mock.patch.object(sw, "WORKSPACE_DIR", os.path.join(sd, "workspace")),
            mock.patch.object(web_steward, "NTFY_TOPIC_FILE", os.path.join(d, "ntfy_topic.txt")),
            mock.patch.object(web_steward, "TUNNEL_URL_FILE", os.path.join(d, "tunnel_url.txt")),
            mock.patch.object(web_steward, "_in_roster", lambda name: True),    # roster reddi ayrı testte (RosterGateTest)
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
