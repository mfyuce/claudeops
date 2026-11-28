"""Çok derin iç içe `settings.json` (TODO rs-prov, #397 ajanının gördüğü): `load_settings` `RecursionError` fırlatmasın.
Rust (`cops_state::json::MAX_DEPTH` = 512: bir değer en çok 512 kapsayıcının içinde) gibi belge bozuk sayılır:
varsayılanlar döner, `store_backend` son iyi değeri korur."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from claudeops import settings as st


def _nested(levels: int, inner: str = "") -> str:
    return "[" * levels + inner + "]" * levels


class DeepSettingsDocument(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.p = os.path.join(self.d, "settings.json")
        patcher = mock.patch.object(st, "SETTINGS_JSON", self.p)
        patcher.start()
        self.addCleanup(patcher.stop)
        st._LOAD_CACHE.update(sig=None, val=None)
        self.addCleanup(st._LOAD_CACHE.update, sig=None, val=None)

    def _write(self, text: str):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write(text)
        st._LOAD_CACHE.update(sig=None, val=None)

    def _doc(self, deep: str) -> str:
        return '{"fleet_sort": "cwd", "stewards": {"x": ' + deep + '}}'

    def test_parser_recursion_does_not_escape(self):
        self._write(self._doc(_nested(100000)))
        out = st.load_settings()
        self.assertEqual(out["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])
        self.assertEqual(out["stewards"], {})

    def test_deep_but_parseable_value_does_not_break_the_cache_copy(self):
        self._write(self._doc(_nested(990)))
        for _ in range(2):          # ikinci çağrı önbellekten derin kopya verir
            out = st.load_settings()
            self.assertEqual(out["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])

    def test_limit_matches_rust(self):
        # belge > stewards: iki kapsayıcı; `_nested(n)` dizileri 2..n+1 düzeyinde. Değer derinliği = içinde olduğu
        # kapsayıcı sayısı; 512 izinli, 513 bozuk (Rust `cops_state::json`).
        self._write(self._doc(_nested(511)))            # en içteki boş dizi 512. düzeyde
        self.assertEqual(st.load_settings()["fleet_sort"], "cwd")
        self.assertEqual(st.load_settings()["fleet_sort"], "cwd")      # önbellek kopyası da taşmaz
        self._write(self._doc(_nested(511, "1")))       # 1, 513. düzeyde
        self.assertEqual(st.load_settings()["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])
        self._write(self._doc(_nested(512)))
        self.assertEqual(st.load_settings()["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])

    def test_dropped_deep_key_still_counts(self):
        # tanınmayan anahtardaki derin değer de belgeyi bozar (Rust ayrıştırıcı bütün belgeyi reddeder)
        self._write('{"fleet_sort": "cwd", "bilinmeyen": ' + _nested(600) + '}')
        self.assertEqual(st.load_settings()["fleet_sort"], st.DEFAULT_SETTINGS["fleet_sort"])

    def test_store_backend_keeps_last_good_value(self):
        self._write('{"store_backend": "db"}')
        self.assertEqual(st.load_settings()["store_backend"], "db")
        self._write('{"store_backend": "db", "x": ' + _nested(100000) + '}')
        self.assertEqual(st.load_settings()["store_backend"], "db")


if __name__ == "__main__":
    unittest.main()
