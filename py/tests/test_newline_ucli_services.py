"""ucli hizmet uç adresi: `.../v1\\n/` sondaki `/` kırpılınca satır sonuyla kalıyor ve `^...$` + `match`ten geçiyordu."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings as st  # noqa: E402


class TrailingNewlineEndpointTest(unittest.TestCase):
    def test_endpoint_with_newline_before_slash_is_dropped(self):
        raw = [{"id": "bad", "env": "BAD_KEY", "endpoint": "https://a.example/v1\n/"},
               {"id": "good", "env": "GOOD_KEY", "endpoint": "https://g.example/v1/"}]
        out = st.normalize_ucli_services(raw)
        self.assertEqual([d["id"] for d in out], ["evren", "good"])
        self.assertEqual(out[1]["endpoint"], "https://g.example/v1")


if __name__ == "__main__":
    unittest.main()
