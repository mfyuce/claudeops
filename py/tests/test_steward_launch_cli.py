"""TBD#156: değnekçi devir/yeniden açma/start oturumu BAŞLADIĞI cli + cli_opts ile açar (instances.json son kayıt;
roster cli yalnız kayıt yoksa yedek). Gerçek spawn/tmux/ağ YOK; `inst_mod.load_instances` sahte, INSTANCES_JSON geçici.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import instances as inst  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

UCLI_OPTS = {"service": "claude", "max_cost_usd": 3}
UREC = {"cli": "ucli", "model": "claude-sonnet-5-5", "effort": "medium", "cli_opts": UCLI_OPTS,
        "blueprint": "kod", "created_at": 10, "last_started_at": 20}


def recs(**r):
    return mock.patch.object(inst, "load_instances", lambda: dict(r))


class LaunchKwargsTest(unittest.TestCase):
    def test_no_record_gives_nothing(self):
        with recs(), mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            self.assertEqual(ws._launch_kwargs("kod", "sonnet", "medium"), {})

    def test_ucli_record_passes_cli_opts_model_effort_from_record(self):
        with recs(kod=UREC):
            kw = ws._launch_kwargs("kod", "sonnet", "high")       # değnekçinin Claude değerleri atlanır
        self.assertEqual(kw, {"cli": "ucli", "cli_opts": UCLI_OPTS, "model": "claude-sonnet-5-5", "effort": "medium"})

    def test_ucli_record_passes_permission_mode(self):
        with recs(kod=dict(UREC, permission_mode="allow-edit")):
            kw = ws._launch_kwargs("kod", "", "")
        self.assertEqual(kw["permission_mode"], "allow-edit")
        self.assertEqual(kw["cli"], "ucli")

    def test_record_without_permission_mode_omits_key(self):
        with recs(kod=UREC):
            self.assertNotIn("permission_mode", ws._launch_kwargs("kod", "", ""))

    def test_claude_plain_record_with_permission_mode_stays_empty(self):
        with recs(p={"cli": "claude", "model": "sonnet", "permission_mode": "auto"}), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            self.assertEqual(ws._launch_kwargs("p", "sonnet", "medium"), {})

    def test_opts_copied_not_aliased(self):
        with recs(kod=UREC):
            kw = ws._launch_kwargs("kod", "", "")
        kw["cli_opts"]["service"] = "x"
        self.assertEqual(UCLI_OPTS["service"], "claude")

    def test_latest_instance_of_blueprint_when_no_own_record(self):
        old = dict(UREC, cli="claude", cli_opts=None, last_started_at=5)
        new = dict(UREC, last_started_at=99)
        gone = dict(UREC, last_started_at=500, forgotten=True, model="zzz")
        with recs(kod20261101=old, kod20261103=new, kod20261104=gone):
            self.assertEqual(ws._launch_kwargs("kod", "", "")["cli"], "ucli")

    def test_claude_record_matching_roster_is_old_behaviour(self):
        with recs(p={"cli": "claude", "model": "sonnet"}), mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            self.assertEqual(ws._launch_kwargs("p", "sonnet", "medium"), {})

    def test_claude_record_with_ucli_roster_forces_claude_keeps_steward_model(self):
        with recs(p={"cli": "claude", "model": "sonnet"}), mock.patch.object(ws, "_project_cli", lambda n: "ucli"):
            self.assertEqual(ws._launch_kwargs("p", "sonnet", "medium"), {"cli": "claude"})

    def test_newer_agy_helper_record_does_not_override_claude_roster(self):
        # 5 Kas: vc'nin yardımcı agy oturumu (`vc20260929_1`) "en son kayıt" oldu, değnekçi vc'yi agy ile açtı
        with recs(vc_old={"cli": "claude", "blueprint": "vc", "last_started_at": 100},
                  vc_agy={"cli": "agy", "model": "gemini-3.8-flash-high", "blueprint": "vc", "last_started_at": 105}), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            self.assertEqual(ws._launch_kwargs("vc", "claude-sonnet-5-5", "medium"), {})

    def test_unknown_cli_record_ignored(self):
        with recs(p={"cli": "nope"}), mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            self.assertEqual(ws._launch_kwargs("p", "", ""), {})


class EnsureRunningUsesRecordTest(unittest.TestCase):
    def _run(self, kw_extra):
        seen = {}

        def start(name, **k):
            seen.update(k)
            return {"ok": True}
        ws.configure(start=start)
        waited = []
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []), \
                mock.patch.object(ws, "_oversized_resume", lambda n, c: 0), \
                mock.patch.object(ws, "steward_config", lambda sid="default": mock.MagicMock()), \
                mock.patch.object(ws, "_closed_in_models", lambda n: False), \
                mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: kw_extra), \
                mock.patch.object(ws, "_start_appeared", lambda n, s="default": True), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: waited.append(c) or True):
            res = ws._ensure_running("kod", model="sonnet", effort="medium", fresh=True)
        return seen, res, waited

    def test_ucli_start_gets_recorded_cli_and_opts_and_fresh(self):
        seen, res, waited = self._run({"cli": "ucli", "cli_opts": UCLI_OPTS, "model": "m", "effort": "high"})
        self.assertEqual((seen["cli"], seen["cli_opts"], seen["model"], seen["effort"]), ("ucli", UCLI_OPTS, "m", "high"))
        self.assertTrue(seen["fresh"])
        self.assertEqual((res["cli"], waited), ("ucli", ["ucli"]))

    def test_permission_mode_reaches_start(self):
        seen, _, _ = self._run({"cli": "ucli", "permission_mode": "allow-edit"})
        self.assertEqual(seen["permission_mode"], "allow-edit")

    def test_no_record_leaves_start_args_unchanged(self):
        seen, res, _ = self._run({})
        self.assertNotIn("cli", seen)
        self.assertNotIn("cli_opts", seen)
        self.assertEqual(seen["model"], "sonnet")


class InstanceRecordsCliOptsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        for target, val in (("INSTANCES_JSON", os.path.join(d, "instances.json")),
                            ("_LOCK_PATH", os.path.join(d, "instances.lock")),
                            ("_cache_key", None)):
            p = mock.patch.object(inst, target, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("claudeops.statedocs.write_json", lambda name, path, data, mode=0o600, writer=None: writer(path, data, mode=mode))
        p.start()
        self.addCleanup(p.stop)

    def test_record_and_mark_started_persist_and_clear_on_cli_change(self):
        inst.record_instance("a", blueprint="kod", cwd="/x", cli="ucli", model="m", origin="t", cli_opts=UCLI_OPTS)
        self.assertEqual(inst.get_instance("a")["cli_opts"], UCLI_OPTS)
        inst.mark_started("a", cli="ucli", model="m", permission_mode="auto", effort="e")   # seçeneksiz, aynı cli: korunur
        self.assertEqual(inst.get_instance("a")["cli_opts"], UCLI_OPTS)
        inst.mark_started("a", cli="claude", model="s", permission_mode="auto", effort="e")  # cli değişti: silinir
        self.assertNotIn("cli_opts", inst.get_instance("a"))
        inst.mark_started("a", cli="ucli", model="m", permission_mode="auto", effort="e", cli_opts={"service": "evren"})
        self.assertEqual(inst.get_instance("a")["cli_opts"], {"service": "evren"})


if __name__ == "__main__":
    unittest.main()
