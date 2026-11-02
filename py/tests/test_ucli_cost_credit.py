"""ucli_cost.credit_total_usd: kalan kredi = toplam - birikmiş (tüm günler) harcama; boş = gösterme."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import settings, ucli_cost  # noqa: E402


def _write(base, name, t_ms):
    with open(os.path.join(base, name), "w") as f:
        f.write(json.dumps({"t": t_ms, "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}) + "\n")


class CreditTest(unittest.TestCase):
    def cfg(self, **kw):
        base = {"daily_cap_usd": 0.0, "cache_ttl": "1h", "credit_total_usd": 0.0}
        base.update(kw)
        return mock.patch.object(ucli_cost, "ucli_cost_config", lambda: base)

    def test_config_parse(self):
        for raw, want in (({"credit_total_usd": "200"}, 200.0), ({"credit_total_usd": "12,5"}, 12.5),
                          ({"credit_total_usd": ""}, 0.0), ({"credit_total_usd": "-3"}, 0.0),
                          ({"credit_total_usd": "abc"}, 0.0), ({}, 0.0)):
            with mock.patch.object(settings, "load_settings", lambda raw=raw: {"ucli_cost": raw}):
                self.assertEqual(settings.ucli_cost_config()["credit_total_usd"], want)

    def test_hidden_when_empty(self):
        with tempfile.TemporaryDirectory() as d, self.cfg():
            ucli_cost.invalidate()
            self.assertNotIn("credit_left_usd", ucli_cost.state(base=d))

    def test_left_counts_old_days_too(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as d, self.cfg(credit_total_usd=200.0):
            _write(d, "eski.jsonl", (now - 5 * 86400) * 1000)    # dünden önceki harcama da birikmişe girer
            _write(d, "bugun.jsonl", now * 1000)
            ucli_cost.invalidate()
            s = ucli_cost.state(now, base=d)
            self.assertEqual(s["credit_total_usd"], 200.0)
            self.assertGreater(s["spent_total_usd"], s["today_usd"])
            self.assertAlmostEqual(s["credit_left_usd"], 200.0 - s["spent_total_usd"], places=3)

    def test_left_never_negative(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as d, self.cfg(credit_total_usd=0.01):
            _write(d, "a.jsonl", now * 1000)
            ucli_cost.invalidate()
            self.assertEqual(ucli_cost.state(now, base=d)["credit_left_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
