"""Terminal girdisi güvenilir teslimi: uzak taraf `input_id` tekrarını yazmaz; proxy yalnız taşıma hatasında AYNI id ile yeniden dener."""
import unittest
from unittest import mock

from claudeops import term_dedup
from claudeops.commands import web, web_hosts


class Dedup(unittest.TestCase):
    def setUp(self):
        term_dedup._seen.clear()

    def test_claim_once_then_dup_until_ttl(self):
        self.assertTrue(term_dedup.claim("/api/term/input", "a", "id1", now=100.0))
        self.assertFalse(term_dedup.claim("/api/term/input", "a", "id1", now=200.0))
        self.assertTrue(term_dedup.claim("/api/term/input", "a", "id1", now=100.0 + term_dedup.TTL_SECONDS + 1))

    def test_scoped_by_path_and_name(self):
        self.assertTrue(term_dedup.claim("/api/term/input", "a", "x", now=1.0))
        self.assertTrue(term_dedup.claim("/api/term/raw", "a", "x", now=1.0))
        self.assertTrue(term_dedup.claim("/api/term/input", "b", "x", now=1.0))

    def test_release_allows_retry(self):
        term_dedup.claim("/api/term/input", "a", "id2", now=1.0)
        term_dedup.release("/api/term/input", "a", "id2")
        self.assertTrue(term_dedup.claim("/api/term/input", "a", "id2", now=2.0))

    def test_valid_id(self):
        self.assertEqual(term_dedup.valid_id("abc-123"), "abc-123")
        for bad in (None, "", 5, "x" * 65, "a b"):
            self.assertIsNone(term_dedup.valid_id(bad))

    def test_failed_write_releases(self):
        term_dedup.claim("/api/term/input", "a", "id3", now=1.0)
        web._Handler._term_dedup_result("/api/term/input", {"name": "a", "input_id": "id3"}, {"ok": False})
        self.assertTrue(term_dedup.claim("/api/term/input", "a", "id3", now=2.0))
        web._Handler._term_dedup_result("/api/term/input", {"name": "a", "input_id": "id3"}, {"ok": True})
        self.assertFalse(term_dedup.claim("/api/term/input", "a", "id3", now=3.0))


class ProxyRetry(unittest.TestCase):
    BODY = {"name": "s", "host": "ulak_31", "text": "hi", "input_id": "u-1"}

    def test_retries_transport_failure_same_body_short_timeout(self):
        calls = []
        def fake(path, host, body, timeout=None):
            calls.append((dict(body), timeout))
            return ({"ok": False, "error": "ulak_31 unreachable: timed out"}, 200) if len(calls) < 3 else ({"ok": True}, 200)
        with mock.patch.object(web_hosts, "proxy_action", side_effect=fake):
            res, _ = web_hosts.proxy_term_action("/api/term/input", "ulak_31", self.BODY)
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(b["input_id"] == "u-1" and t == web_hosts.TERM_ATTEMPT_TIMEOUT for b, t in calls))

    def test_gives_up_after_three(self):
        with mock.patch.object(web_hosts, "proxy_action", return_value=({"ok": False, "error": "h unreachable: x"}, 200)) as m:
            res, _ = web_hosts.proxy_term_action("/api/term/input", "h", self.BODY)
        self.assertFalse(res["ok"])
        self.assertEqual(m.call_count, 3)

    def test_remote_logic_error_not_retried(self):
        with mock.patch.object(web_hosts, "proxy_action", return_value=({"ok": False, "error": "term_session_gone"}, 200)) as m:
            web_hosts.proxy_term_action("/api/term/input", "h", self.BODY)
        self.assertEqual(m.call_count, 1)

    def test_without_input_id_legacy_single_call_default_timeout(self):
        body = {k: v for k, v in self.BODY.items() if k != "input_id"}
        with mock.patch.object(web_hosts, "proxy_action", return_value=({"ok": False, "error": "h unreachable: x"}, 200)) as m:
            web_hosts.proxy_term_action("/api/term/input", "h", body)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(m.call_args.kwargs.get("timeout"), None)

    def test_other_paths_untouched(self):
        with mock.patch.object(web_hosts, "proxy_action", return_value=({"ok": False, "error": "h unreachable: x"}, 200)) as m:
            web_hosts.proxy_term_action("/api/stop", "h", self.BODY)
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class HttpDedup(unittest.TestCase):
    """do_POST uçtan uca: aynı input_id ikinci kez YAZMAZ (ok:true dup), yazım başarısızsa kayıt bırakılır, id'siz eski gibi."""

    def setUp(self):
        import json, threading, urllib.request
        from http.server import ThreadingHTTPServer
        term_dedup._seen.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        p = mock.patch.object(web._Handler, "token", "tok")
        p.start()
        self.addCleanup(p.stop)
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.port = self.srv.server_address[1]
        self._json, self._req = json, urllib.request

    def post(self, body):
        r = self._req.Request(f"http://127.0.0.1:{self.port}/api/term/input?token=tok", self._json.dumps(body).encode(),
                              {"Content-Type": "application/json"})
        return self._json.loads(self._req.urlopen(r, timeout=10).read())

    def test_second_delivery_does_not_write(self):
        with mock.patch.object(web, "_term_input", return_value={"ok": True}) as m:
            a = self.post({"name": "s", "text": "x", "input_id": "i1"})
            b = self.post({"name": "s", "text": "x", "input_id": "i1"})
        self.assertEqual((a, b.get("dup")), ({"ok": True}, True))
        self.assertEqual(m.call_count, 1)

    def test_failed_write_can_be_retried(self):
        with mock.patch.object(web, "_term_input", side_effect=[{"ok": False, "error": "gone"}, {"ok": True}]) as m:
            a = self.post({"name": "s", "text": "x", "input_id": "i2"})
            b = self.post({"name": "s", "text": "x", "input_id": "i2"})
        self.assertFalse(a["ok"])
        self.assertTrue(b["ok"])
        self.assertEqual(m.call_count, 2)

    def test_no_input_id_always_writes(self):
        with mock.patch.object(web, "_term_input", return_value={"ok": True}) as m:
            self.post({"name": "s", "text": "x"})
            self.post({"name": "s", "text": "x"})
        self.assertEqual(m.call_count, 2)
