import datetime, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import chat_dump, periodic
from claudeops.commands import periodic_cmd as C


class ChatsR2Test(unittest.TestCase):
    def test_kv_empty_value_resets(self):
        self.assertEqual(C._kv(["start="])["start"], "")

    def test_cron_never_run_catches_recent_slot(self):
        now = datetime.datetime(2026, 11, 18, 3, 35)
        self.assertTrue(periodic.cron_due("30 3 * * *", None, now))              # 5 dk önceki slot
        self.assertFalse(periodic.cron_due("30 3 * * *", None, now + datetime.timedelta(minutes=30)))

    def test_remote_gemini_and_codex_db_sources(self):
        h = tempfile.mkdtemp()
        ex = os.path.join(h, ".claude", "claudeops", "backups", "chat-mirror", "yuhem", "extract", ".gemini", "antigravity", "conversations")
        os.makedirs(ex)
        open(os.path.join(ex, "x.db"), "w").close()
        got = chat_dump._db_sources(h)
        self.assertIn(("gemini", "yuhem-antigravity", os.path.join(ex, "x.db")), got)


if __name__ == "__main__":
    unittest.main()
