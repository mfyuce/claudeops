"""Handover'ın önbellek-bilinçli model/effort düşürmesi (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_handover_cache_policy.py -v

Kapsadığı karar (TOBEDECIDED.md TBD#87, 2026-10-16): 338 gerçek devir turunda ölçüldü, istem
önbelleği modele özgü ve 1 saatlik; SICAKKEN `/model` bağlamın tamamını yeniden yazdırıyor
(Opus 5.5'te olay başı ~+$1), SOĞUKKEN zaten ödenecek yazmayı ucuz modele kaydırıyor.
Kural: sıcaksa modeli bırak, soğuksa Sonnet'e düş; effort her zaman high (önbelleği bozan
`claude-sonnet-5`te yalnız soğukken); karar bilinmiyorsa ya da kaçış kapağı (`handover_cache_aware`
False) kapalıysa ESKİ davranış (hep düşür). Gerçek session'lara, tmux'a, settings.json'a ya da
transkriptlere DOKUNMAZ.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import handover  # noqa: E402
from claudeops import paths  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402
from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402

NOW = 1_800_000_000.0   # sahte "şimdi" (epoch saniye)
TTL = 3600
EDGE = TTL - handover.CACHE_WARM_MARGIN_SECONDS   # bundan YENİ = sıcak


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def request_row(epoch, model="claude-opus-5-5", usage=(2, 0, 400_000), sidechain=False, with_ts=True):
    row = {"type": "assistant",
           "message": {"model": model,
                       "usage": {"input_tokens": usage[0], "cache_creation_input_tokens": usage[1],
                                 "cache_read_input_tokens": usage[2]}}}
    if with_ts:
        row["timestamp"] = iso(epoch)
    if sidechain:
        row["isSidechain"] = True
    return row


def write_jsonl(path, rows, filler_bytes=0):
    with open(path, "w", encoding="utf-8") as f:
        if filler_bytes:
            line = json.dumps({"type": "user", "timestamp": iso(NOW - 99999), "pad": "x" * 900}) + "\n"
            for _ in range(filler_bytes // len(line)):
                f.write(line)
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def jsonl(self, rows, name="sid-1.jsonl", filler_bytes=0):
        p = self.dir / name
        write_jsonl(p, rows, filler_bytes)
        return p


class LastRealRequestEpochTests(TmpDirCase):
    def test_returns_the_time_of_the_latest_real_request(self):
        p = self.jsonl([request_row(NOW - 500), request_row(NOW - 100)])
        self.assertAlmostEqual(cp.last_real_request_epoch(p), NOW - 100, places=2)

    def test_synthetic_placeholder_after_a_real_request_does_not_refresh_the_cache(self):
        for usage in ((0, 0, 0), (7, 0, 12_000)):      # `<synthetic>` kontrolü sıfır-kullanım kontrolünden bağımsız çalışır
            p = self.jsonl([request_row(NOW - 4000), request_row(NOW - 10, model="<synthetic>", usage=usage)],
                           name=f"syn-{usage[0]}.jsonl")
            self.assertAlmostEqual(cp.last_real_request_epoch(p), NOW - 4000, places=2, msg=str(usage))

    def test_subagent_rows_are_a_separate_context_and_do_not_count(self):
        p = self.jsonl([request_row(NOW - 4000), request_row(NOW - 10, sidechain=True)])
        self.assertAlmostEqual(cp.last_real_request_epoch(p), NOW - 4000, places=2)

    def test_rows_without_any_usage_tokens_do_not_count(self):
        no_usage = {"type": "assistant", "timestamp": iso(NOW - 10), "message": {"model": "claude-opus-5-5"}}
        p = self.jsonl([request_row(NOW - 4000), no_usage,
                        request_row(NOW - 5, usage=(0, 0, 0))])
        self.assertAlmostEqual(cp.last_real_request_epoch(p), NOW - 4000, places=2)

    def test_user_rows_are_ignored_and_no_assistant_means_unknown(self):
        p = self.jsonl([{"type": "user", "timestamp": iso(NOW - 1)}])
        self.assertIsNone(cp.last_real_request_epoch(p))

    def test_missing_file_is_unknown(self):
        self.assertIsNone(cp.last_real_request_epoch(self.dir / "nope.jsonl"))

    def test_large_file_is_read_from_the_tail(self):
        p = self.jsonl([request_row(NOW - 42)], filler_bytes=6_000_000)
        self.assertGreater(os.path.getsize(p), 5_000_000)
        self.assertAlmostEqual(cp.last_real_request_epoch(p), NOW - 42, places=2)


class ClaudeProviderCacheHookTests(TmpDirCase):
    def test_ttl_is_one_hour(self):
        self.assertEqual(ClaudeProvider().prompt_cache_ttl_seconds(), 3600)

    def test_last_request_epoch_reads_only_the_exact_sid_file(self):
        cwd = "/w/proj"
        proj = self.dir / cp._encode_cwd(cwd)
        proj.mkdir()
        write_jsonl(proj / "sid-1.jsonl", [request_row(NOW - 700)])
        write_jsonl(proj / "sibling.jsonl", [request_row(NOW - 5)])   # kardeş oturum: daha yeni
        with mock.patch.object(cp, "PROJECTS_DIR", str(self.dir)):
            p = ClaudeProvider()
            self.assertAlmostEqual(p.last_request_epoch(cwd, "sid-1"), NOW - 700, places=2)

    def test_no_sid_or_no_matching_file_is_unknown_never_the_newest_sibling(self):
        """`jsonl_path_for`un 'sid yoksa en yeni dosya' yedeği burada YOK (yanlışlıkla sıcak sanma)."""
        cwd = "/w/proj"
        proj = self.dir / cp._encode_cwd(cwd)
        proj.mkdir()
        write_jsonl(proj / "sibling.jsonl", [request_row(NOW - 5)])
        with mock.patch.object(cp, "PROJECTS_DIR", str(self.dir)):
            p = ClaudeProvider()
            self.assertIsNone(p.last_request_epoch(cwd, None))
            self.assertIsNone(p.last_request_epoch(cwd, ""))
            self.assertIsNone(p.last_request_epoch(cwd, "other-sid"))

    def test_effort_switch_keeps_cache_by_model(self):
        p = ClaudeProvider()
        safe = ["claude-sonnet-5-5", "claude-sonnet-5-5[1m]", "claude-opus-5-5", "claude-opus-5",
                "claude-fable-5-1", "claude-mythos-5-1", "claude-haiku-5-5", "claude-haiku-5-5[1m]",
                "sonnet", "opus", "fable", "", None]
        busts = ["claude-sonnet-5", "claude-sonnet-5[1m]", "claude-sonnet-5-20260401", "CLAUDE-SONNET-5",
                 "claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001", "claude-fable-5",
                 "claude-mythos-5", "claude-3-5-sonnet"]
        for m in safe:
            self.assertTrue(p.effort_switch_keeps_cache(m), m)
        for m in busts:
            self.assertFalse(p.effort_switch_keeps_cache(m), m)

    def test_other_providers_keep_the_old_behaviour(self):
        for cli in ("codex", "agy", "shell", "ucli"):
            p = get_provider(cli)
            self.assertIsNone(p.prompt_cache_ttl_seconds(), cli)
            self.assertIsNone(p.last_request_epoch("/w", "sid"), cli)
            self.assertIsNone(p.last_request_epoch("/w", "sid", 123), cli)
            self.assertTrue(p.effort_switch_keeps_cache("anything"), cli)


def proc_start_ticks(pid):
    """/proc/<pid>/stat'ın starttime alanı (discovery'nin `procStart` doğrulamasıyla aynı kaynak)."""
    with open(f"/proc/{pid}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[19]


class SessionFileSidTests(TmpDirCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(cp, "SESSIONS_DIR", str(self.dir))
        p.start()
        self.addCleanup(p.stop)
        self.pid = os.getpid()

    def write(self, pid=None, **fields):
        pid = pid or self.pid
        data = {"pid": pid, "sessionId": "sid-fresh", "procStart": proc_start_ticks(self.pid)}
        data.update(fields)
        (self.dir / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_verified_file_gives_the_session_id(self):
        self.write()
        self.assertEqual(cp.session_file_sid(self.pid), "sid-fresh")
        self.assertEqual(cp.session_file_sid(str(self.pid)), "sid-fresh")

    def test_a_reused_pid_is_rejected_by_proc_start(self):
        self.write(procStart="1")
        self.assertIsNone(cp.session_file_sid(self.pid))

    def test_unverifiable_or_inconsistent_files_are_not_trusted(self):
        self.write(procStart="")                       # discovery 'geç' der, burada SIKI
        self.assertIsNone(cp.session_file_sid(self.pid))
        (self.dir / f"{self.pid}.json").write_text(      # dosya adı bu pid, içindeki pid alanı başka
            json.dumps({"pid": self.pid + 1, "sessionId": "sid-fresh", "procStart": proc_start_ticks(self.pid)}),
            encoding="utf-8")
        self.assertIsNone(cp.session_file_sid(self.pid))
        self.write(sessionId="  ")
        self.assertIsNone(cp.session_file_sid(self.pid))
        self.write(sessionId=123)
        self.assertIsNone(cp.session_file_sid(self.pid))
        (self.dir / f"{self.pid}.json").write_text("{bozuk", encoding="utf-8")
        self.assertIsNone(cp.session_file_sid(self.pid))
        (self.dir / f"{self.pid}.json").write_text("[1,2]", encoding="utf-8")
        self.assertIsNone(cp.session_file_sid(self.pid))

    def test_dead_process_and_missing_file_and_no_pid(self):
        dead = 4_194_000                               # pid_max altında ama canlı olmayan
        while os.path.exists(f"/proc/{dead}"):
            dead += 1
        self.write(pid=dead, procStart="123")
        self.assertIsNone(cp.session_file_sid(dead))   # /proc okunamaz: doğrulanamadı
        self.assertIsNone(cp.session_file_sid(self.pid + 100_000))
        self.assertIsNone(cp.session_file_sid(None))
        self.assertIsNone(cp.session_file_sid(0))
        self.assertIsNone(cp.session_file_sid("abc"))


class LastRequestEpochByPidTests(TmpDirCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.proj = self.dir / "projects" / cp._encode_cwd(self.CWD)
        self.proj.mkdir(parents=True)
        self.sessions = self.dir / "sessions"
        self.sessions.mkdir()
        for p in (mock.patch.object(cp, "PROJECTS_DIR", str(self.dir / "projects")),
                  mock.patch.object(cp, "SESSIONS_DIR", str(self.sessions))):
            p.start()
            self.addCleanup(p.stop)
        self.pid = os.getpid()
        self.prov = ClaudeProvider()

    def register(self, sid):
        (self.sessions / f"{self.pid}.json").write_text(json.dumps(
            {"pid": self.pid, "sessionId": sid, "procStart": proc_start_ticks(self.pid)}), encoding="utf-8")

    def test_fresh_session_without_cmdline_sid_is_found_through_its_pid(self):
        write_jsonl(self.proj / "sid-fresh.jsonl", [request_row(NOW - 90)])
        self.register("sid-fresh")
        self.assertAlmostEqual(self.prov.last_request_epoch(self.CWD, None, self.pid), NOW - 90, places=2)

    def test_without_a_pid_the_sidless_session_stays_unknown(self):
        write_jsonl(self.proj / "sid-fresh.jsonl", [request_row(NOW - 90)])
        self.register("sid-fresh")
        self.assertIsNone(self.prov.last_request_epoch(self.CWD, None))
        self.assertIsNone(self.prov.last_request_epoch(self.CWD, None, None))

    def test_the_newest_request_of_the_two_candidate_files_wins(self):
        """cmdline sid'i eski konuşma, sessions dosyası `/clear` sonrası yeni konuşma (ya da tersi)."""
        write_jsonl(self.proj / "old-sid.jsonl", [request_row(NOW - 9000)])
        write_jsonl(self.proj / "new-sid.jsonl", [request_row(NOW - 40)])
        self.register("new-sid")
        self.assertAlmostEqual(self.prov.last_request_epoch(self.CWD, "old-sid", self.pid), NOW - 40, places=2)
        self.register("old-sid")
        write_jsonl(self.proj / "old-sid.jsonl", [request_row(NOW - 9000)])
        self.assertAlmostEqual(self.prov.last_request_epoch(self.CWD, "new-sid", self.pid), NOW - 40, places=2)

    def test_a_missing_candidate_file_falls_back_to_the_other_one(self):
        write_jsonl(self.proj / "cmd-sid.jsonl", [request_row(NOW - 300)])
        self.register("file-sid-without-transcript")
        self.assertAlmostEqual(self.prov.last_request_epoch(self.CWD, "cmd-sid", self.pid), NOW - 300, places=2)

    def test_a_sibling_session_in_the_same_directory_is_never_picked_up(self):
        write_jsonl(self.proj / "sibling.jsonl", [request_row(NOW - 5)])
        self.register("sid-without-file")
        self.assertIsNone(self.prov.last_request_epoch(self.CWD, None, self.pid))
        self.assertIsNone(self.prov.last_request_epoch(self.CWD, "also-missing", self.pid))

    def test_empty_conversation_file_is_unknown(self):
        write_jsonl(self.proj / "sid-fresh.jsonl", [{"type": "system", "timestamp": iso(NOW - 1)}])
        self.register("sid-fresh")
        self.assertIsNone(self.prov.last_request_epoch(self.CWD, None, self.pid))


