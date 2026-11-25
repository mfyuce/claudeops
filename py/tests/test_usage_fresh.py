"""Oturumsuz kullanım okuması (`claude -p /usage`): ayrıştırma + `_usage_all` önce taze yolu dener, olmazsa oturum yoluna düşer."""
import os
import subprocess
import types
import unittest
from unittest import mock

from claudeops.commands import web
from claudeops.providers import PROVIDERS

SAMPLE = """You are currently using your subscription to power your Claude Code usage

Current week (all models): 48% used · resets Nov 16, 6pm (Europe/Istanbul)
Current week (Fable): 8% used · resets Nov 16, 6pm (Europe/Istanbul)

What's contributing to your usage?
"""


class FreshParse(unittest.TestCase):
    def test_parse_one_line_format(self):
        e = PROVIDERS["claude"].parse_fresh_usage(SAMPLE)
        self.assertEqual([x["percent"] for x in e], ["48", "8"])
        self.assertEqual(e[0]["label"], "Current week (all models)")
        self.assertTrue(e[0]["detail"].startswith("Resets Nov 16"))

    def test_parse_falls_back_to_tui_format(self):
        tui = "Current week (all models)\n██  92% used\nResets Sep 14, 6pm (Europe/Istanbul)\n"
        e = PROVIDERS["claude"].parse_fresh_usage(tui)
        self.assertEqual(e[0]["percent"], "92")

    def test_other_providers_have_no_fresh_path(self):
        for n, p in PROVIDERS.items():
            if n not in ("claude", "agy"):
                self.assertIsNone(p.usage_fresh_argv(), n)

    def test_agy_fresh_argv_and_tsv_parse(self):
        agy = PROVIDERS["agy"]
        self.assertEqual(agy.usage_fresh_argv()[1:], ["--print=/usage"])
        tsv = ("Gemini Models\tWeekly Limit Remaining\t81%\t2026-11-25T06:06:52Z\n"
               "Claude and GPT models\tFive Hour Limit Remaining\t0%\t2026-11-18T16:39:44Z\n"
               "Gemini 4 Argon\tGemini 4 Argon Weekly Limit\t99%\t2026-11-25T12:29:11Z\n")
        es = agy.parse_fresh_usage(tsv)
        self.assertEqual([e["percent"] for e in es], ["81", "0", "99"])
        self.assertIn("Resets 2026-11-18T16:39:44Z", es[1]["detail"])


class FreshRun(unittest.TestCase):
    def _run(self, rc, out):
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")

    def test_fresh_ok_without_any_session(self):
        with mock.patch("subprocess.run", return_value=self._run(0, SAMPLE)) as r:
            res = web._usage_fresh(PROVIDERS["claude"])
        self.assertTrue(res["available"])
        self.assertEqual(res["checked_via"], "fresh")
        env = r.call_args.kwargs["env"]
        self.assertFalse(any(k.startswith("CLAUDE_CODE") for k in env))

    def test_fresh_failure_returns_none(self):
        with mock.patch("subprocess.run", return_value=self._run(1, "")):
            self.assertIsNone(web._usage_fresh(PROVIDERS["claude"]))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertIsNone(web._usage_fresh(PROVIDERS["claude"]))

    def test_signed_out_agy_is_auth_required_not_read_failed(self):
        agy = PROVIDERS["agy"]
        err = "Waiting for authentication (timeout 60s)...\n"
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("agy", 45, stderr=err.encode())):
            self.assertEqual(web._usage_fresh(agy), {"available": False, "reason": "auth_required"})
        r = types.SimpleNamespace(returncode=1, stdout="", stderr="error: authentication failed or timed out\n")
        with mock.patch("subprocess.run", return_value=r):
            self.assertEqual(web._usage_fresh(agy)["reason"], "auth_required")
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("agy", 45)):
            self.assertIsNone(web._usage_fresh(agy))

    def test_missing_binary_is_not_installed(self):
        with mock.patch("claudeops.api_balance.collect", return_value={}), \
             mock.patch.object(web, "_usage_fresh", return_value=None), \
             mock.patch.object(web, "_usage_fresh_tui", return_value=None), \
             mock.patch.object(web.shutil, "which", return_value=None):
            self.assertEqual(web._usage_all({"copilot"})["providers"]["copilot"]["reason"], "not_installed")

    def test_usage_all_prefers_fresh_and_skips_sessions(self):
        with mock.patch.object(web, "find_sessions", return_value=[]), \
             mock.patch("claudeops.api_balance.collect", return_value={"api:X": {"supported": True, "available": False, "reason": "no_endpoint"}}), \
             mock.patch.object(web.shutil, "which", return_value="/usr/bin/x"), \
             mock.patch.object(web, "_usage_fresh", side_effect=lambda p: {"available": True, "checked_via": "fresh", "entries": []} if p.name == "claude" else None):
            out = web._usage_all()["providers"]
        self.assertEqual(out["claude"]["checked_via"], "fresh")
        self.assertEqual(out["agy"].get("reason"), "read_failed")
        self.assertEqual(out["api:X"]["reason"], "no_endpoint")      # byok satırları birleştirilir

    def test_usage_never_injects_into_live_sessions(self):
        """P0 (23 Kas): fresh+tui duserse CANLI oturuma /usage enjekte EDILMEZ; 'okunamadi' doner, tmux_send_keys cagrilmaz."""
        live = types.SimpleNamespace(name="cuneiresto", cli="claude", pid=1)
        with mock.patch.object(web, "find_sessions", return_value=[live]), \
             mock.patch("claudeops.api_balance.collect", return_value={}), \
             mock.patch.object(web, "_usage_fresh", return_value=None), \
             mock.patch.object(web, "_usage_fresh_tui", return_value=None), \
             mock.patch.object(web, "tmux_send_keys") as send, \
             mock.patch.object(web, "tmux_send_special_key") as special:
            out = web._usage_all()["providers"]
        send.assert_not_called()
        special.assert_not_called()
        self.assertFalse(out["claude"]["available"])
        self.assertEqual(out["claude"]["reason"], "read_failed")
        self.assertFalse(hasattr(web, "_usage_for_session"))

    def test_api_balance_failure_does_not_break_usage(self):
        with mock.patch.object(web, "find_sessions", return_value=[]), \
             mock.patch("claudeops.api_balance.collect", side_effect=RuntimeError("boom")), \
             mock.patch.object(web, "_usage_fresh", return_value=None):
            res = web._usage_all()
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()


