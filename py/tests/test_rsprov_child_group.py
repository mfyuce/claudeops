"""TBD#397 soru 2 (2): yardımcı alt süreç zaman aşımına uğrayınca torunları yetim kalmaz; sinyal YALNIZ bu kodun yeni
grupta açtığı çocuğun grubuna gider. Sahte ikililer geçici dizinde; torun en çok 20 sn yaşar (testte kimse öldürülmez)."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import searxng, settings, ucli_client  # noqa: E402
from claudeops.providers import agy_provider, base, claude_provider, ucli_provider  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402


def _running(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            return f.read().rsplit(b") ", 1)[1][:1] not in (b"Z", b"X")
    except OSError:
        return False


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.mark = os.path.join(self.tmp, "torun")
        for p in (mock.patch.object(settings, "SETTINGS_JSON", os.path.join(self.tmp, "settings.json")),
                  mock.patch.object(ucli_client, "diag_log", lambda *a, **k: None, create=True),
                  mock.patch.object(claude_provider, "diag_log", lambda *a, **k: None, create=True),
                  mock.patch.object(agy_provider, "diag_log", lambda *a, **k: None),
                  mock.patch.object(ucli_provider, "diag_log", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        ucli_client._HELP_CACHE.clear()
        claude_provider._HELP_CACHE.clear()

    def script(self, name="bin", parent_exits=False):
        """Torun açar (pid'ini yazar), sonra bekler ya da hemen çıkar (boruyu torun açık tutar)."""
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(f"#!/bin/sh\nsleep 20 &\necho $! > {self.mark}\n" + ("exit 0\n" if parent_exits else "wait\n"))
        os.chmod(path, 0o755)
        return path

    def assert_grandchild_gone(self):
        with open(self.mark) as f:
            pid = int(f.read())
        deadline = time.monotonic() + 3
        while _running(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(_running(pid), f"torun yaşıyor: {pid}")


class EveryHelperKillsItsOwnGroup(_Tmp):
    def test_claude_help(self):
        with mock.patch.object(claude_provider, "_HELP_TIMEOUT_SECONDS", 1.0):
            self.assertEqual(claude_provider.claude_help_text(self.script()), "")
        self.assert_grandchild_gone()

    def test_ucli_help_when_only_the_grandchild_is_left_holding_the_pipe(self):
        with mock.patch.object(ucli_client, "_HELP_TIMEOUT_SECONDS", 1.0):
            self.assertEqual(ucli_client.chat_help_text(self.script(parent_exits=True)), "")
        self.assert_grandchild_gone()

    def test_mcp_add(self):
        spec = McpServerSpec(name="s", command="/c", args=(), allowed_tools=("t",))
        with mock.patch.object(ucli_provider, "_MCP_ADD_TIMEOUT", 1):
            self.assertFalse(ucli_provider.register_mcp(self.script(), self.tmp, spec, "vc"))
        self.assert_grandchild_gone()

    def test_oneshot(self):
        binary = self.script()

        class P(claude_provider.ClaudeProvider):
            def oneshot_argv(self, prompt, model):
                return [binary]

        with self.assertRaises(base.OneshotError):
            P().oneshot("x", None, self.tmp, timeout=1)
        self.assert_grandchild_gone()

    def test_ucli_chat_once(self):
        binary = self.script()
        with self.assertRaises(ucli_client.UcliError) as cm:
            ucli_client.ucli_chat_once(self.tmp, "soru", binary=binary, api_key="k", timeout=1)
        self.assertIn("cevap vermedi", str(cm.exception))
        self.assert_grandchild_gone()

    def test_resume(self):
        from claudeops import ucli_approval
        with mock.patch.object(ucli_client, "_subprocess_env", return_value=dict(os.environ)), \
                mock.patch.object(ucli_approval, "set_result") as done:
            res = ucli_client._run_resume("k", "a1", [self.script()], 1, None)
        self.assertFalse(res["ok"])
        self.assertIn("TimeoutExpired", done.call_args[0][2]["error"])
        self.assert_grandchild_gone()

    def test_agy_models(self):
        binary = self.script()
        with mock.patch.object(agy_provider, "resolved_binary", lambda n: binary):
            agy_provider.AgyProvider()._fetch_models()      # kendi 5 sn sınırı
        self.assert_grandchild_gone()

    def test_docker_cli(self):
        self.script("docker")
        with mock.patch.dict(os.environ, {"PATH": self.tmp + os.pathsep + os.environ["PATH"]}):
            with self.assertRaises(searxng.DockerUnavailable):
                searxng._docker("ps", timeout=1)
        self.assert_grandchild_gone()


class NeverSignalsAForeignGroup(unittest.TestCase):
    def kill(self, **popen):
        from claudeops import childgroup
        proc = subprocess.Popen(["sleep", "5"], stdout=subprocess.DEVNULL, **popen)
        with mock.patch.object(childgroup.os, "killpg") as killpg:
            childgroup._kill_group(proc)
        self.assertIsNotNone(proc.returncode)       # doğrudan çocuk her durumda sonlanır ve beklenir
        return proc, killpg

    def test_child_in_the_callers_group_gets_no_group_signal(self):
        _, killpg = self.kill()
        killpg.assert_not_called()

    def test_own_new_group_is_signalled(self):
        proc, killpg = self.kill(start_new_session=True)
        killpg.assert_called_once_with(proc.pid, mock.ANY)

    def test_group_equal_to_the_callers_is_never_signalled(self):
        from claudeops import childgroup
        proc = subprocess.Popen(["sleep", "5"], start_new_session=True)
        with mock.patch.object(childgroup.os, "getpgrp", return_value=proc.pid), \
                mock.patch.object(childgroup.os, "killpg") as killpg:
            childgroup._kill_group(proc)
        killpg.assert_not_called()

    def test_a_reaped_child_is_never_signalled(self):
        from claudeops import childgroup
        proc = subprocess.Popen(["true"], start_new_session=True)
        proc.wait()
        with mock.patch.object(childgroup.os, "killpg") as killpg:
            childgroup._kill_group(proc)
        killpg.assert_not_called()

    def test_normal_run_matches_subprocess_run(self):
        from claudeops import childgroup
        r = childgroup._run_grouped(["sh", "-c", "echo a; echo b >&2; exit 3"], timeout=10, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (3, "a\n", "b\n"))
        with self.assertRaises(subprocess.TimeoutExpired):
            childgroup._run_grouped(["sleep", "5"], timeout=0.2)


if __name__ == "__main__":
    unittest.main()
