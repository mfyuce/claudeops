"""ucli `--search-token-env` (cli_opts `search_token_env`): yalnız ortam değişkeni ADI. Gerçek Popen/ağ yok.
Çalıştırılmadı (yazıldığı oturumda test koşturulamadı)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.ucli_session_opts import validate_opts  # noqa: E402


def apply(opts, argv=None, supports=lambda b, f: True):
    with mock.patch.object(up, "binary_supports_flag", supports), \
            mock.patch.object(up, "_default_session_cap", return_value=0):
        return up._apply_cli_opts(list(argv or ["ucli", "chat"]), opts)[0]


class SearchTokenEnvTest(unittest.TestCase):
    def test_default_absent(self):
        out, err = validate_opts({})
        self.assertEqual(err, "")
        self.assertNotIn("search_token_env", out)
        self.assertNotIn("--search-token-env", apply({}))

    def test_valid_name(self):
        out, err = validate_opts({"search_token_env": "BRAVE_API_KEY"})
        self.assertEqual(err, "")
        self.assertEqual(out["search_token_env"], "BRAVE_API_KEY")

    def test_empty_means_not_sent(self):
        out, err = validate_opts({"search_token_env": ""})
        self.assertEqual((err, "search_token_env" in out), ("", False))

    def test_invalid_names_error(self):
        for bad in ("brave", "1ABC", "A-B", "A B", "sk-abc123=secret", "A" * 65):
            out, err = validate_opts({"search_token_env": bad})
            self.assertTrue(err, bad)
            self.assertEqual(out, {})

    def test_argv_with_search_url(self):
        argv = apply({"search_token_env": "BRAVE_API_KEY"}, ["ucli", "chat", "--search-url", "http://x", "--search-flavor", "searxng"])
        i = argv.index("--search-token-env")
        self.assertEqual(argv[i + 1], "BRAVE_API_KEY")

    def test_skipped_without_search_url(self):
        self.assertNotIn("--search-token-env", apply({"search_token_env": "BRAVE_API_KEY"}))

    def test_unsupported_binary_skips(self):
        argv = apply({"search_token_env": "BRAVE_API_KEY"}, ["ucli", "chat", "--search-url", "http://x"],
                     supports=lambda b, f: False)
        self.assertNotIn("--search-token-env", argv)


if __name__ == "__main__":
    unittest.main()
