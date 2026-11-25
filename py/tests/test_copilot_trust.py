import json, os, tempfile, shutil, unittest
from claudeops.providers.copilot_provider import trust_folder


class TrustFolder(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.p = os.path.join(self.d, "config.json")

    def _w(self, t):
        open(self.p, "w").write(t)

    def test_adds_and_keeps_comments(self):
        self._w('// c\n{\n  "trustedFolders": [\n    "/a"\n  ],\n  "x": 1\n}\n')
        self.assertTrue(trust_folder("/b/c", self.p))
        t = open(self.p).read()
        self.assertIn("// c", t)
        self.assertEqual(json.loads(t.split("\n", 1)[1])["trustedFolders"], ["/b/c", "/a"])

    def test_empty_list(self):
        self._w('{"trustedFolders": []}')
        self.assertTrue(trust_folder("/b", self.p))
        self.assertEqual(json.loads(open(self.p).read())["trustedFolders"], ["/b"])

    def test_keeps_private_mode(self):
        self._w('{"trustedFolders": []}')
        os.chmod(self.p, 0o600)
        old = os.umask(0o002)
        self.addCleanup(os.umask, old)
        self.assertTrue(trust_folder("/b", self.p))
        self.assertEqual(os.stat(self.p).st_mode & 0o777, 0o600)

    def test_idempotent_and_missing(self):
        self._w('{"trustedFolders": ["/b"]}')
        self.assertFalse(trust_folder("/b", self.p))
        self.assertFalse(trust_folder("/b", os.path.join(self.d, "yok.json")))
        self._w('{"x": 1}')
        self.assertFalse(trust_folder("/b", self.p))
        self.assertFalse(trust_folder("rel", self.p))


if __name__ == "__main__":
    unittest.main()
