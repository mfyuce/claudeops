import datetime
import os
import shutil
import sys
import tempfile
import types
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
    def test_redact_json_password(self):
        t, n = P.redact('{"password": "hunter2xx", "parola":"gizli123"}')
        self.assertEqual(n, 2)
        self.assertNotIn("hunter2xx", t)
        self.assertNotIn("gizli123", t)

    def test_redact_escaped_json_and_spaces(self):
        t, n = P.redact('{"a":"password\\": \\"hunter2xyz\\""} password: "p@ss w0rd"')
        self.assertNotIn("hunter2xyz", t)
        self.assertNotIn("w0rd", t)
        self.assertEqual(n, 2)

    def test_gh_cred(self):
        self.assertEqual(P._gh_cred("https://github.com/x/y.git")[0], "-c")
        self.assertEqual(P._gh_cred("https://gitlab.com/x/y.git"), ())

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
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)   # 21 Kas: temizlenmeyen tmp dizinleri 2 günde 5,8 GB sızdırdı
        self.p = [mock.patch.object(P, "CONFIG_JSON", os.path.join(self.d, "periodic.json")),
                  mock.patch.object(P, "STATE_JSON", os.path.join(self.d, "state.json")),
                  mock.patch.object(P, "RUNS_DIR", os.path.join(self.d, "runs")),
                  mock.patch.object(P, "CLAUDEOPS_DIR", self.d),
                  mock.patch.object(P, "diag_log", lambda *a, **k: None)]
        for x in self.p:
            x.start()
            self.addCleanup(x.stop)
        P.set_config("usage_refresh", {"enabled": "off"})      # öntanımlı AÇIK iş testlerde gerçek okuma yapmasın (kendi testi aşağıda)
        P.set_config("model_watch", {"enabled": "off"})        # öntanımlı AÇIK iş testlerde gerçek model taraması yapmasın
        P.set_config("host_probe", {"enabled": "off"})         # öntanımlı AÇIK iş testlerde gerçek host yoklaması yapmasın
        P.set_config("orphan_watch", {"enabled": "off"})       # öntanımlı AÇIK iş testlerde gerçek süreç/soket taraması yapmasın (kendi testi test_orphan_watch.py)
        P.set_config("disk_clean", {"enabled": "off"})         # öntanımlı AÇIK iş testlerde gerçek dizinleri silmesin (kendi testi test_disk_clean.py)


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

    def _run_index(self, add_rc=0, diff_rc=0, commit_rc=0):
        self._setup_repo()
        calls = []

        def fake_git(r, *a, **k):
            calls.append(a)
            if a[0] == "rev-parse":
                return 0, "abcdef1234567890\n"
            if a[0] == "ls-remote":
                return 0, "abcdef1234567890\tHEAD\n"
            if a[0] == "add" and a[-2:] == ("INDEX.jsonl", "INDEX.md"):
                return add_rc, "add hata"
            if a[0] == "diff":
                return diff_rc, ""
            return 0, ""

        def fake_dated(r, day, *a):
            calls.append(a)
            return (commit_rc, "commit hata") if a[0] == "commit" and "INDEX guncellendi" in a else (0, "")
        with mock.patch.object(P, "_local_sources", return_value=self.srcs), \
                mock.patch.object(P, "_private_remotes", return_value=({"origin": "u"}, [])), \
                mock.patch.object(P, "_git", side_effect=fake_git), \
                mock.patch.object(P, "_git_dated", side_effect=fake_dated):
            r = P.run_chat_backup(self.cfg, True, {})
        return r, calls

    def test_index_add_failure_is_warning(self):
        r, calls = self._run_index(add_rc=1)
        self.assertIn("INDEX git add", r["msg"])
        self.assertFalse(any(c[0] == "commit" and "INDEX guncellendi" in c for c in calls))

    def test_index_no_change_no_commit(self):
        r, calls = self._run_index(diff_rc=0)
        self.assertNotIn("UYARI", r["msg"])
        self.assertFalse(any(c[0] == "commit" and "INDEX guncellendi" in c for c in calls))

    def test_index_commit_failure_is_warning(self):
        r, _ = self._run_index(diff_rc=1, commit_rc=1)
        self.assertIn("INDEX git commit", r["msg"])

    def test_remote_pull_failure_visible_in_msg(self):
        repo = self._setup_repo()
        cfg = dict(self.cfg, remote_pull={"yuhem": "shell_yuhem"})
        def fake_git(r, *a, **k):
            return (0, "abcdef1234567890\n") if a[0] == "rev-parse" else (0, "abcdef1234567890\tHEAD\n" if a[0] == "ls-remote" else "")
        from claudeops import chat_remote
        with mock.patch.object(P, "_local_sources", return_value=self.srcs), \
                mock.patch.object(P, "_private_remotes", return_value=({"origin": "u"}, [])), \
                mock.patch.object(P, "_git", side_effect=fake_git), \
                mock.patch.object(chat_remote, "pull", return_value={"ok": False, "msg": "zaman aşımı", "bytes": 0}), \
                mock.patch.object(chat_remote, "PanelTransport", return_value=object()), \
                mock.patch("claudeops.chat_dump.ingest_remote_archives", return_value={}):
            r = P.run_chat_backup(cfg, True, {})
        self.assertTrue(r["ok"])                                               # yerel yedek başarılı
        self.assertIn("UYARI uzak çekme yuhem", r["msg"])
        self.assertEqual(len(r["warnings"]), 1)

    def test_out_of_range_mtime_does_not_crash_plan(self):
        """R-2: aralık dışı st_mtime plan_chat_backup'ı düşürmemeli; gün bugüne düşer, dosya yine yedeklenir."""
        self._setup_repo()
        bad = os.path.join(self.d, "claude", "projects", "-p1", "a.jsonl")
        real_stat = os.stat

        def fake_stat(path, *a, **k):          # ext4 mtime'ı 2446'ya kısar; aralık dışı değeri stat sahtesiyle ver
            st = real_stat(path, *a, **k)
            if path == bad:
                t = list(st)[:10]
                t[8] = 10 ** 12                # yıl 33658: fromtimestamp ValueError
                return os.stat_result(t)
            return st
        with mock.patch.object(P, "_local_sources", return_value=self.srcs), \
                mock.patch.object(P.os, "stat", side_effect=fake_stat):
            plan = P.plan_chat_backup(self.cfg, {})
        ent = [e for e in plan["changed"] if e["src"] == bad]
        self.assertEqual(len(ent), 1)
        self.assertEqual(ent[0]["day"], datetime.date.today().isoformat())

    def test_binary_chunked_and_group_repo(self):
        repo = self._setup_repo()
        patch_chunk = mock.patch.object(P, "CHUNK_MB", 1)   # küçük fikstür: 45 MB yerine 1 MB eşik (2 parça yine çıkar)
        patch_chunk.start()
        self.addCleanup(patch_chunk.stop)
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

    def test_notify_failure_cooldown(self):
        sent = []
        T0 = 10_000_000.0
        with mock.patch("claudeops.commands.web_steward.notify_phone", side_effect=lambda t, **k: sent.append(t) or True):
            st = {}
            self.assertTrue(P._notify_failure("j", {"ok": False, "msg": "x"}, st, now=T0))
            self.assertFalse(P._notify_failure("j", {"ok": False, "msg": "x"}, st, now=T0 + 60))        # soğuma
            self.assertTrue(P._notify_failure("j", {"ok": False, "msg": "x"}, st, now=T0 + P.NOTIFY_COOLDOWN_S + 1))
            self.assertFalse(P._notify_failure("j", {"ok": True}, st, now=1.0))
            self.assertNotIn("last_notify", st)
        self.assertEqual(len(sent), 2)

    def test_blocks(self):
        repo = self._setup_repo()
        with mock.patch.object(P, "_local_sources", return_value=self.srcs):
            with mock.patch.object(P, "_private_remotes", return_value=({"origin": "u"}, ["origin"])):
                self.assertFalse(P.run_chat_backup(self.cfg, True, {})["ok"])   # private değil = durur
            with mock.patch.object(P, "_private_remotes", return_value=({}, [])):
                self.assertFalse(P.run_chat_backup(self.cfg, True, {})["ok"])   # remote yok
        with mock.patch.object(P, "_local_sources", return_value=self.srcs):   # gerçek home taranmasın (40 sn + gerçek repolar)
            self.assertFalse(P.run_chat_backup(dict(self.cfg, repo_dir=os.path.join(self.d, "yok"), repos={}), True, {})["ok"])


