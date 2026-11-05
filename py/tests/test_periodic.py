import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import periodic as P  # noqa: E402

D = datetime.datetime


class CronTest(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(P.parse_cron("x"))
        self.assertIsNone(P.parse_cron("61 * * * *"))
        self.assertIsNone(P.parse_cron("* * * *"))
        self.assertIsNotNone(P.parse_cron("*/15 0-6 * * 1-5"))
        self.assertIn(0, P.parse_cron("0 0 * * 7")[4])

    def test_due(self):
        now = D(2026, 11, 5, 3, 30, 5)
        self.assertTrue(P.cron_due("30 3 * * *", None, now))
        self.assertFalse(P.cron_due("30 3 * * *", D(2026, 11, 5, 3, 30), now))   # aynı dakika zaten çalıştı
        self.assertTrue(P.cron_due("30 3 * * *", D(2026, 11, 4, 3, 30), now))
        self.assertFalse(P.cron_due("0 4 * * *", D(2026, 11, 5, 3, 0), now))
        self.assertTrue(P.cron_due("0 3 * * *", D(2026, 11, 4, 3, 0), D(2026, 11, 5, 3, 31)))  # kaçan dakika yakalanır

    def test_is_due_defaults(self):
        cfg = dict(P.DEFAULT_CHAT_BACKUP)
        self.assertFalse(P.is_due(cfg, {}, D(2026, 11, 5, 9, 0)))       # varsayılan KAPALI
        cfg["enabled"] = "on"
        self.assertFalse(P.is_due(cfg, {}, D(2026, 11, 5, 3, 0)))       # start öncesi
        self.assertTrue(P.is_due(cfg, {}, D(2026, 11, 5, 3, 31)))
        last = D(2026, 11, 5, 3, 31).timestamp()
        self.assertFalse(P.is_due(cfg, {"last_start": last}, D(2026, 11, 5, 20, 0)))
        self.assertTrue(P.is_due(cfg, {"last_start": last}, D(2026, 11, 6, 3, 31)))
        cfg.update(interval_hours=2)
        self.assertFalse(P.is_due(cfg, {"last_start": last}, D(2026, 11, 5, 5, 0)))
        self.assertTrue(P.is_due(cfg, {"last_start": last}, D(2026, 11, 5, 5, 32)))


class RedactTest(unittest.TestCase):
    def test_redact(self):
        t, n = P.redact('x sk-ant-api03-ABCDEFGHIJ y ghp_' + "a" * 24 + ' password: hunter2xx ok')
        self.assertEqual(n, 3)
        self.assertNotIn("hunter2xx", t)
        self.assertNotIn("sk-ant", t)
        self.assertIn("password: " + P._REDACT, t)
        self.assertEqual(P.redact("düz metin")[1], 0)



class _Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = [mock.patch.object(P, "CONFIG_JSON", os.path.join(self.d, "periodic.json")),
                  mock.patch.object(P, "STATE_JSON", os.path.join(self.d, "state.json")),
                  mock.patch.object(P, "RUNS_DIR", os.path.join(self.d, "runs")),
                  mock.patch.object(P, "CLAUDEOPS_DIR", self.d),
                  mock.patch.object(P, "diag_log", lambda *a, **k: None)]
        for x in self.p:
            x.start()
            self.addCleanup(x.stop)


class CustomJobTest(_Tmp):
    def test_add_validate_and_run(self):
        with self.assertRaises(ValueError):
            P.add_custom("Bad-Id", {"command": "echo"})
        with self.assertRaises(ValueError):
            P.add_custom("chat_backup", {"command": "echo"})
        with self.assertRaises(ValueError):
            P.add_custom("a1", {"kind": "command", "command": "echo", "schedule": "nope"})
        with self.assertRaises(ValueError):
            P.add_custom("a2", {"kind": "prompt"})
        with self.assertRaises(KeyError):
            P.add_custom("a3", {"command": "echo", "zzz": 1})
        c = P.add_custom("hello", {"kind": "command", "command": "echo merhaba", "schedule": "*/5 * * * *"})
        self.assertEqual(c["enabled"], "off")
        self.assertEqual(P.tick(D(2026, 11, 5, 3, 5)), [])               # kapalı = çalışmaz
        P.set_config("hello", {"enabled": "on"})
        self.assertEqual(P.tick(D(2026, 11, 5, 3, 5)), ["hello"])
        st = P.load_state()["hello"]
        self.assertTrue(st["last_ok"])
        self.assertIn("merhaba", st["last_msg"])
        self.assertEqual(len(os.listdir(os.path.join(P.RUNS_DIR, "hello"))), 1)

    def test_set_unknown_and_remove(self):
        with self.assertRaises(KeyError):
            P.set_config("yok", {"enabled": "on"})
        with self.assertRaises(KeyError):
            P.set_config("chat_backup", {"zzz": 1})
        P.add_custom("x1", {"command": "true"})
        self.assertTrue(P.remove_custom("x1"))
        self.assertFalse(P.remove_custom("x1"))
        self.assertEqual(P.api_action({"action": "remove", "id": "chat_backup"})["ok"], False)

    def test_failing_command_recorded(self):
        P.add_custom("bad", {"command": "false"})
        r = P.run_job("bad")
        self.assertFalse(r["ok"])
        self.assertFalse(P.load_state()["bad"]["last_ok"])

    def test_prompt_skipped_when_quota_blocked(self):
        P.add_custom("pr", {"kind": "prompt", "prompt": "merhaba"})
        with mock.patch.object(P, "_quota_blocked", return_value=True), mock.patch.object(P.subprocess, "run") as run:
            r = P.run_job("pr")
        self.assertTrue(r.get("skipped"))
        run.assert_not_called()


class ChatBackupTest(_Tmp):
    def _setup_repo(self):
        repo = os.path.join(self.d, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        src = os.path.join(self.d, "claude", "projects", "-p1")
        os.makedirs(src)
        with open(os.path.join(src, "a.jsonl"), "w") as f:
            f.write('{"t":"token sk-ant-api03-ABCDEFGHIJKL"}\n')
        hist = os.path.join(self.d, "claude", "history.jsonl")
        with open(hist, "w") as f:
            f.write("{}\n")
        self.cfg = dict(P.DEFAULT_CHAT_BACKUP, repo_dir=repo, enabled="on", dump_db=False, raw_remote="")
        self.srcs = [(os.path.join(self.d, "claude", "projects"), os.path.join("local", "claude-projects")),
                     (hist, os.path.join("local", "claude-history"))]
        return repo

    def test_plan_then_apply(self):
        repo = self._setup_repo()
        calls = []

        def fake_git(r, *a, **k):
            calls.append(a)
            if a[0] == "rev-parse":
                return 0, "abcdef1234567890\n"
            if a[0] == "ls-remote":
                return 0, "abcdef1234567890\tHEAD\n"
            return 0, ""
        pm = mock.patch.object(P, "_local_sources", return_value=self.srcs)
        pr = mock.patch.object(P, "_private_remotes", return_value=({"origin": "git@gitlab.com:x/y.git"}, []))
        pg = mock.patch.object(P, "_git", side_effect=fake_git)
        with pm, pr, pg:
            st = {}
            r = P.run_chat_backup(self.cfg, False, st)
            self.assertTrue(r["ok"] and not r["applied"] and r["changed"] == 2)
            self.assertFalse(os.path.exists(os.path.join(repo, "local")))      # plan yazmaz
            r = P.run_chat_backup(self.cfg, True, st)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["written"], 2)
            self.assertEqual(r["redacted"], 1)
            gz = os.path.join(repo, "local", "claude-projects", "-p1", "a.jsonl")
            with open(gz) as fh:
                txt = fh.read()
            self.assertNotIn("sk-ant", txt)
            self.assertEqual(oct(os.stat(gz).st_mode & 0o777), "0o600")
            adds = [c for c in calls if c[0] == "add" and "INDEX.jsonl" not in c]
            self.assertTrue(any(c[0] == "add" and c[-2:] == ("INDEX.jsonl", "INDEX.md") for c in calls))   # INDEX açık yolla
            self.assertEqual(len(adds), 1)
            self.assertNotIn("-A", adds[0])
            self.assertNotIn(".", adds[0][2:])                                  # açık yollar, nokta/-A yok
            self.assertTrue(any("push" in c for c in calls))
            self.assertTrue(any(c[0] == "ls-remote" for c in calls))
            r2 = P.run_chat_backup(self.cfg, True, st)                         # değişmeyen = iş yok
            self.assertEqual(r2["changed"], 0)

    def test_binary_chunked_and_group_repo(self):
        repo = self._setup_repo()
        codex = os.path.join(self.d, "codexrepo")
        os.makedirs(os.path.join(codex, ".git"))
        big = os.path.join(self.d, "g", "c.db")
        os.makedirs(os.path.dirname(big))
        with open(big, "wb") as f:
            f.write(b"x" * (P.CHUNK_MB * 1024 * 1024 + 10))
        srcs = self.srcs + [(os.path.dirname(big), os.path.join("local", "codex-db"), "bin")]
        cfg = dict(self.cfg, repos={"codex": codex})
        plan_src = mock.patch.object(P, "_local_sources", return_value=srcs)
        with plan_src:
            plan = P.plan_chat_backup(cfg, {})
            ent = [e for e in plan["changed"] if e["src"] == big][0]
            self.assertEqual((ent["group"], ent["kind"]), ("codex", "bin"))
            written, _sigs, stats = P._write_changed(plan, cfg)
        parts = sorted(w for w in written if w.startswith("local/codex-db/c.db.part"))
        self.assertEqual(len(parts), 2)
        self.assertIn(ent["day"], stats["days"]["codex"])
        with open(os.path.join(codex, parts[0]), "rb") as f:
            self.assertEqual(len(f.read()), P.CHUNK_MB * 1024 * 1024)

    def test_memory_group(self):
        repo = self._setup_repo()
        home = os.path.join(self.d, "home")
        md = os.path.join(home, ".claude", "projects", "-p9", "memory")
        os.makedirs(md)
        with open(os.path.join(md, "m.md"), "w") as f:
            f.write("key sk-ant-api03-ABCDEFGHIJKL\n")
        with open(os.path.join(md, "x.db"), "wb") as f:
            f.write(b"SQLite\0\0\1")
        with open(os.path.join(md, "x.db-shm"), "wb") as f:
            f.write(b"s")
        srcs = P._memory_sources(home, os.path.join(home, "mir"))
        with mock.patch.object(P, "_local_sources", return_value=srcs):
            plan = P.plan_chat_backup(self.cfg, {})
            dests = sorted(e["dest"] for e in plan["changed"])
            self.assertEqual(len(dests), 2)                                     # -shm dışlandı
            self.assertTrue(all(d.startswith("memory/") and "/claude/-p9/" in d for d in dests))
            self.assertEqual({e["group"] for e in plan["changed"]}, {"claude"})
            written, _s, stats = P._write_changed(plan, self.cfg)
        txt = open(os.path.join(repo, [w for w in written if w.endswith("m.md")][0])).read()
        self.assertNotIn("ABCDEFGHIJKL", txt)
        self.assertEqual(open(os.path.join(repo, [w for w in written if w.endswith("x.db")][0]), "rb").read(), b"SQLite\0\0\1")

    def test_zst_and_unvalidated_claude(self):
        repo = self._setup_repo()
        z = os.path.join(self.d, "z", "s.jsonl.zst")
        os.makedirs(os.path.dirname(z))
        open(z, "wb").write(b"\x28\xb5\x2f\xfd\0zst")
        srcs = [(os.path.dirname(z), os.path.join("local", "codex-sessions"), "text")]
        codex = os.path.join(self.d, "codexrepo")
        os.makedirs(os.path.join(codex, ".git"))
        cfg = dict(self.cfg, repos={"codex": codex})
        with mock.patch.object(P, "_local_sources", return_value=srcs):
            plan = P.plan_chat_backup(cfg, {})
            self.assertEqual(len(plan["changed"]), 1)                          # .zst artık görülüyor
            written, _s, _st = P._write_changed(plan, cfg)
            self.assertEqual(open(os.path.join(codex, written[0]), "rb").read()[:4], b"\x28\xb5\x2f\xfd")   # ham, bozulmadan
            # claude doğrulanmadı => repo_dir'e yazma yok
            srcs2 = self.srcs
        with mock.patch.object(P, "_local_sources", return_value=srcs2), \
                mock.patch.object(P, "_check_repo", side_effect=lambda r, c: (None, "doğrulanamadı") if r == repo else ({"origin": "u"}, "")):
            res = P.run_chat_backup(dict(cfg, repos={}), True, {})
            self.assertFalse(res["ok"])
            self.assertFalse(os.path.exists(os.path.join(repo, "local")))

    def test_stale_parts_removed(self):
        self._setup_repo()
        codex = os.path.join(self.d, "codexrepo2")
        os.makedirs(os.path.join(codex, ".git"))
        src = os.path.join(self.d, "g2", "c.db")
        os.makedirs(os.path.dirname(src))
        old = os.path.join(codex, "local", "codex-db", "c.db.part001")
        os.makedirs(os.path.dirname(old))
        open(old, "wb").write(b"eski")
        open(src, "wb").write(b"kucuk")
        cfg = dict(self.cfg, repos={"codex": codex})
        srcs = [(os.path.dirname(src), os.path.join("local", "codex-db"), "bin")]
        with mock.patch.object(P, "_local_sources", return_value=srcs):
            plan = P.plan_chat_backup(cfg, {})
            written, _s, st = P._write_changed(plan, cfg)
        self.assertFalse(os.path.exists(old))
        self.assertIn("local/codex-db/c.db.part001", written)
        self.assertEqual(open(os.path.join(codex, "local/codex-db/c.db"), "rb").read(), b"kucuk")

    def test_blocks(self):
        repo = self._setup_repo()
        with mock.patch.object(P, "_local_sources", return_value=self.srcs):
            with mock.patch.object(P, "_private_remotes", return_value=({"origin": "u"}, ["origin"])):
                self.assertFalse(P.run_chat_backup(self.cfg, True, {})["ok"])   # private değil = durur
            with mock.patch.object(P, "_private_remotes", return_value=({}, [])):
                self.assertFalse(P.run_chat_backup(self.cfg, True, {})["ok"])   # remote yok
        with mock.patch.object(P, "_local_sources", return_value=self.srcs):   # gerçek home taranmasın (40 sn + gerçek repolar)
            self.assertFalse(P.run_chat_backup(dict(self.cfg, repo_dir=os.path.join(self.d, "yok"), repos={}), True, {})["ok"])


if __name__ == "__main__":
    unittest.main()
