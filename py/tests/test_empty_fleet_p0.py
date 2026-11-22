"""Boş filo düzeltmesi (sahip P0, 17 Kas): 'yok' TODO doluyken kabul edilmez; kota kapatması kaydedilip geri açılır; boşta kapasite alarmı;
Canlı servis/tmux YOK."""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops import steward_quota as sq  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_000_000.0
NONE_TXT = "Kalan her şey sahibe bağlı.\nSTEWARD-NEXT: yok"
OLDEST = "Yetki bulgusu P1: /api/x kapısı"


def _view(txt=NONE_TXT, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 3100, last_assistant=txt)
    base.update(kw)
    return sw.SessionView(name="p", **base)


class NoneRejected(unittest.TestCase):
    def plan(self, views, state=None, n_open=5, sha="aaa", now=NOW, oldest=lambda _p: OLDEST):
        projs = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
        cfg = sw.Config(enabled=True, mode="act", claude_idle="act")
        return sw.plan_claude_idle(views, projs, state or {}, cfg, now, [], open_work=lambda _p: n_open, owner_todo=lambda _p: 0,
                                   todo_sha=lambda _p: sha, oldest_open=oldest)

    def test_second_none_with_same_todo_gets_oldest_item_not_silence(self):
        acts, st = self.plan([_view()])
        self.assertEqual([a.kind for a in acts], ["todo_triage"])        # ilk kez: ayıklama
        acts2, _ = self.plan([_view(last_activity=NOW + 7200 - 3100)], st, now=NOW + 7200)
        self.assertEqual([a.kind for a in acts2], ["idle_nudge"])        # aynı sha, yine 'yok': KABUL EDİLMEZ
        self.assertIn(OLDEST, acts2[0].payload["text"])
        self.assertIn("kabul edilmez", acts2[0].payload["text"])
        self.assertEqual(acts2[0].payload["via"], "none_rejected")

    def test_without_oldest_callback_old_behaviour(self):
        _, st = self.plan([_view()], oldest=None)
        acts2, _ = self.plan([_view(last_activity=NOW + 7200 - 3100)], st, now=NOW + 7200, oldest=None)
        self.assertEqual(acts2, [])

    def test_zero_open_still_silent(self):
        self.assertEqual(self.plan([_view()], n_open=0)[0], [])

    def test_loop_guard_caps_repeated_rejection(self):
        _, st = self.plan([_view()])
        acts = []
        for i in range(1, 12):
            t = NOW + 7200 * i
            a, st = self.plan([_view(last_activity=NOW - 3100)], st, now=t)     # oturum dürtmeye cevap vermiyor (etkinlik sabit)
            acts += a
        self.assertLessEqual(len([a for a in acts if a.kind == "idle_nudge"]), sw.Config().ucli_idle_max_consecutive)


class QuotaReopen(unittest.TestCase):
    def test_reopen_ready_gate(self):
        self.assertFalse(sq.reopen_ready(0, 5, NOW))
        self.assertFalse(sq.reopen_ready(NOW - 60, 5, NOW))              # çok yeni
        self.assertFalse(sq.reopen_ready(NOW - 7200, 1, NOW))            # tek ok yoklama
        self.assertTrue(sq.reopen_ready(NOW - 7200, 2, NOW))

    def test_alarm_rules(self):
        f = sq.idle_capacity_alarm
        self.assertTrue(f(9.0, 0, 0, 3, 0, NOW))                         # kullanım düşük, steward yok, açık iş var
        self.assertTrue(f(9.0, 1, 0, 3, 0, NOW))                         # steward var ama hiç oturum yok
        self.assertFalse(f(9.0, 1, 4, 3, 0, NOW))                        # çalışıyor
        self.assertFalse(f(70.0, 0, 0, 3, 0, NOW))                       # kullanım yüksek
        self.assertFalse(f(9.0, 0, 0, 0, 0, NOW))                        # açık iş yok
        self.assertFalse(f(9.0, 0, 0, 3, NOW - 60, NOW))                 # 6 saatte en çok 1

    def _setup(self, enabled=False):
        ws._QUOTA.update(closed=["default", "reviewer"], closed_at=NOW - 7200, ok_polls=0)
        saved = []
        return saved, mock.patch.object(ws, "steward_config", lambda sid="default": types.SimpleNamespace(enabled=enabled)), \
            mock.patch("claudeops.settings.save_settings", lambda patch: saved.append(patch)), \
            mock.patch.object(ws, "notify_phone", lambda *a, **k: True), \
            mock.patch.object(ws, "_quota_save", lambda: None), \
            mock.patch.object(sw, "log_event", lambda *a, **k: None)

    def test_reopens_recorded_sids_after_two_ok_polls_and_clears(self):
        saved, *ps = self._setup()
        d, u = types.SimpleNamespace(action="ok"), types.SimpleNamespace(week_pct=9.0)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(ws._quota_reopen_check(d, u, now=NOW), [])      # 1. ok: bekle
        self.assertEqual(sorted(ws._quota_reopen_check(d, u, now=NOW)), ["default", "reviewer"])
        self.assertEqual(saved, [{"steward": {"enabled": "on"}}, {"stewards": {"reviewer": {"enabled": "on"}}}])
        self.assertEqual(ws._QUOTA["closed"], [])

    def test_cold_reopen_under_two_hours_sends_one_summary(self):
        """D17: kapanışla açılış arası < 2 sa ise tek özet bildirimi (soğuk açılış); 2 sa ve üstünde bildirim yok."""
        for gap, want in ((3600, 1), (7200, 0)):
            saved, *ps = self._setup()
            ws._QUOTA.update(closed_at=NOW - gap, ok_polls=0)
            msgs = []
            ps.append(mock.patch.object(ws, "notify_phone", lambda m, *a, **k: msgs.append(m) or True))
            for p in ps:
                p.start()
            try:
                d, u = types.SimpleNamespace(action="ok"), types.SimpleNamespace(week_pct=9.0)
                ws._quota_reopen_check(d, u, now=NOW)
                ws._quota_reopen_check(d, u, now=NOW)
            finally:
                for p in reversed(ps):      # aynı öznitelik iki kez yamalı: ters sırada durdur, yoksa sahte kalır
                    p.stop()
            self.assertEqual(len([m for m in msgs if "soğuk açılış" in m]), want, gap)

    def test_not_ok_resets_streak_and_keeps_list(self):
        saved, *ps = self._setup()
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        u = types.SimpleNamespace(week_pct=96.0)
        ws._quota_reopen_check(types.SimpleNamespace(action="ok"), u, now=NOW)
        ws._quota_reopen_check(types.SimpleNamespace(action="drain"), u, now=NOW)
        self.assertEqual(ws._QUOTA["ok_polls"], 0)
        self.assertEqual(ws._QUOTA["closed"], ["default", "reviewer"])
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
