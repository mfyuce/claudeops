"""TODO 1233 (5): değnekçi denetimi "proje ANA oturumu fiilen Sonnet medium dışına çıktı mı" (canlı model/effort).

Kural (sahip): ana oturum HEP claude-sonnet-5-5 + medium; bilinçli ağır adımda geçici yükselme olabilir. Bu yüzden
denetim ZORLAMAZ: `upper_main` olayı loglanır + oturuma tek bir HATIRLATMA direktifi gider (kapatma/model değiştirme yok),
aynı oturum + aynı model/effort için tekrar etmez. Ayar `upper_main_warn` (varsayılan AÇIK, `off` ile kapanır).

Canlı servis/tmux/ağ YOK (`_Engine` sahte oturum geri çağrıları; `_give_directive` sahte).
Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TestPure(unittest.TestCase):
    def setUp(self):
        self.cfg = sw.Config()
        self.projects = {n: sw.Project(name=n, phase="planned") for n in ("a", "b", "c", "d", "e")}

    def test_picks_only_running_main_sessions_above_sonnet_medium(self):
        views = [
            _view("a", live_model="claude-opus-5-5", live_effort="medium"),          # model üst kademe
            _view("b", live_model="claude-sonnet-5-5", live_effort="high"),          # effort üst kademe
            _view("c", live_model="claude-sonnet-5-5", live_effort="medium"),        # kurala uygun
            _view("d", running=False, live_model="claude-opus-5-5"),                 # çalışmıyor
            _view("d_2", blueprint="d", live_model="claude-fable-5-1"),              # instance (ana oturum değil)
            _view("zz", live_model="claude-opus-5-5"),                               # kayıtlı proje değil
        ]
        got = [v.name for v in sw.upper_main_views(views, self.projects, self.cfg)]
        self.assertEqual(got, ["a", "b"])

    def test_owners_explicit_upper_choice_is_not_flagged(self):
        self.projects["e"] = sw.Project(name="e", phase="planned", model="claude-opus-5-5")
        views = [_view("e", live_model="claude-opus-5-5", live_effort="medium")]
        self.assertEqual(sw.upper_main_views(views, self.projects, self.cfg), [])
        cfg = sw.Config(planned_effort="high")      # kimliğin faz ayarı bilerek üst kademe
        views = [_view("a", live_model="claude-sonnet-5-5", live_effort="high")]
        self.assertEqual(sw.upper_main_views(views, self.projects, cfg), [])

    def test_reviewer_role_is_not_audited(self):
        views = [_view("a", live_model="claude-opus-5-5")]
        self.assertEqual(sw.upper_main_views(views, self.projects, sw.Config(role="reviewer")), [])

    def test_reminder_text_is_a_reminder_not_an_order(self):
        tr = sw.upper_main_text("a", "claude-opus-5-5", "high", "tr")
        en = sw.upper_main_text("a", "claude-opus-5-5", "high", "en")
        for t in (tr, en):
            self.assertIn("claude-opus-5-5", t)
            self.assertIn(sw.GENERIC_MODEL, t)
        self.assertIn("hatırlatma", tr.lower())
        self.assertIn("reminder", en.lower())


class _Tick(NoRealReviewMixin, _Engine):
    def setUp(self):
        super().setUp()
        ws._UPPER_MAIN_WARNED.clear()
        self.addCleanup(ws._UPPER_MAIN_WARNED.clear)
        self.settings()
        sw.upsert_project("a", phase="planned", cadence_minutes=10_000)
        self.directives = []
        p = mock.patch.object(ws, "_give_directive",
                              lambda proj, text, **kw: self.directives.append((proj.name, text, kw)) or {"ok": True})
        p.start()
        self.addCleanup(p.stop)

    def events(self):
        return [e for e in sw.tail_log(200) if e.get("event") == "upper_main"]

    def mine(self):
        return [d for d in self.directives if d[2].get("reason") == "upper_main"]


class TestTick(_Tick):
    def test_upper_main_logged_and_reminded_once(self):
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="high")]
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        e = self.events()[0]
        self.assertEqual((e["name"], e["model"], e["effort"]), ("a", "claude-opus-5-5", "high"))
        self.assertEqual(len(self.mine()), 1)
        name, text, kw = self.mine()[0]
        self.assertEqual(name, "a")
        self.assertFalse(kw.get("start_if_stopped"))
        self.assertEqual(kw.get("session_name"), "a")
        self.assertFalse(kw.get("model") or kw.get("effort"))       # model DEĞİŞTİRİLMEZ
        self.assertIn("claude-opus-5-5", text)
        ws.tick_once("timer")
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)                       # spam yok
        self.assertEqual(len(self.mine()), 1)
        self.assertFalse([c for c in self.calls if c[0] in ("stop", "handover")])

    def test_new_combo_or_back_and_up_again_warns_again(self):
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="medium")]
        ws.tick_once("timer")
        self.views = [_view("a", live_model="claude-fable-5-1", live_effort="medium")]
        ws.tick_once("timer")
        self.assertEqual(len(self.mine()), 2)
        self.views = [_view("a", live_model="claude-sonnet-5-5", live_effort="medium")]
        ws.tick_once("timer")
        self.views = [_view("a", live_model="claude-fable-5-1", live_effort="medium")]
        ws.tick_once("timer")
        self.assertEqual(len(self.mine()), 3)

    def test_busy_session_waits_until_idle(self):
        self.views = [_view("a", busy=True, live_model="claude-opus-5-5")]
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.mine(), [])
        self.views = [_view("a", busy=False, subagent_active=True, live_model="claude-opus-5-5")]
        ws.tick_once("timer")
        self.assertEqual(self.mine(), [])
        self.views = [_view("a", busy=False, live_model="claude-opus-5-5")]
        ws.tick_once("timer")
        self.assertEqual(len(self.mine()), 1)
        self.assertEqual(len(self.events()), 1)

    def test_failed_send_is_retried(self):
        self.views = [_view("a", live_model="claude-opus-5-5")]
        with mock.patch.object(ws, "_give_directive", lambda proj, text, **kw: {"ok": False, "error": "send failed"}):
            ws.tick_once("timer")
        self.assertEqual(self.mine(), [])
        ws.tick_once("timer")
        self.assertEqual(len(self.mine()), 1)

    def test_observe_mode_logs_only(self):
        self.settings(default={"mode": "observe"})
        self.views = [_view("a", live_model="claude-opus-5-5")]
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.mine(), [])

    def test_setting_off_disables(self):
        self.assertTrue(settings.steward_config().upper_main_warn)     # varsayılan AÇIK
        self.settings(default={"upper_main_warn": "off"})
        self.assertFalse(settings.steward_config().upper_main_warn)
        self.views = [_view("a", live_model="claude-opus-5-5")]
        ws.tick_once("timer")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.mine(), [])

    def test_sonnet_medium_main_is_silent(self):
        self.views = [_view("a", live_model="claude-sonnet-5-5", live_effort="medium")]
        ws.tick_once("timer")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.mine(), [])


class TestCollectViews(NoRealReviewMixin, _Engine):
    def test_status_row_live_values_reach_the_view(self):
        self.settings()
        ws.configure(status_payload=lambda: {"sessions": [
            {"name": "a", "running": True, "cwd": "/tmp/x", "cli": "claude", "model": "claude-sonnet-5-5",
             "live_model": "claude-opus-5-5", "live_effort": "high", "host": "local"}]})
        with mock.patch.object(ws, "find_sessions", lambda measure_cpu=False: []), \
                mock.patch.object(ws, "find_stuck", lambda live: []):
            views = _real_collect(settings.steward_config())
        v = [x for x in views if x.name == "a"][0]
        self.assertEqual((v.model, v.live_model, v.live_effort), ("claude-sonnet-5-5", "claude-opus-5-5", "high"))

    def test_remote_row_live_values_reach_the_view(self):
        v = ws._remote_view({"name": "a", "running": True, "live_model": "claude-fable-5-1", "live_effort": None},
                            "yuhem", 0.0)
        self.assertEqual((v.live_model, v.live_effort), ("claude-fable-5-1", ""))


_real_collect = ws._collect_views     # `_Engine` setUp'ı modül özniteliğini yamalamadan ÖNCE yakalanan gerçek işlev


if __name__ == "__main__":
    unittest.main()
