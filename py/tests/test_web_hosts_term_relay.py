"""`web_hosts.term_output_relay` regresyon testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_web_hosts_term_relay.py -v

Ağa / uzak host'a DOKUNMAZ: `ws_connect` sahte bir bağlantıyla değiştirilir.

Kapsadığı hata (TODO.md 2026-10-08): 4c21cb5 `fetch_fn`'e `relay.is_alive()` çağrısı ekledi
ama `_TermRelay`'de böyle bir metot yoktu. İkinci tick'ten itibaren `AttributeError` atıyor,
`web_ws._term_poll_loop` bunu sessizce yuttuğu için ws/grpc tier'indeki her uzak host'un
`/ws/term`'i ilk karede sonsuza dek susuyordu.
"""
import json
import os
import queue
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_hosts  # noqa: E402

import urllib.parse  # noqa: E402

FAKE_HOST = {"name": "fakehost", "base_url": "http://127.0.0.1:9", "token": "not-a-real-token"}
KEY = ("fakehost", "s1", "en", False)       # (host, name, lang, lite)
LITE_KEY = ("fakehost", "s1", "en", True)


def wait_for(predicate, timeout=3.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class FakeWS:
    """`websockets.sync` ClientConnection yerine: iterasyonla çerçeve verir, close() ile biter."""

    def __init__(self):
        self._q = queue.Queue()

    def push(self, data):
        self._q.put(json.dumps({"type": "term", "data": data}))

    def end(self):
        self._q.put(None)

    def close(self):
        self._q.put(None)

    def __iter__(self):
        return self

    def __next__(self):
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item


class TermRelayTests(unittest.TestCase):
    def setUp(self):
        web_hosts._term_relays.clear()
        web_hosts._consumer_death_log_last.clear()
        self.conns = []          # başarılı her ws_connect'in döndürdüğü FakeWS
        self.urls = []           # başarılı bağlantıların URL'leri (self.conns ile aynı sırada)
        self.connect_calls = 0   # başarısız olanlar dahil TÜM ws_connect denemeleri
        self.connect_error = None
        self.logged = []         # diag_log(event, **data) çağrıları

        def fake_connect(url, **kwargs):
            self.connect_calls += 1
            if self.connect_error is not None:
                raise self.connect_error
            ws = FakeWS()
            self.conns.append(ws)
            self.urls.append(url)
            return ws

        for p in (
            mock.patch.object(web_hosts.hosts_mod, "get_host", lambda name: dict(FAKE_HOST)),
            mock.patch.object(web_hosts, "get_tier", lambda name: "ws"),
            mock.patch.object(web_hosts, "ws_connect", fake_connect),
            mock.patch.object(web_hosts, "diag_log", lambda event, **data: self.logged.append((event, data))),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._stop_relays)

    def _stop_relays(self):
        for r in list(web_hosts._term_relays.values()):
            r.stop()
        web_hosts._term_relays.clear()

    def _deaths(self):
        return [d for e, d in self.logged if e == "push_consumer_died"]

    def test_second_tick_does_not_raise_and_pushed_frame_is_delivered(self):
        """4c21cb5 regresyonu: ikinci fetch_fn() çağrısı AttributeError atıyordu."""
        fn = web_hosts.term_output_relay("fakehost", "s1", "en")
        self.assertEqual(fn()["error"], "relay: henüz veri gelmedi")
        self.assertFalse(fn()["ok"])  # eski kodda burada AttributeError
        self.assertTrue(wait_for(lambda: len(self.conns) == 1))
        self.conns[0].push({"ok": True, "text": "frame-A", "cols": 100, "rows": 30})
        self.assertTrue(wait_for(lambda: fn().get("text") == "frame-A"))
        self.conns[0].push({"ok": True, "text": "frame-B", "cols": 100, "rows": 30})
        self.assertTrue(wait_for(lambda: fn().get("text") == "frame-B"))  # akış ilk kareden sonra da sürer

    def test_dead_consumer_is_recreated_and_old_frame_is_not_replayed(self):
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            fn = web_hosts.term_output_relay("fakehost", "s1", "en")
            fn()
            self.assertTrue(wait_for(lambda: len(self.conns) == 1))
            self.conns[0].push({"ok": True, "text": "frame-A"})
            self.assertTrue(wait_for(lambda: fn().get("text") == "frame-A"))

            relay = web_hosts._term_relays[KEY]
            self.conns[0].end()  # akış bitti, consumer ölür
            self.assertTrue(wait_for(lambda: not relay.is_alive()))
            # Eski kare tekrar OYNATILMAMALI (4c21cb5'in kapattığı hata); yenisi kurulur
            self.assertNotEqual(fn().get("text"), "frame-A")
            self.assertTrue(wait_for(lambda: len(self.conns) == 2))
            self.conns[1].push({"ok": True, "text": "frame-B"})
            self.assertTrue(wait_for(lambda: fn().get("text") == "frame-B"))

    def test_instantly_dying_consumer_is_not_reconnected_every_tick(self):
        self.connect_error = OSError("connection refused")
        fn = web_hosts.term_output_relay("fakehost", "s1", "en")
        results = []
        for _ in range(25):  # ~0.5 sn, varsayılan 2 sn'lik aralığın çok altında
            results.append(fn())
            time.sleep(0.02)
        self.assertEqual(self.connect_calls, 1)
        self.assertTrue(all(r["ok"] is False for r in results))
        # aralık dolunca yeni bir deneme yapılır
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            self.assertTrue(wait_for(lambda: (fn(), self.connect_calls >= 2)[1]))

    def test_consumer_death_is_logged_once_per_label(self):
        self.connect_error = OSError("connection refused")
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            fn = web_hosts.term_output_relay("fakehost", "s1", "en")
            for _ in range(5):  # her biri yeni bir consumer kurup öldürür
                fn()
                time.sleep(0.05)
        self.assertTrue(wait_for(lambda: len(self._deaths()) >= 1))
        time.sleep(0.1)
        deaths = self._deaths()
        self.assertEqual(len(deaths), 1)  # dakikada label başına en fazla bir satır
        self.assertEqual(deaths[0]["label"], "term:fakehost/s1")
        self.assertEqual(deaths[0]["tier"], "ws")
        self.assertIn("connection refused", deaths[0]["reason"])

    def test_intentional_stop_is_not_logged_as_death(self):
        fn = web_hosts.term_output_relay("fakehost", "s1", "en")
        fn()
        self.assertTrue(wait_for(lambda: len(self.conns) == 1))
        relay = web_hosts._term_relays[KEY]
        relay.stop()  # FakeWS.close() akışı bitirir
        self.assertTrue(wait_for(lambda: not relay.is_alive()))
        time.sleep(0.1)
        self.assertEqual(self._deaths(), [])


    # ── lite (TODO.md "Uzak host'a `lite` iletilsin"): host↔host hop da küçük kare taşısın ──

    def _qs(self, url):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    def _conn_for(self, lite):
        """`lite` bayrağıyla (ya da bayraksız) açılmış bağlantının FakeWS'i."""
        for url, ws in zip(self.urls, self.conns):
            if ("lite" in self._qs(url)) == lite:
                return ws
        return None

    def test_lite_relay_asks_the_remote_for_lite_frames(self):
        fn = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)
        fn()
        self.assertTrue(wait_for(lambda: len(self.urls) == 1))
        qs = self._qs(self.urls[0])
        self.assertEqual(qs["lite"], ["1"])
        self.assertEqual((qs["name"], qs["lang"], qs["token"]), (["s1"], ["en"], ["not-a-real-token"]))
        self.assertEqual(urllib.parse.urlsplit(self.urls[0]).path, "/ws/term")

    def test_plain_relay_does_not_send_lite(self):
        fn = web_hosts.term_output_relay("fakehost", "s1", "en")
        fn()
        self.assertTrue(wait_for(lambda: len(self.urls) == 1))
        self.assertNotIn("lite", self._qs(self.urls[0]))

    def test_lite_flag_false_is_the_default_and_matches_the_plain_key(self):
        web_hosts.term_output_relay("fakehost", "s1", "en", lite=False)()
        self.assertEqual(list(web_hosts._term_relays), [KEY])

    def test_lite_and_plain_are_separate_relays_with_separate_frames(self):
        plain_fn = web_hosts.term_output_relay("fakehost", "s1", "en")
        lite_fn = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)
        plain_fn()
        lite_fn()
        self.assertTrue(wait_for(lambda: len(self.conns) == 2))
        self.assertEqual(set(web_hosts._term_relays), {KEY, LITE_KEY})
        self._conn_for(False).push({"ok": True, "text": "FULL-FRAME", "rows": 3})
        self._conn_for(True).push({"ok": True, "text": "lite-frame", "rows": 3, "lite": True})
        self.assertTrue(wait_for(lambda: plain_fn().get("text") == "FULL-FRAME"))
        self.assertTrue(wait_for(lambda: lite_fn().get("text") == "lite-frame"))
        self.assertTrue(lite_fn().get("lite"))
        self.assertFalse(plain_fn().get("lite"))

    def test_two_lite_consumers_share_one_remote_stream(self):
        a = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)
        b = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)
        a()
        b()
        self.assertTrue(wait_for(lambda: len(self.conns) >= 1))
        time.sleep(0.1)
        self.assertEqual(len(self.conns), 1)  # aynı (host, name, lang, lite) anahtarı tek akış

    def test_lite_relay_death_is_logged_under_its_own_label(self):
        self.connect_error = OSError("connection refused")
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)()
        self.assertTrue(wait_for(lambda: len(self._deaths()) >= 1))
        self.assertEqual(self._deaths()[0]["label"], "term:fakehost/s1?lite")


if __name__ == "__main__":
    unittest.main()
