"""Suite-geneli test hijyeni (GATE-TODO2 madde 4): TÜM paket koşarken gerçek ~/.claude/claudeops/settings.json ve
diag.log'a test yazmamış olmalı. Dosya adı `zzz`: `unittest discover` alfabetik sırayla en SON koşturur; anlık görüntü
modül İÇE AKTARILIRKEN alınır (discover tüm modülleri testlerden ÖNCE içe aktarır). Tek başına koşunca da geçer.

Not: canlı claudeops arka plan süreci diag.log'a meşru yazabilir; bu yüzden diag.log'da yalnız TEST İZİ taşıyan
yeni satırlar (sahte `name=cops` / `base_guard`) sızıntı sayılır, settings.json ise baytı baytına aynı kalmalı.
Çalıştırma: python3 -m unittest discover -s py/tests
"""
import hashlib
import os
import re
import unittest

_HOME = os.path.expanduser("~")
_REAL_DIR = os.path.join(_HOME, ".claude", "claudeops")
_SETTINGS = os.path.join(_REAL_DIR, "settings.json")
_DIAG = os.path.join(_REAL_DIR, "diag.log")
_LEAK = re.compile(rb'name["\']?\s*[=:]\s*["\']?cops\b|base_guard')


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


_SETTINGS_BEFORE = _sha(_SETTINGS)
_DIAG_SIZE_BEFORE = _size(_DIAG)


class RealStateUntouched(unittest.TestCase):
    def test_real_settings_json_unchanged(self):
        self.assertEqual(_SETTINGS_BEFORE, _sha(_SETTINGS), "test gerçek ~/.claude/claudeops/settings.json'u değiştirdi")

    def test_real_diag_log_has_no_test_traces(self):
        size = _size(_DIAG)
        if size <= _DIAG_SIZE_BEFORE:
            return
        with open(_DIAG, "rb") as f:
            f.seek(_DIAG_SIZE_BEFORE)
            added = f.read()
        self.assertIsNone(_LEAK.search(added), "test gerçek diag.log'a sahte olay yazdı")

    def test_diag_env_does_not_point_at_real_log(self):
        # İzolasyon bayrağı: conftest/steward_testlib diag yolunu geçici dizine alır (gerçek yola değil).
        diag = os.environ.get("CLAUDEOPS_DIAG_LOG")
        if diag:
            self.assertNotEqual(os.path.realpath(diag), os.path.realpath(_DIAG))


if __name__ == "__main__":
    unittest.main()
