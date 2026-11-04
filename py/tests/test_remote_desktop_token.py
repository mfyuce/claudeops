"""remote_desktop: daemon token'ı (UZAKGOZ_TOKEN) + web proxy yol yeniden yazımı (stdlib unittest).
Gerçek Popen/ağ/süreç sinyali YOK; tüm dosyalar geçici dizinde (gerçek ~/.claude/claudeops'a dokunmaz)."""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import remote_desktop as rd  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d = t.name
        self.pidfile = os.path.join(self.d, "rd.pid")
        self.tokfile = os.path.join(self.d, "rd.token")
        for p in (mock.patch.object(rd, "PID_FILE", self.pidfile), mock.patch.object(rd, "TOKEN_FILE", self.tokfile),
                  mock.patch.object(rd, "_token", None), mock.patch.object(rd, "_proc", None),
                  mock.patch.object(rd, "_port", None), mock.patch.object(rd, "_adopted_pid", None)):
            p.start()
            self.addCleanup(p.stop)


class StartTokenTest(_Base):
    def _start(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        with mock.patch.object(rd, "uzakgoz_config", return_value={"dir": "", "bin": "/bin/true", "port": 9123}), \
                mock.patch.object(rd, "_adopt_if_orphaned"), mock.patch.object(rd, "_port_open", return_value=True), \
                mock.patch.object(rd.subprocess, "Popen", return_value=proc) as popen:
            res = rd.start()
        return res, popen

    def test_token_in_env_only_and_file_0600(self):
        res, popen = self._start()
        self.assertTrue(res["ok"])
        tok = rd.current_token()
        self.assertEqual(len(tok), 64)
        self.assertEqual(popen.call_args.kwargs["env"]["UZAKGOZ_TOKEN"], tok)
        self.assertNotIn(tok, " ".join(popen.call_args[0][0]))      # argv'de yok
        self.assertNotIn(tok, repr(res))                            # yanıt/log'a girmez
        with open(self.tokfile) as f:
            self.assertEqual(f.read(), tok)
        self.assertEqual(stat.S_IMODE(os.stat(self.tokfile).st_mode), 0o600)

    def test_each_start_gets_fresh_token(self):
        self._start()
        a = rd._token
        rd._proc = None
        self._start()
        self.assertNotEqual(a, rd._token)

    def test_stop_clears_token(self):
        self._start()
        rd._proc.terminate = mock.Mock()
        rd.stop()
        self.assertIsNone(rd._token)
        self.assertFalse(os.path.exists(self.tokfile))


class AdoptTokenTest(_Base):
    def _adopt(self):
        with open(self.pidfile, "w") as f:
            f.write("4242 8123\n")
        return mock.patch.multiple(rd, _pid_alive=mock.Mock(return_value=True), _is_screenshare=mock.Mock(return_value=True),
                                   _port_open=mock.Mock(return_value=True))

    def test_adopt_restores_token_from_file(self):
        with open(self.tokfile, "w") as f:
            f.write("abc123")
        with self._adopt():
            self.assertEqual(rd.current_token(), "abc123")
            self.assertEqual(rd.current_port(), 8123)

    def test_tokenless_orphan_is_killed_not_adopted(self):
        with self._adopt(), mock.patch.object(rd, "_kill_pid") as kill:
            self.assertEqual(rd.status(), {"running": False, "port": None})
        kill.assert_called_once_with(4242)
        self.assertFalse(os.path.exists(self.pidfile))
        self.assertIsNone(rd.current_token())

    def test_current_token_none_when_not_running(self):
        self.assertIsNone(rd.current_token())


class RewriteTest(unittest.TestCase):
    def test_strips_client_token_and_ticket_adds_daemon_token(self):
        out = rd.rewrite_path_with_token("/ws/desktop?token=PANEL&ticket=T&Token=X&fps=15", "DAEMON")
        self.assertNotIn("PANEL", out)
        self.assertNotIn("ticket", out)
        self.assertNotIn("X", out.split("?", 1)[1].replace("fps", "").replace("DAEMON", ""))
        self.assertIn("fps=15", out)
        self.assertEqual(out.count("token=DAEMON"), 1)
        self.assertTrue(out.startswith("/ws/desktop?"))

    def test_no_query(self):
        self.assertEqual(rd.rewrite_path_with_token("/viewer.js", "D"), "/viewer.js?token=D")


class WebProxyTest(_Base):
    """_proxy_desktop_ws / _serve_desktop_viewer: daemon'a giden istekte panel token'ı yok, daemon token'ı var."""

    def test_ws_proxy_request_rewritten_and_credentials_dropped(self):
        from claudeops.commands import web
        sent = []

        class FakeSock:
            def settimeout(self, t): pass
            def sendall(self, b): sent.append(b)
            def recv(self, n): return b""
            def shutdown(self, h): pass
            def close(self): pass

        h = mock.Mock()
        h.command = "GET"
        h.path = "/ws/desktop?token=PANELSECRET&ticket=TK"
        h.headers = {"Host": "x", "Upgrade": "websocket", "Cookie": "s=PANELSECRET", "Authorization": "Bearer PANELSECRET"}
        h.rfile.read1.return_value = b""
        with mock.patch.object(web.remote_desktop, "current_port", return_value=9123), \
                mock.patch.object(web.remote_desktop, "current_token", return_value="DAEMONTOK"), \
                mock.patch.object(web.socket, "create_connection", return_value=FakeSock()):
            web._proxy_desktop_ws(h)
        req = b"".join(sent).decode()
        self.assertIn("token=DAEMONTOK", req)
        self.assertNotIn("PANELSECRET", req)
        self.assertNotIn("TK", req.split("\r\n")[0])
        self.assertIn("Upgrade: websocket", req)

    def test_ws_proxy_rewrites_host_and_drops_origin(self):
        from claudeops.commands import web
        sent = []

        class FakeSock:
            def settimeout(self, t): pass
            def sendall(self, b): sent.append(b)
            def recv(self, n): return b""
            def shutdown(self, h): pass
            def close(self): pass

        h = mock.Mock()
        h.command = "GET"
        h.path = "/ws/desktop?token=PANELSECRET"
        h.headers = {"Host": "evil.trycloudflare.com", "Origin": "https://evil.trycloudflare.com",
                     "Upgrade": "websocket", "Cookie": "s=1", "Authorization": "Bearer P",
                     "Sec-WebSocket-Key": "abc"}
        h.rfile.read1.return_value = b""
        with mock.patch.object(web.remote_desktop, "current_port", return_value=9123), \
                mock.patch.object(web.remote_desktop, "current_token", return_value="DAEMONTOK"), \
                mock.patch.object(web.socket, "create_connection", return_value=FakeSock()):
            web._proxy_desktop_ws(h)
        lines = b"".join(sent).decode().split("\r\n")
        hosts = [l for l in lines if l.lower().startswith("host:")]
        self.assertEqual(hosts, ["Host: 127.0.0.1:9123"])
        low = [l.lower() for l in lines]
        self.assertFalse(any(l.startswith(("origin:", "authorization:", "cookie:")) for l in low))
        self.assertNotIn("evil", "".join(lines))
        self.assertIn("Sec-WebSocket-Key: abc", lines)

    def test_gestures_fetch_uses_daemon_token(self):
        from claudeops.commands import web
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"js"
        h = mock.Mock()
        with mock.patch.object(web.remote_desktop, "current_port", return_value=9123), \
                mock.patch.object(web.remote_desktop, "current_token", return_value="DAEMONTOK"), \
                mock.patch("urllib.request.urlopen", return_value=resp) as uo:
            web._serve_desktop_viewer(h, "gestures.js")
        self.assertEqual(uo.call_args[0][0], "http://127.0.0.1:9123/gestures.js?token=DAEMONTOK")
        h.send_response.assert_called_with(200)
        h.wfile.write.assert_called_with(b"js")

    def test_gestures_503_when_daemon_down(self):
        from claudeops.commands import web
        h = mock.Mock()
        with mock.patch.object(web.remote_desktop, "current_port", return_value=None), \
                mock.patch.object(web.remote_desktop, "current_token", return_value=None), \
                mock.patch("urllib.request.urlopen") as uo:
            web._serve_desktop_viewer(h, "gestures.js")
        uo.assert_not_called()
        self.assertEqual(h._json.call_args[1]["status"], 503)

    def test_ws_proxy_503_without_token(self):
        from claudeops.commands import web
        h = mock.Mock()
        with mock.patch.object(web.remote_desktop, "current_port", return_value=9123), \
                mock.patch.object(web.remote_desktop, "current_token", return_value=None), \
                mock.patch.object(web.socket, "create_connection") as cc:
            web._proxy_desktop_ws(h)
        cc.assert_not_called()
        h.send_response.assert_called_with(503)

    def test_viewer_fetch_uses_daemon_token(self):
        from claudeops.commands import web
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"js"
        h = mock.Mock()
        with mock.patch.object(web.remote_desktop, "current_port", return_value=9123), \
                mock.patch.object(web.remote_desktop, "current_token", return_value="DAEMONTOK"), \
                mock.patch("urllib.request.urlopen", return_value=resp) as uo:
            web._serve_desktop_viewer(h)
        self.assertEqual(uo.call_args[0][0], "http://127.0.0.1:9123/viewer.js?token=DAEMONTOK")


if __name__ == "__main__":
    unittest.main()
