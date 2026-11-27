"""TBD#401 (sahip kararı (a)): `/api/io/ask` -> `ucli_chat_once` yalnız `UCLI_API_KEY` ve ayarlarda tanımlı ucli
hizmetlerinin anahtar adlarını kabul eder; gerisi hiçbir alt süreç açılmadan ve ortam değişkeni okunmadan reddedilir."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, ucli_client as uc  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.io_providers import IoProviderError, get_io_provider  # noqa: E402

SECRET = "sk-cok-gizli-deger-123456"


class _Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.settings = Path(d.name) / "settings.json"
        self.started = []
        ok = subprocess.CompletedProcess([], 0, json.dumps({"answer": "tamam"}), "")

        def resolve(binary):
            self.started.append("resolve")
            return "/sahte/ucli"

        def run(argv, **kw):
            self.started.append(argv)
            return ok

        for p in (mock.patch.object(settings, "SETTINGS_JSON", self.settings),
                  mock.patch.object(uc, "resolve_binary", resolve),
                  mock.patch.object(uc, "binary_supports_flag", lambda *a: self.started.append("help") or False),
                  mock.patch.object(uc, "_run_grouped", run),
                  mock.patch.dict(os.environ, {"BASKA_SIR": SECRET, "OZEL_API_KEY": SECRET})):
            p.start()
            self.addCleanup(p.stop)

    def write(self, value):
        self.settings.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

    def accepted(self, name):
        self.started.clear()
        self.assertEqual(uc.ucli_chat_once(self.dir, "soru", api_key_env=name)["answer"], "tamam")
        argv = self.started[-1]
        self.assertEqual(argv[argv.index("--api-key-env") + 1], name)

    def refused(self, name, **kw):
        self.started.clear()
        with mock.patch.object(uc, "_effective_key", side_effect=AssertionError("ortam okundu")), \
                mock.patch.object(uc, "_subprocess_env", side_effect=AssertionError("ortam kuruldu")):
            with self.assertRaises(uc.UcliError) as e:
                uc.ucli_chat_once(self.dir, "soru", session="s", api_key_env=name, **kw)
        self.assertEqual(self.started, [])
        text = str(e.exception)
        self.assertIn("api_key_env kabul edilmedi", text)
        self.assertNotIn(SECRET, text)
        if name and "UCLI_API_KEY" not in name.upper():
            self.assertNotIn(name, text)       # yanlışlıkla ada yapıştırılan anahtar da yankılanmasın
        return text


class AllowedNamesTest(_Base):
    def test_default_and_builtin_service_names_without_a_settings_file(self):
        for name in ("UCLI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"):
            self.accepted(name)

    def test_any_other_name_is_refused(self):
        for name in ("BASKA_SIR", "OZEL_API_KEY", "HOME", "PATH", "", "ucli_api_key", "UCLI_API_KEY\n", " UCLI_API_KEY",
                     SECRET):
            with self.subTest(name=name):
                self.refused(name)
                self.refused(name, api_key="verilen-anahtar", endpoint="http://baska.invalid/v1",
                             approval_run_key="r1")

    def test_service_defined_in_settings_is_accepted_and_replaces_the_builtin_list(self):
        self.write({"ucli_services": [{"id": "ozel", "endpoint": "https://ozel.invalid/v1", "env": "OZEL_API_KEY"}]})
        self.accepted("OZEL_API_KEY")
        self.accepted("UCLI_API_KEY")
        self.refused("GROQ_API_KEY")

    def test_invalid_service_entry_does_not_allow_its_name(self):
        self.write({"ucli_services": [{"id": "ozel", "env": "BASKA_SIR"}]})       # uç noktasız girdi atılır
        self.refused("BASKA_SIR")


class UnsureSettingsTest(_Base):
    def test_broken_settings_allow_only_the_default_name(self):
        for broken in ("{bozuk", "[1]", '"x"', {"ucli_services": "liste değil"}, {"ucli_services": None}):
            with self.subTest(broken=broken):
                self.write(broken)
                self.assertIn("settings.json", self.refused("ANTHROPIC_API_KEY"))
                self.accepted("UCLI_API_KEY")

    def test_non_utf8_and_non_regular_settings_allow_only_the_default_name(self):
        self.settings.write_bytes(b'{"ucli_services": "\xff"}')
        self.refused("ANTHROPIC_API_KEY")
        self.settings.unlink()
        os.mkfifo(self.settings)                 # okumak bloklardı
        self.refused("ANTHROPIC_API_KEY")


class IoAskTest(_Base):
    def test_panel_request_is_refused_before_anything_runs(self):
        fields = {"api_key_env": "BASKA_SIR", "endpoint": "http://baska.invalid/v1", "model": "m"}
        with self.assertRaises(IoProviderError):
            get_io_provider("ucli").ask(self.dir, "", "soru", fields)
        result = web._io_ask("ucli", self.dir, "", "soru", fields)
        self.assertFalse(result["ok"])
        self.assertIn("api_key_env kabul edilmedi", result["error"])
        self.assertNotIn(SECRET, result["error"])
        self.assertEqual(self.started, [])

    def test_panel_request_without_a_name_uses_the_default(self):
        self.assertEqual(get_io_provider("ucli").ask(self.dir, "", "soru", {"api_key_env": ""})["answer"], "tamam")


if __name__ == "__main__":
    unittest.main()