class StaleUntrackedTest(_Tmp):
    def test_vanished_untracked_path_is_not_added(self):
        """R-4: boyut sinifi degisince silinen, hic commit'lenmemis (untracked) eski parca git add'i dusurmemeli."""
        import subprocess
        repo = os.path.join(self.d, "r")
        os.makedirs(os.path.join(repo, "local"))
        git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)  # noqa: E731
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        keep = "local/new.jsonl"
        tracked_gone = "local/old.jsonl"
        for rel in (keep, tracked_gone):
            with open(os.path.join(repo, rel), "w") as f:
                f.write("x\n")
        git("add", "--", tracked_gone)
        git("commit", "-q", "-m", "i")
        os.remove(os.path.join(repo, tracked_gone))              # izlenen + silindi: silme commit'lenmeli, listede KALMALI
        files = [keep, tracked_gone, "local/ghost.jsonl.part001"]  # sonuncu: untracked ve diskte yok
        ok = P._addable_paths(repo, files)
        self.assertEqual(sorted(ok), sorted([keep, tracked_gone]))
        self.assertEqual(git("add", "--", *ok).returncode, 0)


class StateRaceTest(_Tmp):
    def test_save_job_state_waits_for_cross_process_state_lock(self):
        """R-3: _STATE_LOCK yalniz thread kilidi; baska surec (servis+CLI) oku-degistir-yaz yaparken flock beklenmeli."""
        import fcntl
        import threading
        lockp = P.STATE_JSON + ".lock"
        fd = os.open(lockp, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)                # "baska surec" tutuyor
        done = threading.Event()
        t = threading.Thread(target=lambda: (P._save_job_state("x", {"ok": True}), done.set()))
        t.start()
        try:
            self.assertFalse(done.wait(0.4), "kilit tutulurken yazim ilerlememeli")
            self.assertNotIn("x", P.load_state())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        t.join(5)
        self.assertTrue(done.is_set())
        self.assertEqual(P.load_state()["x"], {"ok": True})


