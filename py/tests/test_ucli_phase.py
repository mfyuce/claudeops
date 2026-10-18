"""ucli'nin canlı model-çağrısı AŞAMASI panele geliyor: `provider.live_phase` + `web._live_phase` + satırın `phase` alanı
(stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_phase.py -v

Kapsadığı iş (TODO.md 2026-10-18 (2)): unified-cli 1778f34'ten beri durum dosyası (`.ucli/chat/NAME.status.json`) bir model
çağrısı sürerken `phase` taşıyor (`waiting_response`, `thinking`, `writing`, `retry_backoff`, `rate_limited`; `since_unix`,
`attempt`, `max_attempts`, `wait_secs`, `detail`, `streamed_bytes`). Panel bunu satır başına göstermeli ki bir çağrı
takılınca ya da yeniden denenince "35 dk, rapor yok" dışında bilgi olsun. Gerçek filoya, gerçek settings.json'a, tmux'a ya da
ağa DOKUNMAZ.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops.commands import web  # noqa: E402
from claudeops.commands import web_hosts  # noqa: E402
from claudeops.providers import PROVIDERS, get_provider  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.session import Session  # noqa: E402
from test_ucli_usage import StatusDirCase  # noqa: E402

WRITING = {"name": "writing", "since_unix": 1_700_000_000, "attempt": 1, "max_attempts": 10, "wait_secs": 0,
           "detail": None, "streamed_bytes": 64_936}


class LivePhaseTests(StatusDirCase):
    def phase(self, sid="s1"):
        return up.UcliProvider().live_phase(self.cwd, sid)

    def test_a_streaming_phase_comes_through(self):
        self.write_status("s1", {"activity": "waiting_for_model", "phase": WRITING})
        self.assertEqual(self.phase(), {"name": "writing", "since_unix": 1_700_000_000, "attempt": 1,
                                        "max_attempts": 10, "wait_secs": 0, "streamed_bytes": 64_936})

    def test_the_last_write_time_of_the_file_comes_through_as_last_unix(self):
        """Akış donarsa `since_unix` (aşamanın başı) durmaz ama dosya yazımı durur: "son bayttan beri" yalnız bundan çıkar."""
        self.write_status("s1", {"phase": WRITING, "last_activity_unix": 1_700_000_042})
        self.assertEqual(self.phase()["last_unix"], 1_700_000_042)

    def test_a_missing_or_garbage_last_activity_is_left_out_not_zeroed(self):
        for last in (None, "12", -5, True, 1.5, [1]):
            with self.subTest(last=last):
                self.write_status("s1", {"phase": WRITING, "last_activity_unix": last})
                self.assertNotIn("last_unix", self.phase())
        self.write_status("s1", {"phase": WRITING})
        self.assertNotIn("last_unix", self.phase())

    def test_a_retry_phase_keeps_its_reason(self):
        self.write_status("s1", {"phase": {"name": "retry_backoff", "since_unix": 5, "attempt": 2, "max_attempts": 10,
                                           "wait_secs": 10, "detail": "could not connect (timed out) after 20s"}})
        got = self.phase()
        self.assertEqual((got["name"], got["wait_secs"], got["detail"]), ("retry_backoff", 10, "could not connect (timed out) after 20s"))

    def test_no_phase_a_null_phase_or_an_older_binary_mean_none(self):
        for body in ({"activity": "waiting_for_stdin", "phase": None}, {"activity": "waiting_for_stdin"},
                     {"phase": []}, {"phase": "writing"}, {"phase": 7}):
            with self.subTest(body=body):
                self.write_status("s1", body)
                self.assertIsNone(self.phase())

    def test_a_phase_without_a_usable_name_is_ignored(self):
        for name in (None, "", "   ", 3, ["writing"]):
            with self.subTest(name=name):
                self.write_status("s1", {"phase": {**WRITING, "name": name}})
                self.assertIsNone(self.phase())

    def test_bad_numbers_are_dropped_never_turned_into_an_invented_zero(self):
        junk = {"name": "waiting_response", "since_unix": "12", "attempt": -1, "max_attempts": True, "wait_secs": 1.5,
                "streamed_bytes": None}
        self.write_status("s1", {"phase": junk})
        self.assertEqual(self.phase(), {"name": "waiting_response"})

    def test_text_is_trimmed_and_capped(self):
        self.write_status("s1", {"phase": {"name": "  writing  ", "detail": "x" * 500}})
        got = self.phase()
        self.assertEqual(got["name"], "writing")
        self.assertEqual(len(got["detail"]), 160)

    def test_a_future_phase_name_passes_through_so_the_badge_does_not_go_silent(self):
        self.write_status("s1", {"phase": {"name": "tool_prefetch", "since_unix": 9}})
        self.assertEqual(self.phase()["name"], "tool_prefetch")

    def test_only_the_known_fields_are_returned(self):
        self.write_status("s1", {"phase": {**WRITING, "future_field": 5}})
        self.assertNotIn("future_field", self.phase())

    def test_no_status_file_no_sid_or_a_broken_file_mean_none(self):
        self.assertIsNone(self.phase())
        self.write_status("s1", {"phase": WRITING})
        self.assertIsNone(self.phase(sid=None))
        self.assertIsNone(self.phase(sid=""))
        self.write_status("s1", "{not json")
        self.assertIsNone(self.phase())

    def test_every_other_provider_has_no_phase(self):
        others = [n for n in PROVIDERS if n != "ucli"]
        self.assertTrue(others)
        for name in others:
            with self.subTest(cli=name):
                self.assertIsNone(get_provider(name).live_phase(self.cwd, "s1"))


class LivePhaseHelperTests(unittest.TestCase):
    NOW = 1_800_000_000

    def session(self):
        return Session(name="u1", pid=1, cwd="/w/proj", sid="u1", cli="ucli")

    def helper(self, phase):
        fake = mock.Mock()
        fake.live_phase.return_value = phase
        with mock.patch.object(web, "get_provider", return_value=fake), \
                mock.patch.object(web.time, "time", return_value=self.NOW):
            return web._live_phase(self.session()), fake

    def test_it_asks_the_sessions_own_provider_with_its_cwd_and_sid(self):
        got, fake = self.helper({"name": "writing", "since_unix": self.NOW - 12})
        fake.live_phase.assert_called_once_with("/w/proj", "u1")
        self.assertEqual((got["name"], got["elapsed"]), ("writing", 12))

    def test_waiting_for_the_response_turns_amber_then_red_on_the_thresholds(self):
        for age, want in ((0, 0), (299, 0), (300, 1), (599, 1), (600, 2), (5000, 2)):
            with self.subTest(age=age):
                got, _ = self.helper({"name": "waiting_response", "since_unix": self.NOW - age})
                self.assertEqual((got["elapsed"], got["warn"]), (age, want))

    def test_retries_and_rate_limits_are_always_amber(self):
        for name in ("retry_backoff", "rate_limited"):
            with self.subTest(name=name):
                got, _ = self.helper({"name": name, "since_unix": self.NOW - 1, "wait_secs": 10})
                self.assertEqual(got["warn"], 1)

    def test_a_model_that_is_thinking_or_writing_is_progress_not_a_warning(self):
        for name in ("thinking", "writing"):
            with self.subTest(name=name):
                got, _ = self.helper({"name": name, "since_unix": self.NOW - 4000, "streamed_bytes": 9})
                self.assertEqual(got["warn"], 0)

    def test_a_stream_that_goes_quiet_turns_amber_then_red_and_progress_stays_green(self):
        """Akış açıkken yeşil rozet "ilerliyor" demek: donmuş bir akışta yalan olmasın diye sessizlik süresi uyarır."""
        for name in ("thinking", "writing"):
            for quiet, want in ((0, 0), (59, 0), (60, 1), (179, 1), (180, 2), (4000, 2)):
                with self.subTest(name=name, quiet=quiet):
                    got, _ = self.helper({"name": name, "since_unix": self.NOW - 5000, "last_unix": self.NOW - quiet,
                                          "streamed_bytes": 9})
                    self.assertEqual((got["idle"], got["warn"]), (quiet, want))

    def test_a_long_running_stream_that_keeps_writing_is_not_a_warning(self):
        """Aşama saatlerdir sürse bile (since_unix eski) son yazım yeniyse sorun yok: eşik SESSİZLİĞE bakar, süreye değil."""
        got, _ = self.helper({"name": "writing", "since_unix": self.NOW - 7200, "last_unix": self.NOW - 1})
        self.assertEqual((got["elapsed"], got["idle"], got["warn"]), (7200, 1, 0))

    def test_idle_is_reported_but_does_not_decide_the_waiting_colour(self):
        got, _ = self.helper({"name": "waiting_response", "since_unix": self.NOW - 100, "last_unix": self.NOW - 4000})
        self.assertEqual((got["idle"], got["warn"]), (4000, 0))   # yanıt beklerken renk `elapsed`e bağlı

    def test_without_a_last_write_time_a_stream_has_no_idle_and_no_warning(self):
        got, _ = self.helper({"name": "writing", "since_unix": self.NOW - 100})
        self.assertEqual((got["idle"], got["warn"]), (None, 0))

    def test_the_internal_last_unix_is_not_leaked_to_the_wire(self):
        got, _ = self.helper({"name": "writing", "since_unix": self.NOW - 5, "last_unix": self.NOW - 2})
        self.assertNotIn("last_unix", got)

    def test_the_providers_dict_is_not_mutated(self):
        phase = {"name": "writing", "since_unix": self.NOW - 5, "last_unix": self.NOW - 2}
        self.helper(phase)
        self.assertEqual(phase, {"name": "writing", "since_unix": self.NOW - 5, "last_unix": self.NOW - 2})

    def test_a_missing_since_unix_means_no_elapsed_and_no_warning(self):
        got, _ = self.helper({"name": "waiting_response"})
        self.assertEqual((got["elapsed"], got["warn"]), (None, 0))

    def test_a_since_in_the_future_never_gives_a_negative_elapsed(self):
        got, _ = self.helper({"name": "waiting_response", "since_unix": self.NOW + 90})
        self.assertEqual(got["elapsed"], 0)

    def test_no_phase_means_none(self):
        self.assertIsNone(self.helper(None)[0])
        self.assertIsNone(self.helper({})[0])

    def test_a_failing_provider_never_breaks_the_panel(self):
        fake = mock.Mock()
        fake.live_phase.side_effect = RuntimeError("boom")
        with mock.patch.object(web, "get_provider", return_value=fake):
            self.assertIsNone(web._live_phase(self.session()))


class StatusPayloadPhaseTests(StatusDirCase):
    """Gerçek `_status_payload`: HER İKİ satır kurucusu (kayıtlı roster satırı ve kayıtsız canlı proc) `phase` taşımalı;
    durmuş satır ve aşaması olmayan provider `None`."""

    def setUp(self):
        super().setUp()
        long_ago = int(time.time()) - 400
        self.write_status("reg", {"activity": "waiting_for_model", "phase": {**WRITING, "since_unix": int(time.time()) - 7}})
        self.write_status("adhoc", {"activity": "waiting_for_model",
                                    "phase": {"name": "waiting_response", "since_unix": long_ago, "attempt": 1, "max_attempts": 10}})
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

    def test_a_registered_running_ucli_row_carries_its_phase(self):
        got = self.rows()["reg"]["phase"]
        self.assertEqual((got["name"], got["streamed_bytes"], got["warn"]), ("writing", 64_936, 0))
        self.assertTrue(5 <= got["elapsed"] <= 20, got["elapsed"])

    def test_an_unregistered_running_ucli_row_carries_its_phase_and_the_amber_wait(self):
        row = self.rows()["adhoc"]
        self.assertEqual((row["registered"], row["phase"]["name"], row["phase"]["warn"]), (False, "waiting_response", 1))

    def test_a_frozen_stream_row_goes_amber_from_the_file_write_time(self):
        self.write_status("reg", {"activity": "waiting_for_model", "last_activity_unix": int(time.time()) - 100,
                                  "phase": {**WRITING, "since_unix": int(time.time()) - 500}})
        got = self.rows()["reg"]["phase"]
        self.assertEqual((got["name"], got["warn"]), ("writing", 1))
        self.assertTrue(95 <= got["idle"] <= 115, got["idle"])

    def test_a_stopped_row_and_a_phaseless_provider_have_no_phase(self):
        rows = self.rows()
        self.assertFalse(rows["stopped"]["running"])
        self.assertIsNone(rows["stopped"]["phase"])
        self.assertIsNone(rows["shellrow"]["phase"])


if __name__ == "__main__":
    unittest.main()
