"""Direktif teslim garantisi: kapalı oturumda `queued` + arka plan, pane doğrulama (Enter / yeniden gönder), durum görünürlüğü,
RFH ile bitmiş canlı oturuma yazmama (exact durdur + fresh başlat)."""
import os
import sys
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

MSG = "BASLIK: lutfen su isi yap ve raporla"


class Pane:
    """Sahte tmux paneli: gönderimde `on_send` ile pane metnini değiştirir."""
    def __init__(self, text="", on_send=None):
        self.text, self.on_send, self.sends, self.enters = text, on_send, 0, 0

    def capture(self, name, lines=2000):
        return self.text

    def send(self, name, cli, message, sid="default"):
        self.sends += 1
        if self.on_send:
            self.text = self.on_send(self, message)
        return True

    def raw(self, name, data):
        self.enters += 1
        self.text = self.text.replace("[Pasted text #1 +3 lines]", "") + "\n" + MSG
        return True


def box(inner):
    """Claude Code 2.1.332 giriş kutusu (gerçek yakalama): gri çizgi, `❯`, devam satırları girintili, gri çizgi."""
    rule = "\x1b[38;5;244m" + "─" * 40
    body = inner.replace("\n", "\n  ")
    return rule + "\n\x1b[39m❯\xa0" + body + "\n" + rule + "\n\x1b[39m  ⏵⏵ auto mode on"


def verify(pane, cli="claude"):
    with mock.patch.object(ws, "tmux_capture", pane.capture), mock.patch.object(ws, "_send", pane.send), \
            mock.patch.object(ws, "tmux_send_raw", pane.raw):
        return ws._send_verified("n", cli, MSG, sleep=lambda s: None)


class SendVerified(unittest.TestCase):
    def test_delivered_when_message_appears(self):
        p = Pane("", on_send=lambda self, m: self.text + "\n" + m)
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.sends, 1)

    def test_old_identical_header_does_not_fake_delivery(self):
        p = Pane(MSG, on_send=lambda self, m: self.text)      # eski kopya var, yeni gönderim görünmüyor
        self.assertEqual(verify(p), "failed")
        self.assertEqual(p.sends, 1 + ws.DELIVERY_MAX_RESENDS)

    def test_pasted_text_in_box_gets_enter(self):
        p = Pane("", on_send=lambda self, m: "x\n❯ [Pasted text #1 +3 lines]")
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.enters, 1)

    def test_pasted_text_ignoring_enter_gets_space_then_enter(self):
        """Sahip gözlemi (16 Kas): yapışık metinde yalın Enter gitmiyor; karakter yazıp Enter'layınca gidiyor."""
        keys = []

        class Stuck(Pane):
            def raw(self, name, data):
                keys.append(data)
                if data == "\r" and " " in keys:
                    self.text = "\n" + MSG
                return True

        p = Stuck("", on_send=lambda self, m: "x\n❯ [Pasted text #1 +3 lines]")
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(keys, ["\r", " ", "\r"])     # önce yalın Enter, sonra ayrı yazımlarla boşluk + Enter
        self.assertEqual(p.sends, 1)

    def test_permanently_stuck_paste_fails_without_resend(self):
        keys = []

        class Dead(Pane):
            def raw(self, name, data):
                keys.append(data)
                return True

        p = Dead("", on_send=lambda self, m: "x\n❯ [Pasted text #1 +3 lines]")
        self.assertEqual(verify(p), "failed")
        self.assertEqual(keys.count("\r"), ws.DELIVERY_MAX_ENTERS)
        self.assertEqual(p.sends, 1)

    def test_text_unsent_in_input_box_is_not_delivered(self):
        """26 Kas, Claude Code 2.1.332: açılışta yapıştırılan metin kutuda düz yazı olarak kalıyor; Enter gönderir."""
        class Boxed(Pane):
            def raw(self, name, data):
                self.enters += 1
                self.text = "❯ " + MSG + "\n" + box("")
                return True

        p = Boxed("", on_send=lambda self, m: box(m))
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.enters, 1)
        self.assertEqual(p.sends, 1)

    def test_text_stuck_in_input_box_forever_fails_without_resend(self):
        class Dead(Pane):
            def raw(self, name, data):
                return True

        p = Dead("", on_send=lambda self, m: box(m))
        self.assertEqual(verify(p), "failed")
        self.assertEqual(p.sends, 1)

    def test_placeholder_text_in_transcript_does_not_trigger_enter(self):
        sent = "❯ " + MSG + " [Pasted text #1 +3 lines]\n" + box("")
        p = Pane("", on_send=lambda self, m: sent)
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.enters, 0)

    def test_pasted_placeholder_in_input_box_gets_enter(self):
        class Boxed(Pane):
            def raw(self, name, data):
                self.enters += 1
                self.text = "❯ " + MSG + "\n" + box("")
                return True

        p = Boxed("", on_send=lambda self, m: box("[Pasted text #1 +3 lines]"))
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.enters, 1)

    def test_grey_suggestion_in_box_is_not_unsent_text(self):
        """Boş kutudaki gri öneri başlığı taşısa da gönderilmemiş metin sayılmaz."""
        for grey in ("\x1b[38;5;246m", "\x1b[2m", "\x1b[38;2;128;128;128m"):
            sent = "❯ " + MSG + "\n" + box(grey + MSG + "\x1b[0m")
            p = Pane("", on_send=lambda self, m: sent)
            self.assertEqual(verify(p), "delivered", repr(grey))
            self.assertEqual(p.enters, 0, repr(grey))

    def test_colored_typed_text_in_box_counts_as_unsent(self):
        for colour in ("\x1b[38;2;215;119;87m", "\x1b[48;2;40;40;40m", "\x1b[48;5;2m"):
            p = Pane("", on_send=lambda self, m, c=colour: box(c + m + "\x1b[0m"))
            p.raw = lambda name, data: True
            self.assertEqual(verify(p), "failed", repr(colour))

    def test_resend_when_nothing_arrived(self):
        n = {"k": 0}

        def on(self, m):
            n["k"] += 1
            return self.text + ("\n" + m if n["k"] >= 2 else "")
        p = Pane("", on_send=on)
        self.assertEqual(verify(p), "delivered")
        self.assertEqual(p.sends, 2)

    def test_ucli_unverified_skip(self):
        p = Pane("")
        self.assertEqual(verify(p, cli="ucli"), "unverified")


