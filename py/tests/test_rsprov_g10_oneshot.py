"""rs/prov G10: `oneshot` hata yolları her zaman `OneshotError` (yalnız geçici dizindeki sahte betikler)."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import get_provider, ucli_provider  # noqa: E402
from claudeops.providers.base import OneshotError  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="cops-g10-one-")
        self.addCleanup(d.cleanup)
        self.d = d.name


class BaseOneshot(_Base):
    def run_argv(self, argv):
        prov = get_provider("claude")
        with mock.patch.object(prov, "oneshot_argv", return_value=argv):
            return prov.oneshot("p", None, self.d, timeout=10)

    def test_non_utf8_output(self):
        with self.assertRaises(OneshotError):
            self.run_argv(["/bin/sh", "-c", "printf '\\377'"])

    def test_nul_argument(self):
        with self.assertRaises(OneshotError):
            self.run_argv(["/bin/sh", "-c", "echo\0x"])


class UcliOneshot(_Base):
    def setUp(self):
        super().setUp()
        self.key_file = os.path.join(self.d, "ucli_api_key")
        self.calls = []
        for p in (mock.patch.object(ucli_provider, "_API_KEY_FILE", self.key_file),
                  mock.patch.object(ucli_provider, "byok_env_for", lambda cli: {}),
                  mock.patch.object(ucli_provider, "ucli_chat_once", self.once)):
            p.start()
            self.addCleanup(p.stop)

    def once(self, root, prompt, **kw):
        self.calls.append(kw)
        return {"answer": "x"}

    def shot(self, cwd=None):
        return get_provider("ucli").oneshot("p", None, cwd or os.path.join(self.d, "cwd"), timeout=10)

    def test_non_utf8_key_file_is_refused_without_leaking_bytes(self):
        with open(self.key_file, "wb") as f:
            f.write(b"sk-gizli\xff")
        with self.assertRaises(OneshotError) as c:
            self.shot()
        self.assertNotIn("sk-gizli", str(c.exception))
        self.assertIsNone(c.exception.__context__)
        self.assertEqual(self.calls, [])

    def test_fifo_key_file_does_not_block(self):
        os.mkfifo(self.key_file)
        got = []

        def run():
            try:
                self.shot()
            except Exception as e:      # noqa: BLE001
                got.append(type(e))
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(5)
        blocked = t.is_alive()
        if blocked:                     # asılı okuyucuyu çöz (test süreci temiz bitsin)
            os.close(os.open(self.key_file, os.O_WRONLY | os.O_NONBLOCK))
            t.join(5)
        self.assertFalse(blocked)
        self.assertEqual(got, [OneshotError])

    def test_missing_key_file_and_directory_mean_no_key(self):
        self.assertEqual(self.shot(), "x")
        os.mkdir(self.key_file)
        self.assertEqual(self.shot(), "x")
        self.assertEqual([c["api_key"] for c in self.calls], [None, None])

    def test_unopenable_cwd(self):
        path = os.path.join(self.d, "dosya")
        open(path, "w").close()
        with self.assertRaises(OneshotError):
            self.shot(os.path.join(path, "alt"))


if __name__ == "__main__":
    unittest.main()