class ProcLockTest(_Tmp):
    def test_second_process_lock_refused(self):
        fd = P._acquire_proc_lock()
        self.assertIsNotNone(fd)
        try:
            self.assertIsNone(P._acquire_proc_lock())     # ayrı fd = ayrı açık dosya tanımı: flock çakışır
            P.add_custom("lk1", {"kind": "command", "command": "true", "schedule": "30 3 * * *"})
            r = P.run_job("lk1", apply=False)
            self.assertIn("flock", r["msg"])
        finally:
            os.close(fd)
        fd2 = P._acquire_proc_lock()
        self.assertIsNotNone(fd2)
        os.close(fd2)


class MirrorRegressionTest(_Tmp):
    def test_old_mirror_copy_does_not_regress_after_live_deletion(self):
        live, mir = os.path.join(self.d, "live"), os.path.join(self.d, "mir")
        for r in (live, mir):
            os.makedirs(r)
        lf, mf = os.path.join(live, "s.jsonl"), os.path.join(mir, "s.jsonl")
        open(lf, "w").write("v1\nv2\n"); open(mf, "w").write("v1\n")
        os.utime(lf, (2_000_000_000, 2_000_000_000)); os.utime(mf, (1_900_000_000, 1_900_000_000))
        srcs = [(mir, os.path.join("local", "claude-projects")), (live, os.path.join("local", "claude-projects"))]
        manifest = {}
        with mock.patch.object(P, "_local_sources", return_value=srcs):
            plan = P.plan_chat_backup({}, manifest)
            self.assertEqual([e["src"] for e in plan["changed"]], [lf])           # canlı (yeni) kazanır
            sigs = {e["src"]: e["sig"] for e in plan["changed"]}
            sigs.update(P._dest_marks(plan["changed"]))
            manifest.update(sigs)
            os.remove(lf)                                                         # canlıdan silindi, ayna eski kopyayı taşıyor
            plan2 = P.plan_chat_backup({}, manifest)
            self.assertEqual(plan2["changed"], [])                                # eski ayna kopyası repodaki yeni sürümü EZMEMELİ


class LightHeavySplitTest(_Tmp):
    """20 Kas: uyanış sonrası uzun chat_backup tek kilit/tek döngü yüzünden hafif işleri (host_probe, usage_refresh) saatlerce durdurdu."""

    def test_light_job_runs_while_heavy_lock_held(self):
        P.set_config("host_probe", {"enabled": "on"})
        calls = []
        with mock.patch.dict(P.JOBS, {"host_probe": P.Job("host_probe", {}, lambda c, a, s: calls.append(1) or {"ok": True, "msg": "x"})}):
            self.assertTrue(P._LOCK.acquire(blocking=False))       # ağır iş (chat_backup) koşuyor
            fd = P._acquire_proc_lock()                            # ... ve süreç kilidi onda
            try:
                r = P.run_job("host_probe", apply=True)
            finally:
                os.close(fd)
                P._LOCK.release()
        self.assertTrue(r["ok"], r)
        self.assertEqual(calls, [1])

    def test_heavy_still_refused_while_heavy_lock_held(self):
        P.add_custom("hv1", {"kind": "command", "command": "true", "schedule": "30 3 * * *"})
        self.assertTrue(P._LOCK.acquire(blocking=False))
        try:
            self.assertIn("çalışıyor", P.run_job("hv1", apply=False)["msg"])
        finally:
            P._LOCK.release()

    def test_tick_kind_filters(self):
        P.set_config("host_probe", {"enabled": "on"})
        P.add_custom("hv2", {"kind": "command", "command": "true", "schedule": "* * * * *"})
        P.set_config("hv2", {"enabled": "on"})
        ran = []
        with mock.patch.object(P, "run_job", lambda n, apply=True: ran.append(n) or {"ok": True}):
            P.tick(kind="light")
            light = list(ran)
            ran.clear()
            P.tick(kind="heavy")
        self.assertEqual(light, ["host_probe"])
        self.assertEqual(ran, ["hv2"])

    def test_concurrent_state_saves_do_not_clobber(self):
        P._save_job_state("a", {"last_ok": True})
        P._save_job_state("b", {"last_ok": False})
        self.assertEqual(P.load_state(), {"a": {"last_ok": True}, "b": {"last_ok": False}})

    def test_wake_gap_detects_suspend_only(self):
        self.assertEqual(P.wake_gap(1000, 1060), 0.0)           # normal tur
        self.assertEqual(P.wake_gap(1000, 1000 + 3 * 60), 0.0)  # sınırda: uyanış değil
        self.assertEqual(P.wake_gap(1000, 1000 + 9 * 3600), 9 * 3600)

    def test_stuck_jobs_reported(self):
        with mock.patch.dict(P._RUNNING, {"chat_backup": 1000.0, "host_probe": 9990.0}, clear=True):
            self.assertEqual(P.stuck_jobs(now=10000.0, after_s=3600), {"chat_backup": 9000.0})


