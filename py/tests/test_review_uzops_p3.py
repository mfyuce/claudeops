"""review uzops R-10/R-17/R-20: boş token dosyası, dict olmayan byok yaması, nesne olmayan JSON-RPC satırı."""
import io, json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web, mcp_queue
from claudeops import settings


class P3(unittest.TestCase):
    def test_empty_token_file_recreated(self):
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "token"); open(tok, "w").close()
            old = (web.TOKEN_FILE, web.CLAUDEOPS_DIR); web.TOKEN_FILE, web.CLAUDEOPS_DIR = tok, d
            try:
                t = web._load_or_create_token()
            finally:
                web.TOKEN_FILE, web.CLAUDEOPS_DIR = old
            self.assertEqual(len(t), 48); self.assertEqual(open(tok).read(), t)

    def test_non_dict_byok_patch_keeps_block(self):
        with tempfile.TemporaryDirectory() as d:
            sj = os.path.join(d, "settings.json")
            with mock.patch.object(settings, "SETTINGS_JSON", sj):
                settings.save_settings({"byok": {"claude": {"FOO_KEY": "x"}}})
                settings.save_settings({"byok": "oops"})
                self.assertEqual(settings.load_settings()["byok"], {"claude": {"FOO_KEY": "x"}})

    def test_non_object_jsonrpc_line_skipped(self):
        seen = []
        lines = "5\n[]\n\"x\"\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        with mock.patch("sys.stdin", io.StringIO(lines)), \
             mock.patch.object(mcp_queue, "_handle", side_effect=lambda p, m, *a: seen.append(m) or None):
            mcp_queue.run_server(0)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
