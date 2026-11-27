"""TBD#412 b sonrası: ikinci örnek harcama günlüklerini ve `ucli-state`i `<CLAUDEOPS_DIR>` altına yazar; sohbet yedeği ve
dizini bunları da görmeli. Ortak `ucli-state` de (durum dizini ayarı açıkken sohbetler orada) yedeğe girmeli."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_backup, chat_index, chat_sources, paths, periodic, ucli_client, ucli_cost  # noqa: E402


def _put(path, text="{}\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


class InstanceDirsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.home = os.path.join(tmp.name, "home")
        self.shared = os.path.join(self.home, ".claude", "claudeops")
        self.own = os.path.join(tmp.name, "own")
        os.makedirs(self.shared)
        os.makedirs(self.own)
        self.usage = os.path.join(self.shared, "ucli_usage")
        for p in (mock.patch.dict(os.environ, {"HOME": self.home}),
                  mock.patch.object(ucli_cost, "USAGE_DIR", self.usage),
                  mock.patch.object(ucli_cost, "OTHER_DIR", os.path.join(self.usage, "other")),
                  mock.patch.object(ucli_client, "STATE_ROOT", os.path.join(self.shared, "ucli-state")),
                  mock.patch.object(periodic, "REPO_DIR", os.path.join(tmp.name, "repo")),
                  mock.patch.object(periodic, "_memory_sources", return_value=[]),
                  mock.patch.object(periodic, "_brain_sources", return_value=[]),
                  mock.patch.object(periodic, "_steward_review_sources", return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    def instance(self, state_dir):
        for mod in (paths, periodic):
            p = mock.patch.object(mod, "CLAUDEOPS_DIR", state_dir)
            p.start()
            self.addCleanup(p.stop)

    def plan(self):
        """{kaynak dosya: repo içi hedef}"""
        return {e["src"]: e["dest"] for e in periodic.plan_chat_backup({}, {})["changed"]}

    def written_by_launcher(self, cwd):
        """Açılışın gerçekten yazacağı yollar (yazıcı işlevlerden)."""
        return (_put(ucli_cost.log_path("s")), _put(ucli_cost.other_log_path("s")),
                _put(os.path.join(ucli_client.state_dir_for(cwd), "s.jsonl")))

    def test_second_instance_files_are_backed_up_apart_from_shared_ones(self):
        cwd = os.path.join(self.tmp, "proj")
        self.instance(self.shared)
        live = self.written_by_launcher(cwd)
        self.instance(self.own)
        mine = self.written_by_launcher(cwd)
        self.assertTrue(all(p.startswith(self.own + os.sep) for p in mine), mine)
        got = self.plan()
        for p in (*live, *mine):
            self.assertIn(p, got)
        self.assertEqual(len({got[p] for p in (*live, *mine)}), 6)      # aynı oturum adı birbirini ezmez
        for p in mine:
            self.assertEqual(periodic._group_of(got[p]), "claude")
        chat = chat_index.classify(got[mine[2]])
        self.assertEqual((chat["kind"], chat["cli"], chat["session"]), ("chat", "claude-ucli", "s"))
        self.assertTrue(chat["project"].startswith(os.path.basename(os.path.dirname(mine[2])) + "@"), chat)

    def test_default_instance_backs_up_shared_state_once(self):
        self.instance(self.shared)
        usage, other, chat = self.written_by_launcher(os.path.join(self.tmp, "proj"))
        got = self.plan()
        self.assertEqual(got[usage], os.path.join("local", "claude-ucli-usage", "s.jsonl"))
        self.assertEqual(got[other], os.path.join("local", "claude-ucli-usage", "other", "s.jsonl"))
        proj = os.path.basename(os.path.dirname(chat))
        self.assertEqual(got[chat], os.path.join("local", "claude-ucli", proj, "s.jsonl"))
        self.assertEqual(sorted(got), sorted([usage, other, chat]))

    def test_deleted_state_chat_comes_from_the_mirror(self):
        self.instance(self.shared)
        kept = _put(os.path.join(self.shared, "backups", "chat-mirror", "ucli-state", "p-0123456789", "eski.jsonl"))
        self.assertEqual(self.plan()[kept], os.path.join("local", "claude-ucli", "p-0123456789", "eski.jsonl"))

    def test_linked_state_child_is_not_followed(self):
        self.instance(self.shared)
        outside = os.path.dirname(_put(os.path.join(self.tmp, "baska", "x.jsonl")))
        os.makedirs(os.path.join(self.shared, "ucli-state"))
        os.symlink(outside, os.path.join(self.shared, "ucli-state", "bag"))
        self.assertEqual(self.plan(), {})

    def test_mirror_script_copies_shared_state_dir(self):
        src = next((s for s in chat_sources.default_sources() if s.id == "ucli-state"), None)
        self.assertIsNotNone(src)
        self.assertEqual((src.dest, src.path), ("ucli-state", f"{chat_sources.HOME}/.claude/claudeops/ucli-state"))
        self.assertIn('rsync -a', chat_sources.mirror_script([src]))

    def test_second_instance_does_not_write_shared_mirror_script_or_unit(self):
        script = _put(os.path.join(self.shared, "backups", "chat_mirror.sh"), "canli\n")
        units = os.path.join(self.home, ".config", "systemd", "user")
        live_unit = _put(os.path.join(units, chat_backup.UNIT + ".service"), "canli\n")
        self.instance(self.own)
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(chat_backup, "SCRIPT", script), mock.patch.object(chat_backup, "UNIT_DIR", units), \
                mock.patch.object(chat_backup, "_sysctl", return_value=ok) as sysctl, \
                mock.patch.object(chat_backup.subprocess, "Popen") as popen:
            for res in (chat_backup.install(), chat_backup.run_now()):
                self.assertFalse(res["ok"], res)
                self.assertIn("CLAUDEOPS_DIR", res["error"])
                self.assertEqual(res["manual_command"], "")
        sysctl.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(os.listdir(units), [chat_backup.UNIT + ".service"])
        for p in (script, live_unit):
            with open(p) as f:
                self.assertEqual(f.read(), "canli\n")


if __name__ == "__main__":
    unittest.main()
