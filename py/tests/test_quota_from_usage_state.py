import time
from unittest import mock

from claudeops import steward_quota as sq
from claudeops.commands import web_steward as ws

E = [{"label": "Current session", "percent": "2", "detail": "Resets 12am (Europe/Istanbul)"},
     {"label": "Current week (all models)", "percent": "92", "detail": "Resets Nov 25, 6pm (Europe/Istanbul)"},
     {"label": "Current week (Fable)", "percent": "75", "detail": "Resets Nov 25, 6pm (Europe/Istanbul)"}]


def test_entries_to_usage():
    u = sq.usage_from_entries(E, time.time())
    assert (u.week_pct, u.fable_pct, u.session_pct) == (92.0, 75.0, 2.0) and u.reset_ts


def test_no_week_entry_is_none():
    assert sq.usage_from_entries([E[0]], time.time()) is None


def test_quota_read_prefers_fresh_state_no_subprocess():
    with mock.patch("claudeops.usage_state.provider", return_value={"available": True, "stale": False, "entries": E}), \
         mock.patch.object(ws.subprocess, "run", side_effect=AssertionError("spawned")):
        assert ws.quota_read_usage().week_pct == 92.0


def test_stale_state_falls_back_to_command():
    with mock.patch("claudeops.usage_state.provider", return_value={"available": True, "stale": True, "entries": E}), \
         mock.patch.object(ws.shutil, "which", return_value=None):
        assert ws.quota_read_usage() is None
