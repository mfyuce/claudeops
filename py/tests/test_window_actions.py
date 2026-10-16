"""Pencere eylemleri (`window_actions.py`, TODO.md 2026-10-16) testleri: handover / durdur + yeni isim / durdur / yeni chat /
sıfırla bileşimi, kayıtsız oturumda HİÇBİR şey durdurulmadan reddedilmesi, uzak host yükleri, (host, ad) kilidi.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_window_actions.py' -v

Gerçek panele DOKUNMAZ: 127.0.0.1'de geçici bir stdlib HTTP sunucusu panelin ilkel uçlarını (`/api/status`, `/api/stop`,
`/api/start`, `/api/new-chat`, `/api/handover`) taklit eder ve gelen çağrıları SIRAYLA kaydeder; asıl denetlenen şey
çağrı sırası ve yükleridir (özellikle "durdurmadan önce yeniden başlatılabilirlik denetlendi mi").
"""
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import window_actions as wa  # noqa: E402

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "test-token"


def row(name, host="local", **extra):
    base = {"name": name, "host": host, "cli": "claude", "running": True, "registered": True, "instance": False,
            "blueprint": name, "model": "claude-sonnet-5", "live_model": "claude-opus-5-5"}
    base.update(extra)
    return base


def status(rows, hosts=None, default_model=None):
    return {
        "sessions": rows,
        "cli_options": {"claude": {"effort_levels": ["low", "medium", "high", "xhigh", "max"]},
                        "codex": {"effort_levels": ["low", "medium", "high", "xhigh"]}},
        "hosts": hosts if hosts is not None else [
            {"name": "yuhem", "ok": True, "cli_options": {"claude": {"effort_levels": ["low", "high"]}}}],
        "settings": {"default_model": default_model if default_model is not None else {"claude": "claude-sonnet-5"}},
    }


class FakePanel:
    """Panelin ilkel uçları. `calls`: [(path, gövde)] gelen sırayla (status GET'i dahil)."""

    def __init__(self, status_payload):
        self.status = status_payload
        self.calls = []
        self.responses = {}    # path -> dict (varsayılan {"ok": True})
        self.require_token = True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):   # sessiz
                pass

            def _auth_ok(self):
                return not outer.require_token or self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def _send(self, code, obj):
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if not self._auth_ok():
                    return self._send(401, {"error": "unauthorized"})
                outer.calls.append((self.path, None))
                self._send(200, outer.status)

            def do_POST(self):
                if not self._auth_ok():
                    return self._send(401, {"error": "unauthorized"})
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
                outer.calls.append((self.path, body))
                default = {"ok": True, "name": "yeni_1"} if self.path == "/api/new-chat" else {"ok": True}
                self._send(200, outer.responses.get(self.path, default))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def posts(self):
        return [(p, b) for p, b in self.calls if b is not None]

    def paths(self):
        return [p for p, b in self.calls if b is not None]


class PanelCase(unittest.TestCase):
    def serve(self, payload):
        panel = FakePanel(payload)
        self.addCleanup(panel.close)
        return panel

    def run_act(self, panel, action, name="ae", host="local", steps=None):
        client = wa.PanelClient(panel.port, lambda: TOKEN)
        return wa.run_action(client, action, host, name, on_step=steps.append if steps is not None else None)


