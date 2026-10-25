"""ucli `--state-dir` (opt-in, VARSAYILAN KAPALI): oturum dosyaları depo dışına; okuyucular yeni + eski dizine bakar; geçmişi
eski dizinde olan oturum eskisi gibi açılır. Gerçek settings.json, gerçek ucli, ağ YOK (`STATE_ROOT` geçici).
Çalıştırma: python3 -m unittest discover -s py/tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, ucli_client  # noqa: E402
from claudeops.io_providers.ucli_provider import UcliIoProvider  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import HELP_BOTH, fake_ucli  # noqa: E402


def limits(cfg):
    return mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": cfg})


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "state")
        self.cwd = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.cwd)
        p = mock.patch.object(ucli_client, "STATE_ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def put(self, directory, name, body):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))


class TestSetting(unittest.TestCase):
    def test_default_off_and_words(self):
        self.assertIs(settings.UCLI_STATE_DIR_DEFAULT, False)
        for raw, want in (({}, False), ({"state_dir": "on"}, True), ({"state_dir": "evet"}, True),
                          ({"state_dir": "off"}, False), ({"state_dir": "???"}, False)):
            with limits(raw):
                self.assertIs(settings.ucli_state_dir_enabled(), want, raw)
        with mock.patch.object(settings, "load_settings", lambda: {"ucli_limits": "bozuk"}):
            self.assertIs(settings.ucli_state_dir_enabled(), False)


class TestChatOnce(_Base):
    """`ucli_chat_once(session=...)` de `--state-dir` geçirir (ayar açıkken, bayrak destekliyse); aksi halde argv değişmez."""

    def run_once(self, cfg, session, supports=True):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return mock.Mock(returncode=0, stdout='{"answer": "x"}', stderr="")
        with limits(cfg), mock.patch.object(ucli_client, "binary_supports_flag", lambda b, f: supports), \
                mock.patch.object(ucli_client.subprocess, "run", fake_run), \
                mock.patch.object(ucli_client, "resolve_binary", lambda b=None: "/f/ucli"):
            ucli_client.ucli_chat_once(self.cwd, "hi", session=session, model="m", endpoint="http://e")
        return seen["argv"]

    def test_state_dir_passed_only_when_on_supported_and_session(self):
        sdir = ucli_client.state_dir_for(self.cwd)
        a = self.run_once({"state_dir": "on"}, "s1")
        self.assertEqual(a[a.index("--state-dir") + 1], sdir)
        self.assertNotIn("--state-dir", self.run_once({}, "s1"))                       # ayar kapalı
        self.assertNotIn("--state-dir", self.run_once({"state_dir": "on"}, None))      # oturumsuz tek görev: durum yok
        self.assertNotIn("--state-dir", self.run_once({"state_dir": "on"}, "s1", supports=False))   # eski ikili
        self.put(ucli_client.legacy_chat_dir(self.cwd), "s2.jsonl", "{}\n")            # geçmişi eski dizinde: eskisi gibi
        self.assertNotIn("--state-dir", self.run_once({"state_dir": "on"}, "s2"))


class TestPaths(_Base):
    def test_dir_is_per_root_and_stable_and_outside_the_repo(self):
        a = ucli_client.state_dir_for(self.cwd)
        self.assertEqual(a, ucli_client.state_dir_for(self.cwd))
        other = os.path.join(self.tmp.name, "other", "proj")
        os.makedirs(other)
        self.assertNotEqual(a, ucli_client.state_dir_for(other))               # aynı ad, ayrı kök = ayrı dizin
        self.assertTrue(a.startswith(self.root + os.sep))
        self.assertFalse(a.startswith(self.cwd))

    def test_off_reads_only_legacy_until_the_new_dir_exists(self):
        with limits({}):
            self.assertEqual(ucli_client.chat_session_dirs(self.cwd), [os.path.join(self.cwd, ".ucli", "chat")])
            self.assertEqual(ucli_client.chat_session_dir(self.cwd), os.path.join(self.cwd, ".ucli", "chat"))
            os.makedirs(ucli_client.state_dir_for(self.cwd))
            self.assertEqual(len(ucli_client.chat_session_dirs(self.cwd)), 2)   # kapatılsa da canlı oturum okunsun

    def test_on_prefers_new_then_falls_back_to_legacy_for_files(self):
        new, old = ucli_client.state_dir_for(self.cwd), ucli_client.legacy_chat_dir(self.cwd)
        self.put(old, "eski.jsonl", '{"role":"user","content":"merhaba"}\n')
        self.put(new, "yeni.jsonl", '{"role":"user","content":"selam"}\n')
        self.put(old, "eski.status.json", {"schema_version": 1, "pid": 7})
        with limits({"state_dir": "on"}):
            self.assertEqual(ucli_client.read_chat_history(self.cwd, "yeni"), [{"role": "user", "text": "selam"}])
            self.assertEqual(ucli_client.read_chat_history(self.cwd, "eski"), [{"role": "user", "text": "merhaba"}])
            self.assertEqual(ucli_client.read_status_file(self.cwd, "eski")["pid"], 7)
            self.assertEqual(ucli_client.read_chat_history(self.cwd, "yok"), [])
            self.assertEqual(sorted(UcliIoProvider().list_sessions(self.cwd)), ["eski", "yeni"])


class TestSpawnArgv(_Base):
    def setUp(self):
        super().setUp()
        self.binary = fake_ucli(Path(self.tmp.name), HELP_BOTH + "      --state-dir <DIR>\n")
        self.old_binary = fake_ucli(Path(self.tmp.name), HELP_BOTH, name="ucli-old")

    def args(self, binary=None, session="vc"):
        with mock.patch.object(up, "diag_log", lambda *a, **k: None):
            return up._state_dir_args(binary or self.binary, self.cwd, session)

    def test_off_by_default_adds_nothing(self):
        with limits({}):
            self.assertEqual(self.args(), [])

    def test_on_adds_flag_for_new_session_only_when_binary_knows_it(self):
        with limits({"state_dir": "on"}):
            self.assertEqual(self.args(), ["--state-dir", ucli_client.state_dir_for(self.cwd)])
            self.assertEqual(self.args(self.old_binary), [])                     # eski ikili: 'unexpected argument' riski yok

    def test_session_with_legacy_history_keeps_the_legacy_dir(self):
        self.put(ucli_client.legacy_chat_dir(self.cwd), "vc.jsonl", "{}\n")
        with limits({"state_dir": "on"}):
            self.assertEqual(self.args(session="vc"), [])                        # geçmişi görünmez olmasın
            self.assertEqual(len(self.args(session="baska")), 2)

    def test_session_already_in_new_dir_keeps_it_even_if_setting_turned_off(self):
        self.put(ucli_client.state_dir_for(self.cwd), "vc.jsonl", "{}\n")
        with limits({}):
            self.assertEqual(self.args(session="vc"), ["--state-dir", ucli_client.state_dir_for(self.cwd)])
            self.assertEqual(self.args(session="baska"), [])


if __name__ == "__main__":
    unittest.main()
