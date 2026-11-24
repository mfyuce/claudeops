"""agy review 2026-11-25 (R-3, R-4) + günlük işte yeniden deneme. Gerçek home'u taramaz."""
import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_dump, chat_index, periodic  # noqa: E402


def _touch(*p):
    f = os.path.join(*p)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w") as fh:
        fh.write("x")
    return f


class IndexTests(unittest.TestCase):
    def test_local_reviewer_and_copilot_are_not_remote_hosts(self):
        c = chat_index.classify("local/claude-reviewer-projects/-proj/s1.jsonl")
        self.assertEqual((c["cli"], c["project"], c["session"]), ("claude-reviewer", "-proj", "s1"))
        self.assertNotIn("host", c)
        c = chat_index.classify("local/copilot-sessions/abc/events.jsonl")
        self.assertEqual((c["cli"], c["session"]), ("copilot", "abc"))
        self.assertEqual(chat_index.classify("local/claude-yuhem-projects/-p/s.jsonl")["host"], "yuhem")


class CoverageTests(unittest.TestCase):
    def test_reviewer_agy_dbs_dumped_live_first_mirror_fills_deleted(self):
        with tempfile.TemporaryDirectory() as h:
            tail = (".gemini", "antigravity-cli", "conversations")
            live = _touch(chat_dump._reviewer_root(h), "agy_home_1", *tail, "a.db")
            mir = os.path.join(chat_dump._mirror_root(h), "reviewer", "agy", "agy_home_1", *tail)
            _touch(mir, "a.db")
            gone = _touch(mir, "gone.db")
            got = {p: alt for cli, alt, p in chat_dump._db_sources(h)}
            self.assertEqual(got, {live: "reviewer-agy_home_1-antigravity-cli", gone: "reviewer-agy_home_1-antigravity-cli"})

    def test_raw_upload_includes_reviewer_and_copilot_session_store(self):
        with tempfile.TemporaryDirectory() as h:
            _touch(chat_dump._reviewer_root(h), "agy_home", ".gemini", "antigravity-cli", "conversations", "a.db")
            _touch(h, ".copilot", "session-store.db")
            seen = []
            with mock.patch("subprocess.run", side_effect=lambda cmd, **k: seen.append(cmd) or mock.Mock(returncode=0, stderr="")):
                self.assertEqual(chat_dump.raw_to_remote("r:x", home=h), "")
            flat = [" ".join(c) for c in seen]
            self.assertTrue(any("/reviewer/agy_home/gemini" in c for c in flat))
            self.assertTrue(any("/copilot " in c and "/session-store.db" in c and "data.db" not in c for c in flat))

    def test_local_sources_new_paths_and_group(self):
        with mock.patch.object(periodic, "_memory_sources", return_value=[]):
            dests = {s[1] for s in periodic._local_sources()}
        for d in ("copilot-sessions", "claude-ucli-usage", "claude-reviewer-projects", "claude-reviews"):
            p = os.path.join("local", d)
            self.assertIn(p, dests)
            self.assertEqual(periodic._group_of(p), "claude")


class SteppedPushTests(unittest.TestCase):
    def _repo(self, d):
        import subprocess
        bare, wt = os.path.join(d, "bare.git"), os.path.join(d, "wt")
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@x")

        def g(*a, cwd=wt):
            return subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True, text=True, env=env).stdout.strip()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, env=env)
        subprocess.run(["git", "init", "-q", "-b", "main", wt], check=True, env=env)
        g("remote", "add", "o", bare)
        for i in range(3):
            g("commit", "-q", "--allow-empty", "-m", str(i))
            if i == 0:
                g("push", "-q", "o", "HEAD")
        return bare, wt, g

    def test_pushes_remaining_commits_one_by_one(self):
        with tempfile.TemporaryDirectory() as d:
            bare, wt, g = self._repo(d)
            real, pushed = periodic._git, []

            def spy(repo, *a, **k):
                if "push" in a:
                    pushed.append(a[-1])
                return real(repo, *a, **k)
            with mock.patch.object(periodic, "_git", spy):
                self.assertTrue(periodic._push_stepped(wt, "o", bare))
            self.assertEqual(len(pushed), 2)
            self.assertEqual(g("rev-parse", "main", cwd=bare), g("rev-parse", "HEAD"))

    def test_diverged_remote_is_not_forced(self):
        with tempfile.TemporaryDirectory() as d:
            bare, wt, g = self._repo(d)
            g("push", "-q", "o", "HEAD")
            tip = g("rev-parse", "HEAD")
            g("reset", "-q", "--hard", "HEAD~1")
            g("commit", "-q", "--allow-empty", "-m", "other")
            self.assertFalse(periodic._push_stepped(wt, "o", bare))
            self.assertEqual(g("rev-parse", "main", cwd=bare), tip)


class RetryTests(unittest.TestCase):
    CFG = {"enabled": "on", "start": "03:30", "interval_hours": 24, "retry_hours": 1}

    def _due(self, ago_h, **st):
        now = datetime.datetime(2026, 11, 24, 12, 0)
        st["last_start"] = (now - datetime.timedelta(hours=ago_h)).timestamp()
        return periodic.is_due(self.CFG, st, now)

    def test_failed_daily_run_retried_bounded(self):
        self.assertTrue(self._due(2, last_ok=False, fail_streak=1))
        self.assertFalse(self._due(0.5, last_ok=False, fail_streak=1))
        self.assertFalse(self._due(2, last_ok=False, fail_streak=periodic.RETRY_MAX + 1))
        self.assertFalse(self._due(2, last_ok=True, fail_streak=0))
        self.CFG = dict(self.CFG, retry_hours=0)
        self.assertFalse(self._due(2, last_ok=False, fail_streak=1))


if __name__ == "__main__":
    unittest.main()