class StubTtl:
    def __init__(self, ttl, last):
        self._ttl, self._last = ttl, last

    def prompt_cache_ttl_seconds(self):
        return self._ttl

    def last_request_epoch(self, cwd, sid, pid=None):
        self.asked = (cwd, sid, pid)
        return self._last


class PromptCacheIsWarmTests(unittest.TestCase):
    def warm(self, age, ttl=TTL):
        return handover.prompt_cache_is_warm(StubTtl(ttl, NOW - age), "/w", "sid", now=NOW)

    def test_margin_is_five_minutes(self):
        self.assertEqual(handover.CACHE_WARM_MARGIN_SECONDS, 300.0)

    def test_fresh_request_is_warm(self):
        self.assertIs(self.warm(0), True)
        self.assertIs(self.warm(60), True)
        self.assertIs(self.warm(EDGE - 1), True)

    def test_boundary_and_older_is_cold(self):
        self.assertIs(self.warm(EDGE), False)
        self.assertIs(self.warm(TTL), False)
        self.assertIs(self.warm(TTL * 5), False)

    def test_future_timestamp_from_clock_skew_counts_as_warm(self):
        self.assertIs(self.warm(-30), True)

    def test_unknown_when_provider_has_no_ttl_or_no_transcript(self):
        self.assertIsNone(handover.prompt_cache_is_warm(StubTtl(None, NOW - 10), "/w", "s", now=NOW))
        self.assertIsNone(handover.prompt_cache_is_warm(StubTtl(0, NOW - 10), "/w", "s", now=NOW))
        self.assertIsNone(handover.prompt_cache_is_warm(StubTtl(TTL, None), "/w", "s", now=NOW))

    def test_now_defaults_to_the_wall_clock(self):
        with mock.patch.object(handover.time, "time", return_value=NOW):
            self.assertIs(handover.prompt_cache_is_warm(StubTtl(TTL, NOW - 10), "/w", "s"), True)
            self.assertIs(handover.prompt_cache_is_warm(StubTtl(TTL, NOW - TTL), "/w", "s"), False)

    def test_the_process_id_reaches_the_provider(self):
        stub = StubTtl(TTL, NOW - 10)
        handover.prompt_cache_is_warm(stub, "/w", None, pid=777, now=NOW)
        self.assertEqual(stub.asked, ("/w", None, 777))


