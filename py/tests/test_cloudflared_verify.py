"""cloudflared indirmesi sha256 doğrulamalı (12 Kas araç turu): özet yoksa/uyuşmuyorsa ikili kurulmaz."""
import hashlib
import os
import tempfile
import unittest
from unittest import mock

from claudeops.commands import web

BASE = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.7/"
H = "a" * 64


class CloudflaredVerifyTest(unittest.TestCase):
    def test_asset_ok(self):
        rel = {"assets": [{"name": "cloudflared-linux-amd64", "digest": "sha256:" + H.upper(), "browser_download_url": BASE + "cloudflared-linux-amd64"}]}
        self.assertEqual(web._cloudflared_asset(rel, "amd64"), (BASE + "cloudflared-linux-amd64", H))

    def test_no_digest_or_bad_url_or_wrong_arch(self):
        a = {"name": "cloudflared-linux-amd64", "browser_download_url": BASE + "x"}
        self.assertIsNone(web._cloudflared_asset({"assets": [a]}, "amd64"))
        self.assertIsNone(web._cloudflared_asset({"assets": [dict(a, digest="sha256:zz")]}, "amd64"))
        self.assertIsNone(web._cloudflared_asset({"assets": [dict(a, digest="sha256:" + H, browser_download_url="https://evil.example/x")]}, "amd64"))
        self.assertIsNone(web._cloudflared_asset({"assets": [dict(a, digest="sha256:" + H)]}, "arm64"))
        self.assertIsNone(web._cloudflared_asset(None, "amd64"))

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"abc")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(web._sha256_file(f.name), hashlib.sha256(b"abc").hexdigest())

    def test_mismatch_does_not_install(self):
        home = tempfile.mkdtemp()
        rel = {"assets": [{"name": "cloudflared-linux-amd64", "digest": "sha256:" + H, "browser_download_url": BASE + "cloudflared-linux-amd64"}]}

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return __import__("json").dumps(rel).encode()

        def fake_retrieve(url, tmp):
            with open(tmp, "wb") as f:
                f.write(b"\x7fELF" + b"0" * 2_000_000)

        with mock.patch.object(web.shutil, "which", return_value=None), mock.patch.object(web.platform, "system", return_value="Linux"), \
             mock.patch.object(web.platform, "machine", return_value="x86_64"), mock.patch.object(web.os.path, "expanduser", lambda p: p.replace("~", home)), \
             mock.patch.object(web.urllib.request, "urlopen", return_value=R()), mock.patch.object(web.urllib.request, "urlretrieve", fake_retrieve):
            self.assertIsNone(web._ensure_cloudflared())
        self.assertFalse(os.path.exists(os.path.join(home, ".local/bin/cloudflared")))
        self.assertFalse(os.path.exists(os.path.join(home, ".local/bin/cloudflared.part")))


if __name__ == "__main__":
    unittest.main()
