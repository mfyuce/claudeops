"""reviewer değnekçi adım 2: rol kapısı. reviewer kimliği tick'te yalnız `web_review.review_tick` çalıştırır (spawn yok,
sahipliğe dokunmaz), `_target` onu her zaman reddeder, `projects.json`'a yazamaz (upsert/transfer), beyin açamaz;
`role` yalnız yaratılırken (`http_identity_create` / CLI `steward create --role`) verilir.

Canlı servis/tmux/gerçek `~/.claude/claudeops/` YOK (`_Engine` = `_Tmp` + sahte oturum geri çağrıları).
Çalıştırma: python3 -m unittest discover -s py/tests"""
import json
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cmd  # noqa: E402
from claudeops.commands import web_review  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class _Reviewer(_Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        os.makedirs(sw.paths_for("rev").root, exist_ok=True)


class TestReviewerTick(_Reviewer):
    def test_reviewer_tick_runs_only_review_tick(self):
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        self.views = [_view("a", running=False), _view("degnekci_rev", running=False)]
        seen = []
        with mock.patch.object(ws.web_review, "review_tick", lambda cfg: seen.append(cfg.sid) or {"ok": True}), \
                mock.patch.object(ws, "tick_once", wraps=ws.tick_once) as to, \
                mock.patch.object(ws, "passive_scan", wraps=ws.passive_scan) as ps, \
                mock.patch.object(ws, "brain_start", side_effect=AssertionError("brain")), \
                mock.patch.object(ws, "shutdown_tick", wraps=ws.shutdown_tick) as sd:
            res = ws.tick_round("timer")
        self.assertEqual(seen, ["rev"])
        self.assertNotIn("rev", [c.args[1] if len(c.args) > 1 else c.kwargs.get("sid") for c in to.call_args_list])
        self.assertNotIn("rev", [c.args[0] if c.args else c.kwargs.get("sid") for c in sd.call_args_list])
        self.assertEqual(ps.call_count, 0)
        self.assertIn({"sid": "rev", "role": "reviewer", "ok": True}, res)
        self.assertEqual(self.touched, ["a"])               # yalnız default'un projesi
        self.assertFalse(os.path.exists(sw.paths_for("rev").projects))
        self.assertEqual(sw.tail_log(20, "rev"), [])

    def test_idle_review_tick_is_noop_and_spawns_nothing(self):
        before = sorted(os.listdir(sw.paths_for("rev").root))
        with mock.patch.object(web_review, "current_targets", lambda cfg: []):     # gerçek agy/Evren model listesi YOK
            res = ws.tick_round("timer")                    # spawn_session gerçek çağrılırsa AssertionError (taban)
            self.assertTrue(any(r.get("sid") == "rev" and r.get("noop") for r in res))
            self.assertEqual([f for f in os.listdir(sw.paths_for("rev").root) if f != ".lock"], before)
            self.assertEqual(web_review.review_tick(settings.steward_config("rev"))["actions"], [])

    def test_disabled_reviewer_is_not_passively_scanned(self):
        settings.save_settings({"stewards": {"rev": {"enabled": "off"}}})
        self.views = [_view("x", busy=True, last_assistant="STEWARD-ASK: soru?")]
        with mock.patch.object(ws.web_review, "review_tick", side_effect=AssertionError("kapalı")):
            ws.tick_round("timer")
        self.assertEqual(sw.load_questions("rev"), [])

    def test_ownership_ignores_reviewer_projects_json(self):
        with open(sw.paths_for("rev").projects, "w") as f:            # elle/eski yazılmış dosya
            json.dump({"a": {"phase": "planned"}, "z": {"phase": "planned"}}, f)
        sw.upsert_project("a", phase="planned")                     # çakışma sayılmaz, OwnedElsewhere yok
        idx = sw.ownership_index(fresh=True)
        self.assertEqual(idx["owners"].get("a"), "default")
        self.assertNotIn("z", idx["owners"])
        self.assertEqual(idx["conflicts"], {})
        self.assertEqual(sw.project_owner("z"), "")
        self.assertEqual(idx["brains"].get("degnekci_rev"), "rev")  # beyin adı yine rezerve


class TestReviewerTarget(_Reviewer):
    def test_target_always_denied(self):
        for actor in ("brain", "engine", ""):
            for name in ("degnekci_rev", "a", "egy"):
                d = ws._target(name, actor, sid="rev", kind="directive")
                self.assertIsNotNone(d, (actor, name))
                self.assertEqual(d.get("code"), "reviewer")

    def test_default_target_unchanged(self):
        self.assertIsNone(ws._target("egy", "", sid="default"))

    def test_brain_start_refused(self):
        res = ws.brain_start(settings.steward_config("rev"))
        self.assertFalse(res["ok"])
        self.assertIn("reviewer", res["error"])
        self.assertFalse(ws.http_brain({"action": "start"}, sid="rev")["ok"])


class TestReviewerProjects(_Reviewer):
    def test_upsert_refused(self):
        with self.assertRaises(sw.ReviewerRefused):
            sw.upsert_project("x", paths="rev", phase="planned")
        self.assertFalse(os.path.exists(sw.paths_for("rev").projects))
        cwd = os.path.join(self.dir.name, "x")
        self.assertFalse(ws.http_register({"name": "x", "cwd": cwd}, sid="rev")["ok"])
        self.assertFalse(os.path.exists(cwd))                       # yan etki yok (klasör/git/roster)
        self.assertEqual(self.calls, [])

    def test_transfer_to_reviewer_refused(self):
        sw.upsert_project("a", phase="planned")
        with self.assertRaises(sw.ReviewerRefused):
            sw.transfer_project("a", "rev")
        self.assertIn("a", sw.load_projects())
        with mock.patch.object(ws, "find_sessions", lambda **kw: []):
            self.assertFalse(ws.http_identity_transfer({"project": "a", "to": "rev"})["ok"])

    def test_transfer_from_reviewer_refused(self):
        with open(sw.paths_for("rev").projects, "w") as f:
            json.dump({"z": {"phase": "planned"}}, f)
        with self.assertRaises(ValueError):
            sw.transfer_project("z", "kitap")
        self.assertEqual(sw.load_projects("kitap"), {})


class TestReviewerCreate(_Engine):
    def test_http_create_with_role(self):
        res = ws.http_identity_create({"target": "rev", "role": "reviewer"})
        self.assertTrue(res["ok"])
        cfg = settings.steward_config("rev")
        self.assertEqual((cfg.role, cfg.enabled, cfg.mode), ("reviewer", False, "observe"))
        self.assertIn("rev", sw.reviewer_ids())
        self.assertTrue(ws.http_identity_create({"target": "plain"})["ok"])
        self.assertEqual(settings.steward_config("plain").role, "steward")
        self.assertNotIn("role", settings.load_settings()["stewards"]["plain"])

    def test_http_create_unknown_role_refused(self):
        res = ws.http_identity_create({"target": "rev", "role": "admin"})
        self.assertFalse(res["ok"])
        self.assertNotIn("rev", settings.steward_ids())

    def test_brain_cannot_create(self):
        self.assertFalse(ws.http_identity_create({"target": "rev", "role": "reviewer", "actor": "brain"})["ok"])

    def test_cli_create_with_role(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cmd.cmd_create(NS(target_sid="rev", label="", role="reviewer")), 0)
            self.assertEqual(cmd.cmd_create(NS(target_sid="bad", label="", role="admin")), 1)
            self.assertEqual(cmd.cmd_create(NS(target_sid="plain", label="")), 0)      # eski çağrı biçimi
        self.assertEqual(settings.steward_config("rev").role, "reviewer")
        self.assertFalse(settings.steward_config("rev").enabled)
        self.assertNotIn("bad", settings.steward_ids())
        self.assertEqual(settings.steward_config("plain").role, "steward")

    def test_cli_parser_role_choices(self):
        import argparse
        ap = argparse.ArgumentParser()
        cmd.register(ap.add_subparsers(dest="cmd"))
        a = ap.parse_args(["steward", "create", "rev", "--role", "reviewer"])
        self.assertEqual(a.role, "reviewer")
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            ap.parse_args(["steward", "create", "rev", "--role", "admin"])

    def test_cli_config_cannot_change_role(self):
        settings.save_settings({"stewards": {"kitap": {"enabled": "off"}}})
        with mock.patch("builtins.print"):
            self.assertEqual(cmd.cmd_config(NS(sid="kitap", key="role", value="reviewer")), 1)
        self.assertEqual(settings.steward_config("kitap").role, "steward")

    def test_default_is_never_reviewer(self):
        settings.save_settings({"steward": {"role": "reviewer"}})
        self.assertEqual(settings.steward_config("default").role, "steward")
        self.assertFalse(sw.is_reviewer("default"))


if __name__ == "__main__":
    unittest.main()
