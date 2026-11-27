"""Private kapısı: ağ hatası "repo private değil"den ayrı raporlanır; karar değişmez (yalnız "private" geçer)."""
import unittest
from unittest import mock

from claudeops import periodic as P
from claudeops.commands import memory_backup as mb

URLS = {"gitlab": "git@gitlab.com:x/y.git"}


class PrivateReasonTest(unittest.TestCase):
    def _check(self, rc, out, urls=URLS):
        with mock.patch.object(mb, "_run", return_value=(rc, out)), mock.patch.object(mb, "remotes_of", return_value=dict(urls)):
            return P._private_remotes("repo")[1]

    def test_private_passes(self):
        self.assertEqual(self._check(0, '{"visibility":"PRIVATE"}'), [])

    def test_query_failure_is_named(self):
        bad = self._check(1, "")
        self.assertEqual(len(bad), 1)
        self.assertIn("sorgu başarısız rc=1", bad[0])

    def test_public_and_internal_stay_blocked(self):
        for v in ("public", "internal"):
            self.assertEqual(self._check(0, '{"visibility":"%s"}' % v), [f"gitlab (görünürlük {v})"])

    def test_unreadable_answer_stays_blocked(self):
        for out in ("", "[]", "{}", '{"visibility":1}'):
            self.assertEqual(self._check(0, out), ["gitlab (yanıt okunamadı)"])

    def test_unknown_remote_url_stays_blocked(self):
        self.assertEqual(self._check(0, '{"visibility":"private"}', {"o": "git@example.com:x/y.git"}),
                         ["o (tanınmayan remote adresi)"])


if __name__ == "__main__":
    unittest.main()