class Queue(unittest.TestCase):
    def setUp(self):
        ws._DELIVERIES.clear()

    def _call(self, inner, data=None):
        done = threading.Event()
        calls = []

        def fake(d, sid="default"):
            calls.append(d)
            if d.get("_bg"):
                r = inner(d)
                done.set()
                return r
            return real(d, sid)
        real = ws.http_directive
        with mock.patch.object(ws, "_live_sessions", lambda n, sid="default": []), \
                mock.patch.object(ws, "_gate", lambda *a, **k: None), \
                mock.patch.object(ws, "_upper_model_gate", lambda *a, **k: None), \
                mock.patch.object(ws, "_brain_directive_blocks", lambda *a, **k: None), \
                mock.patch.object(ws, "_name_host", lambda n: ""), \
                mock.patch.object(ws, "_notify", mock.MagicMock()) as notify, \
                mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(ws, "steward_config", lambda sid="default": types.SimpleNamespace(drain=False, lang="tr")), \
                mock.patch.object(ws, "quota_blocking", lambda: False), \
                mock.patch.object(ws.sw, "panic_active", lambda: False), \
                mock.patch.object(ws, "http_directive", fake):
            r = real(dict({"name": "p", "text": "x", "queue": True}, **(data or {})))
            done.wait(3)
            for _ in range(50):
                st = ws.http_directive_status({"id": [r["id"]]})
                if st.get("status") != "queued":
                    break
                threading.Event().wait(0.05)
        return r, st, notify, calls

    def test_start_path_returns_queued_immediately_then_delivered(self):
        r, st, notify, calls = self._call(lambda d: {"ok": True, "name": "p"})
        self.assertEqual(r["status"], "queued")
        self.assertEqual(st["status"], "delivered")
        self.assertTrue(calls[-1]["_bg"] and calls[-1]["queue"] is False)
        notify.assert_not_called()

    def test_failure_is_visible_with_reason_and_notifies(self):
        r, st, notify, _ = self._call(lambda d: {"ok": False, "error": "start backoff", "code": "start_backoff"})
        self.assertEqual(st["status"], "failed")
        self.assertEqual(st["reason"], "start_backoff")
        notify.assert_called_once()

    def test_brain_actor_stays_synchronous(self):
        with mock.patch.object(ws, "_queue_directive") as q, mock.patch.object(ws, "_gate", lambda *a, **k: {"ok": False, "error": "g"}):
            ws.http_directive({"name": "p", "text": "x", "actor": "brain"})
        q.assert_not_called()