if __name__ == "__main__":
    unittest.main()


def test_local_sources_review_io_jsonl_dahil():
    from claudeops import periodic as P
    src = [s for s in P._local_sources() if s[1] == os.path.join("local", "claude-reviews")]
    assert src and src[0][0].endswith(os.sep + "reviews") and src[0][2] == "text"
    assert P._group_of(src[0][1]) == "claude"


class UsageRefreshJobTest(_Tmp):
    def test_default_on_5_minutes_and_runs_shared_refresh(self):
        P.set_config("usage_refresh", {"enabled": "on"})
        cfg = P.load_config()["usage_refresh"]
        self.assertTrue(P._is_on(cfg["enabled"]))
        self.assertAlmostEqual(float(cfg["interval_hours"]) * 60, 5.0, places=2)
        calls = []
        fake = types.SimpleNamespace(usage_refresh=lambda source="": calls.append(source) or
                                     {"providers": {"agy": {"supported": True, "available": True}, "copilot": {"supported": True, "available": False}}})
        with mock.patch.dict("sys.modules", {"claudeops.commands.web": fake}), mock.patch("claudeops.commands.web", fake, create=True):
            r = P.run_usage_refresh({}, True, {})
            self.assertEqual(P.run_usage_refresh({}, False, {})["applied"], False)
        self.assertEqual(calls, ["periodic"])
        self.assertTrue(r["ok"])
        self.assertIn("1 okundu", r["msg"])
        self.assertIn("copilot", r["msg"])

    def test_builtin_default_without_stored_config_is_on(self):
        os.remove(P.CONFIG_JSON) if os.path.exists(P.CONFIG_JSON) else None
        self.assertTrue(P._is_on(P.load_config()["usage_refresh"]["enabled"]))


def test_redact_cli_anahtar_siniflari():
    g = "AIza" + "A" * 35
    for tok in ("github_pat_" + "a1B2" * 8, "sk-proj-" + "x" * 30, g, "xoxb-1234567890-abc", "hf_" + "a" * 34, "npm_" + "a" * 36):
        out, n = P.redact("anahtar " + tok + " son")
        assert tok not in out and n >= 1, tok


def test_maske_surumu_degisince_imzalar_duser():
    m = {"/x/a.jsonl": "1:2", P._DEST_PFX + "d/a": "5", P._MASKVER_KEY: "eski"}
    st = {"chat_backup": {"manifest": m}}
    cfg = dict(P.DEFAULT_CHAT_BACKUP, dump_db=False, raw_remote="", enabled="on")
    seen = {}
    def fake_plan(c, man):
        seen.update(man)
        return {"repo": "", "seen": 0, "changed": [], "marks": {}}
    with mock.patch.object(P, "plan_chat_backup", fake_plan), mock.patch.object(P, "_local_sources", lambda: []):
        try:
            P.run_chat_backup(cfg, False, st)
        except Exception:
            pass
    assert "/x/a.jsonl" not in seen and P._DEST_PFX + "d/a" in seen


class TmpCleanupRegressionTest(unittest.TestCase):
    """21 Kas: _Tmp.setUp mkdtemp dizinini silmiyordu (2 günde 23.466 dizin, 5,8 GB /tmp). Temizlik tamamlanınca dizin kalmamalı."""

    def test_tmp_dir_removed_after_cleanup(self):
        class _Probe(_Tmp):
            def runTest(self):
                pass

        probe = _Probe()
        res = unittest.TestResult()
        probe.run(res)
        self.assertTrue(res.wasSuccessful())
        self.assertFalse(os.path.exists(probe.d), probe.d)
