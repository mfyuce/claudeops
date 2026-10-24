"""web_review çalıştırıcı testleri: sahte Popen / sahte ikili; gerçek süreç, ağ, agy, Evren YOK. Yollar geçici dizinde."""
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

EV = rv.ReviewTarget("evren", "glm/4.6", "glm-4.6")
AGY = rv.ReviewTarget("agy", "gemini-3-flash-high", "gemini-3-flash-high")
AGY2 = rv.ReviewTarget("agy", "claude-sonnet-4", "claude-sonnet-4")
SECRET = "sk-" + "A" * 40


class FakeProc:
    instances = []

    def __init__(self, argv, out="", err="", rc=0, hang=False, **kw):
        self.argv, self.kw, self.out, self.err, self.returncode_final, self.hang = argv, kw, out, err, rc, hang
        self.pid = 424242
        self.returncode = None
        self.calls = 0
        self.release = False
        FakeProc.instances.append(self)

    def communicate(self, timeout=None):
        self.calls += 1
        if self.hang and not self.release:
            if timeout is not None and self.calls == 1 and not hasattr(self, "_wait_cancel"):
                # cancel testi için: bekle, iptal gelirse bırak
                end = time.time() + 0.3
                while not self.release and time.time() < end:
                    time.sleep(0.01)
                if not self.release:
                    raise subprocess.TimeoutExpired(self.argv, timeout, output=self.out)
        self.returncode = self.returncode_final
        return self.out, self.err

    def wait(self, timeout=None):
        self.returncode = self.returncode_final
        return self.returncode

    def poll(self):
        return self.returncode


class Base(NoRealReviewMixin, unittest.TestCase):
    def setUp(self):
        FakeProc.instances = []
        self.tmp = tempfile.mkdtemp()
        base = sw.paths_for("rev")
        r = os.path.join(self.tmp, "rev")
        os.makedirs(r)
        self.paths = dataclasses.replace(
            base, root=r, lock=os.path.join(r, ".lock"), reviews=os.path.join(r, "reviews"),
            review_pool=os.path.join(r, "review_pool.json"), review_history=os.path.join(r, "review_history.json"),
            findings=os.path.join(r, "findings.json"))
        self.cfg = NS(review_timeout_minutes=45)
        self.logdir = os.path.join(self.tmp, "log")
        os.makedirs(self.logdir)
        self.cwd = os.path.join(self.tmp, "proj")
        os.makedirs(self.cwd)
        self.assertFalse(wr._REVIEW_LOCK.locked())

    def tearDown(self):
        if wr._REVIEW_LOCK.locked():
            wr._REVIEW_LOCK.release()

    def popen(self, **kw):
        def f(argv, **k):
            return FakeProc(argv, **kw, **k)
        return f

    def ev(self, target=EV, popen=None, **kw):
        args = dict(popen=popen or self.popen(out=json.dumps({"answer": "## R-1 | P2 | t | a.py:1\nbody"})),
                    ucli_bin="/fake/ucli", api_key="KEY123", endpoint_fn=lambda: "https://ev.example/v1",
                    supports_flag=lambda b, f: True)
        args.update(kw)
        res = wr.run_job(self.paths, self.cfg, "proj", self.cwd, target, **args)
        if res.get("thread"):
            res["thread"].join(10)
        return res

    def pair(self, t):
        return rv.load_history(self.paths)["pairs"][rv.pair_key("proj", t)]


class TestEvren(Base):
    def test_argv_safe_and_key_in_env_only(self):
        res = self.ev()
        self.assertTrue(res["ok"])
        argv = FakeProc.instances[0].argv
        self.assertNotIn("--allow-edit", argv)
        self.assertNotIn("--allow-create", argv)
        self.assertNotIn("KEY123", " ".join(argv))
        self.assertIn("--max-io-mib", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "glm/4.6")
        self.assertEqual(argv[argv.index("--api-key-env") + 1], "UCLI_API_KEY")
        self.assertEqual(argv[argv.index("--max-steps") + 1], "200")
        self.assertEqual(FakeProc.instances[0].kw["env"]["UCLI_API_KEY"], "KEY123")
        self.assertTrue(FakeProc.instances[0].kw["start_new_session"])
        self.assertEqual(self.pair(EV)["status"], "done")

    def test_no_io_flag_when_unsupported(self):
        self.ev(supports_flag=lambda b, f: False)
        self.assertNotIn("--max-io-mib", FakeProc.instances[0].argv)

    def test_claude_env_filtered(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "x", "CLAUDECODE": "1", "KEEPME": "y"}):
            self.ev()
        env = FakeProc.instances[0].kw["env"]
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(env["KEEPME"], "y")

    def test_redact_applied_and_answer_extracted(self):
        self.ev(popen=self.popen(out=json.dumps({"answer": f"token {SECRET} bitti"})))
        rec = self.pair(EV)
        text = open(rec["file"]).read()
        self.assertNotIn(SECRET, text)
        self.assertIn("bitti", text)
        self.assertNotIn('"answer"', text)

    def test_timeout_writes_partial(self):
        self.cfg.review_timeout_minutes = 1
        with mock.patch.object(wr, "KILL_GRACE_SECONDS", 0.01), mock.patch.object(wr.os, "killpg") as kp:
            self.ev(popen=self.popen(out="yarim cikti", hang=True))
        rec = self.pair(EV)
        self.assertEqual(rec["status"], "partial")
        self.assertIn("timeout", rec["error"])
        self.assertIn("yarim cikti", open(rec["file"]).read())
        self.assertTrue(kp.called)

    def test_nonzero_no_output_is_error(self):
        self.ev(popen=self.popen(out="", err="boom", rc=2))
        self.assertEqual(self.pair(EV)["status"], "error")

    def test_busy_lock(self):
        wr._REVIEW_LOCK.acquire()
        res = wr.run_job(self.paths, self.cfg, "proj", self.cwd, EV, popen=self.popen(), api_key="k")
        self.assertFalse(res["ok"])
        self.assertTrue(res["busy"])

    def test_missing_key_errors_and_releases_lock(self):
        with mock.patch.object(wr, "_api_key", return_value=""):
            res = self.ev(api_key=None)
        self.assertFalse(res["ok"])
        self.assertFalse(wr._REVIEW_LOCK.locked())
        self.assertEqual(self.pair(EV)["status"], "error")


