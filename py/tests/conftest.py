"""pytest: testler gerçek ~/.claude/claudeops/diag.log'a yazmasın — `claudeops` içe aktarılmadan ÖNCE yol geçici dizine döner."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="cops-test-diag-")
os.environ["CLAUDEOPS_DIAG_LOG"] = os.path.join(_TMP, "diag.log")


# 21 Kas: ~60 test dosyası `tempfile.mkdtemp()`i silmeden bırakıyordu (test_periodic tek başına 2 günde 5,8 GB /tmp sızdırdı).
# Genel ağ: oturum boyunca açılan HER mkdtemp dizini kayda geçer, oturum sonunda silinir (test içinde canlı kalır; setUpClass güvenli).
# Yeni testte yine de addCleanup/TemporaryDirectory tercih edilir; bu yalnız sızıntıya karşı emniyet.
import shutil  # noqa: E402

_orig_mkdtemp = tempfile.mkdtemp
_CREATED = [_TMP]


def _tracked_mkdtemp(*a, **k):
    d = _orig_mkdtemp(*a, **k)
    _CREATED.append(d)
    return d


tempfile.mkdtemp = _tracked_mkdtemp


def pytest_sessionfinish(session, exitstatus):
    for d in _CREATED:
        shutil.rmtree(d, ignore_errors=True)
