"""Oturum satırında istem önbelleği ömrü: `cache` alanı, YALNIZ izleme (stdlib unittest).

Çalıştırma:  python3 py/tests/test_cache_info.py -v

Kapsadığı iş (TBD#87 öneri A, kullanıcı "Sıcak/soğuk izleme (A)"yı seçti): claude'un istem önbelleği 1 saatlik ve
uçurum gibi (ölçüm: 60 dk'yı geçen aralıkta bağlamın ~%91'i yeniden yazılıyor, 132/134), ama panelde bir oturumun
önbelleğinin sıcak mı soğuk mu olduğu görünmüyordu. Satıra `cache: {age, ttl}` eklenir (`age` = son GERÇEK model
isteğinden bu yana saniye); hiçbir karara bağlanmaz, davranış değişmez. Önbellek ömrü ya da eşleşen transkript
yoksa `None` (rozet yok): "bilinmiyor" ASLA "soğuk" diye gösterilmez. Gerçek filoya, transkriptlere, tmux'a ya da
ağa DOKUNMAZ.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402
from claudeops.commands import web_hosts  # noqa: E402
from claudeops.session import Session  # noqa: E402


class FakeClock:
    """`web.time` yerine: monotonic (TTL) ve duvar saati (age) ayrı ayrı ilerletilir."""

    def __init__(self):
        self.mono = 1000.0
        self.wall = 1_800_000_000.0

    def monotonic(self):
        return self.mono

    def time(self):
        return self.wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


def fake_provider(ttl=3600, last=None, raises=None):
    p = mock.Mock()
    p.prompt_cache_ttl_seconds.return_value = ttl
    if raises:
        p.last_request_epoch.side_effect = raises
    else:
        p.last_request_epoch.return_value = last
    return p


class CacheInfoTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        web._CACHEINFO_CACHE.clear()
        self.addCleanup(web._CACHEINFO_CACHE.clear)
        p = mock.patch.object(web, "time", self.clock)
        p.start()
        self.addCleanup(p.stop)

    def session(self, name="c1", pid=10, cli="claude", sid="sid-1"):
        return Session(name=name, pid=pid, cwd="/w/proj", sid=sid, cli=cli)

    def info(self, provider, **kw):
        with mock.patch.object(web, "get_provider", return_value=provider):
            return web._cache_info_cached(self.session(**kw))

    def test_a_recent_request_gives_its_age_and_the_one_hour_ttl(self):
        prov = fake_provider(last=self.clock.wall - 600)
        self.assertEqual(self.info(prov), {"age": 600, "ttl": 3600})
        prov.last_request_epoch.assert_called_once_with("/w/proj", "sid-1", 10)   # sid VE pid: taze --new oturumlar

    def test_a_cli_without_a_cache_lifetime_has_no_info_and_is_never_probed(self):
        prov = fake_provider(ttl=None, last=self.clock.wall - 10)
        self.assertIsNone(self.info(prov, cli="ucli"))
        prov.last_request_epoch.assert_not_called()

    def test_no_matching_transcript_is_unknown_not_cold(self):
        self.assertIsNone(self.info(fake_provider(last=None)))

    def test_an_expired_cache_still_reports_so_the_ui_can_show_cold(self):
        self.assertEqual(self.info(fake_provider(last=self.clock.wall - 7200)), {"age": 7200, "ttl": 3600})

    def test_the_probe_is_cached_but_the_age_keeps_advancing(self):
        prov = fake_provider(last=self.clock.wall - 600)
        self.assertEqual(self.info(prov)["age"], 600)
        self.clock.advance(15)                                        # TTL (20 sn) içinde
        self.assertEqual(self.info(prov)["age"], 615)
        self.assertEqual(prov.last_request_epoch.call_count, 1)

    def test_the_probe_is_repeated_after_the_ttl_and_sees_a_new_request(self):
        prov = fake_provider(last=self.clock.wall - 600)
        self.info(prov)
        self.clock.advance(25)
        prov.last_request_epoch.return_value = self.clock.wall - 5     # bu arada yeni istek
        self.assertEqual(self.info(prov)["age"], 5)
        self.assertEqual(prov.last_request_epoch.call_count, 2)

    def test_a_failing_provider_is_unknown_never_an_error_and_is_not_hammered(self):
        prov = fake_provider(raises=RuntimeError("boom"))
        self.assertIsNone(self.info(prov))
        self.assertIsNone(self.info(prov))
        self.assertEqual(prov.last_request_epoch.call_count, 1)

    def test_a_clock_skew_never_gives_a_negative_age(self):
        self.assertEqual(self.info(fake_provider(last=self.clock.wall + 90))["age"], 0)

    def test_a_restarted_session_with_a_new_pid_is_probed_afresh(self):
        old = fake_provider(last=self.clock.wall - 3000)
        new = fake_provider(last=self.clock.wall - 30)
        self.assertEqual(self.info(old, pid=10)["age"], 3000)
        self.assertEqual(self.info(new, pid=11)["age"], 30)

    def test_retired_sessions_do_not_pile_up_in_the_cache(self):
        for i in range(300):
            web._CACHEINFO_CACHE[(f"old{i}", i)] = (self.clock.mono - 1, None, 0)
        self.info(fake_provider(last=self.clock.wall - 1))
        self.assertLessEqual(len(web._CACHEINFO_CACHE), 2)


class StatusPayloadCacheTests(unittest.TestCase):
    """Gerçek `_status_payload`: HER İKİ satır kurucusu `cache` taşımalı; durmuş satırda `None`."""

    def setUp(self):
        live = [Session(name="reg", pid=11, cwd="/w/a", sid="reg", cli="claude"),
                Session(name="adhoc", pid=12, cwd="/w/b", sid="adhoc", cli="claude")]
        fleet = {"reg": {"cwd": "/w/a", "model": "sonnet", "cli": "claude", "state": "active"},
                 "stopped": {"cwd": "/w/c", "model": "sonnet", "cli": "claude", "state": "active"}}
        for p in (
            mock.patch.object(web, "find_sessions", lambda measure_cpu=True, mirrors_out=None: live),
            mock.patch.object(web, "_fleet_status", lambda: fleet),
            mock.patch.object(web, "PROVIDERS", {}),
            mock.patch.object(web, "is_tmux_backed", lambda pid: False),
            mock.patch.object(web, "_needs_ho_cached", lambda s: None),
            mock.patch.object(web, "_live_usage", lambda s: None),
            mock.patch.object(web, "_cache_info_cached", lambda s: {"age": 42, "ttl": 3600}),
            mock.patch.object(web.inst_mod, "load_instances", lambda: {}),
            mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: []),
        ):
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        return {r["name"]: r for r in web._status_payload()["sessions"] if r["host"] == web.LOCAL_HOST_NAME}

    def test_both_running_row_builders_carry_the_cache_info(self):
        rows = self.rows()
        self.assertEqual(rows["reg"]["cache"], {"age": 42, "ttl": 3600})
        self.assertEqual(rows["adhoc"]["cache"], {"age": 42, "ttl": 3600})

    def test_a_stopped_row_has_none(self):
        row = self.rows()["stopped"]
        self.assertFalse(row["running"])
        self.assertIsNone(row["cache"])


if __name__ == "__main__":
    unittest.main()