class HoDoneFresh(unittest.TestCase):
    def test_ho_done_live_session_stopped_exact_and_started_fresh(self):
        s = types.SimpleNamespace(name="p20261116", cli="claude", cwd="/x", pid=1)
        cfg = types.SimpleNamespace(sid="default", lang="tr", ho_on_open="act")
        proj = sw.Project(name="p")
        lives = [[s], [s], []]      # direktif öncesi canlı, durdurmadan sonra bir yoklama hâlâ canlı, sonra çıktı
        fresh = {}

        def ensure(target, **kw):
            fresh["v"] = kw.get("fresh")
            return {"ok": True, "started": True}
        import contextlib
        patches = [
            mock.patch.object(ws, "_live_ho_done", lambda x: True),
            mock.patch.object(ws, "_live_sessions", lambda n, sid="default": lives.pop(0) if len(lives) > 1 else lives[0]),
            mock.patch.object(ws, "_act", return_value={"ok": True}),
            mock.patch.object(ws, "_scan_invalidate", lambda: None),
            mock.patch.object(ws, "_ensure_running", ensure),
            mock.patch.object(ws, "_consume_fresh_start", lambda *a: False),
            mock.patch.object(ws, "is_tmux_backed", lambda pid: True),
            mock.patch.object(ws, "_send", return_value=True),
            mock.patch.object(ws, "_running", lambda n: s),
            mock.patch.object(ws, "_proc_born", lambda pid: 0.0),
            mock.patch.object(ws, "_name_host", lambda n: ""),
            mock.patch.object(ws, "_wake_gate", lambda *a, **k: False),
            mock.patch.object(ws, "_wake_record", lambda *a, **k: None),
            mock.patch.object(ws, "_mark_after_send", lambda *a, **k: True),
            mock.patch.object(ws.sw, "upsert_project", lambda *a, **k: None),
            mock.patch.object(ws.sw, "load_projects", lambda p=None: {}),
            mock.patch.object(ws.sw, "steward_lock", mock.MagicMock()),
            mock.patch.object(ws.sw, "load_state", lambda p=None: {}),
            mock.patch.object(ws.sw, "save_state", lambda *a, **k: None),
            mock.patch.object(ws.sw, "log_event", lambda *a, **k: None),
            mock.patch.object(ws.sw, "auto_remove_labels", lambda *a, **k: None),
            mock.patch.object(ws.sw, "build_directive", lambda *a, **k: "m"),
            mock.patch.object(ws.sw, "phase_model_effort", lambda p, c: ("", "")),
        ]
        with contextlib.ExitStack() as st:
            mocks = [st.enter_context(x) for x in patches]
            act = mocks[2]
            r = ws._give_directive_impl(proj, "x", cfg=cfg, reason="cli", session_name="p")
        self.assertTrue(r["ok"])
        # tek durdurma; açılıştan önce ana oturum modeli için cli sorgusu (`fleet_status`) yapılabilir (sahip kuralı 18 Kas)
        stops = [c for c in act.call_args_list if c.args and c.args[0] == "stop"]
        self.assertEqual(stops, [mock.call("stop", "p20261116", lang="tr")])
        self.assertTrue(fresh["v"])


class ClosedHoDoneAndPersistence(unittest.TestCase):
    def test_closed_ho_done_conversation_starts_fresh(self):
        started = []
        ws.configure(start=lambda *a, **k: started.append(k) or {"ok": True})
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []), \
                mock.patch.object(ws, "_resume_ho_done", lambda n: True), \
                mock.patch.object(ws, "_resume_lacks_ho", lambda n, c: ""), \
                mock.patch.object(ws, "_oversized_resume", lambda n, c: self.fail("fresh: boyut denetimi gerekmez")), \
                mock.patch.object(ws, "_closed_in_models", lambda n: False), \
                mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: {}), \
                mock.patch.object(ws, "steward_config", lambda sid="default": sw.Config()), \
                mock.patch.object(ws, "_start_appeared", lambda n, s="default": True), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: True), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"), \
                mock.patch.object(ws, "_record_owned", lambda *a, **k: None), \
                mock.patch.object(sw, "log_event", lambda *a, **k: None):
            res = ws._ensure_running("p")
        self.assertTrue(res["ok"])
        self.assertTrue(started[0].get("fresh"))

    def test_deliveries_survive_restart_and_queued_becomes_failed(self):
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(), "deliveries.json")
        with mock.patch.object(ws, "DELIVERIES_FILE", tmp):
            ws._DELIVERIES.clear()
            ws._DELIVERIES_LOADED = True
            ws._delivery_set("a", name="x", status="delivered")
            ws._delivery_set("b", name="y", status="queued")
            ws._DELIVERIES.clear()                 # restart: bellek boş
            ws._DELIVERIES_LOADED = False
            r = ws.http_directive_status({"id": ["a"]})
            self.assertEqual(r["status"], "delivered")
            r = ws.http_directive_status({"id": ["b"]})
            self.assertEqual((r["status"], r["reason"]), ("failed", "restart_lost"))
        ws._DELIVERIES.clear()
        ws._DELIVERIES_LOADED = True


if __name__ == "__main__":
    unittest.main()
