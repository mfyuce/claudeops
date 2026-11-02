"""review.usage_cost_usd: bozuk satırlar (dict olmayan JSON, bozuk t/usage, UTF-8) fırlatmaz — P3 #44/#47."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402


class UsageCostRobustTest(unittest.TestCase):
    def _cost(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            return rv.usage_cost_usd(p, "sonnet-5-5")

    def test_bad_lines_skipped(self):
        good = '{"t": 1, "usage": {"input_tokens": 1000000, "output_tokens": 0}}\n'
        base = self._cost(good)
        self.assertGreater(base, 0)
        junk = '[1,2]\nnull\n"x"\n3\n{"t": "abc", "usage": {"input_tokens": 1000000}}\n{"t": 1, "usage": [1]}\n{"usage": "s"}\n'
        # t="abc" kaydı t=0 sayılır ve usage'ı geçerli: ek maliyet; diğerleri yok sayılır.
        self.assertAlmostEqual(self._cost(junk + good), base * 2, places=6)

    def test_since_filters(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.jsonl")
            open(p, "w").write('{"t": 5, "usage": {"input_tokens": 1000000}}\n')
            self.assertEqual(rv.usage_cost_usd(p, "sonnet-5-5", since_ms=10), 0.0)


if __name__ == "__main__":
    unittest.main()
