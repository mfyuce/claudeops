"""TBD#374 (a) S8: yanlış tipli `ucli_services.models` yok sayılır."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)


class UcliModelsType(unittest.TestCase):
    def test_s8_non_list_models_ignored(self):
        for bad in (5, True, 1.5, {"a": 1}):
            with self.subTest(bad=bad):
                out = settings.normalize_ucli_services([{"id": "evren", "env": "EVREN_KEY", "models": bad}])
                self.assertEqual(out[0]["models"], [])


if __name__ == "__main__":
    unittest.main()
