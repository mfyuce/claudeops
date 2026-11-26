"""H3 yarışı: REST yoklaması sürerken gelen push karesi, aynı turun (daha eski) REST sonucuyla ezilmemeli."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts as wh  # noqa: E402

NAME = "racehost"
HOST = {"name": NAME, "token": "t", "base_url": "http://x"}


def _row(name):
    return {"name": name}


def _rest(name):
    return {"ok": True, "error": None, "sessions": [_row(name)]}


class PushDuringRestTest(unittest.TestCase):
    def setUp(self):
        stores = (wh._cache, wh._last_good, wh._fail_streak, wh._last_ok_at, wh._last_try_at, wh._probe_at)

        def clear():
            for d in stores:
                d.pop(NAME, None)
        clear()
        self.addCleanup(clear)
        captured = {}

        class Capture:
            def __init__(self, tier, make_call, parse_item, on_item, label=""):
                captured["on_item"] = on_item

        with mock.patch.object(wh, "_PushConsumer", Capture):
            wh._start_status_consumer(HOST, "ws")
        self.push = lambda: captured["on_item"]({"ok": True, "sessions": [_row("fresh")]})

    def _fetch_with_push(self, result):
        def fetch(host):
            self.push()
            return result
        return mock.patch.object(wh, "fetch_remote_status", fetch)

    def _names(self):
        return [s["name"] for s in wh._cache[NAME]["sessions"]]

    def _hosts(self):
        return mock.patch.object(wh.hosts_mod, "load_hosts", lambda: [HOST])

    def test_poll_once_keeps_frame_that_arrived_during_rest(self):
        with self._hosts(), self._fetch_with_push(_rest("old")), \
                mock.patch.object(wh, "_apply_probe_choice", lambda h: None), \
                mock.patch.object(wh, "_ensure_status_consumer", lambda h: False), \
                mock.patch.object(wh, "_reap_status_consumers", lambda names: None):
            wh._poll_once()
        self.assertEqual(self._names(), ["fresh"])

    def test_late_rest_failure_does_not_count_against_live_push(self):
        with self._hosts(), self._fetch_with_push({"ok": False, "error": "timeout"}):
            wh.probe_host(NAME)
        self.assertEqual(wh._fail_streak.get(NAME), 0)
        self.assertEqual(self._names(), ["fresh"])

    def test_probe_host_keeps_frame_that_arrived_during_rest(self):
        with self._hosts(), self._fetch_with_push(_rest("old")):
            wh.probe_host(NAME)
        self.assertEqual(self._names(), ["fresh"])

    def test_test_now_returns_own_result_but_keeps_newer_cache(self):
        with mock.patch.object(wh.hosts_mod, "get_host", lambda n: HOST), self._fetch_with_push(_rest("old")), \
                mock.patch.object(wh, "_probe_tier", lambda h: "rest"), \
                mock.patch.object(wh, "_update_tier", lambda n, t: None):
            out = wh.test_now(NAME)
        self.assertEqual([s["name"] for s in out["sessions"]], ["old"])
        self.assertEqual(self._names(), ["fresh"])

    def test_rest_started_after_frame_still_overwrites(self):
        self.push()
        with self._hosts(), mock.patch.object(wh, "fetch_remote_status", lambda h: _rest("newer")):
            wh.probe_host(NAME)
        self.assertEqual(self._names(), ["newer"])


if __name__ == "__main__":
    unittest.main()
