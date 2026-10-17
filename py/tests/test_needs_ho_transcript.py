"""needs_ho'nun transkript seçimi: oturumun KENDİ sid'inin jsonl'ı, cwd'deki "en yeni dosya" değil (stdlib unittest).

Hata (TODO.md 2026-10-16 (6), son madde): `web._needs_ho_cached` ve `handover.handover_faz1` (batch) `needs_ho`ya
`find_latest_jsonl(cwd)` veriyordu; aynı cwd'yi paylaşan iki claude oturumunda (ör. handover çakışması) "ho gerekir
/gerekmez" kararı başkasının transkriptine göre çıkabiliyordu. `needs_ho` `sid`'i kullanmaz, yalnız verilen jsonl
yoluna bakar; sid'i çözmek çağıranın işi: `jsonl_path_for(cwd, sid)` (sid yoksa ya da dosya yoksa eski tahmine düşer).

Çalıştırma:  python3 py/tests/test_needs_ho_transcript.py -v

Gerçek oturumlara, tmux'a, git'e, STATE_DIR'e ya da ~/.claude'a DOKUNMAZ (needs_ho, PROJECTS_DIR, STATE_DIR ve
discovery sahte).
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import handover  # noqa: E402
from claudeops import paths  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.session import Session  # noqa: E402

CWD = "/w/shared"


class SharedCwdCase(unittest.TestCase):
    """Aynı cwd'de iki transkript: `sid-mine` ESKİ, `sid-sibling` YENİ (eski tahmin yenisini seçerdi)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proj = Path(tmp.name) / cp._encode_cwd(CWD)
        proj.mkdir()
        self.mine = proj / "sid-mine.jsonl"
        self.sibling = proj / "sid-sibling.jsonl"
        for p, mtime in ((self.mine, 1_000), (self.sibling, 2_000)):
            p.write_text("{}\n")
            os.utime(p, (mtime, mtime))
        patcher = mock.patch.object(cp, "PROJECTS_DIR", tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)


class WebNeedsHoCachedTests(SharedCwdCase):
    def setUp(self):
        super().setUp()
        web._NEEDSHO_CACHE.clear()
        self.addCleanup(web._NEEDSHO_CACHE.clear)

    def seen_path(self, session):
        """`_needs_ho_cached`in `needs_ho`ya verdiği jsonl yolu (karar kendisi sahte)."""
        with mock.patch.object(web, "needs_ho", return_value=True) as m:
            web._needs_ho_cached(session)
        m.assert_called_once()
        return m.call_args.args[2]

    def test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd(self):
        s = Session(name="a", pid=1, cwd=CWD, sid="sid-mine")
        self.assertEqual(self.seen_path(s), self.mine)

    def test_without_a_sid_or_a_matching_file_it_falls_back_to_the_newest_file(self):
        for sid in (None, "sid-gone"):
            web._NEEDSHO_CACHE.clear()
            s = Session(name="a", pid=1, cwd=CWD, sid=sid)
            self.assertEqual(self.seen_path(s), self.sibling, msg=str(sid))


class HandoverBatchTests(SharedCwdCase):
    def run_batch(self, session):
        """Batch kipinde (`names` yok) `handover_faz1`; `needs_ho` False döner, yani tmux'a hiç inilmez."""
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(paths, "STATE_DIR", Path(state)), \
                mock.patch.object(handover, "find_sessions", return_value=[session]), \
                mock.patch.object(handover, "ancestor_pids", return_value=set()), \
                mock.patch.object(handover, "needs_ho", return_value=False) as nho, \
                contextlib.redirect_stdout(io.StringIO()):
            summary = handover.handover_faz1(batch_delay=0)
        nho.assert_called_once()
        self.assertEqual([r.status for r in summary.results], ["skipped-no-ho"])
        return nho.call_args.args[2]

    def test_the_sessions_own_transcript_is_used_not_the_newest_in_the_cwd(self):
        s = Session(name="a", pid=424242, cwd=CWD, sid="sid-mine")
        self.assertEqual(self.run_batch(s), str(self.mine))

    def test_without_a_sid_it_falls_back_to_the_newest_file(self):
        s = Session(name="a", pid=424242, cwd=CWD, sid=None)
        self.assertEqual(self.run_batch(s), str(self.sibling))


if __name__ == "__main__":
    unittest.main()
