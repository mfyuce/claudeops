"""Test geçici dizin ağı (adı `test_` ile başlamaz: keşfe girmez). İçe aktarınca kurulur, ikinci kez kurulmaz.

21 Kas: ~60 test dosyası `tempfile.mkdtemp()`i silmeden bırakıyordu (test_periodic tek başına 2 günde 5,8 GB /tmp sızdırdı).
Süreçte açılan HER mkdtemp dizini kayda geçer ve süreç sonunda silinir (test içinde canlı kalır; setUpClass güvenli).
`conftest.py` (pytest) ve `test_000_diag_env.py` (`unittest discover`) yükler; tek modül koşusunda ağ YOKTUR, bu yüzden
yeni testte yine de addCleanup/TemporaryDirectory kullanılır.
"""
import atexit
import os
import shutil
import tempfile

_orig_mkdtemp = tempfile.mkdtemp
_OWNER = os.getpid()
CREATED = []


def _tracked_mkdtemp(*a, **k):
    d = _orig_mkdtemp(*a, **k)
    CREATED.append(d)
    return d


def cleanup():
    if os.getpid() != _OWNER:     # fork edilen çocuk ebeveynin dizinlerini silmez
        return
    for d in CREATED:
        shutil.rmtree(d, ignore_errors=True)


tempfile.mkdtemp = _tracked_mkdtemp
atexit.register(cleanup)