class RecProvider(ClaudeProvider):
    """Gerçek claude kararları (`handover_model_downgrade`, `handover_effort_downgrade`,
    `effort_switch_keeps_cache`), ama tmux'a gitmeyen kayıt tutan uygulayıcılar."""

    def __init__(self, last=NOW - 60):
        self.calls = []
        self.pids = []
        self._last = last
        self.last_asked = 0

    def last_request_epoch(self, cwd, sid, pid=None):
        self.last_asked += 1
        self.pids.append(pid)
        if isinstance(self._last, Exception):
            raise self._last
        return self._last

    def apply_live_model_switch(self, tmux_name, target_model):
        self.calls.append(("model", target_model))

    def apply_live_effort_switch(self, tmux_name, target_effort):
        if isinstance(self.__dict__.get("effort_error"), Exception):
            raise self.effort_error
        self.calls.append(("effort", target_effort))

    def dismiss_stray_dialog(self, tmux_name):
        return None


class PolicyCase(unittest.TestCase):
    def setUp(self):
        self.events = []
        patches = [
            mock.patch.object(handover, "diag_log", lambda event, **kw: self.events.append((event, kw))),
            mock.patch.object(handover, "load_settings",
                              lambda: {"handover_effort": "", "handover_cache_aware": self.cache_aware}),
        ]
        self.cache_aware = True
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_policy(self, prov, model, effort, spawn_model="spawn-model", spawn_effort="spawn-effort"):
        with mock.patch.object(handover, "live_or_spawn_model", return_value=model), \
             mock.patch.object(handover, "live_or_spawn_effort", return_value=effort):
            return handover.apply_handover_downgrades(prov, "vc", "claude", "/w/p", "sid-1",
                                                      spawn_model, spawn_effort, pid=4242, now=NOW)

    def event_names(self):
        return [e for e, _ in self.events]


