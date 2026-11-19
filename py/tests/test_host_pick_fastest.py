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


def win(ms_list, n_fail=0):
    """Pencere: ms değerleri (tekrarlanır) + sonuna n_fail başarısız deneme; ısınma eşiğini aşar."""
    out = list(ms_list)
    while len(out) < hp.WARMUP + 4 - n_fail:
        out += list(ms_list)
    return out[:hp.WARMUP + 4 - n_fail] + [None] * n_fail


def ok(med, n_fail=0, **kw):
    return dict({"ok": True, "window": win([med, med + 20, med - 20], n_fail), "fails": 0, "total": 20}, **kw)


class ScoreTest(unittest.TestCase):
    def test_components_and_penalty(self):
        sc = hp.score_of({"window": [100] * 10 + [200] * 10})
        self.assertEqual((sc["n"], sc["fail_rate"], sc["warm"]), (20, 0.0, True))
        self.assertEqual(sc["med"], 150)
        clean = hp.score_of({"window": [400] * 20})["score"]
        flaky = hp.score_of({"window": [400] * 14 + [None] * 6})["score"]     # %30 hata
        self.assertGreater(flaky, clean + 1500)                                  # hata puanı BELİRGİN düşürür
        self.assertIsNone(hp.score_of({"window": [None] * 20})["score"])
        self.assertFalse(hp.score_of({"window": [5, 5]})["warm"])                # ısınma
        self.assertEqual(hp.score_of(None)["n"], 0)

    def test_record_fills_window_capped(self):
        r = None
        for i in range(hp.WINDOW + 5):
            r = hp.record(r, 0.1 if i % 2 else None, "x", 1.0)
        self.assertEqual(len(r["window"]), hp.WINDOW)


class ChooseTest(unittest.TestCase):
    NOW = 10000.0

    def setUp(self):
        hp._last_switch.clear()

    def choose(self, **urls):
        return hp.choose_for(hrec(), now=self.NOW, store=store_with(self.NOW, **urls))

    def test_picks_much_better_score(self):
        self.assertEqual(self.choose(**{BASE: ok(380), LAN: ok(4), CF: ok(500)}), LAN)

    def test_keeps_base_when_gain_small(self):
        self.assertIsNone(self.choose(**{BASE: ok(40), LAN: ok(30)}))            # 100 ms kazanç altı
        self.assertIsNone(self.choose(**{BASE: ok(400), LAN: ok(300)}))          # oran 0,7 altına inmiyor

    def test_cold_candidate_never_chosen_even_if_fast(self):
        cold = {"ok": True, "window": [5, 5, 5], "fails": 0}                     # tek tur ısınma ölçümü
        self.assertIsNone(self.choose(**{BASE: ok(900), LAN: cold}))

    def test_flaky_base_loses_to_clean_candidate_with_similar_latency(self):
        # devtunnel: 2 zaman aşımı / 6; menzil: hepsi başarılı ve benzer gecikme -> puan farkı (hata cezası) geçişi sağlar
        self.assertEqual(self.choose(**{BASE: ok(600, n_fail=6), LAN: ok(550)}), LAN)

    def test_candidate_too_flaky_ignored(self):
        self.assertIsNone(self.choose(**{BASE: ok(900), LAN: ok(5, n_fail=10)}))

    def test_base_down_picks_best_warm_candidate(self):
        down = {"ok": False, "window": [None] * 20, "fails": 3}
        self.assertEqual(self.choose(**{BASE: down, LAN: ok(5), CF: ok(200)}), LAN)

    def test_hysteresis_no_flapping(self):
        st = store_with(self.NOW, **{BASE: ok(380), LAN: ok(4)})
        self.assertEqual(hp.choose_for(hrec(), now=self.NOW, store=st), LAN)
        hp.note_switch("ulak_31", self.NOW)
        self.assertIsNone(hp.choose_for(hrec(), now=self.NOW + hp.DWELL_SECONDS - 1, store=st))
        self.assertEqual(hp.choose_for(hrec(), now=self.NOW + hp.DWELL_SECONDS + 1, store=store_with(self.NOW + hp.DWELL_SECONDS + 1, **{BASE: ok(380), LAN: ok(4)})), LAN)

    def test_stale_store_means_no_decision(self):
        st = store_with(self.NOW - hp.STALE_SECONDS - 1, **{BASE: ok(380), LAN: ok(4)})
        self.assertIsNone(hp.choose_for(hrec(), now=self.NOW, store=st))

    def test_public_http_candidate_never_chosen(self):
        pub = "http://8.8.8.8:8765"
        self.assertIsNone(hp.choose_for(hrec(extras=(pub,)), now=self.NOW, store=store_with(self.NOW, **{BASE: ok(380), pub: ok(1)})))

    def test_unknown_host_or_empty_store(self):
        self.assertIsNone(hp.choose_for(hrec(), now=self.NOW, store={"hosts": {}}))


class RunProbeTest(unittest.TestCase):
    def test_probes_candidates_several_attempts_writes_store_and_drops_gone_urls(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
                lat = {BASE: (0.38, ""), LAN: (0.004, ""), CF: (None, "timed out")}
                probed = []
                def probe(u, t):
                    probed.append(u)
                    return lat[u]
                r = hp.run_probe([hrec(), {"name": "solo", "base_url": "https://s", "token": "x"}], probe=probe, now=50.0)
                self.assertEqual((r["hosts"], r["urls"], r["ok"]), (1, 3, 2))       # tek adresli host yoklanmaz
                self.assertEqual(sorted(set(probed)), sorted([BASE, LAN, CF]))
                self.assertEqual(len(probed), 3 * hp.ATTEMPTS)                       # tur başına ATTEMPTS deneme
                view = hp.public_view("ulak_31")
                self.assertEqual(view[-1]["url"], CF)                                 # puansız (hiç başarı yok) sonda
                self.assertEqual(view[0]["n"], hp.ATTEMPTS)
                self.assertFalse(view[0]["warm"])                                     # tek tur = ısınmadı
                hp._cache["mtime"] = None
                r2 = hp.run_probe([hrec(extras=(LAN,))], probe=probe, now=60.0)       # CF artık aday değil
                self.assertNotIn(CF, [v["url"] for v in hp.public_view("ulak_31")])

    def test_same_host_addresses_probed_sequentially(self):
        import threading
        import time as _t
        active, peak = [0], [0]
        lock = threading.Lock()

        def probe(u, t):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            _t.sleep(0.01)
            with lock:
                active[0] -= 1
            return 0.01, ""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
            hp.run_probe([hrec()], probe=probe, now=1.0)
        self.assertEqual(peak[0], 1)                                  # aynı host'a hiç eşzamanlı istek yok

    def test_public_http_candidate_not_probed(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
            probed = []
            hp.run_probe([hrec(extras=("http://8.8.8.8:8765", LAN))], probe=lambda u, t: probed.append(u) or (0.01, ""), now=1.0)
            self.assertNotIn("http://8.8.8.8:8765", probed)

    def test_probe_exception_counts_as_failed_attempt(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hp, "STORE_JSON", os.path.join(d, "hp.json")):
            def boom(u, t):
                raise RuntimeError("x")
            hp.run_probe([hrec(extras=(LAN,))], probe=boom, now=1.0)
            self.assertTrue(all(v["fail_rate"] == 1.0 for v in hp.public_view("ulak_31")))


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
