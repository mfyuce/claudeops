"""`/ws/term?interval=` ve girdide uyanma testleri (stdlib unittest, ek bağımlılık yok; yalnız 127.0.0.1).

Çalıştırma:  python3 py/tests/test_term_poll_interval.py -v

Kapsadığı tasarım (TODO.md 2026-10-13 (2)): her `/ws/term` bağlantısı, ekran değişmese bile, 0,2 sn'de bir gerçek iş
(3 tmux alt süreci + 2000 satırlık capture) yapıyor; 17 mirror ulak_31 panelini %148, 7 mirror yuhem panelini %211
CPU'ya çıkardı. Mirror (`cops watch`) `interval=1` ister; yerel panel bunu uzak host'un `/ws/term`'ine iletir, uzak
döngü o kadar seyrek yoklar; oturuma girdi yazılınca döngü hemen uyanır (yazılanın yankısı seyrek aralığı beklemez).
Eski kod yolları AYNEN çalışmalı: `interval` yoksa anahtar/URL/imza değişmez. Ağa / tmux'a DOKUNMAZ.
"""
import json
import os
import queue
import sys
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from websockets.sync.client import connect
    from claudeops.commands import watch, web, web_hosts, web_ws
except ImportError as e:  # pragma: no cover
    raise unittest.SkipTest(f"websockets kurulu değil: {e}")


