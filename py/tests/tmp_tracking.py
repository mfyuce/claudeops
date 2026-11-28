"""Test geçici dizin ağı (adı `test_` ile başlamaz: keşfe girmez). İçe aktarınca kurulur, ikinci kez kurulmaz.

21 Kas: ~60 test dosyası `tempfile.mkdtemp()`i silmeden bırakıyordu (test_periodic tek başına 2 günde 5,8 GB /tmp sızdırdı).
Süreçte açılan HER mkdtemp dizini kayda geçer ve süreç sonunda silinir (test içinde canlı kalır; setUpClass güvenli).
`mkstemp` ve `NamedTemporaryFile(delete=False)` dosyaları da kayda geçer; yalnız sistem geçici dizini altındakiler silinir
(ürün kodu `mkstemp(dir=hedef)` ile atomik yazıp yeniden adlandırır, hedef dizine dokunulmaz).
`conftest.py` (pytest), `test_000_diag_env.py` (`unittest discover`) ve `cops test` (modül listesinin başına
`test_000_diag_env` koyar) yükler; elle `python3 -m unittest test_x` koşusunda ağ YOKTUR, bu yüzden yeni testte yine
de addCleanup/TemporaryDirectory kullanılır.
"""
import atexit
import os
import shutil
import tempfile

_orig_mkdtemp = tempfile.mkdtemp
_orig_mkstemp = tempfile.mkstemp
_orig_named = tempfile.NamedTemporaryFile
_OWNER = os.getpid()
_TMP_ROOT = os.path.realpath(tempfile.gettempdir()) + os.sep
CREATED = []
CREATED_FILES = []


def _tracked_mkdtemp(*a, **k):
    d = _orig_mkdtemp(*a, **k)
    CREATED.append(d)
    return d


def _tracked_mkstemp(*a, **k):
    fd, path = _orig_mkstemp(*a, **k)
    CREATED_FILES.append(path)
    return fd, path


def _tracked_named(*a, **k):
    f = _orig_named(*a, **k)
    if not k.get("delete", a[7] if len(a) > 7 else True):
        CREATED_FILES.append(f.name)
    return f


def cleanup_files(paths):
    for p in paths:
        if isinstance(p, str) and os.path.realpath(p).startswith(_TMP_ROOT) and os.path.isfile(p):
            try:
                os.unlink(p)
            except OSError:
                pass


def cleanup():
    if os.getpid() != _OWNER:     # fork edilen çocuk ebeveynin dizinlerini silmez
        return
    for d in CREATED:
        shutil.rmtree(d, ignore_errors=True)
    cleanup_files(CREATED_FILES)


tempfile.mkdtemp = _tracked_mkdtemp
tempfile.mkstemp = _tracked_mkstemp
tempfile.NamedTemporaryFile = _tracked_named
atexit.register(cleanup)
