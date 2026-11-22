"""Kota bekçisi sağlayıcıya göre (22 Kas, sahip: "api kredisi ile her şeyi yürütebilir miyiz"): beyin ucli'deyse
Claude Code sayacı dolunca tüm değnekçi drain OLMAZ, yalnız claude CLI projeleri başlatılmaz; panelden beyin CLI'ı/hizmeti/
tur tavanı; ucli_cost kredi dönemi (başlangıç/bitiş, kalan gün, günlük bütçe). Gerçek oturum ve ağ YOK."""
import dataclasses
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw, ucli_cost  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TestPlanTickQuotaHeld(unittest.TestCase):
    def test_quota_held_project_is_not_started_others_are(self):
        projects = {"c": sw.Project(name="c", phase="planned", cadence_minutes=60),
                    "u": sw.Project(name="u", phase="planned", cadence_minutes=60)}
        world = sw.world_for("default", sw.build_ownership_index({"default": list(projects)}))
        held = dataclasses.replace(world, quota_held=frozenset({"c"}))
        cfg = dataclasses.replace(sw.Config(), max_starts_per_tick=2)
        acts, _ = sw.plan_tick([], projects, {}, cfg, 100000.0, [], [], world=held)
        self.assertEqual(sorted((a.kind, a.name) for a in acts if a.kind == "start"), [("start", "u")])
        acts, _ = sw.plan_tick([], projects, {}, cfg, 100000.0, [], [], world=world)     # tutma yok: ikisi de açılır
        self.assertEqual(sorted(a.name for a in acts if a.kind == "start"), ["c", "u"])

    def test_answer_does_not_start_held_project(self):
        projects = {"c": sw.Project(name="c", phase="planned", cadence_minutes=0)}
        world = dataclasses.replace(sw.world_for("default", sw.build_ownership_index({"default": ["c"]})), quota_held=frozenset({"c"}))
        q = sw.Question(id="q1", project="c", text="?", created_at=1.0, status="answered", answer="evet", answered_at=2.0)
        acts, _ = sw.plan_tick([], projects, {}, sw.Config(), 100000.0, [q], [], world=world)
        self.assertNotIn(("start", "c"), [(a.kind, a.name) for a in acts])


class TestQuotaScopeHelpers(unittest.TestCase):
    def tearDown(self):
        ws._QUOTA.pop("decision", None)

    def test_held_projects_only_metered_cli(self):
        clis = {"a": "claude", "b": "ucli", "c": "codex"}
        self.assertEqual(ws.quota_held_projects(["a", "b", "c"], cli_of=clis.get), frozenset({"a"}))

    def test_blocks_target_depends_on_brain_cli(self):
        ws._QUOTA["decision"] = mock.Mock(action="drain")
        clis = {"a": "claude", "b": "ucli"}
        with mock.patch.object(ws, "_project_cli", side_effect=clis.get):
            self.assertTrue(ws.quota_blocks_target("b", sw.Config(brain_cli="claude")))    # eski davranış: hepsi tutulur
            self.assertFalse(ws.quota_blocks_target("b", sw.Config(brain_cli="ucli")))     # API beyni: ucli projesi sürer
            self.assertTrue(ws.quota_blocks_target("a", sw.Config(brain_cli="ucli")))
        ws._QUOTA["decision"] = mock.Mock(action="ok")
        self.assertFalse(ws.quota_blocks_target("a", sw.Config()))


class TestBrainCliConfig(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        self.addCleanup(ws._reset_contexts)

    def test_set_brain_cli_service_cost(self):
        self.assertTrue(ws.http_config({"key": "brain_cli", "value": "ucli"})["ok"])
        self.assertTrue(ws.http_config({"key": "brain_service", "value": "claude"})["ok"])
        self.assertTrue(ws.http_config({"key": "brain_max_cost_usd", "value": "2,5"})["ok"])
        cfg = ws.steward_config("default")
        self.assertEqual((cfg.brain_cli, cfg.brain_service, cfg.brain_max_cost_usd), ("ucli", "claude", 2.5))

    def test_rejects_bad(self):
        self.assertFalse(ws.http_config({"key": "brain_cli", "value": "codex"})["ok"])
        self.assertFalse(ws.http_config({"key": "brain_service", "value": "x y"})["ok"])
        self.assertFalse(ws.http_config({"key": "brain_max_cost_usd", "value": "99"})["ok"])
        self.assertFalse(ws.http_config({"key": "brain_cli", "value": "ucli", "actor": "brain"})["ok"])


def _write(base, name, t_ms):
    with open(os.path.join(base, name), "w") as f:
        f.write(json.dumps({"t": t_ms, "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}) + "\n")


class TestCreditWindow(unittest.TestCase):
    def test_config_dates_validated(self):
        with mock.patch.object(settings, "load_settings", lambda: {"ucli_cost": {"credit_since": "2026-11-22", "credit_until": "yarın"}}):
            c = settings.ucli_cost_config()
        self.assertEqual((c["credit_since"], c["credit_until"]), ("2026-11-22", ""))

    def test_spent_counts_only_since(self):
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        cfg = {"daily_cap_usd": 0.0, "cache_ttl": "1h", "credit_total_usd": 100.0, "credit_since": today, "credit_until": ""}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ucli_cost, "ucli_cost_config", lambda: cfg):
            _write(d, "eski.jsonl", (now - 5 * 86400) * 1000)
            os.utime(os.path.join(d, "eski.jsonl"), (now - 5 * 86400, now - 5 * 86400))
            _write(d, "bugun.jsonl", now * 1000)
            ucli_cost.invalidate()
            s = ucli_cost.state(now, base=d)
            self.assertAlmostEqual(s["spent_total_usd"], s["today_usd"], places=4)    # eski dönem harcaması sayılmaz
            self.assertEqual(s["credit_since"], today)

    def test_window_days_and_budget(self):
        now = time.mktime((2026, 11, 22, 12, 0, 0, 0, 0, -1))
        w = ucli_cost.credit_window({"credit_total_usd": 162.0, "credit_until": "2026-12-01"}, 12.0, now)
        self.assertEqual(w["days_left"], 9.5)
        self.assertAlmostEqual(w["daily_budget_usd"], round(150.0 / 9.5, 2))
        self.assertEqual(ucli_cost.credit_window({"credit_total_usd": 10.0, "credit_until": "2026-11-01"}, 0.0, now)["days_left"], 0.0)


if __name__ == "__main__":
    unittest.main()
