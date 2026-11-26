"""26 Kas review bulguları: ayar varsayılanı takma adı, günlük tekilleştirme yarışı, token üretim yarışı."""
import os, sys, tempfile, threading, time, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import settings, steward
from claudeops.commands import web


class SettingsAlias(unittest.TestCase):
    def _mutate_and_reload(self, path):
        with mock.patch.object(settings, "SETTINGS_JSON", path):
            first = settings.load_settings()
            first["byok"]["sızıntı"] = {"K": "v"}
            self.assertNotIn("sızıntı", settings.DEFAULT_SETTINGS["byok"])
            self.assertNotIn("sızıntı", settings.load_settings()["byok"])

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self._mutate_and_reload(os.path.join(d, "settings.json"))

    def test_file_without_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "settings.json")
            with open(p, "w") as f:
                f.write("{}")
            self._mutate_and_reload(p)


class LogSeenPrune(unittest.TestCase):
    def test_insert_during_prune_does_not_raise(self):
        seen = {}

        class Inserting(list):
            """Budama süzgeci kaydı okurken başka bir iş parçacığının eklemesini taklit eder."""
            def __getitem__(self, i):
                seen[("x", "y", "z")] = ["h", 0.0, 0]
                return list.__getitem__(self, i)

        seen.update({("log", "e", str(i)): Inserting(["h", 0.0, 0]) for i in range(4001)})
        with mock.patch.object(steward, "_LOG_SEEN", seen):
            self.assertEqual(steward._log_dedup("log", "olay", {"name": "n"}, 1e9), {})


class TokenCreateRace(unittest.TestCase):
    def test_concurrent_creators_agree(self):
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "token")
            real_fdopen = os.fdopen

            def slow_fdopen(fd, mode="r", *a, **k):
                if mode == "w":
                    time.sleep(0.2)      # dosya açıldı ama henüz boş
                return real_fdopen(fd, mode, *a, **k)

            out, errors = [], []

            def run():
                try:
                    out.append(web._load_or_create_token())
                except Exception as e:      # noqa: BLE001
                    errors.append(e)

            with mock.patch.object(web, "TOKEN_FILE", tok), mock.patch.object(web, "CLAUDEOPS_DIR", d), \
                 mock.patch.object(web.os, "fdopen", slow_fdopen):
                a, b = threading.Thread(target=run), threading.Thread(target=run)
                a.start(); time.sleep(0.05); b.start(); a.join(5); b.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(len(out), 2)
            with open(tok) as f:
                on_disk = f.read()
            self.assertEqual(out, [on_disk, on_disk])


if __name__ == "__main__":
    unittest.main()
