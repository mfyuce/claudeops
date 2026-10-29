"""Uzak host "kapalı" bayrağı takılması (2026-10-29, ulak_31 18+ dk): sessiz push akışı yenilenir, poller watchdog'u, tick başı
hafif yoklama, `steward status` nedeni. Gerçek ağ/thread YOK (stdlib unittest)."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts as wh, web_steward as ws, steward as cli  # noqa: E402

HOST = {"name": "ulak31", "token": "t", "base_url": "http://x"}
OK = {"ok": True, "error": "", "sessions": [], "closed": []}


class FakeConsumer:
    def __init__(self, tier="ws", silent=0.0, alive=True):
        self.tier, self._silent, self._alive, self.stopped = tier, silent, alive, False

    def is_alive(self):
        return self._alive

    def silent_seconds(self):
        return self._silent

    def stop(self):
        self.stopped = True


class SilentConsumerTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(wh._status_consumers.clear)
        wh._status_consumers.clear()

    def test_healthy_consumer_keeps_rest_off(self):
        c = FakeConsumer(silent=5.0)
        wh._status_consumers["ulak31"] = c
        with mock.patch.object(wh, "get_tier", lambda n: "ws"):
            self.assertTrue(wh._ensure_status_consumer(HOST))
        self.assertFalse(c.stopped)

    def test_silent_but_alive_consumer_replaced_and_rest_used_this_tick(self):
        old, new = FakeConsumer(silent=wh.STATUS_PUSH_SILENCE_SECONDS + 1), FakeConsumer(silent=0.0)
        wh._status_consumers["ulak31"] = old
        with mock.patch.object(wh, "get_tier", lambda n: "ws"), \
                mock.patch.object(wh, "_start_status_consumer", lambda h, t: new):
            self.assertFalse(wh._ensure_status_consumer(HOST))        # False -> _poll_once REST'e düşer
            self.assertTrue(old.stopped)
            self.assertIs(wh._status_consumers["ulak31"], new)
            self.assertTrue(wh._ensure_status_consumer(HOST))         # sonraki tick: yeni akış (sessizlik 0) güvenilir

    def test_replacement_failure_still_stops_old_and_falls_to_rest(self):
        old = FakeConsumer(silent=999.0)
        wh._status_consumers["ulak31"] = old

        def boom(h, t):
            raise OSError("x")
        with mock.patch.object(wh, "get_tier", lambda n: "ws"), mock.patch.object(wh, "_start_status_consumer", boom):
            self.assertFalse(wh._ensure_status_consumer(HOST))
        self.assertTrue(old.stopped)
        self.assertNotIn("ulak31", wh._status_consumers)

    def test_push_consumer_tracks_last_message(self):
        got = []
        c = wh._PushConsumer("ws", lambda: iter(["a", "b"]), lambda r: {"v": r}, got.append)
        c._thread.join(2)
        self.assertEqual([g["v"] for g in got], ["a", "b"])
        self.assertLess(c.silent_seconds(), 5.0)
        c.last_msg_mono -= 100
        self.assertGreater(c.silent_seconds(), 90.0)


class PollerWatchdogTest(unittest.TestCase):
    def setUp(self):
        saved = (wh._poller_started, wh._poller_gen, wh._poller_beat, wh._poller_thread, wh._poller_restarts)
        self.addCleanup(lambda: (setattr(wh, "_poller_started", saved[0]), setattr(wh, "_poller_gen", saved[1]),
                                 setattr(wh, "_poller_beat", saved[2]), setattr(wh, "_poller_thread", saved[3]),
                                 setattr(wh, "_poller_restarts", saved[4])))
        wh._poller_restarts = 0

    def test_not_started_is_noop(self):
        wh._poller_started = False
        self.assertFalse(wh.ensure_poller_alive())

    def test_dead_thread_restarted(self):
        wh._poller_started = True
        dead = mock.Mock()
        dead.is_alive.return_value = False
        wh._poller_thread, wh._poller_beat = dead, time.monotonic()
        with mock.patch.object(wh, "_poller_loop", lambda gen=0: None):
            self.assertTrue(wh.ensure_poller_alive())
        self.assertEqual(wh.poller_health()["restarts"], 1)

    def test_stalled_thread_restarted_and_healthy_left_alone(self):
        wh._poller_started = True
        live = mock.Mock()
        live.is_alive.return_value = True
        wh._poller_thread, wh._poller_beat = live, time.monotonic()
        with mock.patch.object(wh, "_poller_loop", lambda gen=0: None):
            self.assertFalse(wh.ensure_poller_alive())                # canlı ve nabzı taze
            wh._poller_beat = time.monotonic() - wh.POLLER_STALL_SECONDS - 5
            gen = wh._poller_gen
            self.assertTrue(wh.ensure_poller_alive())                 # canlı ama takılı (ağ çağrısında)
        self.assertEqual(wh._poller_gen, gen + 1)                     # eski thread nesil uyuşmazlığıyla çıkar

    def test_old_generation_loop_exits(self):
        wh._poller_gen = 5
        with mock.patch.object(wh, "_poll_once") as po:
            wh._poller_loop(4)
        po.assert_not_called()


class ProbeTest(unittest.TestCase):
    def setUp(self):
        for d in (wh._cache, wh._fail_streak, wh._last_good, wh._last_ok_at, wh._last_try_at, wh._probe_at):
            self.addCleanup(d.clear)
            d.clear()

    def test_probe_records_success_and_is_rate_limited(self):
        with mock.patch.object(wh.hosts_mod, "load_hosts", lambda: [HOST]), \
                mock.patch.object(wh, "fetch_remote_status", lambda h: dict(OK)):
            self.assertTrue(wh.probe_host("ulak31", now=1000.0))
            self.assertGreater(wh.last_ok_at("ulak31"), 0)            # poller ile aynı kayıt yolu: host taze olur
            self.assertGreater(wh.last_try_at("ulak31"), 0)
            self.assertIsNone(wh.probe_host("ulak31", now=1005.0))    # 15 sn içinde ikinci yoklama atlanır
            self.assertTrue(wh.probe_host("ulak31", now=1000.0 + wh._PROBE_MIN_GAP_SECONDS + 1))

    def test_probe_failure_and_unknown_host(self):
        with mock.patch.object(wh.hosts_mod, "load_hosts", lambda: [HOST]), \
                mock.patch.object(wh, "fetch_remote_status", lambda h: {"ok": False, "error": "timeout"}):
            self.assertFalse(wh.probe_host("ulak31", now=1.0))
            self.assertEqual(wh.last_ok_at("ulak31"), 0.0)
            self.assertIsNone(wh.probe_host("yok", now=1.0))

    def test_probe_never_raises(self):
        with mock.patch.object(wh.hosts_mod, "load_hosts", side_effect=RuntimeError("x")):
            self.assertFalse(wh.probe_host("ulak31", now=1.0))


class StewardSideTest(unittest.TestCase):
    def test_probe_stale_hosts_recovers_and_refreshes(self):
        calls = []

        class IO:
            def probe(self, h):
                calls.append(h)
                return {"a": True, "b": False, "c": None}[h]

            def status(self, h):
                return {"ok": True, "last_ok_at": time.time()}
        rt = ws._RemoteTick(now=time.time(), statuses={"a": None, "b": None, "c": None, "d": None}, fresh=frozenset({"d"}))
        with mock.patch.object(ws, "_remote", IO()):
            self.assertEqual(ws._probe_stale_hosts(rt), ["a"])
            self.assertEqual(calls, ["a", "b"])                       # tick başına en çok 2 yoklama; taze "d" yoklanmaz
            self.assertIn("a", rt.fresh)                              # toparlanan host bu tick'te taze

    def test_probe_cap_per_tick_and_errors_swallowed(self):
        class IO:
            def probe(self, h):
                raise RuntimeError("x")

            def status(self, h):
                return None
        rt = ws._RemoteTick(now=time.time(), statuses={"a": None}, fresh=frozenset())
        with mock.patch.object(ws, "_remote", IO()):
            self.assertEqual(ws._probe_stale_hosts(rt), [])

    def test_remote_health_gives_reason_and_last_try_when_down(self):
        with mock.patch.object(ws._remote, "status", lambda h: {"ok": False, "error": "timed out", "last_ok_at": 0}), \
                mock.patch.object(ws, "_caps_cached", lambda h, n: None), \
                mock.patch.object(wh, "last_try_at", lambda h: time.time() - 7):
            e = ws.remote_health({"ulak31"})["ulak31"]
        self.assertEqual(e["state"], "down")
        self.assertEqual(e["reason"], "timed out")
        self.assertTrue(5 <= e["last_try"] <= 9)

    def test_status_line_shows_reason(self):
        res = {"ok": True, "remote_hosts": {"ulak31": {"state": "down", "api": 1, "age": 1100, "reason": "timed out", "last_try": 4}}}
        with mock.patch.object(cli, "_api", lambda *a, **k: res):
            line = cli._remote_health_line(mock.Mock(port=1), "default", ["ulak31"])
        self.assertIn("timed out", line)
        self.assertIn("son deneme", line)


if __name__ == "__main__":
    unittest.main()
