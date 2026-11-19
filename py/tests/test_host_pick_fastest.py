"""Uzak host en hızlı erişilebilir adres seçimi (LAN extra_url vs devtunnel) + https→http kuralının özel-ağ istisnası."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts as wh  # noqa: E402

BASE = "https://x-8765.euw.devtunnels.ms"
LAN = "http://10.20.4.31:8765"
CF = "https://dead.trycloudflare.com"


def rec(extras=(LAN, CF), base=BASE):
    return {"name": "ulak_31", "base_url": base, "token": "t", "extra_urls": list(extras)}


class AllowedTest(unittest.TestCase):
    def test_http_to_https_base_only_for_private_lan_literal(self):
        self.assertTrue(wh._candidate_allowed(BASE, LAN))
        self.assertTrue(wh._candidate_allowed(BASE, "http://192.168.1.5:8765"))
        self.assertTrue(wh._candidate_allowed(BASE, "http://172.16.0.9"))
        for bad in ("http://8.8.8.8:8765", "http://127.0.0.1:8765", "http://169.254.169.254", "http://host.lan:8765",
                    "http://0.0.0.0:8765"):
            self.assertFalse(wh._candidate_allowed(BASE, bad), bad)
        self.assertTrue(wh._candidate_allowed(BASE, CF))                      # https aday her zaman
        self.assertTrue(wh._candidate_allowed("http://1.2.3.4", "http://8.8.8.8"))   # base zaten http: kısıt yok


class PickTest(unittest.TestCase):
    def pick(self, lat, **kw):
        with mock.patch.object(wh.hosts_mod, "promote_base_url") as prom, mock.patch.object(wh, "diag_log"):
            r = wh.pick_fastest_url(rec(**kw), probe=lambda u, t: lat.get(u))
        return r, prom

    def test_promotes_much_faster_lan(self):
        r, prom = self.pick({BASE: 0.38, LAN: 0.004, CF: None})
        self.assertEqual(r, LAN)
        prom.assert_called_once_with("ulak_31", LAN)

    def test_keeps_base_when_gain_small_or_not_proportional(self):
        self.assertIsNone(self.pick({BASE: 0.040, LAN: 0.030})[0])        # kazanç < 50 ms
        self.assertIsNone(self.pick({BASE: 0.40, LAN: 0.30})[0])          # oran > %60

    def test_base_down_picks_fastest_working_candidate(self):
        r, _ = self.pick({BASE: None, LAN: 0.01, CF: 0.2})
        self.assertEqual(r, LAN)

    def test_nothing_reachable_or_no_extras(self):
        self.assertIsNone(self.pick({BASE: 0.3, LAN: None, CF: None})[0])
        self.assertIsNone(self.pick({BASE: 0.3}, extras=())[0])

    def test_public_http_candidate_never_probed(self):
        probed = []
        with mock.patch.object(wh.hosts_mod, "promote_base_url"), mock.patch.object(wh, "diag_log"):
            r = wh.pick_fastest_url(rec(extras=("http://8.8.8.8:8765",)), probe=lambda u, t: probed.append(u) or 0.001)
        self.assertIsNone(r)
        self.assertEqual(probed, [BASE])          # token genel http adrese gitmez


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        wh._pick_last.clear()
        wh._pick_running.clear()

    def test_runs_in_thread_at_most_once_per_interval(self):
        calls = []
        done = []
        import threading
        ev = threading.Event()

        def fake(h):
            calls.append(h["name"]); ev.set()

        with mock.patch.object(wh, "pick_fastest_url", fake):
            wh._maybe_pick_fastest(rec())
            ev.wait(2)
            wh._maybe_pick_fastest(rec())             # aralık dolmadı
            wh._maybe_pick_fastest(rec(extras=()))     # extras yok
        self.assertEqual(calls, ["ulak_31"])


if __name__ == "__main__":
    unittest.main()
