"""TBD#374 (a) S4: db kipinde oturum kaydı önbelleğe alınmaz."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import instances, statedocs  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)


class InstancesCacheDbMode(_Tmp):
    def test_s4_db_mode_not_cached(self):
        path = os.path.join(self.d, "instances.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
        self.patch(instances, "INSTANCES_JSON", path)
        self.patch(instances, "_cache_key", None)
        self.patch(instances, "_cache", {})
        docs = [{"a": {}}, {"a": {}, "b": {}}]
        self.patch(instances, "read_strict", lambda: {"instances": docs.pop(0)})
        self.patch(statedocs, "backend", lambda: "db")
        self.assertEqual(set(instances.load_instances()), {"a"})
        self.assertEqual(set(instances.load_instances()), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
