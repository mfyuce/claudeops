"""P12 review: DSN maskeleme (büyük harfli şema, parolada @), kaza sayılmayan hatalar deneme hakkı tüketmez."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402


class DsnRedactionTest(unittest.TestCase):
    def test_uppercase_scheme_masked(self):
        t = rv.redact_secrets("DSN POSTGRESQL://u:hunter22@h:5/db ok")
        self.assertNotIn("hunter22", t)

    def test_password_with_at_sign_masked(self):
        t = rv.redact_secrets("postgresql://u:pa@ss-word1@host/db")
        self.assertNotIn("pa@ss", t)
        self.assertNotIn("word1", t)


class CountsAsAttemptTest(unittest.TestCase):
    def test_uncounted_errors(self):
        for err in ("cancelled", "spawn: yok", "yeniden başlatma (servis)"):
            self.assertFalse(rv.counts_as_attempt({"error": err}), err)

    def test_real_errors_count(self):
        for rec in ({"error": "timeout"}, {"error": "rc=1"}, {}, None):
            self.assertTrue(rv.counts_as_attempt(rec), rec)


if __name__ == "__main__":
    unittest.main()
