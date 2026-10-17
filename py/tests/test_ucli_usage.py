"""ucli token/istek sayacı panele geliyor: `provider.live_usage` + satırın `usage` alanı (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_usage.py -v

Kapsadığı iş (TODO.md 2026-10-16 (5) madde 1 ve (8) madde 1): unified-cli'nin durum dosyası
(`.ucli/chat/NAME.status.json`) süreç boyunca biriken `usage` taşıyor (istek sayısı, girdi/önbellekli/çıktı/akıl
yürütme tokeni, ve 1d64d73'ten beri cevapsız denemeler = `unmetered`). Panel bunu satır başına göstermeli ki "10 dakikada
10 milyon token" gibi bir yakım tek bakışta görünsün; sayı yalnız ucli'de var, başka provider'larda `None` (rozet yok,
"0 token" değil). Gerçek filoya, gerçek settings.json'a, tmux'a ya da ağa DOKUNMAZ.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.commands import web_hosts  # noqa: E402
from claudeops.providers import PROVIDERS, get_provider  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.session import Session  # noqa: E402

FULL = {"requests": 12, "reported": 12, "prompt_tokens": 466_378, "cached_tokens": 251_648,
        "completion_tokens": 9_001, "reasoning_tokens": 4_200, "request_bytes": 1_234_567,
        "unmetered": 0, "unmetered_bytes": 0}


class StatusDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = tmp.name

    def write_status(self, session, body):
        d = Path(ucli_client.chat_session_dir(self.cwd))
        d.mkdir(parents=True, exist_ok=True)
        text = body if isinstance(body, str) else json.dumps(body)
        (d / f"{session}.status.json").write_text(text, encoding="utf-8")


class LiveUsageTests(StatusDirCase):
    def usage(self, sid="s1"):
        return up.UcliProvider().live_usage(self.cwd, sid)

    def test_the_counters_come_through_as_written(self):
        self.write_status("s1", {"activity": "waiting_for_stdin", "usage": FULL})
        self.assertEqual(self.usage(), FULL)

    def test_a_binary_without_usage_means_unknown_not_zero(self):
        self.write_status("s1", {"activity": "waiting_for_stdin", "turns": 3})
        self.assertIsNone(self.usage())

    def test_a_usage_that_is_not_an_object_means_unknown(self):
        for bad in (None, [], "x", 7):
            with self.subTest(usage=bad):
                self.write_status("s1", {"usage": bad})
                self.assertIsNone(self.usage())

    def test_no_status_file_no_sid_or_a_broken_file_mean_unknown(self):
        self.assertIsNone(self.usage())
        self.write_status("s1", {"usage": FULL})
        self.assertIsNone(self.usage(sid=None))
        self.assertIsNone(self.usage(sid=""))
        self.write_status("s1", "{not json")
        self.assertIsNone(self.usage())

    def test_the_unmetered_fields_of_an_older_binary_count_as_zero(self):
        """`usage` var ama 1d64d73'ten önceki ikili `unmetered*` yazmaz: diğer alanlar korunur."""
        old = {k: v for k, v in FULL.items() if not k.startswith("unmetered")}
        self.write_status("s1", {"usage": old})
        self.assertEqual(self.usage(), {**FULL, "unmetered": 0, "unmetered_bytes": 0})

    def test_garbage_values_become_zero_never_an_invented_number(self):
        junk = {"requests": "12", "reported": -3, "prompt_tokens": 1.5, "cached_tokens": True,
                "completion_tokens": None, "reasoning_tokens": [1], "request_bytes": {}, "unmetered": 2}
        self.write_status("s1", {"usage": junk})
        self.assertEqual(self.usage(), {"requests": 0, "reported": 0, "prompt_tokens": 0, "cached_tokens": 0,
                                        "completion_tokens": 0, "reasoning_tokens": 0, "request_bytes": 0,
                                        "unmetered": 2, "unmetered_bytes": 0})

    def test_only_the_known_counters_are_returned(self):
        self.write_status("s1", {"usage": {**FULL, "future_field": 5}})
        got = self.usage()
        self.assertEqual(set(got), set(up._USAGE_FIELDS))
        self.assertNotIn("future_field", got)

    def test_every_other_provider_has_no_counter(self):
        others = [n for n in PROVIDERS if n != "ucli"]
        self.assertTrue(others)
        for name in others:
            with self.subTest(cli=name):
                self.assertIsNone(get_provider(name).live_usage(self.cwd, "s1"))


