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


class ChatsR3Test(unittest.TestCase):
    def test_pack_checks_pipestatus(self):
        from claudeops import chat_remote as R
        self.assertIn("PIPESTATUS", R.pack_command("yuhem", "20261107", outdir="/live"))

    def test_pack_runs_and_fails_on_tar_error(self):
        import subprocess, shlex
        from claudeops import chat_remote as R
        d = tempfile.mkdtemp()
        env = dict(os.environ, HOME=d)
        open(os.path.join(d, "f"), "w").write("x")
        ok = subprocess.run(["bash", "-c", R.pack_command("t", "20261107", [("f")], d).replace(" nice -n 19 ionice -c3", "")], env=env, cwd=d)
        self.assertTrue(os.path.exists(os.path.join(d, ".chatpull-t-20261107.done")))
        os.remove(os.path.join(d, ".chatpull-t-20261107.done"))
        subprocess.run(["bash", "-c", R.pack_command("t", "20261107", ["f"], d).replace("--ignore-failed-read", "--bogus-option")], env=env, cwd=d)
        self.assertFalse(os.path.exists(os.path.join(d, ".chatpull-t-20261107.done")))
        self.assertTrue(os.path.exists(os.path.join(d, ".chatpull-t-20261107.fail")))

    def test_set_config_reset_validates_default(self):
        import json
        d = tempfile.mkdtemp()
        old = periodic.CONFIG_JSON
        periodic.CONFIG_JSON = os.path.join(d, "periodic.json")
        try:
            json.dump({"jobs": {"chat_backup": {"start": "25:99"}}}, open(periodic.CONFIG_JSON, "w"))
            try:
                periodic.set_config("chat_backup", {"start": ""})    # bozuk değer varsayılana dönünce kabul edilmeli
            except ValueError as e:
                self.fail(f"varsayılana sıfırlama reddedildi: {e}")
        finally:
            periodic.CONFIG_JSON = old


class ChatsR4Test(unittest.TestCase):
    def test_index_remote_codex_dump(self):
        from claudeops import chat_index
        c = chat_index.classify("local/codex-dump/yuhem/proj/2026-11-01/s.jsonl")
        self.assertEqual((c["host"], c["project"], c["day"]), ("yuhem", "proj", "2026-11-01"))
        c = chat_index.classify("local/codex-dump/proj/2026-11-01/s.jsonl")
        self.assertEqual((c["project"], c["day"]), ("proj", "2026-11-01"))

    def test_summary_error_not_cached(self):
        db = os.path.join(tempfile.mkdtemp(), "c", "conversations", "x.db")
        sdb = os.path.join(os.path.dirname(os.path.dirname(db)), "..", "conversation_summaries.db")
        os.makedirs(os.path.dirname(db))
        sdb = os.path.join(os.path.dirname(os.path.dirname(db)), "conversation_summaries.db")
        open(sdb, "w").write("not sqlite")                          # sqlite3.Error
        chat_dump._summary(db)
        self.assertNotIn(sdb, chat_dump._SUMM)


class ChatsR5Test(unittest.TestCase):
    def test_kv_numeric_types(self):
        self.assertEqual(C._kv(["remote_tgz_keep=5"])["remote_tgz_keep"], 5)
        self.assertEqual(C._kv(["interval_hours=0.5"])["interval_hours"], 0.5)
        with self.assertRaises(ValueError):
            C._kv(["interval_hours=abc"])

    def test_validate_rejects_bad_numbers(self):
        for k, v in (("interval_hours", -1), ("interval_hours", 0), ("remote_tgz_keep", 2.5), ("max_file_mb", "x")):
            with self.assertRaises(ValueError, msg=f"{k}={v}"):
                periodic._validate({k: v})
        periodic._validate({"interval_hours": 0.5, "remote_tgz_keep": 3, "max_file_mb": 50})

    def test_stamp_changes_with_mtime(self):
        d = tempfile.mkdtemp(); f = os.path.join(d, "a.tgz"); open(f, "wb").write(b"abc")
        s1 = chat_dump._arch_stamp(f); os.utime(f, ns=(1, 2)); self.assertNotEqual(s1, chat_dump._arch_stamp(f))


class ChatsR6Test(unittest.TestCase):
    def test_prune_enum(self):
        periodic._validate({"remote_tgz_prune": "dry"})
        periodic._validate({"remote_tgz_prune": "off"})
        with self.assertRaises(ValueError):
            periodic._validate({"remote_tgz_prune": "evet"})
