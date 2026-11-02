"""`web_grpc` SessionRow <-> dict eşlemesinde `ucli_flags` (WEBUI-TODO 14) — stdlib unittest.

pb2 yeniden üretilmediyse (`ucli_write` alanı yok) rozet testleri atlanır; "alanlar yok sayılır, hata yok" testi her durumda koşar.

Çalıştırma:  python3 py/tests/test_web_grpc_ucli_flags.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_grpc  # noqa: E402

BASE = {"name": "u1", "host": "h", "model": "m", "cwd": "/x", "cli": "ucli", "running": True}


class GrpcUcliFlagsTest(unittest.TestCase):
    def test_roundtrip_never_raises_and_keeps_core_fields(self):
        d = web_grpc._session_row_to_dict(web_grpc._dict_to_session_row({**BASE, "ucli_flags": {"write": True, "exec": False, "max_cost_usd": 1.5}}))
        self.assertEqual((d["name"], d["cli"], d["running"]), ("u1", "ucli", True))
        self.assertIn("ucli_flags", d)

    def test_no_flags_means_none(self):
        d = web_grpc._session_row_to_dict(web_grpc._dict_to_session_row(BASE))
        self.assertIsNone(d["ucli_flags"])

    @unittest.skipUnless(web_grpc._PB_HAS_UCLI_FLAGS, "host_bridge_pb2 yeniden üretilmedi")
    def test_flags_roundtrip(self):
        for flags in ({"write": True, "exec": True, "max_cost_usd": 2.5},
                      {"write": False, "exec": False, "max_cost_usd": None},
                      {"write": True, "exec": False, "max_cost_usd": 0.0}):
            d = web_grpc._session_row_to_dict(web_grpc._dict_to_session_row({**BASE, "ucli_flags": flags}))
            self.assertEqual(d["ucli_flags"], flags)

    @unittest.skipUnless(web_grpc._PB_HAS_UCLI_FLAGS, "host_bridge_pb2 yeniden üretilmedi")
    def test_non_ucli_row_has_no_flags(self):
        d = web_grpc._session_row_to_dict(web_grpc._dict_to_session_row({**BASE, "cli": "claude", "ucli_flags": None}))
        self.assertIsNone(d["ucli_flags"])


if __name__ == "__main__":
    unittest.main()