class ComposeTests(PanelCase):
    def test_handover_posts_to_the_primitive_endpoint(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "handover")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(p.posts(), [("/api/handover", {"name": "ae", "host": "local", "lang": "tr"})])

    def test_stop_posts_stop_only(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "stop")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(p.paths(), ["/api/stop"])

    def test_newchat_does_not_stop_and_carries_the_live_model_default_permission_and_top_effort(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "newchat")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(r.name, "yeni_1")
        self.assertIn("yeni_1", r.message)
        self.assertEqual(p.posts(), [("/api/new-chat", {
            "base": "ae", "host": "local", "model": "claude-opus-5-5",   # CANLI model, kayıtlı (claude-sonnet-5) değil
            "permission_mode": "auto", "effort": "max", "cli": "claude", "lang": "tr"})])

    def test_restart_stops_first_then_opens_a_new_chat_from_the_same_base(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "restart")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(p.paths(), ["/api/stop", "/api/new-chat"])
        self.assertEqual(p.posts()[1][1]["base"], "ae")
        self.assertIn("yeni_1", r.message)

    def test_restart_of_an_already_stopped_session_skips_the_stop_half(self):
        p = self.serve(status([row("ae", running=False, live_model=None)]))
        r = self.run_act(p, "restart")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(p.paths(), ["/api/new-chat"])

    def test_reset_stops_then_starts_fresh_under_the_same_name(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "reset")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(p.paths(), ["/api/stop", "/api/start"])
        start = p.posts()[1][1]
        self.assertEqual((start["name"], start["fresh"], start["host"]), ("ae", True, "local"))
        self.assertEqual((start["permission_mode"], start["effort"], start["cli"]), ("auto", "max", "claude"))

    def test_steps_are_reported_in_order(self):
        p = self.serve(status([row("ae")]))
        steps = []
        self.run_act(p, "restart", steps=steps)
        self.assertEqual(steps[0], "panel durumu okunuyor…")
        self.assertTrue(any("durduruluyor" in s for s in steps))
        self.assertTrue(any("yeni chat" in s for s in steps))

    def test_a_stopped_local_session_gets_the_settings_default_model(self):
        p = self.serve(status([row("ae", running=False, live_model=None)], default_model={"claude": "claude-haiku-5"}))
        self.run_act(p, "newchat")
        self.assertEqual(p.posts()[0][1]["model"], "claude-haiku-5")

    def test_effort_is_the_last_level_of_that_clis_own_list(self):
        p = self.serve(status([row("cx", cli="codex", live_model="gpt-6")]))
        self.run_act(p, "newchat", name="cx")
        self.assertEqual(p.posts()[0][1]["effort"], "xhigh")   # codex'in listesinin sonu, claude'un "max"ı DEĞİL

    def test_an_unknown_model_placeholder_is_never_sent(self):
        p = self.serve(status([row("ae", live_model=None, model="?")]))   # panel kayıtsız satırlara "?" yazar
        self.run_act(p, "newchat")
        self.assertEqual(p.posts()[0][1]["model"], "")


class RemoteHostTests(PanelCase):
    def test_remote_payloads_carry_the_host_and_leave_model_to_that_host(self):
        p = self.serve(status([row("ae"), row("ae", host="yuhem", live_model="claude-opus-5-5")]))
        r = self.run_act(p, "restart", host="yuhem")
        self.assertTrue(r.ok, r.message)
        stop, newchat = p.posts()
        self.assertEqual(stop[1]["host"], "yuhem")
        self.assertEqual(newchat[1]["host"], "yuhem")
        self.assertEqual(newchat[1]["model"], "")        # uzak host kendi varsayılanını uygular (arayüzle aynı kural)
        self.assertEqual(newchat[1]["effort"], "high")   # o host'un kendi cli_options'ı (listenin sonu), yerelin "max"ı değil

    def test_the_same_name_on_two_hosts_picks_the_row_of_the_requested_host(self):
        # yerelde kayıtlı, yuhem'de KAYITSIZ: yuhem eylemi reddedilmeli, yerel olan geçmeli
        p = self.serve(status([row("ae"), row("ae", host="yuhem", registered=False)]))
        self.assertFalse(self.run_act(p, "restart", host="yuhem").ok)
        self.assertEqual(p.paths(), [])
        self.assertTrue(self.run_act(p, "restart", host="local").ok)
        self.assertEqual(p.paths(), ["/api/stop", "/api/new-chat"])