class ModelDowngradeTests(PolicyCase):
    def test_warm_opus_keeps_its_model_but_still_lowers_effort(self):
        prov = RecProvider(last=NOW - 60)
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("effort", "high")])
        self.assertEqual(prov.pids, [4242])            # süreç kimliği sağlayıcıya ulaşır (sid'siz taze oturumlar için)
        self.assertTrue(res.warm)
        self.assertTrue(res.model_kept_warm)
        self.assertIsNone(res.model_to)
        self.assertEqual(res.effort_to, "high")
        self.assertIn("handover_model_downgrade_skipped", self.event_names())
        self.assertNotIn("handover_model_downgrade", self.event_names())

    def test_cold_opus_goes_down_to_sonnet_then_effort_in_that_order(self):
        prov = RecProvider(last=NOW - TTL)
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("model", "sonnet"), ("effort", "high")])
        self.assertIs(res.warm, False)
        self.assertEqual(res.model_to, "sonnet")
        self.assertFalse(res.model_kept_warm)
        ev = dict(self.events)["handover_model_downgrade"]
        self.assertEqual((ev["frm"], ev["to"], ev["cache"]), ("claude-opus-5-5", "sonnet", "cold"))

    def test_fable_follows_the_same_rule(self):
        warm = RecProvider(last=NOW - 120)
        self.run_policy(warm, "claude-fable-5-1", "max")
        self.assertEqual(warm.calls, [("effort", "high")])
        cold = RecProvider(last=NOW - 7200)
        self.run_policy(cold, "claude-fable-5-1", "max")
        self.assertEqual(cold.calls, [("model", "sonnet"), ("effort", "high")])

    def test_boundary_is_the_ttl_minus_margin(self):
        young = RecProvider(last=NOW - (EDGE - 1))
        self.run_policy(young, "claude-opus-5-5", "high")
        self.assertEqual(young.calls, [])                                   # sıcak: model kalır, effort zaten high
        old = RecProvider(last=NOW - EDGE)
        self.run_policy(old, "claude-opus-5-5", "high")
        self.assertEqual(old.calls, [("model", "sonnet")])                  # soğuk: düşer

    def test_models_that_are_not_downgrade_candidates_never_get_a_model_command(self):
        for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-sonnet-5"):
            for last in (NOW - 10, NOW - 9000):
                prov = RecProvider(last=last)
                res = self.run_policy(prov, model, "high")
                self.assertEqual(prov.calls, [], (model, last))
                self.assertFalse(res.model_kept_warm)
                self.assertIsNone(res.model_to)

    def test_unknown_warmth_keeps_the_old_always_downgrade_behaviour(self):
        prov = RecProvider(last=None)
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("model", "sonnet"), ("effort", "high")])
        self.assertIsNone(res.warm)
        self.assertEqual(dict(self.events)["handover_model_downgrade"]["cache"], "unknown")

    def test_a_failing_cache_probe_never_blocks_the_wrap_up(self):
        prov = RecProvider(last=OSError("disk gitti"))
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("model", "sonnet"), ("effort", "high")])
        self.assertIsNone(res.warm)
        self.assertIn("handover_cache_state_failed", self.event_names())

    def test_escape_hatch_restores_the_old_behaviour_and_never_probes(self):
        self.cache_aware = False
        prov = RecProvider(last=NOW - 10)                                   # sıcak olurdu
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("model", "sonnet"), ("effort", "high")])
        self.assertIsNone(res.warm)
        self.assertEqual(prov.last_asked, 0)

    def test_missing_setting_defaults_to_cache_aware(self):
        with mock.patch.object(handover, "load_settings", lambda: {"handover_effort": ""}):
            prov = RecProvider(last=NOW - 10)
            res = self.run_policy(prov, "claude-opus-5-5", "high")
        self.assertTrue(res.model_kept_warm)

    def test_provider_without_a_cache_ttl_keeps_the_old_behaviour(self):
        class NoTtl(RecProvider):
            def prompt_cache_ttl_seconds(self):
                return None
        prov = NoTtl(last=NOW - 10)
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertEqual(prov.calls, [("model", "sonnet"), ("effort", "high")])
        self.assertIsNone(res.warm)