def wait_until(predicate, timeout=5.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


# ── parse_term_interval ─────────────────────────────────────────────────────────────────────

class ParseIntervalTests(unittest.TestCase):
    def test_missing_or_invalid_or_not_slower_means_no_parameter(self):
        for raw in (None, "", "  ", "abc", "nan", "inf", "-inf", "-1", "0", "0.1", "0.2", "0.24"):
            self.assertIsNone(web_ws.parse_term_interval(raw), raw)

    def test_slower_intervals_are_kept_and_rounded_to_a_tenth(self):
        self.assertEqual(web_ws.parse_term_interval("1"), 1.0)
        self.assertEqual(web_ws.parse_term_interval(" 1.0 "), 1.0)
        self.assertEqual(web_ws.parse_term_interval("2.5"), 2.5)
        self.assertEqual(web_ws.parse_term_interval("0.34"), 0.3)   # röle anahtarı sayısı patlamasın
        self.assertEqual(web_ws.parse_term_interval("0.26"), 0.3)

    def test_upper_bound_keeps_a_forgotten_connection_from_going_stale(self):
        self.assertEqual(web_ws.parse_term_interval("99"), web_ws._TERM_MAX_INTERVAL_SECONDS)
        self.assertEqual(web_ws._TERM_MAX_INTERVAL_SECONDS, 5.0)


# ── poll döngüsü: aralık + uyanma ───────────────────────────────────────────────────────────

class PollLoopTests(unittest.TestCase):
    """Sahte `_send` ve sahte istemciyle; zamanlar gevşek aralıklarla doğrulanır (yavaş makine)."""

    def setUp(self):
        self.calls = []
        self.client = SimpleNamespace(closed=threading.Event(), wake=threading.Event())
        for p in (mock.patch.object(web_ws, "_send", lambda c, data: True),
                  mock.patch.object(web_ws, "_TERM_POLL_SECONDS", 0.05),
                  mock.patch.object(web_ws, "_TERM_WAKE_BURST_SECONDS", 0.4)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._stop)
        self.thread = None

    def _stop(self):
        self.client.closed.set()
        self.client.wake.set()
        if self.thread is not None:
            self.thread.join(3)

    def fetch(self):
        self.calls.append(time.monotonic())
        return {"ok": True, "text": f"f{len(self.calls)}"}   # her kare farklı, hepsi yollanır

    def start(self, poll_seconds):
        self.thread = threading.Thread(target=web_ws._term_poll_loop,
                                       args=(self.client, self.fetch, poll_seconds), daemon=True)
        self.thread.start()

    def test_default_cadence_is_the_module_constant_read_at_call_time(self):
        self.start(None)
        time.sleep(0.6)
        self.assertGreaterEqual(len(self.calls), 6)   # ~12 beklenir (0,05 sn); sabit çağrı anında okunuyor

    def test_slow_interval_polls_much_less_often(self):
        self.start(0.4)
        time.sleep(1.1)
        self.assertGreaterEqual(len(self.calls), 2)
        self.assertLessEqual(len(self.calls), 4)      # ~3 beklenir (0, 0,4, 0,8); varsayılanla ~22 olurdu

    def test_wake_polls_immediately_then_fast_for_the_burst_then_slows_down_again(self):
        self.start(1.5)
        time.sleep(0.15)
        self.assertEqual(len(self.calls), 1)            # ilk yoklama hemen, sonraki 1,5 sn sonra
        t_wake = time.monotonic()
        self.client.wake.set()
        self.assertTrue(wait_until(lambda: len(self.calls) >= 2, 0.4), "uyanma hemen yoklatmadı")
        self.assertLess(self.calls[1] - t_wake, 0.3)
        time.sleep(0.3)                                  # burst (0,4 sn) sürerken hızlı yoklama
        self.assertGreaterEqual(len(self.calls), 5)
        before = len(self.calls)
        time.sleep(0.8)                                  # burst bitti: yeniden 1,5 sn'lik seyrek yoklama
        self.assertLessEqual(len(self.calls) - before, 3)

    def test_close_wakes_a_long_wait_immediately(self):
        self.start(5.0)
        self.assertTrue(wait_until(lambda: len(self.calls) == 1, 1.0))
        t0 = time.monotonic()
        self.client.closed.set()
        self.client.wake.set()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertLess(time.monotonic() - t0, 1.0)      # 5 sn beklemedi

    def test_plain_client_without_wake_keeps_the_old_behavior(self):
        plain = SimpleNamespace(closed=threading.Event())   # mevcut testlerin kullandığı sade istemci
        t = threading.Thread(target=web_ws._term_poll_loop, args=(plain, self.fetch, 5.0), daemon=True)
        t.start()
        self.assertTrue(wait_until(lambda: len(self.calls) == 1, 1.0))
        plain.closed.set()
        t.join(2)
        self.assertFalse(t.is_alive())


class WakerRegistryTests(unittest.TestCase):
    def setUp(self):
        with web_ws._TERM_WAKERS_LOCK:
            web_ws._TERM_WAKERS.clear()

    def test_notify_sets_only_the_watchers_of_that_name(self):
        a, b, other = threading.Event(), threading.Event(), threading.Event()
        web_ws._register_term_waker("s1", a)
        web_ws._register_term_waker("s1", b)
        web_ws._register_term_waker("s2", other)
        web_ws.notify_term_activity("s1")
        self.assertTrue(a.is_set() and b.is_set())
        self.assertFalse(other.is_set())

    def test_unregister_removes_the_entry_so_the_registry_cannot_leak(self):
        a = threading.Event()
        web_ws._register_term_waker("s1", a)
        web_ws._unregister_term_waker("s1", a)
        self.assertEqual(web_ws._TERM_WAKERS, {})
        web_ws.notify_term_activity("s1")
        self.assertFalse(a.is_set())

    def test_unknown_or_empty_names_are_harmless(self):
        web_ws.notify_term_activity("nobody")
        web_ws.notify_term_activity("")
        web_ws._register_term_waker(None, threading.Event())
        web_ws._unregister_term_waker(None, threading.Event())
        self.assertEqual(web_ws._TERM_WAKERS, {})


# ── gerçek WS sunucusu: aralık, girdi bildirimi, kapanışta temizlik ─────────────────────────

class RealServerTests(unittest.TestCase):
    def serve(self, poll_seconds, name="n"):
        calls = []

        def fetch():
            calls.append(time.monotonic())
            return {"ok": True, "text": f"f{len(calls)}", "cols": 80, "rows": 24, "lite": True}

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self_h):
                web_ws.handle_ws_term(self_h, fetch, poll_seconds=poll_seconds, name=name)

            def log_message(self_h, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = connect(f"ws://127.0.0.1:{server.server_address[1]}/ws/term?name={name}",
                       ping_interval=None, close_timeout=3.0)
        self.addCleanup(conn.close)
        return conn, calls

    def setUp(self):
        with web_ws._TERM_WAKERS_LOCK:
            web_ws._TERM_WAKERS.clear()

    def test_default_connection_polls_every_200ms(self):
        _conn, calls = self.serve(None)
        time.sleep(1.3)
        self.assertGreaterEqual(len(calls), 5)   # ~7

    def test_interval_connection_polls_far_less_often(self):
        _conn, calls = self.serve(0.75)
        time.sleep(1.6)
        self.assertGreaterEqual(len(calls), 2)
        self.assertLessEqual(len(calls), 4)      # ~3 (0, 0,75, 1,5)

    def test_input_notification_wakes_the_slow_loop_and_the_new_frame_reaches_the_client(self):
        conn, calls = self.serve(3.0)
        first = json.loads(conn.recv(timeout=2))
        self.assertEqual(first["data"]["text"], "f1")
        time.sleep(0.2)
        self.assertEqual(len(calls), 1)          # 3 sn'lik aralık: başka yoklama yok
        t0 = time.monotonic()
        web_ws.notify_term_activity("n")         # /api/term/input|key|raw'ın yaptığı
        second = json.loads(conn.recv(timeout=2))
        self.assertEqual(second["data"]["text"], "f2")
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_closing_the_client_stops_the_loop_and_unregisters_the_waker(self):
        conn, calls = self.serve(3.0)
        self.assertTrue(wait_until(lambda: "n" in web_ws._TERM_WAKERS, 2.0))
        conn.close()
        self.assertTrue(wait_until(lambda: "n" not in web_ws._TERM_WAKERS, 2.0),
                        "kapanış, 3 sn'lik bekleyişi bölüp waker kaydını silmedi")
        n = len(calls)
        time.sleep(0.5)
        self.assertEqual(len(calls), n)          # döngü durdu


# ── web.py: fetch_fn'e iletim, yerel döngü aralığı, girdide bildirim ─────────────────────────

class FetchFnIntervalTests(unittest.TestCase):
    def setUp(self):
        self.relay_calls = []
        self.tier = "ws"

        def fake_relay(host, name, lang, lite=False, **extra):
            self.relay_calls.append((host, name, lang, lite, dict(extra)))
            return lambda: {"ok": True, "text": "x", "rows": 1, "lite": True}

        for p in (mock.patch.object(web.web_hosts, "get_tier", lambda host: self.tier),
                  mock.patch.object(web.web_hosts, "term_output_relay", fake_relay),
                  mock.patch.object(web.web_hosts, "proxy_get", lambda path, host, query: ({"ok": True}, 200))):
            p.start()
            self.addCleanup(p.stop)

    def test_without_interval_the_relay_is_called_exactly_as_before(self):
        web._term_fetch_fn("ulak_31", "s1", "en", True)
        self.assertEqual(self.relay_calls, [("ulak_31", "s1", "en", True, {})])

    def test_interval_is_forwarded_to_the_relay_only_when_given(self):
        web._term_fetch_fn("ulak_31", "s1", "en", True, interval=1.0)
        self.assertEqual(self.relay_calls, [("ulak_31", "s1", "en", True, {"interval": 1.0})])

    def test_loop_interval_lands_on_the_local_loop_only_when_the_tick_is_real_work(self):
        self.tier = "ws"      # relay: yerel döngü bellekten okur, aralık uzak hop'a gider
        self.assertIsNone(web._term_loop_seconds("ulak_31", 1.0))
        self.tier = "rest"    # her tick bir HTTP isteği: aralık döngünün kendisine
        self.assertEqual(web._term_loop_seconds("ulak_31", 1.0), 1.0)
        self.assertEqual(web._term_loop_seconds(web.LOCAL_HOST_NAME, 1.0), 1.0)   # yerel: her tick tmux
        self.assertIsNone(web._term_loop_seconds(web.LOCAL_HOST_NAME, None))
        self.assertIsNone(web._term_loop_seconds("ulak_31", None))


class InputNotifiesTests(unittest.TestCase):
    """`/api/term/input|key|raw` girdi pane'e GİTTİKTEN sonra o oturumu izleyen döngüleri uyandırır; gitmediyse uyandırmaz."""

    def setUp(self):
        self.sent_ok = True
        with web_ws._TERM_WAKERS_LOCK:
            web_ws._TERM_WAKERS.clear()
        self.event = threading.Event()
        web_ws._register_term_waker("n", self.event)
        self.addCleanup(web_ws._unregister_term_waker, "n", self.event)
        sess = SimpleNamespace(name="tm", cli="shell")
        for p in (mock.patch.object(web, "_term_resolve", lambda name, lang: (sess, None)),
                  mock.patch.object(web, "get_provider", lambda cli: SimpleNamespace(input_settle_delay=lambda: 0)),
                  mock.patch.object(web, "tmux_send_keys", lambda *a, **k: self.sent_ok),
                  mock.patch.object(web, "tmux_send_special_key", lambda *a, **k: self.sent_ok),
                  mock.patch.object(web, "tmux_send_raw", lambda *a, **k: self.sent_ok)):
            p.start()
            self.addCleanup(p.stop)

    def test_text_key_and_raw_input_wake_the_watchers(self):
        for call in (lambda: web._term_input("n", "hello"), lambda: web._term_key("n", "Enter"),
                     lambda: web._term_raw("n", "abc")):
            self.event.clear()
            self.assertTrue(call()["ok"])
            self.assertTrue(self.event.is_set())

    def test_failed_send_does_not_wake(self):
        self.sent_ok = False
        for call in (lambda: web._term_input("n", "hello"), lambda: web._term_key("n", "Enter"),
                     lambda: web._term_raw("n", "abc")):
            self.event.clear()
            self.assertFalse(call()["ok"])
            self.assertFalse(self.event.is_set())

    def test_rejected_key_and_empty_raw_do_not_wake(self):
        self.assertFalse(web._term_key("n", "F13")["ok"])
        self.assertTrue(web._term_raw("n", "")["ok"])
        self.assertFalse(self.event.is_set())

    def test_other_sessions_are_not_woken(self):
        other = threading.Event()
        web_ws._register_term_waker("other", other)
        self.addCleanup(web_ws._unregister_term_waker, "other", other)
        web._term_input("n", "hello")
        self.assertFalse(other.is_set())


# ── web_hosts.term_output_relay: uzak URL'ye, anahtara, etikete ───────────────────────────────

FAKE_HOST = {"name": "fakehost", "base_url": "http://127.0.0.1:9", "token": "not-a-real-token"}


class FakeWS:
    def __init__(self):
        self._q = queue.Queue()

    def close(self):
        self._q.put(None)

    def __iter__(self):
        return self

    def __next__(self):
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item


class RelayIntervalTests(unittest.TestCase):
    def setUp(self):
        web_hosts._term_relays.clear()
        web_hosts._consumer_death_log_last.clear()
        self.urls = []
        self.logged = []
        self.connect_error = None

        def fake_connect(url, **kwargs):
            if self.connect_error is not None:
                raise self.connect_error
            self.urls.append(url)
            return FakeWS()

        for p in (mock.patch.object(web_hosts.hosts_mod, "get_host", lambda name: dict(FAKE_HOST)),
                  mock.patch.object(web_hosts, "get_tier", lambda name: "ws"),
                  mock.patch.object(web_hosts, "ws_connect", fake_connect),
                  mock.patch.object(web_hosts, "diag_log", lambda event, **data: self.logged.append((event, data)))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._stop_relays)

    def _stop_relays(self):
        for r in list(web_hosts._term_relays.values()):
            r.stop()
        web_hosts._term_relays.clear()

    def qs(self, url):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    def test_interval_goes_to_the_remote_url_and_into_the_key(self):
        web_hosts.term_output_relay("fakehost", "s1", "en", lite=True, interval=1.0)()
        self.assertTrue(wait_until(lambda: len(self.urls) == 1))
        qs = self.qs(self.urls[0])
        self.assertEqual((qs["interval"], qs["lite"], qs["name"]), (["1"], ["1"], ["s1"]))
        self.assertEqual(list(web_hosts._term_relays), [("fakehost", "s1", "en", True, 1.0)])

    def test_without_interval_url_and_key_are_exactly_as_before(self):
        web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)()
        self.assertTrue(wait_until(lambda: len(self.urls) == 1))
        self.assertNotIn("interval", self.qs(self.urls[0]))
        self.assertEqual(list(web_hosts._term_relays), [("fakehost", "s1", "en", True)])

    def test_slow_and_default_watchers_of_one_session_get_separate_remote_streams(self):
        slow = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True, interval=1.0)
        fast = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)
        slow()
        fast()
        self.assertTrue(wait_until(lambda: len(self.urls) == 2))
        self.assertEqual(sorted("interval" in self.qs(u) for u in self.urls), [False, True])

    def test_two_slow_watchers_share_one_remote_stream(self):
        a = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True, interval=1.0)
        b = web_hosts.term_output_relay("fakehost", "s1", "en", lite=True, interval=1.0)
        a()
        b()
        self.assertTrue(wait_until(lambda: len(self.urls) >= 1))
        time.sleep(0.1)
        self.assertEqual(len(self.urls), 1)

    def test_death_label_names_the_interval(self):
        self.connect_error = OSError("connection refused")
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            web_hosts.term_output_relay("fakehost", "s1", "en", lite=True, interval=1.0)()
        deaths = lambda: [d for e, d in self.logged if e == "push_consumer_died"]
        self.assertTrue(wait_until(lambda: len(deaths()) >= 1))
        self.assertEqual(deaths()[0]["label"], "term:fakehost/s1?lite@1s")

    def test_death_label_without_interval_is_unchanged(self):
        self.connect_error = OSError("connection refused")
        with mock.patch.object(web_hosts, "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS", 0.0):
            web_hosts.term_output_relay("fakehost", "s1", "en", lite=True)()
        deaths = lambda: [d for e, d in self.logged if e == "push_consumer_died"]
        self.assertTrue(wait_until(lambda: len(deaths()) >= 1))
        self.assertEqual(deaths()[0]["label"], "term:fakehost/s1?lite")


# ── cops watch ───────────────────────────────────────────────────────────────────────────────

class WatchQueryTests(unittest.TestCase):
    def test_ws_asks_for_the_slow_interval_but_the_rest_fallback_does_not(self):
        ws_qs = dict(urllib.parse.parse_qsl(watch._ws_query("yuhem", "s1")))
        self.assertEqual(ws_qs, {"name": "s1", "host": "yuhem", "lang": "en", "lite": "1", "interval": "1"})
        rest = watch.RestTransport(8765, "yuhem", "s1")
        self.assertNotIn("interval", dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(rest.url).query)))

    def test_the_viewers_interval_is_one_the_panel_accepts_as_slow(self):
        self.assertIsNotNone(web_ws.parse_term_interval(str(watch.WS_POLL_INTERVAL_SECONDS)))
        # sunucunun sessizlik bekçisi (75 sn) ve heartbeat'i (30 sn) seyrek yoklamadan etkilenmez
        self.assertLess(watch.WS_POLL_INTERVAL_SECONDS, watch.WS_SILENCE_SECONDS)


if __name__ == "__main__":
    unittest.main()
