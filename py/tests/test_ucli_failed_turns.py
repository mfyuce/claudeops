"""ucli `failed/` tur kayıtları panele "N başarısız tur" olarak gelir: `provider.live_failed_turns` + `web._live_failed_turns`
(stdlib unittest). Geçici dizinde çalışır; gerçek filoya/settings.json'a/tmux'a/ağa DOKUNMAZ."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops import ucli_client  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_usage import StatusDirCase  # noqa: E402


class FailedTurnsTests(StatusDirCase):
    def put(self, name, body):
        d = Path(ucli_client.chat_session_dir(self.cwd)) / "failed"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")

    def get(self, sid="s1"):
        return up.UcliProvider().live_failed_turns(self.cwd, sid)

    def test_no_directory_or_no_record_is_none_not_zero(self):
        self.assertIsNone(self.get())
        Path(ucli_client.chat_session_dir(self.cwd), "failed").mkdir(parents=True)
        self.assertIsNone(self.get())

    def test_counts_this_session_only_and_reports_the_newest_error(self):
        self.put("s1-1700000000-1.json", {"error": "old"})
        self.put("s1-1700000500-2.json", {"error": "timed out\nafter 600s"})
        self.put("s1-2-1700000900-1.json", {"error": "other session"})     # "s1-2" oturumu, s1'e SAYILMAZ
        self.put("s1-notes.json", {})
        self.put("s1-1700000600-1.txt", "x")
        r = self.get()
        self.assertEqual(r, {"count": 2, "last_unix": 1700000500, "last_error": "timed out after 600s"})

    def test_a_broken_or_errorless_record_still_counts(self):
        self.put("s1-1700000000-1.json", "{not json")
        self.assertEqual(self.get(), {"count": 1, "last_unix": 1700000000})

    def test_dict_error_uses_its_message(self):
        self.put("s1-1700000000-1.json", {"error": {"message": "HTTP 400"}})
        self.assertEqual(self.get()["last_error"], "HTTP 400")

    def test_no_sid_is_none(self):
        self.assertIsNone(self.get(None))

    def test_web_wrapper_never_raises(self):
        s = mock.Mock(cli="ucli", cwd=self.cwd, sid="s1")
        with mock.patch.object(up.UcliProvider, "live_failed_turns", side_effect=RuntimeError("x")):
            self.assertIsNone(web._live_failed_turns(s))

    def test_other_cli_has_no_failed_turns(self):
        self.assertIsNone(web._live_failed_turns(mock.Mock(cli="claude", cwd=self.cwd, sid="s1")))


if __name__ == "__main__":
    unittest.main()