class LiveUsageHelperTests(unittest.TestCase):
    def session(self):
        return Session(name="u1", pid=1, cwd="/w/proj", sid="u1", cli="ucli")

    def test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid(self):
        fake = mock.Mock()
        fake.live_usage.return_value = {"requests": 1}
        with mock.patch.object(web, "get_provider", return_value=fake) as gp:
            self.assertEqual(web._live_usage(self.session()), {"requests": 1})
        gp.assert_called_once_with("ucli")
        fake.live_usage.assert_called_once_with("/w/proj", "u1")

    def test_a_failing_provider_never_breaks_the_panel(self):
        fake = mock.Mock()
        fake.live_usage.side_effect = RuntimeError("boom")
        with mock.patch.object(web, "get_provider", return_value=fake):
            self.assertIsNone(web._live_usage(self.session()))


class StatusPayloadUsageTests(StatusDirCase):
    """Gerçek `_status_payload`: HER İKİ satır kurucusu (kayıtlı roster satırı ve kayıtsız/instance canlı proc)
    `usage` taşımalı; durmuş satır ve sayaçsız provider `None`."""

    def setUp(self):
        super().setUp()
        self.write_status("reg", {"usage": FULL})
        self.write_status("adhoc", {"usage": {**FULL, "requests": 3, "unmetered": 1}})
        live = [Session(name="reg", pid=11, cwd=self.cwd, sid="reg", cli="ucli"),
                Session(name="adhoc", pid=12, cwd=self.cwd, sid="adhoc", cli="ucli"),
                Session(name="shellrow", pid=13, cwd=self.cwd, sid=None, cli="shell")]
        fleet = {"reg": {"cwd": self.cwd, "model": "deepseek-v4-flash", "cli": "ucli", "state": "active"},
                 "stopped": {"cwd": self.cwd, "model": "deepseek-v4-flash", "cli": "ucli", "state": "active"}}
        for p in (
            mock.patch.object(web, "find_sessions", lambda measure_cpu=True, mirrors_out=None: live),
            mock.patch.object(web, "_fleet_status", lambda: fleet),
            mock.patch.object(web, "PROVIDERS", {}),                       # model_choices() alt süreç açabilir (agy)
            mock.patch.object(web, "is_tmux_backed", lambda pid: False),
            mock.patch.object(web, "_needs_ho_cached", lambda s: None),     # git alt süreci yok
            mock.patch.object(web, "ucli_usage_warn_thresholds", lambda: (1_000_000, 3_000_000)),   # gerçek ayar sızmasın
            mock.patch.object(web.inst_mod, "load_instances", lambda: {}),
            mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: []),
        ):
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        return {r["name"]: r for r in web._status_payload()["sessions"] if r["host"] == web.LOCAL_HOST_NAME}

    def test_a_registered_running_ucli_row_carries_its_counters(self):
        # + kota eşdeğeri ve uyarı kademesi (test_ucli_quota_warn.py ayrıntıyı sınar): 214.730 önbelleksiz girdi
        # + 251.648 x 0,03 önbellekli + 9.001 çıktı = 231.280, varsayılan eşiklerin (1M/3M) altında.
        self.assertEqual(self.rows()["reg"]["usage"], {**FULL, "quota_tokens": 231_280, "warn": 0})

    def test_an_unregistered_running_ucli_row_carries_its_counters(self):
        row = self.rows()["adhoc"]
        self.assertEqual((row["registered"], row["usage"]["requests"], row["usage"]["unmetered"]), (False, 3, 1))

    def test_a_stopped_row_and_a_counterless_provider_have_no_usage(self):
        rows = self.rows()
        self.assertFalse(rows["stopped"]["running"])
        self.assertIsNone(rows["stopped"]["usage"])
        self.assertIsNone(rows["shellrow"]["usage"])


if __name__ == "__main__":
    unittest.main()
