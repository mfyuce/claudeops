"""Antigravity `brain/` yan dosyaları (sahip kararı 2026-11-26): gerçek haliyle, maskesiz; kayıp yok. Gerçek home'u taramaz."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_dump, chat_index, periodic  # noqa: E402

SECRET = "ghp_" + "a" * 36


def _init(d, name):
    bare, repo = os.path.join(d, name + ".git"), os.path.join(d, name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "o", bare], check=True)
    return bare, repo


def _check(repo, cfg):
    return {"o": repo + ".git"}, ""


def _w(root, rel, data=b"x"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


class BrainSourceTests(unittest.TestCase):
    def test_sources_cover_live_mirror_and_remote_in_gemini_group(self):
        with tempfile.TemporaryDirectory() as d:
            mir = os.path.join(d, "mir")
            os.makedirs(os.path.join(mir, "yuhem", "extract"))
            src = periodic._brain_sources(d, mir)
            paths = {s[0] for s in src}
            for p in (os.path.join(d, ".gemini", "antigravity", "brain"), os.path.join(mir, "gemini", "antigravity-ide", "brain"),
                      os.path.join(mir, "yuhem", "extract", ".gemini", "antigravity-cli", "brain")):
                self.assertIn(p, paths)
            self.assertEqual({(periodic._group_of(s[1]), s[2]) for s in src}, {("gemini", "raw")})
        with mock.patch.object(periodic, "_memory_sources", return_value=[]):
            self.assertIn(os.path.join("local", "gemini-brain", "antigravity"), {s[1] for s in periodic._local_sources()})

    def test_not_indexed(self):
        self.assertIsNone(chat_index.classify("local/gemini-brain/antigravity/c1/a.md"))
        self.assertIsNone(chat_index.classify("local/gemini-brain-hosts/h/antigravity/c1/a.md"))


class BrainBackupTests(unittest.TestCase):
    def test_real_content_reaches_remote_and_big_binary_goes_to_raw(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
            bare, repo, brain = os.path.join(d, "gem.git"), os.path.join(d, "gem"), os.path.join(d, "brain")
            big_text = b"satir\n" * 300000
            files = {
                "c1/.env": f"TOKEN={SECRET}\n".encode(),
                "c1/.gitignore": b".env\n*.log\n",
                "c1/run.log": b"log\r\n",
                "c1/.gitattributes": b"* text eol=lf\n",
                "c1/x": b"bir", "c1/x.tmp": b"iki", "c1/x.partial": b"uc",
                "c1/a[1].png": b"\x89PNG\0\1", "c1/-dash é.md": b"md",
                "c1/sub/.git/config": b"[core]\n",
                "c1/big.txt": big_text,
            }
            for rel, data in files.items():
                _w(brain, rel, data)
            big_bin = _w(brain, "c1/big.tar", b"\0" * (2 * 1024 * 1024))
            db = _w(brain, "c1/s.db", b"SQLite format 3\0veri")
            os.symlink("/etc/hostname", os.path.join(brain, "c1", "link"))
            uploaded = []
            with mock.patch.dict(os.environ, env):
                bare, repo = _init(d, "gem")
                _b, claude = _init(d, "cla")
                prefix = os.path.join("local", "gemini-brain", "antigravity")
                cfg = {"sources": ["local"], "dump_db": False, "raw_remote": "r:x", "repos": {"gemini": repo, "claude": claude},
                       "remote_tgz_prune": "off", "max_repo_mb": 100}
                state = {}
                with mock.patch.object(periodic, "_local_sources", return_value=[(brain, prefix, "raw")]), \
                        mock.patch.object(periodic, "CLAUDEOPS_DIR", os.path.join(d, "cops")), \
                        mock.patch.object(periodic, "_check_repo", side_effect=_check), \
                        mock.patch.object(periodic, "diag_log"), \
                        mock.patch.object(periodic, "CHUNK_MB", 1), mock.patch.object(periodic, "BATCH_FILES", 3), \
                        mock.patch.object(chat_dump, "upload_files", side_effect=lambda r, f: uploaded.extend(f) or {}):
                    res = periodic.run_chat_backup(cfg, True, state)
                    self.assertTrue(res["ok"], res)
                    self.assertNotIn("warnings", res)
                    again = periodic.run_chat_backup(cfg, True, state)
                self.assertEqual(again["changed"], 0, again)

                def show(rel):
                    return subprocess.run(["git", "-C", bare, "cat-file", "blob", f"main:{prefix}/{rel}"],
                                          check=True, capture_output=True).stdout
                for rel, data in files.items():
                    if rel == "c1/big.txt":
                        continue
                    self.assertEqual(show(rel.replace("/.git/", "/_.git/")), data, rel)
                self.assertEqual(show("c1/big.txt.part000") + show("c1/big.txt.part001"), big_text)
                tree = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", "main"], check=True,
                                      capture_output=True, text=True).stdout
                self.assertNotIn("big.tar", tree)
                self.assertNotIn("s.db", tree)
                self.assertNotIn("c1/link", tree)
                self.assertEqual({s for s, _d in uploaded}, {big_bin, db})


class LeftoverTests(unittest.TestCase):
    def test_ignored_leftover_from_half_run_is_committed(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
            bare, repo, brain = os.path.join(d, "gem.git"), os.path.join(d, "gem"), os.path.join(d, "brain")
            _w(brain, "c1/.env", b"A=1\n")
            _w(brain, "c1/.gitignore", b".env\n")
            prefix = os.path.join("local", "gemini-brain", "antigravity")
            _w(repo, prefix + "/c1/.env", b"A=1\n")          # önceki koşu yazmış, commit edememiş
            _w(repo, prefix + "/c1/.gitignore", b".env\n")
            with mock.patch.dict(os.environ, env):
                _init(d, "gem")
                _b, claude = _init(d, "cla")
                cfg = {"sources": ["local"], "dump_db": False, "raw_remote": "", "repos": {"gemini": repo, "claude": claude},
                       "remote_tgz_prune": "off", "max_repo_mb": 100}
                with mock.patch.object(periodic, "_local_sources", return_value=[(brain, prefix, "raw")]), \
                        mock.patch.object(periodic, "CLAUDEOPS_DIR", os.path.join(d, "cops")), \
                        mock.patch.object(periodic, "_check_repo", side_effect=_check), \
                        mock.patch.object(periodic, "diag_log"):
                    res = periodic.run_chat_backup(cfg, True, {})
                self.assertTrue(res["ok"], res)
                got = subprocess.run(["git", "-C", bare, "cat-file", "blob", f"main:{prefix}/c1/.env"], check=True, capture_output=True).stdout
                self.assertEqual(got, b"A=1\n")


if __name__ == "__main__":
    unittest.main()
