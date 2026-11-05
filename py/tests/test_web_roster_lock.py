"""WEB-08: _toggle_comment/_replace_tsv_line roster.lock flock'u altında çalışır (geçici dizin)."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class RosterLockTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "roster.tsv")
        with open(self.p, "w", encoding="utf-8") as f:
            f.write("a\tx\nb\ty\n")

    def test_toggle_creates_lock_and_works(self):
        self.assertTrue(web._toggle_comment(self.p, "a", want_active=False))
        self.assertTrue(os.path.exists(os.path.join(self.d, "roster.lock")))
        with open(self.p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "#a\tx\nb\ty\n")

    def test_replace_keeps_comment(self):
        web._toggle_comment(self.p, "b", want_active=False)
        self.assertTrue(web._replace_tsv_line(self.p, "b", ["b", "z"]))
        with open(self.p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "a\tx\n#b\tz\n")

    def test_missing_file_false(self):
        self.assertFalse(web._toggle_comment(os.path.join(self.d, "nope.tsv"), "a", True))

    def test_concurrent_toggles_no_lost_update(self):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write("".join("n%d\tv\n" % i for i in range(20)))
        ts = [threading.Thread(target=web._toggle_comment, args=(self.p, "n%d" % i, False))
              for i in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with open(self.p, encoding="utf-8") as f:
            self.assertTrue(all(l.startswith("#") for l in f.read().splitlines()))

    def test_concurrent_appends_no_lost_line(self):
        ts = [threading.Thread(target=web._append_tsv_line, args=(self.p, ["c%d" % i, "v"])) for i in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with open(self.p, encoding="utf-8") as f:
            names = {l.split("\t")[0] for l in f.read().splitlines()}
        self.assertEqual(names, {"a", "b"} | {"c%d" % i for i in range(20)})

    def test_web_close_migrate_share_one_lock(self):
        # web `_roster_lock`, close `_rewrite_models` ve migrate-instances AYNI `<dir>/roster.lock`u almali
        from claudeops import atomic_json
        from claudeops.commands import close
        seen = []
        real = atomic_json.file_lock

        def spy(path):
            seen.append(path)
            return real(path)
        models = os.path.join(self.d, "models.tsv")
        with open(models, "w", encoding="utf-8") as f:
            f.write("a\tm\n")
        with mock.patch.object(atomic_json, "file_lock", spy), mock.patch.object(close, "MODELS_TSV", models):
            web._toggle_comment(self.p, "a", want_active=False)
            close._rewrite_models(lambda lines: ("ok", None))
        self.assertEqual(len(seen), 2)
        self.assertEqual({os.path.normpath(x) for x in seen}, {os.path.join(self.d, "roster")})

    def test_lock_reentrant_in_same_thread(self):
        with web._roster_lock(self.p):
            web._append_tsv_line(self.p, ["z", "v"])      # kilitliyken ekleme kendini kilitlememeli
        with open(self.p, encoding="utf-8") as f:
            self.assertIn("z\tv", f.read())


if __name__ == "__main__":
    unittest.main()