class EffortDowngradeTests(PolicyCase):
    def test_warm_sonnet_55_gets_the_cache_safe_effort_drop(self):
        prov = RecProvider(last=NOW - 30)
        res = self.run_policy(prov, "claude-sonnet-5-5", "max")
        self.assertEqual(prov.calls, [("effort", "high")])
        self.assertEqual(res.effort_to, "high")
        self.assertFalse(res.effort_kept_cache)

    def test_warm_sonnet_5_skips_the_effort_drop_that_would_rewrite_the_cache(self):
        prov = RecProvider(last=NOW - 30)
        res = self.run_policy(prov, "claude-sonnet-5", "max")
        self.assertEqual(prov.calls, [])
        self.assertIsNone(res.effort_to)
        self.assertTrue(res.effort_kept_cache)
        ev = dict(self.events)["handover_effort_downgrade_skipped"]
        self.assertEqual((ev["reason"], ev["model"], ev["frm"], ev["would_be"]),
                         ("cache_would_be_rewritten", "claude-sonnet-5", "max", "high"))

    def test_cold_sonnet_5_gets_the_effort_drop_because_the_cache_is_gone_anyway(self):
        prov = RecProvider(last=NOW - 9000)
        res = self.run_policy(prov, "claude-sonnet-5", "max")
        self.assertEqual(prov.calls, [("effort", "high")])
        self.assertFalse(res.effort_kept_cache)

    def test_unknown_warmth_on_sonnet_5_keeps_the_old_behaviour(self):
        prov = RecProvider(last=None)
        self.run_policy(prov, "claude-sonnet-5", "max")
        self.assertEqual(prov.calls, [("effort", "high")])

    def test_effort_already_at_or_below_the_target_is_left_alone(self):
        for eff in ("high", "medium", "low", "", None):
            prov = RecProvider(last=NOW - 30)
            self.run_policy(prov, "claude-opus-5-5", eff)
            self.assertEqual(prov.calls, [], eff)

    def test_effort_command_failure_is_swallowed(self):
        prov = RecProvider(last=NOW - 30)
        prov.effort_error = RuntimeError("tmux gitti")
        res = self.run_policy(prov, "claude-opus-5-5", "max")
        self.assertIsNone(res.effort_to)
        self.assertIn("handover_effort_downgrade_failed", self.event_names())

    def test_public_wrapper_keeps_its_old_positional_signature(self):
        prov = RecProvider(last=NOW - 30)
        with mock.patch.object(handover, "live_or_spawn_effort", return_value="max"):
            self.assertEqual(handover.downgrade_effort_for_handover(prov, "vc", "claude", "/w", "sid", "max"), "high")
            self.assertEqual(handover.downgrade_effort_for_handover(
                prov, "vc", "claude", "/w", "sid", "max", warm=True, model="claude-sonnet-5"), None)
            self.assertEqual(handover.downgrade_effort_for_handover(
                prov, "vc", "claude", "/w", "sid", "max", warm=True, model="claude-opus-5-5"), "high")
        self.assertEqual(prov.calls, [("effort", "high"), ("effort", "high")])


