"""Günlük tavan reddi: ucli_cost.refusal sonucu (`code`) ve ucli_provider._claude_service_flags'in DailyCapExceeded fırlatması."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import ucli_cost  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class RefusalTests(unittest.TestCase):
    def test_cap_refusal_has_code_and_amounts(self):
        exc = ucli_cost.DailyCapExceeded(14.08, 10.0)
        self.assertEqual(ucli_cost.refusal(exc), {
            "ok": False, "code": "ucli_daily_cap", "today_usd": 14.08, "cap_usd": 10.0, "error": str(exc)})

    def test_plain_value_error_has_no_code(self):
        res = ucli_cost.refusal(ValueError("x"))
        self.assertEqual(res, {"ok": False, "error": "x"})
        self.assertNotIn("code", res)


class ProviderRaisesTests(unittest.TestCase):
    def test_claude_service_flags_raises_over_cap(self):
        st = {"today_usd": 14.08, "cap_usd": 10.0}
        with mock.patch.object(up.ucli_cost, "cap_exceeded", return_value=True), \
                mock.patch.object(up.ucli_cost, "state", return_value=st):
            with self.assertRaises(ucli_cost.DailyCapExceeded) as cm:
                up._claude_service_flags(["ucli"], "vc")
        self.assertEqual(cm.exception.today_usd, 14.08)
        self.assertEqual(cm.exception.cap_usd, 10.0)
        self.assertIsInstance(cm.exception, ValueError)


if __name__ == "__main__":
    unittest.main()
