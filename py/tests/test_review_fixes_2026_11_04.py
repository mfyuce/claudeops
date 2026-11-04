"""Doğrulanmış reviewer bulgularının düzeltmeleri (2026-11-04, deepseek denemeleri E2/E3/E6/E7/E11/E13, 4B R-6/R-7,
4A R-02/R-06; ayrıntı ~/.claude/claudeops/backups/evren-deepseek-nolimit-2026-11-03/DOGRULAMA-2026-11-04.md).

Gerçek oturumlara, tmux'a, STATE_DIR'e ya da ~/.claude'a DOKUNMAZ (hepsi geçici dizin/sahte).
Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from claudeops import cli_install, files, handover, needs_ho, paths  # noqa: E402
from claudeops.commands import guard as guard_cmd  # noqa: E402
from claudeops.guard import GuardResult  # noqa: E402
from claudeops.session import Session  # noqa: E402


class CommittedSinceTimeCompare(unittest.TestCase):
    """E2: baseline ile commit zamanı dizgi değil ZAMAN olarak karşılaştırılır."""

    def run_case(self, baseline, commit_iso):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "last-handover.ts").write_text(baseline)
            with mock.patch.object(needs_ho, "_STATE_DIR", Path(d)), \
                    mock.patch.object(needs_ho, "_is_git_repo", return_value=True), \
                    mock.patch.object(needs_ho, "_repo_baseline_get", return_value=None), \
                    mock.patch.object(needs_ho, "_git", return_value=commit_iso):
                return needs_ho.repo_committed_since("/w/x")

    def test_offsets_compared_as_instants(self):
        # sözlüksel: "2026-11-04T09:00:00+03:00" > "2026-11-04T07:30:00+00:00" (True) ama gerçekte 06:00Z < 07:30Z
        self.assertFalse(self.run_case("2026-11-04T07:30:00+00:00", "2026-11-04T09:00:00+03:00"))
        self.assertTrue(self.run_case("2026-11-04T05:00:00+00:00", "2026-11-04T09:00:00+03:00"))

    def test_unparseable_baseline_means_unknown_so_do_ho(self):
        self.assertTrue(self.run_case("yarim-dosy", "2026-11-04T09:00:00+03:00"))

    def test_no_commit_is_not_new(self):
        self.assertFalse(self.run_case("2026-11-04T07:30:00+00:00", ""))


class HandoverBatchFixes(unittest.TestCase):
    def run_batch(self, sessions, dry_run, needs=False):
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(paths, "STATE_DIR", Path(state)), \
                mock.patch.object(handover, "find_sessions", return_value=sessions), \
                mock.patch.object(handover, "ancestor_pids", return_value=set()), \
                mock.patch.object(handover, "jsonl_path_for", return_value=None), \
                mock.patch.object(handover, "needs_ho", return_value=needs) as nho, \
                mock.patch.object(handover, "is_tmux_backed", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            summary = handover.handover_faz1(dry_run=dry_run, batch_delay=0)
            ts_written = (Path(state) / "last-handover.ts").exists()
            leftovers = [n for n in os.listdir(state) if n.endswith(".tmp")]
        return summary, nho, ts_written, leftovers

    def test_dry_run_does_not_write_baseline_and_shows_skip(self):
        s = Session(name="a", pid=424242, cwd="/w/a", sid="sid-a")
        summary, nho, ts, _ = self.run_batch([s], dry_run=True, needs=False)
        self.assertFalse(ts)                                                     # E3
        nho.assert_called_once()                                                 # E11: önizleme de needs_ho'ya bakar
        self.assertEqual([r.status for r in summary.results], ["skipped-no-ho"])

    def test_real_run_writes_baseline_atomically(self):
        s = Session(name="a", pid=424242, cwd="/w/a", sid="sid-a")
        _, _, ts, leftovers = self.run_batch([s], dry_run=False, needs=False)
        self.assertTrue(ts)
        self.assertEqual(leftovers, [])

    def test_sidless_session_in_shared_cwd_is_not_skipped(self):
        # E6: sid yok + aynı cwd'de komşu canlı oturum -> komşunun transkriptiyle "atla" kararı verilmez
        a = Session(name="a", pid=424242, cwd="/w/shared", sid=None)
        b = Session(name="b", pid=424243, cwd="/w/shared", sid="sid-b")
        summary, nho, _, _ = self.run_batch([a, b], dry_run=True, needs=False)
        by = {r.name: r.status for r in summary.results}
        self.assertEqual(by["a"], "dry-run")
        self.assertEqual(by["b"], "skipped-no-ho")
        self.assertEqual(nho.call_count, 1)


class GuardExitCode(unittest.TestCase):
    def run_cmd(self, spawned):
        res = GuardResult(missing=[object()] * len(spawned), spawned=spawned, dups=[])
        args = argparse.Namespace(display=":0", dry_run=False, delay=0, no_lock=True)
        with mock.patch.object(guard_cmd, "guard_once", return_value=res), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            return guard_cmd.run(args), out.getvalue()

    def test_spawn_error_gives_nonzero_exit(self):
        rc, out = self.run_cmd([("a", "tmux"), ("b", "error:boom")])
        self.assertEqual(rc, 1)                                                  # E7
        self.assertIn("1 HATA: b", out)

    def test_all_ok_exit_zero(self):
        rc, _ = self.run_cmd([("a", "tmux")])
        self.assertEqual(rc, 0)


class UploadNoOverwriteRace(unittest.TestCase):
    def test_file_appearing_after_check_is_not_clobbered(self):
        # E13: varlık denetimi geçti, yazımdan önce biri aynı adla dosya oluşturdu
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.txt")
            Path(dest).write_bytes(b"baskasi")
            self.assertEqual(files.write_upload(dest, io.BytesIO(b"yeni"), 4, 2, overwrite=False), "exists")
            self.assertEqual(Path(dest).read_bytes(), b"baskasi")
            self.assertEqual(os.listdir(d), ["a.txt"])

    def test_no_overwrite_creates_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.txt")
            self.assertIsNone(files.write_upload(dest, io.BytesIO(b"yeni"), 4, 2, overwrite=False))
            self.assertEqual(Path(dest).read_bytes(), b"yeni")
            self.assertEqual(os.listdir(d), ["a.txt"])

    def test_dir_is_fsynced_after_write(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.txt")
            with mock.patch.object(files, "_fsync_dir") as fd:
                self.assertIsNone(files.write_upload(dest, io.BytesIO(b"yeni"), 4, 2))
            fd.assert_called_once_with(d)                                        # 4B R-6


class CliStatusOverride(unittest.TestCase):
    def status(self, override):
        with mock.patch.object(cli_install, "load_settings", return_value={"provider_bin": {"claude": override}}), \
                mock.patch.object(cli_install.shutil, "which",
                                  side_effect=lambda n: None if n in ("claude", "/yok/claude") else n):
            return cli_install.cli_status("claude")

    def test_stale_override_is_not_found(self):
        st = self.status("/yok/claude")                                          # 3. deneme R-02 / 4A R-03
        self.assertFalse(st["found"])
        self.assertTrue(st["override_invalid"])

    def test_valid_override_is_found(self):
        st = self.status("/opt/bin/claude")
        self.assertTrue(st["found"])
        self.assertEqual(st["path"], "/opt/bin/claude")
        self.assertFalse(st["override_invalid"])


class SeedNonDict(unittest.TestCase):
    def test_list_content_is_left_alone(self):
        home = tempfile.mkdtemp()
        path = os.path.join(home, ".claude", "settings.json")
        os.makedirs(os.path.dirname(path))
        Path(path).write_text("[1, 2]")
        with mock.patch.dict(os.environ, {"HOME": home}):
            cli_install._seed_claude_tui_default()                               # 4A R-06: TypeError yok
        self.assertEqual(json.loads(Path(path).read_text()), [1, 2])


if __name__ == "__main__":
    unittest.main()
