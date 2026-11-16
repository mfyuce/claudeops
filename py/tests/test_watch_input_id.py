"""`watch.InputSender`: her gönderim `input_id` taşır ve taşıma hatasında AYNI id ile yeniden denenir (uzak oturum
mesajı kaybı hatası). Ağ yok: `urlopen` sahte. Çalıştırılmadı (yazıldığı oturumda test koşturulamadı)."""
import io
import json
import os
import sys
import time
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import term_dedup  # noqa: E402
from claudeops.commands import watch  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def drain(sender, n=1, timeout=5.0):
    end = time.monotonic() + timeout
    out = []
    while len(out) < n and time.monotonic() < end:
        out += sender.take_results()
        time.sleep(0.01)
    return out


class InputIdTests(unittest.TestCase):
    def make(self, script):
        bodies = []

        def urlopen(req, timeout=None):
            bodies.append(json.loads(req.data))
            step = script[min(len(bodies) - 1, len(script) - 1)]
            if isinstance(step, Exception):
                raise step
            return FakeResp(step)

        sender = watch.InputSender(1, "uzak", "s1", read_token=lambda: "tok", urlopen=urlopen)
        self.addCleanup(sender.close, 0.5)
        return sender, bodies

    def test_input_id_is_sent_and_valid(self):
        sender, bodies = self.make([{"ok": True}])
        sender.submit("text", "merhaba")
        res = drain(sender)
        self.assertTrue(res[0][2])
        self.assertEqual(bodies[0]["host"], "uzak")
        self.assertIsNotNone(term_dedup.valid_id(bodies[0].get("input_id")))

    def test_distinct_ids_per_message(self):
        sender, bodies = self.make([{"ok": True}])
        sender.submit("text", "a")
        sender.submit("text", "b")
        drain(sender, 2)
        self.assertEqual(len(bodies), 2)
        self.assertNotEqual(bodies[0]["input_id"], bodies[1]["input_id"])

    def test_transport_timeout_retried_with_same_id(self):
        sender, bodies = self.make([TimeoutError("timed out"), TimeoutError("timed out"), {"ok": True}])
        sender.submit("text", "uzaga git")
        res = drain(sender)
        self.assertTrue(res[0][2])
        self.assertEqual(len(bodies), 3)
        self.assertEqual(len({b["input_id"] for b in bodies}), 1)

    def test_transport_failure_gives_up_after_max_attempts(self):
        sender, bodies = self.make([urllib.error.URLError("down")])
        sender.submit("text", "x")
        res = drain(sender)
        self.assertFalse(res[0][2])
        self.assertEqual(len(bodies), watch.InputSender.MAX_ATTEMPTS)

    def test_panel_rejection_not_retried(self):
        sender, bodies = self.make([{"ok": False, "error": "oturum yok"}])
        sender.submit("text", "x")
        res = drain(sender)
        self.assertFalse(res[0][2])
        self.assertEqual(res[0][3], "oturum yok")
        self.assertEqual(len(bodies), 1)

    def test_http_error_not_retried(self):
        err = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b""))
        sender, bodies = self.make([err])
        sender.submit("text", "x")
        res = drain(sender)
        self.assertFalse(res[0][2])
        self.assertEqual(len(bodies), 1)


if __name__ == "__main__":
    unittest.main()
