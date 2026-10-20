"""Değnekçi testlerinin ortak yardımcısı (adı `test_` ile başlamaz: keşfe girmez).

`_Tmp`: her test için geçici bir `CLAUDEOPS_DIR` benzeri dizin; `settings.SETTINGS_JSON` ve değnekçi modül sabitleri
oraya yönlendirilir, gerçek `~/.claude/claudeops/` ve `settings.json`'a dokunulmaz."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
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
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
