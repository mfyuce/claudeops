"""rs/prov G8: spawn yardımcıları (yardım yoklaması, araç zinciri, PATH listesi). Yalnız geçici dizin ve sahte betik."""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client, ucli_session_opts as uso  # noqa: E402
from claudeops.providers import copilot_provider as copilot_p, ucli_provider as ucli_p  # noqa: E402


def _script(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


class HelpProbe(unittest.TestCase):
    def test_chat_help_does_not_read_the_callers_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            binary = os.path.join(d, "ucli")
            _script(binary, 'read x; echo "okunan:$x"')
            r, w = os.pipe()
            os.write(w, b"gizli-girdi\n")
            os.close(w)
            saved = os.dup(0)
            try:
                os.dup2(r, 0)
                ucli_client._HELP_CACHE.clear()
                text = ucli_client.chat_help_text(binary)
                left = os.read(0, 100)
            finally:
                os.dup2(saved, 0)
                os.close(saved)
                os.close(r)
                ucli_client._HELP_CACHE.clear()
            self.assertEqual(text, "okunan:\n")
            self.assertEqual(left, b"gizli-girdi\n")


class Toolchain(unittest.TestCase):
    def test_a_non_utf8_rustup_settings_file_means_ambiguous_not_an_exception(self):
        with tempfile.TemporaryDirectory() as home:
            for name in ("a", "b"):
                os.makedirs(os.path.join(home, ".rustup", "toolchains", name, "bin"))
                for tool in ("cargo", "rustc"):
                    open(os.path.join(home, ".rustup", "toolchains", name, "bin", tool), "w").close()
            with open(os.path.join(home, ".rustup", "settings.toml"), "wb") as f:
                f.write(b'\xff\ndefault_toolchain = "a"\n')
            with mock.patch.dict(os.environ, {"HOME": home}):
                os.environ.pop("RUSTUP_TOOLCHAIN", None)
                tc, err = uso.rust_toolchain()
            self.assertEqual(tc, {})
            self.assertIn("2 aday", err)


class PathList(unittest.TestCase):
    def test_a_name_ending_in_a_newline_is_not_a_command(self):
        with tempfile.TemporaryDirectory() as d:
            _script(os.path.join(d, "iyi"), "true")
            _script(os.path.join(d, "kotu\n"), "true")
            self.assertEqual(uso.path_executables(d), ["iyi"])


class SecretTargets(unittest.TestCase):
    def finishes_with_oserror(self, call, fifo):
        out = []

        def run():
            try:
                call()
                out.append("yazdı")
            except OSError:
                out.append("OSError")
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(3)
        blocked = t.is_alive()
        deadline = time.monotonic() + 5
        while t.is_alive() and time.monotonic() < deadline:      # eski davranışta bloklanan yazarı serbest bırak
            fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            t.join(0.05)
            os.close(fd)
        self.assertFalse(blocked)
        self.assertEqual(out, ["OSError"])

    def test_a_fifo_at_a_key_path_is_refused_without_blocking(self):
        for module, key_attr, marker_attr, fn, settings in (
                (ucli_p, "_API_KEY_FILE", "_API_KEY_MANAGED_MARKER", "_sync_api_key_file", {"UCLI_API_KEY": "k"}),
                (copilot_p, "_BYOK_ENV_FILE", "_BYOK_ENV_MANAGED_MARKER", "_sync_byok_env_file", {"COPILOT_MODEL": "m"})):
            for fifo_at in (key_attr, marker_attr):
                with tempfile.TemporaryDirectory() as d, mock.patch.object(module, "byok_env_for", lambda cli: dict(settings)), \
                        mock.patch.object(module, key_attr, os.path.join(d, "anahtar")), \
                        mock.patch.object(module, marker_attr, os.path.join(d, "damga")):
                    fifo = getattr(module, fifo_at)
                    os.mkfifo(fifo)
                    self.finishes_with_oserror(getattr(module, fn), fifo)

    def test_a_fifo_with_a_reader_never_receives_the_secret(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ucli_p, "byok_env_for", lambda cli: {"UCLI_API_KEY": "sir"}), \
                mock.patch.object(ucli_p, "_API_KEY_FILE", os.path.join(d, "anahtar")):
            os.mkfifo(ucli_p._API_KEY_FILE)
            reader = os.open(ucli_p._API_KEY_FILE, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with self.assertRaises(OSError):
                    ucli_p._sync_api_key_file()
                try:
                    got = os.read(reader, 100)
                except BlockingIOError:
                    got = b""
                self.assertEqual(got, b"")
            finally:
                os.close(reader)

    def test_a_service_key_path_that_is_a_fifo_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "key_grok")
            os.mkfifo(path)
            with mock.patch.object(ucli_p, "_service_key_file", lambda s: path), \
                    mock.patch.object(ucli_p, "byok_env_for", lambda cli: {"XAI_API_KEY": "k"}), \
                    mock.patch.object(ucli_p, "binary_supports_flag", lambda *a: True):
                self.finishes_with_oserror(lambda: ucli_p._apply_cli_opts(["ucli", "chat"], {"service": "grok"}, "s"), path)


if __name__ == "__main__":
    unittest.main()
