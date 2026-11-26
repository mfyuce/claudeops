"""TBD#367 (kapalı yön) bütün otomatik gönderim yollarında: pane gizli girdi bekliyorsa ya da durum bilinmiyorsa
`tmux_send_keys` (varsayılan) hiçbir şey yazmaz. İnsanın panelden yazdığı girdi geçer; uzak otomatik gönderim
`/api/term/input` gövdesinde `auto` ile gelir."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from claudeops import tmux_backend as tb
from claudeops.commands import web, web_orch
from _tmux_iso import HAVE_TMUX, IsoTmux


class BackendGuardTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        p = mock.patch("claudeops.diaglog.diag_log", lambda ev, **d: self.events.append((ev, d)))
        p.start()
        self.addCleanup(p.stop)

    def send(self, masked, fn, *args, **kw):
        calls = []
        with mock.patch.object(tb, "pane_is_masked_input", lambda n: masked), \
                mock.patch.object(tb.subprocess, "run", lambda argv, **k: calls.append(argv) or mock.Mock(returncode=0)), \
                mock.patch.object(tb.time, "sleep", lambda s: None):
            return fn("k", *args, **kw), calls

    def test_default_refuses_masked_and_unknown(self):
        for masked, state in ((True, "masked"), (None, "unknown")):
            self.events.clear()
            ok, calls = self.send(masked, tb.tmux_send_keys, "metin")
            self.assertFalse(ok)
            self.assertEqual(calls, [])
            self.assertEqual(self.events, [("send_refused_mask", {"name": "k", "state": state})])

    def test_default_sends_when_known_unmasked(self):
        ok, calls = self.send(False, tb.tmux_send_keys, "metin")
        self.assertTrue(ok and calls)

    def test_user_typed_input_is_not_probed(self):
        ok, calls = self.send(True, tb.tmux_send_keys, "metin", guard=False)
        self.assertTrue(ok and calls)

    def test_raw_is_unguarded_for_live_typing_and_guarded_on_request(self):
        ok, calls = self.send(None, tb.tmux_send_raw, "x")
        self.assertTrue(ok and calls)
        ok, calls = self.send(None, tb.tmux_send_raw, "\r", guard=True)
        self.assertEqual((ok, calls), (False, []))


class TermInputTests(unittest.TestCase):
    def call(self, masked, **kw):
        sent = []
        s = SimpleNamespace(name="k", cli="shell")
        with mock.patch.object(web, "_term_resolve", lambda *a, **k: (s, None)), \
                mock.patch.object(web, "pane_is_masked_input", lambda n: masked), \
                mock.patch.object(web, "tmux_send_keys", lambda *a, **k: sent.append(k) or True), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web.web_ws, "notify_term_activity", lambda n: None):
            return web._term_input("k", "metin", **kw), sent

    def test_panel_input_reaches_a_password_prompt(self):
        res, sent = self.call(True)
        self.assertEqual(res, {"ok": True})
        self.assertIs(sent[0]["guard"], False)

    def test_automatic_input_is_refused_with_a_reason(self):
        for masked in (True, None):
            res, sent = self.call(masked, auto=True)
            self.assertEqual(sent, [])
            self.assertFalse(res["ok"])
            self.assertEqual(res["code"], "mask_blocked")

    def test_automatic_input_keeps_the_backend_guard(self):
        res, sent = self.call(False, auto=True)
        self.assertEqual(res, {"ok": True})
        self.assertNotIn("guard", sent[0])

    def test_remote_orchestration_marks_itself_automatic(self):
        seen = []
        with mock.patch.object(web_orch.web_hosts, "proxy_action",
                               lambda path, host, body, **k: seen.append(body) or ({"ok": True}, 200)):
            self.assertTrue(web_orch._send_prompt("uzak", "k", "claude", "metin"))
        self.assertIs(seen[0]["auto"], True)


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealPasswordPromptTests(unittest.TestCase):
    def test_automatic_send_does_not_answer_a_password_prompt(self):
        with IsoTmux() as iso, mock.patch("claudeops.diaglog.diag_log", lambda *a, **k: None):
            out = iso.dir + "/okunan"
            with open(iso.dir + "/sor.py", "w") as f:
                f.write(f"import getpass\nv = getpass.getpass('Parola: ')\nopen({out!r}, 'w').write(v)\n")
            iso.spawn("p", f"python3 -I {iso.dir}/sor.py; sleep 60")
            iso.wait(lambda: tb.pane_is_masked_input("p") is True, "parola istemi")
            self.assertFalse(tb.tmux_send_keys("p", "otomatik"))
            self.assertFalse(tb.tmux_send_raw("p", "\r", guard=True))
            self.assertIs(tb.pane_is_masked_input("p"), True)
            self.assertTrue(tb.tmux_send_keys("p", "insan", guard=False))

            def read():
                if not os.path.exists(out):
                    return ""
                with open(out) as f:
                    return f.read()

            iso.wait(lambda: read() == "insan", "yalnız insan girdisi okunsun")


if __name__ == "__main__":
    unittest.main()
