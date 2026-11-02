"""pytest: testler gerçek ~/.claude/claudeops/diag.log'a yazmasın — `claudeops` içe aktarılmadan ÖNCE yol geçici dizine döner."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="cops-test-diag-")
os.environ["CLAUDEOPS_DIAG_LOG"] = os.path.join(_TMP, "diag.log")
