"""D9: load_settings dosya imzasına bağlı önbellek; değişiklik görülür, çağırana kopya verilir."""
import json
import os
import tempfile
import unittest
from unittest import mock

from claudeops import settings as st


class Cache(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "settings.json")
        patcher = mock.patch.object(st, "SETTINGS_JSON", self.p)
        patcher.start()
        self.addCleanup(patcher.stop)
        st._LOAD_CACHE.update(sig=None, val=None)

    def _write(self, d):
        tmp = self.p + ".t"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.p)

    def test_unchanged_file_parsed_once(self):
        self._write({"fleet_sort": "cwd"})
        with mock.patch.object(st, "_load_settings_uncached", wraps=st._load_settings_uncached) as m:
            for _ in range(5):
                self.assertEqual(st.load_settings()["fleet_sort"], "cwd")
            self.assertEqual(m.call_count, 1)

    def test_change_is_seen(self):
        self._write({"fleet_sort": "cwd"})
        self.assertEqual(st.load_settings()["fleet_sort"], "cwd")
        self._write({"fleet_sort": "name"})
        self.assertEqual(st.load_settings()["fleet_sort"], "name")

    def test_callers_get_copies(self):
        self._write({"default_model": {"claude": "x"}})
        a = st.load_settings()
        a["default_model"]["claude"] = "KIRLENDI"
        self.assertEqual(st.load_settings()["default_model"]["claude"], "x")

    def test_missing_file_defaults_and_save_roundtrip(self):
        self.assertEqual(st.load_settings()["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])
        st.save_settings({"fleet_sort": "cwd"})
        self.assertEqual(st.load_settings()["fleet_sort"], "cwd")
        st.save_settings({"fleet_sort": "name"})
        self.assertEqual(st.load_settings()["fleet_sort"], "name")


if __name__ == "__main__":
    unittest.main()
