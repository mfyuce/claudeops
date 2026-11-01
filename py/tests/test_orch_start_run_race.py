"""start_run: yer ayrılmış ama henüz kaydedilmemiş (load_run None) run AKTİF sayılır; ikinci başlatma reddedilir."""
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_orch as wo  # noqa: E402


class StartRunRaceTest(unittest.TestCase):
    def test_reserved_but_unsaved_run_blocks_second_start(self):
        with mock.patch.object(wo, "_preflight", return_value=None), \
                mock.patch.object(wo.orch_store, "load_run", return_value=None), \
                mock.patch.object(wo, "_ACTIVE_RUN_ID", "r-pending"), \
                mock.patch.dict(wo._CANCEL_EVENTS, {"r-pending": threading.Event()}, clear=False):
            rid, err = wo.start_run([{"role": "worker", "host": "local", "name": "x"}], "görev")
        self.assertIsNone(rid)
        self.assertIn("already active", err)


if __name__ == "__main__":
    unittest.main()
