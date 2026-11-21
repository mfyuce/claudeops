"""ucli başlatma payı: başarısız başlatmada `release` payı hemen geri verir (TTL'i beklemez)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_cost as uc  # noqa: E402


class ReleaseOnFailedStart(unittest.TestCase):
    def test_release_returns_the_reserved_share_immediately(self):
        with mock.patch.object(uc, "state", lambda *a, **k: {"cap_usd": 10.0, "today_usd": 0.0}):
            uc.reserve("zz-rel")
            self.assertIn("zz-rel", uc._RESERVED)
            uc.release("zz-rel")
            self.assertNotIn("zz-rel", uc._RESERVED)
            uc.release("zz-rel")        # ikinci kez: sorun değil


if __name__ == "__main__":
    unittest.main()
