"""`py/cops winact` (commands/winact.py, TODO.md 2026-10-16) testleri: tmux şeridi menüsünün çağırdığı komut.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_winact.py' -v

Panele, tmux'a ve canlı süreçlere DOKUNMAZ: `run_action`, `tmux_message`, `tmux_client_session` sahte; kilit dizini geçici.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import cli, window_actions as wa  # noqa: E402
from claudeops.commands import winact  # noqa: E402


class Rig:
    """Bir `winact` çağrısını sahte bağımlılıklarla koşturur; çıktıları ve çağrıları toplar."""

    def __init__(self, tc: unittest.TestCase, result=None, session="ae", run_raises=None):
        self.tmp = tempfile.TemporaryDirectory()
        tc.addCleanup(self.tmp.cleanup)
        self.result = result if result is not None else wa.Result(True, "✓ tamam")
        self.session = session
        self.run_raises = run_raises
        self.runs, self.messages, self.events = [], [], []

    def go(self, *argv):
        args = cli.build_parser().parse_args(["winact", *argv])

        def fake_run(client, action_id, host, name, **kw):
            self.runs.append((action_id, host, name, client.port))
            if self.run_raises:
                raise self.run_raises
            return self.result

        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name}))
            st.enter_context(mock.patch.object(winact, "run_action", fake_run))
            st.enter_context(mock.patch.object(winact, "tmux_message",
                                               lambda client, text, ms=0: self.messages.append((client, text, ms)) or True))
            st.enter_context(mock.patch.object(winact, "tmux_client_session",
                                               lambda client: self.session if client == "/dev/pts/9" else None))
            st.enter_context(mock.patch.object(winact, "diag_log", lambda event, **kw: self.events.append((event, kw))))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            code = args.func(args)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code


class ParserTests(unittest.TestCase):
    def test_registered_and_parses(self):
        a = cli.build_parser().parse_args(["winact", "restart", "--client", "/dev/pts/9", "--port", "9000"])
        self.assertEqual((a.action, a.name, a.client, a.port, a.host), ("restart", "", "/dev/pts/9", 9000, "local"))

    def test_unknown_action_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["winact", "format-disk", "ae"])


class FromTmuxTests(unittest.TestCase):
    def test_name_is_resolved_from_the_client_and_the_action_runs_against_the_local_host(self):
        rig = Rig(self)
        self.assertEqual(rig.go("stop", "--client", "/dev/pts/9"), 0)
        self.assertEqual(rig.runs, [("stop", "local", "ae", 8765)])

    def test_nothing_is_ever_printed_when_a_client_is_given(self):
        # run-shell çıktıyı pane'in üstünde bir görünüm olarak açar: stdout/stderr SUSMALI
        for result in (wa.Result(True, "✓ tamam"), wa.Result(False, "✗ olmadı")):
            rig = Rig(self, result=result)
            rig.go("handover", "--client", "/dev/pts/9")
            self.assertEqual((rig.out, rig.err), ("", ""))

    def test_a_start_notice_is_shown_first_then_a_failure_is_shown_for_longer(self):
        rig = Rig(self, result=wa.Result(False, "✗ durdurulamadı: x"))
        self.assertEqual(rig.go("stop", "--client", "/dev/pts/9"), 1)
        self.assertEqual([m[0] for m in rig.messages], ["/dev/pts/9", "/dev/pts/9"])
        self.assertTrue(rig.messages[0][1].startswith("… Durdur"))
        self.assertEqual(rig.messages[1][1], "✗ durdurulamadı: x")
        self.assertGreater(rig.messages[1][2], rig.messages[0][2])

    def test_destructive_successes_stay_silent_because_the_window_goes_away(self):
        for action in ("stop", "restart", "reset"):
            rig = Rig(self)
            self.assertEqual(rig.go(action, "--client", "/dev/pts/9"), 0)
            self.assertEqual(len(rig.messages), 1, action)   # yalnız "çalışıyor" bildirimi

    def test_sessionless_successes_are_confirmed_on_the_client(self):
        for action in ("handover", "newchat"):
            rig = Rig(self, result=wa.Result(True, "✓ yeni chat: ae_1", name="ae_1"))
            self.assertEqual(rig.go(action, "--client", "/dev/pts/9"), 0)
            self.assertEqual(rig.messages[-1][1], "✓ yeni chat: ae_1", action)

    def test_an_unresolvable_client_is_reported_and_nothing_runs(self):
        rig = Rig(self)
        self.assertEqual(rig.go("stop", "--client", "/dev/pts/77"), 2)
        self.assertEqual(rig.runs, [])
        self.assertIn("bağlı görünmüyor", rig.messages[-1][1])

    def test_a_crash_inside_the_action_becomes_a_message_and_releases_the_lock(self):
        rig = Rig(self, run_raises=RuntimeError("boom"))
        self.assertEqual(rig.go("stop", "--client", "/dev/pts/9"), 1)
        self.assertIn("iç hata", rig.messages[-1][1])
        self.assertIn("winact_error", [e for e, _ in rig.events])
        again = wa.ActionLock("local", "ae", directory=rig.tmp.name)   # istisna kilidi tutulu bırakmadı
        again.acquire()
        again.release()


class ManualTests(unittest.TestCase):
    def test_explicit_name_and_host_without_a_client_print_the_result(self):
        rig = Rig(self)
        self.assertEqual(rig.go("restart", "ae20261016", "--host", "yuhem", "--port", "9000"), 0)
        self.assertEqual(rig.runs, [("restart", "yuhem", "ae20261016", 9000)])
        self.assertEqual(rig.messages, [])
        self.assertIn("✓ tamam", rig.out)

    def test_failure_goes_to_stderr_with_exit_one(self):
        rig = Rig(self, result=wa.Result(False, "✗ olmadı"))
        self.assertEqual(rig.go("stop", "ae"), 1)
        self.assertIn("✗ olmadı", rig.err)
        self.assertEqual(rig.out, "")

    def test_neither_name_nor_client_is_a_usage_error(self):
        rig = Rig(self)
        self.assertEqual(rig.go("stop"), 2)
        self.assertEqual(rig.runs, [])
        self.assertIn("ad verin", rig.err)


class LockTests(unittest.TestCase):
    def test_a_second_action_on_the_same_session_is_refused_without_running(self):
        rig = Rig(self)
        held = wa.ActionLock("local", "ae", directory=rig.tmp.name)
        held.acquire()
        self.addCleanup(held.release)
        self.assertEqual(rig.go("restart", "ae"), 1)
        self.assertEqual(rig.runs, [])
        self.assertIn("başka bir pencere eylemi sürüyor", rig.err)

    def test_begin_and_end_are_logged(self):
        rig = Rig(self)
        rig.go("stop", "ae")
        names = [e for e, _ in rig.events]
        self.assertEqual(names, ["winact_begin", "winact_end"])
        self.assertEqual(rig.events[1][1]["ok"], True)


if __name__ == "__main__":
    unittest.main()
