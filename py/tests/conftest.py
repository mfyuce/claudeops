"""pytest: testler gerçek ~/.claude/claudeops/diag.log'a yazmasın — `claudeops` içe aktarılmadan ÖNCE yol geçici dizine döner."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tmp_tracking  # noqa: E402  (mkdtemp ağı; ayrıntı modülde)

_TMP = tempfile.mkdtemp(prefix="cops-test-diag-")
os.environ["CLAUDEOPS_DIAG_LOG"] = os.path.join(_TMP, "diag.log")


def pytest_sessionfinish(session, exitstatus):
    tmp_tracking.cleanup()
