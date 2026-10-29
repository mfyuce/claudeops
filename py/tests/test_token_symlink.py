"""review R-3: token dosyası CREATE yolu symlink'i izlemez (stdlib unittest)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web


class TokenSymlink(unittest.TestCase):
    def test_dangling_symlink_not_written_through(self):
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "victim")
            tok = os.path.join(d, "token")
            os.symlink(victim, tok)
            old = (web.TOKEN_FILE, web.CLAUDEOPS_DIR)
            web.TOKEN_FILE, web.CLAUDEOPS_DIR = tok, d
            try:
                with self.assertRaises(OSError):
                    web._load_or_create_token()
            finally:
                web.TOKEN_FILE, web.CLAUDEOPS_DIR = old
            self.assertFalse(os.path.exists(victim))

    def test_creates_0600(self):
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "token")
            old = (web.TOKEN_FILE, web.CLAUDEOPS_DIR)
            web.TOKEN_FILE, web.CLAUDEOPS_DIR = tok, d
            try:
                t = web._load_or_create_token()
            finally:
                web.TOKEN_FILE, web.CLAUDEOPS_DIR = old
            self.assertEqual(os.stat(tok).st_mode & 0o777, 0o600)
            self.assertEqual(open(tok).read(), t)


if __name__ == "__main__":
    unittest.main()