class NoUsageRows(unittest.TestCase):
    def test_codex_and_ucli_explain_instead_of_unsupported(self):
        from claudeops.commands import web
        for n in ("codex", "ucli"):
            r = web._no_usage_row(n)
            self.assertEqual((r["supported"], r["available"], r["reason"]), (True, False, "no_account_usage"))
            self.assertTrue(r["note"])
        self.assertEqual(web._no_usage_row("shell"), {"supported": False})

    def test_note_follows_request_language_without_mutating_state(self):
        from claudeops.commands import web
        res = {"ok": True, "at": 1.0, "providers": {n: web._no_usage_row(n) for n in ("codex", "ucli")}}
        res["providers"]["claude"] = {"supported": True, "available": True, "entries": []}
        self.assertIs(web._usage_localized(res, "tr"), res)
        en = web._usage_localized(res, "en")
        for n in ("codex", "ucli"):
            self.assertEqual(en["providers"][n]["note"], web._NO_USAGE_NOTES[n]["en"])
            self.assertEqual(res["providers"][n]["note"], web._NO_USAGE_NOTES[n]["tr"])
        self.assertEqual((en["at"], en["providers"]["claude"]), (1.0, res["providers"]["claude"]))


class PruneTranscripts(unittest.TestCase):
    def test_only_pure_usage_command_files_after_since_are_removed(self):
        import tempfile, time as _t
        from claudeops.commands import web
        d = tempfile.mkdtemp()
        mk = lambda n, txt: open(os.path.join(d, n), "w").write(txt)  # noqa: E731
        mk("usage.jsonl", '{"content":"<command-name>/usage</command-name>"}\n')
        mk("real.jsonl", '{"content":"<command-name>/usage</command-name>"}\n{"type":"assistant"}\n')
        mk("other.jsonl", '{"content":"merhaba"}\n')
        mk("big.jsonl", '<command-name>/usage</command-name>' + "x" * 30000)
        old = os.path.join(d, "old.jsonl")
        mk("old.jsonl", '<command-name>/usage</command-name>')
        os.utime(old, (1, 1))
        self.assertEqual(web._prune_usage_transcripts(_t.time() - 60, d), 1)
        self.assertEqual(sorted(os.listdir(d)), ["big.jsonl", "old.jsonl", "other.jsonl", "real.jsonl"])
        self.assertEqual(web._prune_usage_transcripts(0, os.path.join(d, "yok")), 0)


class ResolvedBinaryFallback(unittest.TestCase):
    def test_claude_found_outside_path(self):
        import tempfile
        from claudeops import settings
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "claude.exe")
        open(exe, "w").write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(settings, "load_settings", return_value={}), \
             mock.patch.dict(settings._KNOWN_BINARY_PATHS, {"claude": (exe,)}):
            self.assertEqual(settings.resolved_binary("claude"), exe)
            self.assertEqual(PROVIDERS["claude"].usage_fresh_argv()[0], exe)

    def test_provider_bin_override_used_by_usage_fresh_argv(self):
        import tempfile
        from claudeops import settings
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "claude")
        open(exe, "w").write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(settings, "load_settings", return_value={"provider_bin": {"claude": exe}}):
            self.assertEqual(PROVIDERS["claude"].usage_fresh_argv()[0], exe)
