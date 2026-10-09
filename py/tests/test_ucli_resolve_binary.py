"""`ucli_client.resolve_binary()` seçim sırası testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_ucli_resolve_binary.py -v

Ağa / gerçek ucli build'ine / gerçek ayarlara DOKUNMAZ: ayar, `UCLI_BIN`, PATH, ev dizini ve
claudeops'un kendi kopyası (`OWN_UCLI`) geçici dizinle değiştirilir.

Kapsadığı kararlar (2026-10-09, kullanıcı):
- "claudeops release kullansın. debug gerekirse debug kullansın": kardeş proje `unified-cli`'nin
  build'leri release ÖNCE, debug YEDEK denenir (eskiden tersiydi).
- "claudeops ucli'yi kendi reposunda tutsun, gerektiğinde release'i/debug'ı oraya gönderelim":
  claudeops'un KENDİ kopyası (`<repo>/bin/ucli`, `scripts/install-ucli.sh` teslim eder) PATH'in ve
  kardeş build'lerin önündedir. Geçersiz kılma sırası (açık argüman > `provider_bin.ucli` >
  `UCLI_BIN`) kendi kopyanın da önünde kalır: debug'a zorlamanın yolu bunlar.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client  # noqa: E402
from claudeops.providers.ucli_provider import UcliProvider  # noqa: E402

REAL_OWN_UCLI = ucli_client.OWN_UCLI  # testler yamalamadan ÖNCE yakalanır


class OwnCopyLocationTests(unittest.TestCase):
    def test_own_copy_lives_in_the_repo_bin_directory_and_is_named_ucli(self):
        repo = REAL_OWN_UCLI.parent.parent
        self.assertEqual(REAL_OWN_UCLI.parent.name, "bin")
        self.assertEqual(REAL_OWN_UCLI.name, "ucli")
        self.assertTrue((repo / "py" / "claudeops" / "ucli_client.py").is_file())

    def test_a_session_started_from_the_own_copy_is_still_recognised_as_ucli(self):
        # matches_proc dosya ADINA bakıyor: kopya `ucli` adını taşımazsa claudeops kendi
        # açtığı oturumu tanımaz.
        argv = [str(REAL_OWN_UCLI), "--root", "/tmp/x", "chat", "--repl", "--session", "s1"]
        provider = UcliProvider()
        self.assertTrue(provider.matches_proc(argv))
        self.assertEqual(provider.extract_name(None, argv), "s1")


class ResolveBinaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.target = self.home / "work" / "projects" / "tmp" / "unified-cli" / "target"
        self.own = self.home / "claudeops" / "bin" / "ucli"
        self.settings = {}
        for patcher in (
            mock.patch.object(ucli_client, "load_settings", side_effect=lambda: self.settings),
            mock.patch.object(ucli_client.shutil, "which", return_value=None),
            mock.patch.object(ucli_client.Path, "home", return_value=self.home),
            mock.patch.object(ucli_client, "OWN_UCLI", self.own),
            mock.patch.dict(os.environ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("UCLI_BIN", None)

    def _sibling(self, *profiles):
        for profile in profiles:
            path = self.target / profile / "ucli"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\n")

    def _own(self):
        self.own.parent.mkdir(parents=True, exist_ok=True)
        self.own.write_text("#!/bin/sh\n")

    def _sibling_path(self, profile):
        return str(self.target / profile / "ucli")

    def test_own_copy_beats_path_and_the_sibling_builds(self):
        self._own()
        self._sibling("debug", "release")
        with mock.patch.object(ucli_client.shutil, "which", return_value="/usr/bin/ucli"):
            self.assertEqual(ucli_client.resolve_binary(), str(self.own))

    def test_path_beats_the_sibling_builds_when_there_is_no_own_copy(self):
        self._sibling("debug", "release")
        with mock.patch.object(ucli_client.shutil, "which", return_value="/usr/bin/ucli"):
            self.assertEqual(ucli_client.resolve_binary(), "/usr/bin/ucli")

    def test_sibling_release_is_preferred_over_sibling_debug(self):
        self._sibling("debug", "release")
        self.assertEqual(ucli_client.resolve_binary(), self._sibling_path("release"))

    def test_sibling_debug_is_the_fallback_when_there_is_no_sibling_release(self):
        self._sibling("debug")
        self.assertEqual(ucli_client.resolve_binary(), self._sibling_path("debug"))

    def test_sibling_release_alone_is_used(self):
        self._sibling("release")
        self.assertEqual(ucli_client.resolve_binary(), self._sibling_path("release"))

    def test_no_build_raises_a_clear_error_that_names_the_installer(self):
        with self.assertRaises(ucli_client.UcliError) as ctx:
            ucli_client.resolve_binary()
        message = str(ctx.exception)
        self.assertIn("scripts/install-ucli.sh", message)
        self.assertIn("UCLI_BIN", message)

    def test_overrides_beat_the_own_copy_so_debug_can_be_forced(self):
        self._own()
        self._sibling("debug", "release")
        debug = self._sibling_path("debug")

        self.assertEqual(ucli_client.resolve_binary("/explicit/ucli"), "/explicit/ucli")

        self.settings = {"provider_bin": {"ucli": debug}}
        self.assertEqual(ucli_client.resolve_binary(), debug)

        self.settings = {}
        os.environ["UCLI_BIN"] = debug
        self.assertEqual(ucli_client.resolve_binary(), debug)

    def test_settings_override_beats_env_and_env_beats_the_own_copy(self):
        self._own()
        os.environ["UCLI_BIN"] = "/from/env/ucli"
        self.assertEqual(ucli_client.resolve_binary(), "/from/env/ucli")

        self.settings = {"provider_bin": {"ucli": "/from/settings/ucli"}}
        self.assertEqual(ucli_client.resolve_binary(), "/from/settings/ucli")


if __name__ == "__main__":
    unittest.main()
