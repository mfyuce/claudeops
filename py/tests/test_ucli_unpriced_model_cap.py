"""Fiyatı ucli'de yerleşik olmayan model + USD tavanı: ucli `needs a price for this model` ile çıkar (26 Kas, Haiku 5.5 alt ajanı
"proc görünmedi" diye öldü). claudeops fiyatı biliyorsa `--price` verir; bilmiyorsa spawn'ı nedeniyle reddeder."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web_agents as wa  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


def apply(opts, model, flags=None):
    # anahtar dosyası normal bir dosya olmalı (`_open_private_target` /dev/null'u reddeder)
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(up.ucli_cost, "OTHER_DIR", os.path.join(tmp, "other")), \
            mock.patch.object(up, "binary_supports_flag", lambda b, f: flags is None or f in flags), \
            mock.patch.object(up, "_default_session_cap", return_value=8.0), \
            mock.patch.object(up, "byok_env_for", return_value={"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"}), \
            mock.patch.object(up, "_services", return_value={"claude": ("anthropic-messages", "http://x", "ANTHROPIC_API_KEY"),
                                                             "openai": ("", "http://y", "OPENAI_API_KEY")}), \
            mock.patch.object(up, "_service_key_file", return_value=os.path.join(tmp, "key")), \
            mock.patch.object(up, "_claude_service_flags", lambda argv, *a: argv), \
            mock.patch.object(up, "diag_log", lambda *a, **k: None), \
            mock.patch.object(up, "path_executables", return_value={}):
        return up._apply_cli_opts(["ucli", "chat", "--model", model], opts)[0]


def val(argv, flag):
    return argv[argv.index(flag) + 1]


class UnpricedModelCapTest(unittest.TestCase):
    def test_haiku_gets_highest_tier_price_and_both_caps(self):
        argv = apply({"service": "claude", "max_cost_usd": 2}, "claude-haiku-5-5")
        self.assertEqual(val(argv, "--price"), "0.5,2.5,0.05,0.625")   # >100K dilimi: tavan eksik saymasın
        self.assertEqual(val(argv, "--max-session-usd"), "8")
        self.assertEqual(val(argv, "--max-cost-usd"), "2")

    def test_fable_gets_table_price(self):
        argv = apply({"service": "claude"}, "claude-fable-5-1")
        self.assertEqual(val(argv, "--price"), "10,50,0.25,12.5")

    def test_builtin_priced_model_gets_no_price_flag(self):
        argv = apply({"service": "claude"}, "claude-sonnet-5-5")
        self.assertNotIn("--price", argv)
        self.assertIn("--max-session-usd", argv)

    def test_explicit_price_wins_and_enables_per_turn_cap(self):
        argv = apply({"service": "claude", "price": "1,5", "max_cost_usd": 2}, "claude-haiku-5-5")
        self.assertEqual((argv.count("--price"), val(argv, "--price")), (1, "1,5"))
        self.assertEqual(val(argv, "--max-cost-usd"), "2")

    def test_unknown_price_with_cap_is_refused_with_reason(self):
        for opts in ({"service": "claude"}, {"service": "openai"}, {"service": "evren", "max_session_usd": 3}):
            with self.assertRaises(ValueError, msg=opts) as c:
                apply(dict(opts), "nobody-knows-1")
            self.assertIn("nobody-knows-1", str(c.exception))

    def test_binary_without_price_flag_is_refused(self):
        with self.assertRaises(ValueError):
            apply({"service": "claude"}, "claude-haiku-5-5", flags={"--max-session-usd", "--provider"})

    def test_no_cap_no_refusal(self):
        argv = apply({"service": "evren"}, "nobody-knows-1")
        self.assertNotIn("--max-session-usd", argv)


class CatalogMarksUnstartableTest(unittest.TestCase):
    """`/api/agents/models`: alt ajan açılışı oturum tavanı yüzünden reddedilecek model `startable: false` + nedenle listelenir."""
    SERVICES = [{"id": "evren", "env": "EVREN_API_KEY"}, {"id": "claude", "env": "ANTHROPIC_API_KEY", "models": [
        "claude-sonnet-5-5", "claude-haiku-5-5", "claude-nobody-9"]},
        {"id": "openai", "env": "OPENAI_API_KEY", "models": ["nobody-knows-1"]}]

    def catalog(self, cap=8.0, flags=None):
        with mock.patch.object(wa, "ucli_services", return_value=self.SERVICES), \
                mock.patch.object(wa, "byok_env_for", return_value={"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"}), \
                mock.patch.object(wa, "_efforts_for", return_value=["medium"]), \
                mock.patch.object(up, "_live_models", return_value=["evren-free-1"]), \
                mock.patch.object(up, "resolve_binary", return_value="ucli"), \
                mock.patch.object(up, "binary_supports_flag", lambda b, f: flags is None or f in flags), \
                mock.patch.object(up, "_default_session_cap", return_value=cap), \
                mock.patch.object(up, "diag_log", lambda *a, **k: None):
            return {m["id"]: m for m in wa.models_catalog()}

    def unstartable(self, **kw):
        return sorted(i for i, m in self.catalog(**kw).items() if m.get("startable") is False)

    def test_only_unpriced_paid_models_are_marked_with_reason(self):
        got = self.catalog()
        self.assertEqual(self.unstartable(), ["claude-nobody-9", "nobody-knows-1"])
        self.assertIn("nobody-knows-1", got["nobody-knows-1"]["reason"])
        for i in ("evren-free-1", "claude-sonnet-5-5", "claude-haiku-5-5"):
            self.assertEqual(sorted(got[i]), ["efforts", "id", "service"], i)

    def test_reason_is_the_one_the_launch_refuses_with(self):
        for service, model in (("openai", "nobody-knows-1"), ("claude", "claude-nobody-9")):
            with self.assertRaises(ValueError) as c:
                apply({"service": service}, model)
            self.assertEqual(self.catalog()[model]["reason"], str(c.exception))

    def test_cap_off_marks_nothing(self):
        self.assertEqual(self.unstartable(cap=0.0), [])

    def test_binary_without_session_cap_flag_marks_nothing(self):
        self.assertEqual(self.unstartable(flags={"--price"}), [])

    def test_binary_without_price_flag_marks_table_priced_model_too(self):
        self.assertEqual(self.unstartable(flags={"--max-session-usd"}),
                         ["claude-haiku-5-5", "claude-nobody-9", "nobody-knows-1"])

    def test_check_failure_keeps_the_list(self):
        with mock.patch.object(up, "session_cap_refusal", side_effect=OSError("no binary"), create=True), \
                mock.patch.object(wa, "diag_log", lambda *a, **k: None):
            got = self.catalog()
        self.assertEqual(len(got), 5)
        self.assertFalse([m for m in got.values() if "startable" in m])


if __name__ == "__main__":
    unittest.main()