class TestCancel(Base):
    def test_cancel_kills_own_group_and_marks_partial(self):
        started = {}

        def popen(argv, **k):
            p = FakeProc(argv, out="kismi", hang=True, **k)
            started["p"] = p
            return p
        with mock.patch.object(wr.os, "killpg") as kp, mock.patch.object(wr, "KILL_GRACE_SECONDS", 0.01):
            res = wr.run_job(self.paths, self.cfg, "proj", self.cwd, EV, popen=popen, ucli_bin="/f/ucli", api_key="k",
                             endpoint_fn=lambda: "e", supports_flag=lambda b, f: False)
            for _ in range(200):
                if "p" in started and wr._JOBS:
                    break
                time.sleep(0.01)
            time.sleep(0.05)
            self.assertTrue(wr.cancel_job("proj", EV))
            started["p"].release = True
            res["thread"].join(10)
        self.assertEqual(kp.call_args_list[0].args, (424242, wr.signal.SIGTERM))
        rec = self.pair(EV)
        self.assertEqual(rec["status"], "partial")
        self.assertEqual(rec["error"], "cancelled")
        self.assertFalse(wr.cancel_job("proj", EV))


class TestAgy(Base):
    def setUp(self):
        super().setUp()
        self.fake_home = tempfile.mkdtemp()                                  # gerçek ~/.gemini'ye dokunulmaz
        real = os.path.join(self.fake_home, ".gemini", "antigravity-cli")
        os.makedirs(real)
        open(os.path.join(real, "antigravity-oauth-token"), "w").write("TOKEN-X")
        p = mock.patch.dict(os.environ, {"HOME": self.fake_home})
        p.start()
        self.addCleanup(p.stop)
        w = mock.patch.object(wr.shutil, "which", return_value=None)        # ana makinenin bwrap'ine bağımlı olma
        w.start()
        self.addCleanup(w.stop)

    def test_isolated_home_with_readonly_allow_list(self):
        self.agy()
        env = FakeProc.instances[0].kw["env"]
        home = env["HOME"]
        self.assertTrue(home.endswith("agy_home"))
        self.assertNotEqual(home, self.fake_home)
        cfgdir = os.path.join(home, ".gemini", "antigravity-cli")
        st = json.load(open(os.path.join(cfgdir, "settings.json")))
        self.assertEqual(st["permissions"]["allow"], ["command(ls)", "command(grep)", "command(head)", "command(tail)", "command(wc)"])
        self.assertFalse(st["allowNonWorkspaceAccess"])
        self.assertEqual(st["trustedWorkspaces"], [self.cwd])
        self.assertEqual(open(os.path.join(cfgdir, "antigravity-oauth-token")).read(), "TOKEN-X")
        self.assertEqual(os.stat(os.path.join(cfgdir, "antigravity-oauth-token")).st_mode & 0o777, 0o600)
        for banned in ("rg", "git", "find", "cat", "sed", "sh", "rm"):
            self.assertNotIn(f"command({banned})", st["permissions"]["allow"])

    def test_bwrap_jail_wraps_argv_when_available(self):
        with mock.patch.object(wr.shutil, "which", return_value="/usr/bin/bwrap"):
            self.agy()
        a = FakeProc.instances[0].argv
        home = FakeProc.instances[0].kw["env"]["HOME"]
        self.assertEqual(a[0], "/usr/bin/bwrap")
        self.assertEqual(a[1:4], ["--ro-bind", "/", "/"])
        self.assertEqual(a[a.index("--bind") + 1:a.index("--bind") + 3], [home, home])        # yalnız izole HOME yazılabilir
        for f in ("--unshare-pid", "--new-session", "--die-with-parent"):
            self.assertIn(f, a)
        i = a.index("--")
        self.assertEqual(a[i + 1:i + 3], ["/fake/agy", "--dangerously-skip-permissions"])
        self.assertEqual(a.count("--bind"), 1)                                                 # proje/ev dizini bağlanmaz
        self.assertEqual(a[-2:], ["--mode", "plan"])

    def test_no_bwrap_or_jail_off_falls_back_to_allow_list(self):
        with mock.patch.object(wr.shutil, "which", return_value=None):
            self.agy()
        a = FakeProc.instances[0].argv
        self.assertEqual(a[0], "/fake/agy")
        self.assertNotIn("--dangerously-skip-permissions", a)
        FakeProc.instances = []
        self.cfg.review_agy_jail = False
        with mock.patch.object(wr.shutil, "which", return_value="/usr/bin/bwrap"):
            self.agy()
        self.assertNotIn("--dangerously-skip-permissions", FakeProc.instances[0].argv)
        FakeProc.instances = []
        self.cfg.review_agy_jail = True
        self.cfg.review_agy_allow = "off"                                                       # izolasyon kapalı = kafes de yok
        with mock.patch.object(wr.shutil, "which", return_value="/usr/bin/bwrap"):
            self.agy()
        self.assertNotIn("--dangerously-skip-permissions", FakeProc.instances[0].argv)

    def test_allow_override_and_off(self):
        self.cfg.review_agy_allow = "ls, grep ,bad name;rm"
        self.agy()
        st = json.load(open(os.path.join(FakeProc.instances[0].kw["env"]["HOME"], ".gemini", "antigravity-cli", "settings.json")))
        self.assertEqual(st["permissions"]["allow"], ["command(ls)", "command(grep)"])
        FakeProc.instances = []
        self.cfg.review_agy_allow = "off"
        self.agy()
        self.assertNotEqual(FakeProc.instances[0].kw["env"].get("HOME"), os.path.join(self.fake_home, "agy_home"))
        self.assertNotIn("agy_home", FakeProc.instances[0].kw["env"].get("HOME", ""))

    def prov(self, levels=("high",)):
        p = mock.Mock()
        p.model_effort_levels.side_effect = lambda m: list(levels) if m.endswith("-high") else None
        p.resolve_effort.side_effect = lambda m, r: "high"
        return p

    def agy(self, target=AGY, label="gemini-3-flash-high", models=None, **kw):
        log = os.path.join(self.logdir, "cli-1.log")
        t0 = time.time()
        if label is not None:
            with open(log, "w") as f:
                f.write(f"x Propagating selected model override foo label={label}\n")
        os.utime(log, (t0 + 5, t0 + 5)) if label is not None else None
        return self.ev(target=target, popen=self.popen(out="## R-1 | P3 | t | a:1\nok"), agy_bin="/fake/agy",
                       agy_log_dir=self.logdir, agy_models=models or [target.model], provider=self.prov(), **kw)

    def test_ok_done_and_argv(self):
        self.agy()
        argv = FakeProc.instances[0].argv
        self.assertEqual(argv[0], "/fake/agy")
        self.assertTrue(argv[1].startswith("--print="))
        self.assertEqual(argv[-2:], ["--mode", "plan"])
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        self.assertEqual(FakeProc.instances[0].kw["cwd"], self.cwd)
        rec = self.pair(AGY)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["label_seen"], "gemini-3-flash-high")

    def test_label_mismatch_is_model_fallback_but_file_kept(self):
        self.agy(label="gemini-3-flash-low")
        rec = self.pair(AGY)
        self.assertEqual(rec["status"], "model_fallback")
        self.assertTrue(os.path.isfile(rec["file"]))

    def test_no_log_is_model_fallback(self):
        self.agy(label=None)
        self.assertEqual(self.pair(AGY)["status"], "model_fallback")

    def test_no_effort_for_non_gemini(self):
        self.agy(target=AGY2, label="claude-sonnet-4")
        self.assertNotIn("--effort", FakeProc.instances[0].argv)

    def test_model_not_in_agy_list(self):
        res = self.ev(target=AGY, popen=self.popen(), agy_bin="/f/agy", agy_log_dir=self.logdir,
                      agy_models=["other"], provider=self.prov())
        self.assertFalse(res["ok"])
        self.assertEqual(FakeProc.instances, [])
        self.assertEqual(self.pair(AGY)["status"], "error")


class TestRecover(Base):
    def test_recover_on_start(self):
        rv.update_pair(self.paths, "proj", EV, status="running", started_at=1.0)
        rv.update_pair(self.paths, "other", EV, status="done", started_at=1.0, finished_at=2.0)
        self.assertEqual(wr.recover_on_start(self.paths, now=lambda: 99.0), 1)
        self.assertEqual(self.pair(EV)["status"], "partial")
        self.assertEqual(rv.load_history(self.paths)["pairs"][rv.pair_key("other", EV)]["status"], "done")
        self.assertEqual(wr.recover_on_start(self.paths), 0)


if __name__ == "__main__":
    unittest.main()
