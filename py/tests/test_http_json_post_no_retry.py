"""FED-02: _http_json havuzdan gelen bağlantıda POST'u, istek gönderildikten sonra patlarsa RETRY ETMEZ (sahte bağlantı, ağ yok)."""
import http.client
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts  # noqa: E402


class _Resp:
    status = 200

    def read(self):
        return b'{"ok": true}'


class _Conn:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.requests = 0

    def request(self, *a, **k):
        self.requests += 1
        if self.fail_on == "request":
            raise BrokenPipeError("stale")

    def getresponse(self):
        if self.fail_on == "response":
            raise http.client.RemoteDisconnected("stale")
        return _Resp()

    def close(self):
        pass


class PostRetryTest(unittest.TestCase):
    def _run(self, method, conns):
        it = iter(conns)
        with mock.patch.object(web_hosts, "_pool_checkout",
                               side_effect=lambda *a, **k: (next(it), True)), \
                mock.patch.object(web_hosts, "_pool_checkin"):
            return web_hosts._http_json(method, "http://h.example:1/api/x", {"a": 1}, 1.0)

    def test_post_not_retried_after_send(self):
        bad, good = _Conn("response"), _Conn()
        status, data, err = self._run("POST", [bad, good])
        self.assertEqual(status, 0)
        self.assertIsNotNone(err)
        self.assertEqual(good.requests, 0)

    def test_post_retried_when_send_failed(self):
        bad, good = _Conn("request"), _Conn()
        status, data, err = self._run("POST", [bad, good])
        self.assertEqual(status, 200)
        self.assertEqual(good.requests, 1)

    def test_get_still_retried_after_send(self):
        bad, good = _Conn("response"), _Conn()
        status, data, err = self._run("GET", [bad, good])
        self.assertEqual(status, 200)
        self.assertEqual(good.requests, 1)


if __name__ == "__main__":
    unittest.main()
