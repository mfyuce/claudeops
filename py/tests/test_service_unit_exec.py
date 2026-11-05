"""OPS-06: web unit'i python'u `exec` ile baslatir (MainPID bash kalmasin)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import service  # noqa: E402


class UnitExecTest(unittest.TestCase):
    def test_web_unit_execs_python(self):
        unit = service.WEB_UNIT_TEMPLATE.format(python="/usr/bin/python3", repo_py="/r", uid=1000,
                                                run_tunnel="/t", **{k: "" for k in ()})
        line = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
        self.assertIn("'exec /usr/bin/python3 -m claudeops web'", line)


if __name__ == "__main__":
    unittest.main()
