"""Uzak host adres yoklaması (host_probe): depo kaydı, en hızlı SAĞLIKLI adres seçimi, https→http özel-ağ kuralı, periodic iş, poller okuması."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import host_probe as hp  # noqa: E402
from claudeops import periodic  # noqa: E402
from claudeops.commands import web_hosts as wh  # noqa: E402

BASE = "https://x-8765.euw.devtunnels.ms"
LAN = "http://10.20.4.31:8765"
CF = "https://dead.trycloudflare.com"


def hrec(extras=(LAN, CF), base=BASE):
    return {"name": "ulak_31", "base_url": base, "token": "t", "extra_urls": list(extras)}


class AllowedTest(unittest.TestCase):
    def test_http_to_https_base_only_for_private_lan_literal(self):
        self.assertTrue(wh._candidate_allowed(BASE, LAN))
        self.assertTrue(wh._candidate_allowed(BASE, "http://192.168.1.5:8765"))
        for bad in ("http://8.8.8.8:8765", "http://127.0.0.1:8765", "http://169.254.169.254", "http://host.lan:8765",
                    "http://0.0.0.0:8765"):
            self.assertFalse(wh._candidate_allowed(BASE, bad), bad)
        self.assertTrue(wh._candidate_allowed(BASE, CF))
        self.assertTrue(wh._candidate_allowed("http://1.2.3.4", "http://8.8.8.8"))


class RecordTest(unittest.TestCase):
    def test_avg_of_last_n_and_fail_counters(self):
        r = None
        for i in range(12):
            r = hp.record(r, 0.010 * (i + 1), "", 100.0 + i)
        self.assertEqual(len(r["samples"]), hp.SAMPLES)
        self.assertEqual(r["avg_ms"], round(sum(range(30, 130, 10)) / 10))
        self.assertTrue(r["ok"])
        self.assertEqual(r["fails"], 0)
        r = hp.record(r, None, "timed out", 200.0)
        self.assertFalse(r["ok"])
        self.assertEqual((r["fails"], r["total_fail"], r["total"]), (1, 1, 13))
        self.assertIsNotNone(r["avg_ms"])           # önceki ölçümler ortalamada kalır
        r = hp.record(r, 0.02, "", 210.0)
        self.assertEqual((r["fails"], r["total_fail"]), (0, 1))


def store_with(now, **urls):
    return {"hosts": {"ulak_31": {"urls": {u: dict(r, at=now) for u, r in urls.items()}}}}


def ok(avg, **kw):
    return dict({"ok": True, "ms": avg, "avg_ms": avg, "fails": 0, "total": 5, "total_fail": 0, "samples": [avg]}, **kw)


class ChooseTest(unittest.TestCase):
    NOW = 1000.0

    def choose(self, **urls):
        return hp.choose_for(hrec(), now=self.NOW, store=store_with(self.NOW, **urls))

    def test_picks_fastest_healthy_when_much_faster(self):
        self.assertEqual(self.choose(**{BASE: ok(380), LAN: ok(4), CF: ok(500)}), LAN)

    def test_keeps_base_when_gain_small(self):
        self.assertIsNone(self.choose(**{BASE: ok(40), LAN: ok(30)}))
        self.assertIsNone(self.choose(**{BASE: ok(400), LAN: ok(300)}))

    def test_unhealthy_candidates_ignored(self):
        bad = ok(2, fails=2, ok=False)
        self.assertIsNone(self.choose(**{BASE: ok(380), LAN: bad}))
        self.assertIsNone(self.choose(**{BASE: ok(380), LAN: ok(4, avg_ms=None)}))

    def test_base_down_picks_fastest_healthy(self):
        self.assertEqual(self.choose(**{BASE: ok(0, ok=False, fails=3), LAN: ok(5), CF: ok(200)}), LAN)

    def test_stale_store_means_no_decision(self):
        st = store_with(self.NOW - hp.STALE_SECONDS - 1, **{BASE: ok(380), LAN: ok(4)})
        self.assertIsNone(hp.choose_for(hrec(), now=self.NOW, store=st))

    def test_public_http_candidate_never_chosen(self):
        pub = "http://8.8.8.8:8765"
        self.assertIsNone(hp.choose_for(hrec(extras=(pub,)), now=self.NOW, store=store_with(self.NOW, **{BASE: ok(380), pub: ok(1)})))

    def test_unknown_host_or_empty_store(self):
        self.assertIsNone(hp.choose_for(hrec(), now=self.NOW, store={"hosts": {}}))


class RunProbeTest(unittest.TestCase):
    def test_probes_candidates_in_parallel_writes_store_and_drops_gone_urls(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
                lat = {BASE: (0.38, ""), LAN: (0.004, ""), CF: (None, "timed out")}
                probed = []
                def probe(u, t):
                    probed.append(u)
                    return lat[u]
                r = hp.run_probe([hrec(), {"name": "solo", "base_url": "https://s", "token": "x"}], probe=probe, now=50.0)
                self.assertEqual((r["hosts"], r["urls"], r["ok"]), (1, 3, 2))       # tek adresli host yoklanmaz
                self.assertEqual(sorted(probed), sorted([BASE, LAN, CF]))
                view = hp.public_view("ulak_31")
                self.assertEqual([v["url"] for v in view], [LAN, BASE, CF])           # hızlıdan yavaşa, hatalı sonda
                self.assertEqual(view[-1]["fails"], 1)
                hp._cache["mtime"] = None
                r2 = hp.run_probe([hrec(extras=(LAN,))], probe=probe, now=60.0)       # CF artık aday değil
                self.assertNotIn(CF, [v["url"] for v in hp.public_view("ulak_31")])

    def test_public_http_candidate_not_probed(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
            probed = []
            hp.run_probe([hrec(extras=("http://8.8.8.8:8765", LAN))], probe=lambda u, t: probed.append(u) or (0.01, ""), now=1.0)
            self.assertNotIn("http://8.8.8.8:8765", probed)


class PollerAndJobTest(unittest.TestCase):
    def test_poller_promotes_from_store_without_network(self):
        with mock.patch.object(hp, "choose_for", return_value=LAN), \
             mock.patch.object(wh.hosts_mod, "promote_base_url") as prom, mock.patch.object(wh, "diag_log"):
            wh._apply_probe_choice(hrec())
            prom.assert_called_once_with("ulak_31", LAN)
            prom.reset_mock()
            wh._apply_probe_choice(hrec(extras=()))                                  # extra_urls yok: dokunmaz
            prom.assert_not_called()

    def test_periodic_job_registered_on_and_plans_without_probing(self):
        self.assertIn("host_probe", periodic.JOBS)
        self.assertEqual(periodic.JOBS["host_probe"].defaults["enabled"], "on")
        with mock.patch.object(hp, "run_probe") as rp:
            r = periodic.run_host_probe({}, False, {})
            self.assertTrue(r["ok"])
            rp.assert_not_called()
            rp.return_value = {"hosts": 1, "urls": 3, "ok": 2}
            self.assertIn("3 adres", periodic.run_host_probe({}, True, {})["msg"])


if __name__ == "__main__":
    unittest.main()
