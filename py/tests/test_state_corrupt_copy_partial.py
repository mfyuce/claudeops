"""Yarım kalmış `.corrupt-<sha8>` yedeği kalıcı olmaz: sonraki çağrı tam içerikle değiştirir (dört yazar)."""
import glob
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts, instances, settings, snapshot  # noqa: E402

RAW = b"{bozuk-icerik-tam"


class PartialBackup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cops-corrupt-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "files",
                                         "CLAUDEOPS_DIAG_LOG": os.path.join(self.dir, "diag.log")})
        p.start()
        self.addCleanup(p.stop)

    def check(self, module, attr, func):
        path = os.path.join(self.dir, attr.lower())
        with open(path, "wb") as f:
            f.write(RAW)
        dest = f"{path}.corrupt-{hashlib.sha256(RAW).hexdigest()[:8]}"
        with open(dest, "wb") as f:
            f.write(RAW[:3])                    # önceki yazım yarıda kesilmiş
        with mock.patch.object(module, attr, path):
            func()
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), RAW)
            self.assertEqual(os.stat(dest).st_mode & 0o777, 0o600)
            os.remove(dest)
            with mock.patch("os.replace", side_effect=OSError("disk")):
                func()                          # yazılamazsa hata yutulur, yarım/geçici dosya kalmaz
            self.assertEqual(glob.glob(path + ".*"), [])

    def test_instances(self):
        self.check(instances, "INSTANCES_JSON", instances._keep_corrupt_mirror)

    def test_settings(self):
        self.check(settings, "SETTINGS_JSON", settings._backup_if_corrupt)

    def test_hosts(self):
        self.check(hosts, "HOSTS_JSON", hosts._backup_corrupt)

    def test_snapshots(self):
        self.check(snapshot, "SNAPSHOTS_JSON", snapshot._backup_if_corrupt)


if __name__ == "__main__":
    unittest.main()
