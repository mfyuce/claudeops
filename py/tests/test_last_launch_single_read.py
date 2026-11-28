"""`_last_launch` tek okuma (rs-state kapı notu, TODO "_last_launch iki okuma arasında yarış").

Kayıt `view_instances()` anlık görüntüsünden seçilip cli'si denetleniyordu, dönen kopya ise ikinci bir okumadan
(`get_instance`) geliyordu: arada kayıt silinir ya da değişirse denetlenmemiş (cli'si geçersiz) kayıt ya da None dönerdi.
Dönen kayıt denetlenen anlık görüntünün kopyası olmalı ve çağıranın değişikliği önbelleği kirletmemeli.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class LastLaunchSingleReadTest(unittest.TestCase):
    def setUp(self):
        self.snap = {"p": {"cli": "claude", "cli_opts": {"service": "x"}, "created_at": 1}}
        p1 = mock.patch.object(ws.inst_mod, "view_instances", return_value=self.snap)
        # ikinci okuma (yarış): kayıt artık başka cli'de
        p2 = mock.patch.object(ws.inst_mod, "get_instance", return_value={"cli": "bogus"})
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_returns_checked_snapshot_record(self):
        rec = ws._last_launch("p")
        self.assertEqual(rec, self.snap["p"])

    def test_returned_record_is_a_copy(self):
        rec = ws._last_launch("p")
        rec["cli_opts"]["service"] = "changed"
        self.assertEqual(self.snap["p"]["cli_opts"]["service"], "x")

    def test_blueprint_fallback_uses_same_snapshot(self):
        self.snap.clear()
        self.snap.update({"p1": {"cli": "ucli", "blueprint": "p", "created_at": 5},
                          "p0": {"cli": "claude", "blueprint": "p", "created_at": 2}})
        self.assertEqual(ws._last_launch("p")["cli"], "ucli")


if __name__ == "__main__":
    unittest.main()
