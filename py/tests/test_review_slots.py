"""reviewer mod başına eşzamanlı koşu yuvaları (`review_slots`): yuva sayıları, aynı-proje yasağı, varsayılan tek iş,
uzak proje yalnız evren, kota engelli hedefin atlanması, 0 yuvalı mod, boşalan yuvanın dolması. Sahte run_job (gerçek
Popen/agy/Evren YOK), `settings.SETTINGS_JSON` geçici dosyada (`_Engine`)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_web_review_tick import _Tick, NOW, T1, T2  # noqa: E402
from claudeops import review as rv, settings, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

T3 = rv.ReviewTarget("agy", "m3", "m3")
CX = rv.ReviewTarget("codex", "c1", "c1")


class TestParseSlots(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(rv.parse_slots(""), {})
        self.assertEqual(rv.parse_slots("off"), {})
        self.assertEqual(rv.parse_slots("bozuk"), {})
        s = rv.parse_slots("agy=5, evren=1,codex=1,copilot=0,xx=9,claude=a")
        self.assertEqual(s, {"agy": 5, "evren": 1, "claude": 1, "codex": 1, "copilot": 0, "anthropic": 1})


class TestTakeSlot(unittest.TestCase):
    def setUp(self):
        wr._ACTIVE.clear()
        self.addCleanup(wr._ACTIVE.clear)

    def test_single_mode_one_job(self):
        self.assertEqual(wr._take_slot("a|evren/m1", "a", "evren", {})[0], 0)
        self.assertLess(wr._take_slot("b|agy/m2", "b", "agy", {})[0], 0)

    def test_slots(self):
        s = rv.parse_slots("agy=2,evren=1,copilot=0")
        self.assertEqual(wr._take_slot("a|agy/m2", "a", "agy", s)[0], 0)
        self.assertEqual(wr._take_slot("b|agy/m2", "b", "agy", s)[0], 1)      # ayrı agy HOME numarası
        self.assertLess(wr._take_slot("c|agy/m2", "c", "agy", s)[0], 0)       # agy dolu
        self.assertLess(wr._take_slot("a|evren/m1", "a", "evren", s)[0], 0)   # aynı proje başka koşuda
        self.assertEqual(wr._take_slot("c|evren/m1", "c", "evren", s)[0], 0)
        self.assertIn("0", wr._take_slot("d|copilot/x", "d", "copilot", s)[1])
        wr._release_slot("a|agy/m2")
        self.assertEqual(wr._take_slot("d|agy/m2", "d", "agy", s)[0], 0)      # boşalan en küçük numara yeniden

    def test_agy_home_per_slot(self):
        with tempfile.TemporaryDirectory() as d:
            h0 = wr.agy_home(d, "/x", ["ls"], real_home=d)
            h2 = wr.agy_home(d, "/y", ["ls"], real_home=d, slot=2)
            self.assertEqual(os.path.basename(h0), "agy_home")
            self.assertEqual(os.path.basename(h2), "agy_home_2")
            self.assertTrue(os.path.isdir(os.path.join(h2, "tmp")))


class TestSlotsTick(_Tick):
    def setUp(self):
        super().setUp()
        self.hold = True
        wr._ACTIVE.clear()
        self.addCleanup(wr._ACTIVE.clear)

    def slots(self, spec, gap="0"):
        settings.save_settings({"stewards": {"rev": {"review_slots": spec, "review_min_gap_minutes": gap}}})

    def modes(self):
        return sorted(k.split("/")[0] for _p, k in self.started)

    def test_default_single_job(self):
        self.own("a", "b", "c")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)

    def test_slot_counts_per_mode(self):
        self.own("a", "b", "c", "e")
        self.targets = [T1, T2, CX]
        self.slots("agy=2,evren=1,codex=0")
        res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(res["started"], 3)
        self.assertEqual(self.modes(), ["agy", "agy", "evren"])
        self.assertEqual(len({p for p, _k in self.started}), 3)              # her koşu ayrı proje
        wr.review_tick(self.cfg(), now=NOW + 60)                             # yuvalar dolu: yeni başlatma yok
        self.assertEqual(len(self.started), 3)

    def test_same_project_never_twice(self):
        self.own("a")
        self.slots("agy=5,evren=1")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)

    def test_zero_slot_mode_never_starts_and_running_survives(self):
        self.own("a", "b")
        self.targets = [T2]
        wr.review_tick(self.cfg(), now=NOW)                                  # tek iş kipinde agy koşusu başladı
        self.assertEqual(len(self.started), 1)
        self.slots("agy=0,evren=1")
        res = wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(res["started"], 0)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(wr.running_keys()), 1)                          # 0'a çekmek çalışanı öldürmez
        self.assertFalse(any(a.get("kind") == "cancel" for a in res["actions"]))
        st = wr.review_state(self.cfg(), now=NOW + 60)
        self.assertEqual(st["slots"]["agy"]["slots"], 0)
        self.assertEqual(len(st["slots"]["agy"]["running"]), 1)
        self.assertFalse(wr.manual_run(self.cfg(), "b", "agy", "m2")["ok"])  # elle de başlamaz

    def test_remote_project_only_evren(self):
        self.own("far", "loc")
        self.targets = [T2, T1]
        self.slots("agy=5,evren=1")
        with mock.patch.object(wr, "remote_host", lambda n, idx=None: "h" if n == "far" else ""), \
                mock.patch.object(wr, "remote_ready", lambda n, idx=None: (True, "")):
            wr.review_tick(self.cfg(), now=NOW)
        far = [k for p, k in self.started if p == "far"]
        self.assertTrue(far)
        self.assertTrue(all(k.startswith("evren/") for k in far))
        self.assertIn("loc", [p for p, _k in self.started])

    def test_evren_review_not_started_while_evren_self_verify_runs(self):
        """review R-5/R-3: Evren hep tek iş; Evren doğrulaması (self-verify) sürerken Evren review hedefi planlanmaz, öteki modlar koşar."""
        self.own("a", "b")
        self.targets = [T1, T2]            # T1 evren, T2 agy
        self.slots("agy=1,evren=1")
        with mock.patch.object(wr, "verify_provider", lambda cfg: "evren"), mock.patch.object(wr, "self_verify_running", lambda project="": True):
            res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(self.modes(), ["agy"])
        self.assertEqual(res["started"], 1)
        # doğrulama bitince Evren hedefi yeniden planlanır
        with mock.patch.object(wr, "verify_provider", lambda cfg: "evren"), mock.patch.object(wr, "self_verify_running", lambda project="": False):
            wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertIn("evren", self.modes())

    def test_single_job_mode_also_skips_evren_during_verify(self):
        self.own("a")
        self.targets = [T1]                # yalnız evren
        with mock.patch.object(wr, "verify_provider", lambda cfg: "evren"), mock.patch.object(wr, "self_verify_running", lambda project="": True):
            res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(self.started, [])
        self.assertEqual(res.get("reason"), "no targets")

    def test_quota_blocked_target_skipped(self):
        self.own("a", "b")
        self.targets = [T2, T3]
        rv.set_block(sw.paths_for("rev"), T2.key, NOW + 3600, "kota")
        self.slots("agy=2")
        res = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(res["started"], 2)
        self.assertEqual({k for _p, k in self.started}, {T3.key})

    def test_freed_slot_refilled_next_tick(self):
        self.own("a", "b")
        self.targets = [T1]
        self.slots("evren=1")
        wr.review_tick(self.cfg(), now=NOW)
        wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(len(self.started), 1)
        proj = self.started[0][0]
        wr._JOBS.clear()                                                     # koşu bitti
        rv.update_pair(sw.paths_for("rev"), proj, T1, status="done", finished_at=NOW + 90)
        wr.review_tick(self.cfg(), now=NOW + 120)
        self.assertEqual(len(self.started), 2)
        self.assertNotEqual(self.started[1][0], proj)

    def test_min_gap_one_start_per_tick(self):
        self.own("a", "b", "c")
        self.targets = [T2]
        self.slots("agy=5", gap="10")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(len(self.started), 1)
        wr.review_tick(self.cfg(), now=NOW + 60)                             # aralık dolmadı
        self.assertEqual(len(self.started), 1)
        wr.review_tick(self.cfg(), now=NOW + 11 * 60)
        self.assertEqual(len(self.started), 2)


if __name__ == "__main__":
    unittest.main()


class TestAgyHomeTokenPrivate(unittest.TestCase):
    def test_token_copy_is_0600_never_wider_and_replaces_symlink(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, ".gemini", "antigravity-cli")
            os.makedirs(real)
            with open(os.path.join(real, "antigravity-oauth-token"), "w") as f:
                f.write("sir")
            old = os.umask(0)                                             # en gevşek umask: yine de 0600 olmalı
            try:
                home = wr.agy_home(d, "/x", ["ls"], real_home=d)
                dst = os.path.join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token")
                self.assertEqual(os.stat(dst).st_mode & 0o777, 0o600)
                victim = os.path.join(d, "victim")
                os.remove(dst)
                os.symlink(victim, dst)                                   # hedef symlink: izlenmez, yerine dosya konur
                wr.agy_home(d, "/x", ["ls"], real_home=d)
            finally:
                os.umask(old)
            self.assertFalse(os.path.exists(victim))
            self.assertFalse(os.path.islink(dst))
            self.assertEqual(open(dst).read(), "sir")


class TestReportFilesPrivateUtf8(unittest.TestCase):
    def test_write_report_utf8_0600_and_recover_partial_0600(self):
        import json as _json, tempfile
        with tempfile.TemporaryDirectory() as d:
            old = os.umask(0)
            try:
                p = os.path.join(d, "r", "x.md")
                wr._write_report(p, "## R-1 | P2 | a.py:1 | şğüİ\n")
                self.assertEqual(open(p, encoding="utf-8").read(), "## R-1 | P2 | a.py:1 | şğüİ\n")
                self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
                pp = wr.rv.partial_path(p)
                with open(pp, "w", encoding="utf-8") as f:
                    _json.dump({"assistant_text": "## R-1 | P3 | b.py:2 | kısmi"}, f)
                os.chmod(pp, 0o644)
                self.assertIn("R-1", wr._recover_partial(p))
                self.assertEqual(os.stat(pp).st_mode & 0o777, 0o600)
            finally:
                os.umask(old)


class TestClaudeIsError(unittest.TestCase):
    def test_is_error_message_is_not_a_report_but_real_report_is_kept(self):
        import json as _json
        err = _json.dumps({"type": "result", "is_error": True, "result": "API Error: 529 overloaded"})
        self.assertEqual(wr._extract_text("claude", err), ("", "API Error: 529 overloaded"))
        part = _json.dumps({"type": "result", "is_error": True, "result": "## R-1 | P2 | a.py:1 | x\ngövde"})
        txt, e = wr._extract_text("claude", part)
        self.assertIn("R-1", txt)
        self.assertTrue(e)


class AgyBlockClearedBySuccessTest(unittest.TestCase):
    """17 Kas olayı: bir agy modelinin kota engeli, havuzda sonradan `done` koşu varsa planlayıcıyı kilitlememeli."""

    def _hist(self, **blocks):
        return {"pairs": {}, "blocks": blocks}

    def test_done_after_limit_clears_pool_block(self):
        now = 10_000_000.0
        h = self._hist(**{"agy/gemini-3.8-flash-high": {"until": now + 4 * 86400, "reason": "x"}})
        h["pairs"]["hc|agy/gemini-3.8-flash-high"] = {"status": "limit", "started_at": now - 200, "finished_at": now - 100}
        self.assertEqual(rv.blocked_modes(h, now), ["agy/gemini-3.8-flash-high"])
        h["pairs"]["cliops|agy/gemini-3.8-flash-medium"] = {"status": "done", "finished_at": now - 50}
        self.assertEqual(rv.blocked_modes(h, now), [])

    def test_done_before_block_or_other_pool_keeps_block(self):
        now = 10_000_000.0
        h = self._hist(**{"agy/claude-opus-5-5-high": {"until": now + 86400, "reason": "x", "set_at": now - 100}})
        h["pairs"]["a|agy/claude-sonnet-5-5-medium"] = {"status": "done", "finished_at": now - 500}    # engelden önce
        h["pairs"]["b|agy/gemini-3.8-flash-medium"] = {"status": "done", "finished_at": now - 10}      # başka havuz
        self.assertEqual(rv.blocked_modes(h, now), ["agy/claude-opus-5-5-high"])
        h["pairs"]["c|agy/gpt-oss-120b-medium"] = {"status": "done", "finished_at": now - 10}          # aynı havuz (claude_gpt)
        self.assertEqual(rv.blocked_modes(h, now), [])

    def test_non_agy_block_unaffected_and_planner_picks_pool_again(self):
        now = 10_000_000.0
        h = self._hist(codex={"until": now + 100, "reason": "x"})
        h["pairs"]["a|agy/gemini-3.8-flash-medium"] = {"status": "done", "finished_at": now - 10}
        self.assertEqual(rv.blocked_modes(h, now), ["codex"])
        h2 = self._hist(**{"agy/gemini-3.8-flash-high": {"until": now + 100, "reason": "x", "set_at": now - 100}})
        h2["pairs"]["a|agy/gemini-3.8-flash-medium"] = {"status": "done", "finished_at": now - 10}
        t = rv.ReviewTarget("agy", "gemini-3.8-flash-medium", "gemini-3.8-flash-medium")
        pool = {"projects": {"p1": {"enabled": True}}}
        nxt = rv.next_review(pool, h2, [t], now)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt[0], "p1")

    def test_set_block_records_set_at(self):
        import tempfile
        from unittest import mock
        h = {"pairs": {}, "runs": []}
        with mock.patch.object(rv, "load_history", return_value=h), mock.patch.object(rv, "save_history"), \
                mock.patch.object(rv.sw, "steward_lock"), mock.patch.object(rv.sw, "_pp", side_effect=lambda x: x):
            rv.set_block("p", "agy/x", 123.0, "r")
        self.assertIn("set_at", h["blocks"]["agy/x"])




_USAGE = ("Gemini Models\tWeekly Limit Remaining\t81%\t2026-11-25T06:06:52Z\n"
          "Gemini Models\tFive Hour Limit Remaining\t37%\t2026-11-18T16:06:52Z\n"
          "Claude and GPT models\tWeekly Limit Remaining\t44%\t2026-11-25T11:39:44Z\n"
          "Claude and GPT models\tFive Hour Limit Remaining\t0%\t2026-11-18T16:39:44Z\n"
          "Gemini 4 Argon\tGemini 4 Argon Weekly Limit\t99%\t2026-11-25T12:29:11Z\n")


class AgyUsageBlocksTest(unittest.TestCase):
    NOW = rv.calendar.timegm((2026, 11, 18, 12, 30, 0))

    def test_parse(self):
        u = rv.parse_agy_usage(_USAGE)
        self.assertEqual(set(u), {"gemini", "claude_gpt", "argon"})
        self.assertEqual(u["claude_gpt"]["five"][0], 0.0)
        self.assertEqual(u["argon"]["weekly"][0], 99.0)
        self.assertNotIn("five", u["argon"])
        self.assertEqual(rv.parse_agy_usage("junk\nA\tB\tx%\tz\n"), {})

    def test_blocked_until_picks_window(self):
        u = rv.parse_agy_usage(_USAGE)
        self.assertIsNone(rv.agy_pool_blocked_until(u, "gemini", self.NOW))
        self.assertIsNone(rv.agy_pool_blocked_until(u, "argon", self.NOW))
        self.assertEqual(rv.agy_pool_blocked_until(u, "claude_gpt", self.NOW), u["claude_gpt"]["five"][1])   # yalnız 5sa dolu
        self.assertEqual(rv.agy_pool_blocked_until(u, "yok", self.NOW), -1.0)
        u["claude_gpt"]["weekly"] = (0.0, u["claude_gpt"]["weekly"][1])
        self.assertEqual(rv.agy_pool_blocked_until(u, "claude_gpt", self.NOW), u["claude_gpt"]["weekly"][1])     # haftalık daha geç

    def test_reconcile_removes_stale_and_sets_five_hour(self):
        u = rv.parse_agy_usage(_USAGE)
        h = {"blocks": {
            "agy/gemini-4-argon-high": {"until": self.NOW + 4 * 86400, "set_at": self.NOW - 86400},        # bayat: Argon %99 kalan
            "agy/gemini-3.8-flash-high": {"until": self.NOW + 4 * 86400, "set_at": self.NOW - 60},         # az önce konan: korunur
            "evren": {"until": self.NOW + 99},
        }}
        ch = rv.reconcile_agy_blocks(h, u, ["agy/claude-sonnet-5-5-medium", "agy/gpt-oss-120b-medium"], self.NOW)
        self.assertNotIn("agy/gemini-4-argon-high", h["blocks"])
        self.assertIn("agy/gemini-3.8-flash-high", h["blocks"])
        self.assertIn("evren", h["blocks"])
        self.assertEqual(h["blocks"]["agy/claude-sonnet-5-5-medium"]["until"], u["claude_gpt"]["five"][1])
        self.assertEqual(h["blocks"]["agy/gpt-oss-120b-medium"]["until"], u["claude_gpt"]["five"][1])
        self.assertEqual(sorted(ch), ["agy/claude-sonnet-5-5-medium", "agy/gemini-4-argon-high", "agy/gpt-oss-120b-medium"])
        # ikinci geçiş: değişiklik yok
        self.assertEqual(rv.reconcile_agy_blocks(h, u, ["agy/claude-sonnet-5-5-medium"], self.NOW), [])

    def test_unknown_pool_untouched(self):
        h = {"blocks": {"agy/hydrogen-high": {"until": self.NOW + 100, "set_at": 1}}}
        self.assertEqual(rv.reconcile_agy_blocks(h, rv.parse_agy_usage(_USAGE), [], self.NOW), [])
        self.assertIn("agy/hydrogen-high", h["blocks"])

    def test_refresh_uses_fetch_and_skips_without_agy_targets(self):
        wr._AGY_USAGE_CACHE.update(at=0.0, usage={})
        called = []
        run = lambda: called.append(1) or _USAGE  # noqa: E731
        self.assertEqual(wr.refresh_agy_blocks("p", [CX], self.NOW, run), [])
        self.assertEqual(called, [])
        wr._AGY_USAGE_CACHE.update(at=0.0, usage={})
        u = wr.fetch_agy_usage(self.NOW, run)
        self.assertIn("argon", u)
        wr.fetch_agy_usage(self.NOW + 10, run)
        self.assertEqual(len(called), 1)          # önbellek
        wr._AGY_USAGE_CACHE.update(at=0.0, usage={})
        self.assertEqual(wr.fetch_agy_usage(self.NOW, lambda: "bozuk"), {})
