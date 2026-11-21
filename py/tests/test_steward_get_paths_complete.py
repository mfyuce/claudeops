"""Review bulgusu (21 Kas, web_steward.py:7515): `http_get` içinde işlenen her `/api/steward/<yol>` `_GET_PATHS`'te olmalı;
yoksa uç her zaman 404 döner (örn. review/models)."""
import os
import re
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "claudeops", "commands", "web_steward.py")


class GetPathsCompleteTest(unittest.TestCase):
    def test_every_handled_get_path_is_registered(self):
        from claudeops.commands import web_steward as ws
        src = open(SRC, encoding="utf-8").read()
        body = src[src.index("def http_get("):]
        body = body[: body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
        handled = set(re.findall(r'path == "/api/steward/([a-z/_]+)"', body))
        missing = sorted(p for p in handled if p not in ws._GET_PATHS)
        self.assertEqual(missing, [], f"http_get işliyor ama _GET_PATHS'te yok: {missing}")
