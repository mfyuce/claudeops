"""`rc --dry-run --kill-first`: süreç taraması da önizleme kipinde koşar, agy keşfi öğrendiği sid'i diske yazmaz
(TODO rs-prov "kuru çalıştırma kenarları"; eskiden önizleme yalnız `spawn_session` içinde açılıyordu)."""
import contextlib
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from claudeops import preview, statedocs  # noqa: E402
from claudeops.commands import rc  # noqa: E402
from claudeops.providers import agy_provider  # noqa: E402
from claudeops.roster import RosterEntry  # noqa: E402


def _args(dry_run: bool):
    return types.SimpleNamespace(
        names=["agyproj"], fresh=False, kill_first=True, model=None, permission_mode=None, effort=None, prompt=None,
        one_by_one=False, proc_wait=0.0, grace=0.0, kill_settle=0.0, dry_run=dry_run, display=":0", force=False)


class RcDryRunRunsInPreview(unittest.TestCase):
    def run_rc(self, dry_run: bool):
        seen = {"scan": [], "spawn": []}
        writes = []

        def fake_find_sessions(measure_cpu=True, mirrors_out=None):
            seen["scan"].append(preview.active())
            agy_provider._remember_agy_sid("agyproj", "conv-1")     # keşfin her turda yaptığı öğrenme
            return []

        def fake_spawn(**kw):
            seen["spawn"].append((kw["dry_run"], preview.active()))
            return "[dry-run] x" if kw["dry_run"] else "new"

        roster = {"agyproj": RosterEntry(name="agyproj", cwd="/tmp", model="m", cli="agy")}
        with mock.patch.object(rc, "guard_lock", lambda timeout: contextlib.nullcontext()), \
                mock.patch.object(rc, "read_models", return_value={}), \
                mock.patch.object(rc, "roster_by_name", return_value=roster), \
                mock.patch.object(rc, "find_sessions", fake_find_sessions), \
                mock.patch.object(rc, "spawn_session", fake_spawn), \
                mock.patch.object(rc, "mark_started"), mock.patch.object(rc, "repo_baseline_set"), \
                mock.patch.object(rc, "resolved_model_for", return_value="m"), \
                mock.patch.object(agy_provider, "_load_agy_sids", return_value={}), \
                mock.patch.object(agy_provider, "_load_agy_sids_for_write", return_value={}), \
                mock.patch.object(agy_provider, "file_lock", lambda *a, **k: contextlib.nullcontext()), \
                mock.patch.object(statedocs, "write_json", lambda *a, **k: writes.append(a)), \
                mock.patch("builtins.print"):
            self.assertEqual(rc.run(_args(dry_run)), 0)
        return seen, writes

    def test_dry_run_scan_is_in_preview_and_writes_no_sid(self):
        seen, writes = self.run_rc(True)
        self.assertEqual(seen["scan"], [True])
        self.assertEqual(seen["spawn"], [(True, True)])
        self.assertEqual(writes, [])
        self.assertFalse(preview.active())

    def test_real_run_is_unchanged(self):
        seen, writes = self.run_rc(False)
        self.assertEqual(seen["scan"], [False])
        self.assertEqual(seen["spawn"], [(False, False)])
        self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