class CallSiteWiringTests(PolicyCase):
    """Her iki giriş yolu da TEK karar noktasını çağırıyor (eskiden iki kopyaydı)."""

    def proc(self, **kw):
        base = dict(name="vc", pid=4242, cwd="/w/p", sid="sid-1", cli="claude", model="claude-opus-5-5",
                    effort="max", base="vc")
        base.update(kw)
        return SimpleNamespace(**base)

    def test_cli_path_calls_the_shared_policy_once_per_target(self):
        prov = RecProvider()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(paths, "STATE_DIR", Path(tmp)), \
             mock.patch.object(handover, "find_sessions", lambda measure_cpu=False: [self.proc()]), \
             mock.patch.object(handover, "ancestor_pids", lambda: set()), \
             mock.patch.object(handover, "is_tmux_backed", lambda pid: True), \
             mock.patch.object(handover, "get_provider", lambda cli: prov), \
             mock.patch.object(handover, "tmux_send_keys", lambda *a, **k: True), \
             mock.patch.object(handover, "apply_handover_downgrades") as policy:
            summary = handover.handover_faz1(names=["vc"])
        policy.assert_called_once_with(prov, "vc", "claude", "/w/p", "sid-1", "claude-opus-5-5", "max", pid=4242)
        self.assertEqual([r.status for r in summary.results], ["sent"])

    def test_web_path_calls_the_shared_policy_with_the_spawn_time_values(self):
        prov = RecProvider()
        proc = self.proc()
        with mock.patch.object(web, "_find_running_for_action", lambda name: ("one", [proc])), \
             mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
             mock.patch.object(web, "get_provider", lambda cli: prov), \
             mock.patch.object(web, "diag_log", lambda *a, **k: None), \
             mock.patch.object(web, "tmux_send_keys", lambda *a, **k: True), \
             mock.patch.object(web, "apply_handover_downgrades") as policy:
            result = web._handover("vc")
        self.assertEqual(result, {"ok": True})
        policy.assert_called_once_with(prov, "vc", "claude", "/w/p", "sid-1", "claude-opus-5-5", "max", pid=4242)

    def test_web_path_targets_the_resolved_session_for_unique_base(self):
        """`cli` -> tek canlı `cli20261023` (unique_base): tmux ve politika HAM adı değil çözülmüş adı alır."""
        prov = RecProvider()
        proc = self.proc()
        proc.name = "vc20261023"
        sent = []
        with mock.patch.object(web, "_find_running_for_action", lambda name: ("unique_base", [proc])), \
             mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
             mock.patch.object(web, "get_provider", lambda cli: prov), \
             mock.patch.object(web, "diag_log", lambda *a, **k: None), \
             mock.patch.object(web, "tmux_send_keys", lambda n, *a, **k: sent.append(n) or True), \
             mock.patch.object(web, "apply_handover_downgrades") as policy:
            result = web._handover("vc")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(sent, ["vc20261023"])
        self.assertEqual(policy.call_args.args[1], "vc20261023")

    def test_real_policy_runs_end_to_end_through_the_web_path(self):
        """Sahte yok: web yolu gerçek kararı çalıştırır (sıcak Opus: model komutu YOK, effort var)."""
        prov = RecProvider(last=time_now() - 60)
        proc = self.proc()
        with mock.patch.object(web, "_find_running_for_action", lambda name: ("one", [proc])), \
             mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
             mock.patch.object(web, "get_provider", lambda cli: prov), \
             mock.patch.object(web, "diag_log", lambda *a, **k: None), \
             mock.patch.object(web, "tmux_send_keys", lambda *a, **k: True), \
             mock.patch.object(handover, "live_or_spawn_model", return_value="claude-opus-5-5"), \
             mock.patch.object(handover, "live_or_spawn_effort", return_value="max"):
            result = web._handover("vc")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(prov.calls, [("effort", "high")])


def time_now():
    import time
    return time.time()


if __name__ == "__main__":
    unittest.main()