class RefusalTests(PanelCase):
    """Hiçbir şey durdurulmadan ÖNCE denetlenen durumlar: "durdurdu ama geri açamadı" yarım kalması olmamalı."""

    def test_unregistered_session_is_never_stopped_by_a_restart_or_reset(self):
        for action in ("restart", "reset"):
            p = self.serve(status([row("adhoc", registered=False)]))
            r = self.run_act(p, action, name="adhoc")
            self.assertFalse(r.ok)
            self.assertEqual(p.paths(), [], action)               # /api/stop dahil HİÇBİR POST yok
            self.assertIn("HİÇBİR şey durdurulmadı", r.message)

    def test_unregistered_session_cannot_spawn_a_new_chat_but_can_be_stopped(self):
        p = self.serve(status([row("adhoc", registered=False)]))
        r = self.run_act(p, "newchat", name="adhoc")
        self.assertFalse(r.ok)
        self.assertEqual(p.paths(), [])
        self.assertIn("yeni chat", r.message)
        self.assertTrue(self.run_act(p, "stop", name="adhoc").ok)   # durdurmak kayıt gerektirmez

    def test_stop_and_handover_need_a_running_session(self):
        p = self.serve(status([row("ae", running=False)]))
        for action in ("stop", "handover"):
            r = self.run_act(p, action)
            self.assertFalse(r.ok)
            self.assertIn("çalışmıyor", r.message)
        self.assertEqual(p.paths(), [])

    def test_unknown_session_and_unknown_action(self):
        p = self.serve(status([row("ae")]))
        self.assertIn("panelde yok", self.run_act(p, "stop", name="nope").message)
        self.assertIn("bilinmeyen eylem", self.run_act(p, "format-disk").message)
        self.assertEqual(p.paths(), [])

    def test_hostile_targets_are_refused_before_ANY_call_even_when_the_panel_has_such_a_row(self):
        # satır panelde VAR: hedef denetimi olmasaydı /api/stop giderdi (kullanıcı girdisi komut satırından da gelebilir)
        weird = ["a b", "a\nb", "a\x1b[2Jb", "tab\tname"]
        p = self.serve(status([row(n) for n in weird] + [row("ae", host="yu hem")]))
        for name in weird:
            r = self.run_act(p, "stop", name=name)
            self.assertFalse(r.ok, repr(name))
            self.assertIn("geçersiz", r.message)
        self.assertFalse(self.run_act(p, "stop", name="").ok)
        r = self.run_act(p, "stop", name="ae", host="yu hem")
        self.assertFalse(r.ok)
        self.assertIn("geçersiz host", r.message)
        self.assertEqual(p.calls, [])     # status GET'i dahil HİÇBİR çağrı yapılmadı


class FailureTests(PanelCase):
    def test_a_failed_stop_aborts_the_compound_action_before_anything_new_starts(self):
        p = self.serve(status([row("ae")]))
        p.responses["/api/stop"] = {"ok": False, "error": "ambiguous_name"}
        r = self.run_act(p, "restart")
        self.assertFalse(r.ok)
        self.assertEqual(p.paths(), ["/api/stop"])
        self.assertIn("ambiguous_name", r.message)
        self.assertIn("yeni bir şey başlatılmadı", r.message)

    def test_new_chat_failure_after_a_successful_stop_says_so(self):
        p = self.serve(status([row("ae")]))
        p.responses["/api/new-chat"] = {"ok": False, "error": "newchat_start_failed"}
        r = self.run_act(p, "restart")
        self.assertFalse(r.ok)
        self.assertEqual(p.paths(), ["/api/stop", "/api/new-chat"])
        self.assertIn("durduruldu ama yeni chat açılamadı", r.message)

    def test_start_failure_after_a_successful_stop_says_so(self):
        p = self.serve(status([row("ae")]))
        p.responses["/api/start"] = {"ok": False, "error": "start_no_proc"}
        r = self.run_act(p, "reset")
        self.assertFalse(r.ok)
        self.assertIn("durduruldu ama sıfırdan başlatılamadı", r.message)

    def test_handover_error_is_surfaced(self):
        p = self.serve(status([row("ae")]))
        p.responses["/api/handover"] = {"ok": False, "error": "no_conversation"}
        r = self.run_act(p, "handover")
        self.assertFalse(r.ok)
        self.assertIn("no_conversation", r.message)

    def test_unreachable_panel_is_a_message_not_an_exception(self):
        p = self.serve(status([row("ae")]))
        client = wa.PanelClient(1, lambda: TOKEN)   # port 1: kimse dinlemiyor
        r = wa.run_action(client, "stop", "local", "ae")
        self.assertFalse(r.ok)
        self.assertIn("panel durumu alınamadı", r.message)
        self.assertEqual(p.calls, [])

    def test_rejected_token_and_unreadable_token_are_reported_with_the_cause(self):
        p = self.serve(status([row("ae")]))
        bad = wa.run_action(wa.PanelClient(p.port, lambda: "wrong"), "stop", "local", "ae")
        self.assertFalse(bad.ok)
        self.assertIn("401", bad.message)
        self.assertEqual(p.posts(), [])

        def broken():
            raise OSError("web.token okunamadı")

        unreadable = wa.run_action(wa.PanelClient(p.port, broken), "stop", "local", "ae")
        self.assertFalse(unreadable.ok)
        self.assertIn("web.token okunamadı", unreadable.message)

    def test_the_token_goes_in_a_header_never_in_the_url_or_body(self):
        seen = {}

        def opener(req, timeout=None):
            seen["url"], seen["data"], seen["headers"] = req.full_url, req.data, dict(req.header_items())
            raise OSError("stop here")

        client = wa.PanelClient(1234, lambda: "s3cret-token", urlopen=opener)
        with self.assertRaises(wa.PanelError):
            client.post("/api/stop", {"name": "ae"})
        self.assertNotIn("s3cret-token", seen["url"])
        self.assertNotIn(b"s3cret-token", seen["data"])
        self.assertEqual(seen["headers"]["Authorization"], "Bearer s3cret-token")


class ActionLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def lock(self, host="local", name="ae"):
        return wa.ActionLock(host, name, directory=self.tmp.name)

    def test_a_second_holder_of_the_same_session_is_refused_until_release(self):
        a = self.lock()
        a.acquire()
        with self.assertRaises(wa.ActionBusy):
            self.lock().acquire()
        a.release()
        b = self.lock()
        b.acquire()   # serbest
        b.release()

    def test_other_sessions_and_other_hosts_do_not_block_each_other(self):
        held = [self.lock("local", "ae"), self.lock("local", "be"), self.lock("yuhem", "ae")]
        for lk in held:
            lk.acquire()
        for lk in held:
            lk.release()

    def test_names_that_sanitise_to_the_same_text_still_get_different_locks(self):
        self.assertNotEqual(self.lock(name="a b").path, self.lock(name="a_b").path)

    def test_lock_file_name_is_filesystem_safe(self):
        path = self.lock(name="we'ird/../name").path
        self.assertEqual(os.path.dirname(path), self.tmp.name)
        self.assertRegex(os.path.basename(path), r"^claudeops-winact\.[A-Za-z0-9_.-]+\.lock$")

    def test_context_manager_releases(self):
        with self.lock():
            with self.assertRaises(wa.ActionBusy):
                self.lock().acquire()
        self.lock().acquire()

    def test_only_a_held_lock_blocks_other_flock_failures_do_not(self):
        import errno
        from unittest import mock
        lk = self.lock()
        with mock.patch.object(wa.fcntl, "flock", side_effect=OSError(errno.ENOLCK, "no locks")):
            lk.acquire()      # kilit kurulamadı: eylem ENGELLENMEZ
        lk.release()
        with mock.patch.object(wa.fcntl, "flock", side_effect=BlockingIOError(errno.EWOULDBLOCK, "held")):
            with self.assertRaises(wa.ActionBusy):
                self.lock().acquire()

    def test_an_unusable_lock_directory_never_blocks_the_action(self):
        bad = wa.ActionLock("local", "ae", directory=os.path.join(self.tmp.name, "no", "such", "dir"))
        bad.acquire()    # kilitsiz sürer, istisna yok
        bad.release()


class TableTests(unittest.TestCase):
    def test_keys_ids_and_confirm_flags(self):
        self.assertEqual([a.id for a in wa.ACTIONS], ["handover", "restart", "stop", "newchat", "reset"])
        self.assertEqual(len({a.key for a in wa.ACTIONS}), 5)
        self.assertEqual({a.id for a in wa.ACTIONS if a.confirm}, {"restart", "stop", "reset"})   # yıkıcı olanlar
        self.assertEqual(wa.BY_KEY["h"].id, "handover")
        self.assertEqual(wa.BY_KEY["r"].id, "reset")

    def test_labels_match_the_panels_turkish_strings(self):
        """Arayüzdeki ad değişirse burası da değişmeli (tek kaynak panel)."""
        with open(os.path.join(PY_DIR, "webui", "src", "i18n", "strings.ts"), encoding="utf-8") as f:
            text = f.read()
        for action in wa.ACTIONS:
            self.assertIn(f': "{action.label.lower()}', text, action.label)

    def test_default_permission_mode_matches_the_frontend_constant(self):
        with open(os.path.join(PY_DIR, "webui", "src", "components", "RunningTab", "cliDefaults.ts"),
                  encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'DEFAULT_PERMISSION_MODE\s*=\s*"([^"]+)"', text)
        self.assertIsNotNone(m)
        self.assertEqual(wa.DEFAULT_PERMISSION_MODE, m.group(1))


if __name__ == "__main__":
    unittest.main()
