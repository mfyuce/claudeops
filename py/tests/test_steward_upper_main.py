"""TODO 1233 (5): değnekçi denetimi "proje ANA oturumu fiilen ana oturum varsayılanı dışına çıktı mı" (canlı model/effort).

Kural (sahip): ana oturum HEP `sw.GENERIC_MODEL` + medium (28 Kas 2026'dan beri claude-opus-5-5; önce Sonnet); bilinçli ağır adımda geçici yükselme olabilir. Bu yüzden
denetim ZORLAMAZ ve oturuma YAZMAZ: yalnız `upper_main` olayı loglanır (sahibe/panele görünür), kalıcı kayıtla
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

    def test_picks_only_running_main_sessions_above_main_default(self):
        views = [
            _view("a", live_model="claude-fable-5-1", live_effort="medium"),         # model üst kademe
            _view("b", live_model="claude-sonnet-5-5", live_effort="high"),          # effort üst kademe
            _view("c", live_model="claude-opus-5-5", live_effort="medium"),          # kurala uygun (ana oturum varsayılanı)
            _view("d", running=False, live_model="claude-fable-5-1"),                # çalışmıyor
            _view("d_2", blueprint="d", live_model="claude-fable-5-1"),              # instance (ana oturum değil)
            _view("zz", live_model="claude-fable-5-1"),                              # kayıtlı proje değil
        ]
        got = [v.name for v in sw.upper_main_views(views, self.projects, self.cfg)]
        self.assertEqual(got, ["a", "b"])

    def test_owners_explicit_upper_choice_is_not_flagged(self):
        self.projects["e"] = sw.Project(name="e", phase="planned", model="claude-fable-5-1")
        views = [_view("e", live_model="claude-fable-5-1", live_effort="medium")]
        self.assertEqual(sw.upper_main_views(views, self.projects, self.cfg), [])
        cfg = sw.Config(planned_effort="high")      # kimliğin faz ayarı bilerek üst kademe
        views = [_view("a", live_model="claude-sonnet-5-5", live_effort="high")]
        self.assertEqual(sw.upper_main_views(views, self.projects, cfg), [])

    def test_only_claude_family_models_are_audited(self):
        """Claude dışı model (ucli/evren deepseek vb.) effort high olsa da uyarılmaz; boş model de uyarılmaz."""
        cases = [
            ("deepseek-v4-flash", "high", False),
            ("claude-opus-5-5", "", False),           # 28 Kas 2026: Opus ana oturum varsayılanı, üst değil
            ("claude-opus-5-5", "medium", False),
            ("claude-opus-5-5", "high", True),
            ("claude-fable-5-1", "medium", True),
            ("claude-sonnet-5-5", "max", True),
            ("claude-sonnet-5-5", "medium", False),
            ("", "high", False),
            ("", "", False),
        ]
        for model, effort, flagged in cases:
            with self.subTest(model=model, effort=effort):
                views = [_view("a", live_model=model, live_effort=effort)]
                got = [v.name for v in sw.upper_main_views(views, self.projects, self.cfg)]
                self.assertEqual(got, ["a"] if flagged else [])

    def test_is_upper_tier_itself_stays_model_family_agnostic(self):
        # direktif kapısı (_upper_model_gate) bu davranışa dayanır; değişmemeli
        self.assertTrue(sw.is_upper_tier("deepseek-v4-flash", "high"))
        self.assertTrue(sw.is_upper_tier("", "high"))

    def test_opus_medium_is_the_main_default_not_upper(self):
        """Sahip kararı 28 Kas 2026: ana oturum Opus + medium; Opus artık üst kademe DEĞİL. Fable ve high/xhigh/max üst kalır."""
        self.assertEqual(sw.GENERIC_MODEL, "claude-opus-5-5")
        self.assertFalse(sw.is_upper_tier("claude-opus-5-5", "medium"))
        self.assertFalse(sw.is_upper_tier("claude-opus-5-5", ""))
        self.assertTrue(sw.is_upper_tier("claude-opus-5-5", "high"))
        self.assertTrue(sw.is_upper_tier("claude-fable-5-1", "medium"))
        views = [_view("a", live_model="claude-opus-5-5", live_effort="medium"),
                 _view("b", live_model="claude-fable-5-1", live_effort="medium"),
                 _view("c", live_model="claude-opus-5-5", live_effort="max")]
        self.assertEqual([v.name for v in sw.upper_main_views(views, self.projects, self.cfg)], ["b", "c"])
        for lang in ("tr", "en"):
            t = sw.upper_main_text("b", "claude-fable-5-1", "medium", lang)
            self.assertIn("`/model claude-opus-5-5`", t)
            self.assertNotIn("sonnet", t.lower())
            self.assertNotIn("Sonnet", sw.upper_tier_question_text("b", "claude-fable-5-1", "high", lang))

    def test_reviewer_role_is_not_audited(self):
        views = [_view("a", live_model="claude-fable-5-1")]
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
    """22 Kas dersi: oturum `/model`'i KENDİSİ değiştiremez; oturuma hatırlatma yollamak her seferinde ~160K bağlamlı boş bir tur
    yakıyordu (line: 24 saatte 16 kez). Denetim artık YALNIZ sahibe görünen `upper_main` olayı yazar (oturuma direktif YOK),
    kayıt kalıcıdır (state `upper_main_seen`), bilinmeyen model/effort okuması değişiklik sayılmaz."""

    def notified(self):
        """`upper_main` bildirim ÇAĞRISI sayısı (log_event'in 15 dk içerik tekilleştirmesinden bağımsız)."""
        real = sw.log_event
        calls = []
        def spy(ev, **kw):
            if ev == "upper_main":
                calls.append(kw.get("name"))
            return real(ev, **kw)
        p = mock.patch.object(ws.sw, "log_event", spy)
        p.start()
        self.addCleanup(p.stop)
        return calls

    def seen(self):
        return sw.load_state(sw.paths_for("default")).get("upper_main_seen") or {}

    def test_upper_main_logged_once_and_never_sent_to_the_session(self):
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="high")]
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        e = self.events()[0]
        self.assertEqual((e["name"], e["model"], e["effort"]), ("a", "claude-opus-5-5", "high"))
        ws.tick_once("timer")
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)                       # spam yok
        self.assertEqual(self.directives, [])                         # oturuma HİÇ direktif gitmez
        self.assertFalse([c for c in self.calls if c[0] in ("stop", "handover")])
        self.assertEqual(self.seen()["a"]["model"], "claude-opus-5-5")  # kalıcı (servis yeniden başlasa da yinelemez)

    def test_flapping_unknown_live_reading_is_not_a_change(self):
        # line vakası: canlı okuma sonnet/high <-> bilinmiyor arasında gidip geldi; her dönüşte yeniden uyarıldı
        for i in range(6):
            self.views = [_view("a", live_model="claude-sonnet-5-5", live_effort="high")] if i % 2 == 0 else \
                         [_view("a", live_model="", live_effort="")]
            ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.directives, [])

    def test_unknown_effort_on_known_upper_model_is_not_a_change(self):
        for eff in ("high", "", "high", ""):
            self.views = [_view("a", live_model="claude-opus-5-5", live_effort=eff)]
            ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)

    def test_known_change_or_back_and_up_again_logs_again(self):
        calls = self.notified()
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="high")]
        ws.tick_once("timer")
        self.views = [_view("a", live_model="claude-fable-5-1", live_effort="medium")]
        ws.tick_once("timer")
        self.assertEqual(len(calls), 2)
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="medium")]       # BİLİNEN uyumlu: kayıt düşer
        ws.tick_once("timer")
        self.assertNotIn("a", self.seen())
        self.views = [_view("a", live_model="claude-fable-5-1", live_effort="medium")]
        ws.tick_once("timer")
        self.assertEqual(len(calls), 3)

    def test_new_process_same_combo_logs_once_more(self):
        calls = self.notified()
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="high", started_at=1000.0)]
        ws.tick_once("timer")
        ws.tick_once("timer")
        self.views = [_view("a", live_model="claude-opus-5-5", live_effort="high", started_at=9000.0)]   # yeniden açıldı
        ws.tick_once("timer")
        ws.tick_once("timer")
        self.assertEqual(len(calls), 2)

    def test_observe_mode_logs_too(self):
        self.settings(default={"mode": "observe"})
        self.views = [_view("a", live_model="claude-fable-5-1")]
        ws.tick_once("timer")
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.directives, [])

    def test_setting_off_disables(self):
        self.assertTrue(settings.steward_config().upper_main_warn)     # varsayılan AÇIK
        self.settings(default={"upper_main_warn": "off"})
        self.assertFalse(settings.steward_config().upper_main_warn)
        self.views = [_view("a", live_model="claude-fable-5-1")]
        ws.tick_once("timer")
        self.assertEqual(self.events(), [])

    def test_opus_or_sonnet_medium_main_is_silent(self):
        for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            self.views = [_view("a", live_model=model, live_effort="medium")]
            ws.tick_once("timer")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.seen(), {})


class TestCollectViews(NoRealReviewMixin, _Engine):
    def test_status_row_live_values_reach_the_view(self):
        self.settings()
        ws.configure(status_payload=lambda: {"sessions": [
            {"name": "a", "running": True, "cwd": "/tmp/x", "cli": "claude", "model": "claude-sonnet-5-5",
             "live_model": "claude-opus-5-5", "live_effort": "high", "host": "local"}]})
        with mock.patch.object(ws, "find_sessions", lambda measure_cpu=False: []):
            views = _real_collect(settings.steward_config())
        v = [x for x in views if x.name == "a"][0]
        self.assertEqual((v.model, v.live_model, v.live_effort), ("claude-sonnet-5-5", "claude-opus-5-5", "high"))

    def test_dated_local_session_without_instance_resolves_to_its_project(self):
        # TODO 2026-10-28 (21): blueprint'siz tarihli yerel oturum ("a20261029") yönetilen ama "çalışmıyor" sayılıyordu
        self.settings()
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        ws.configure(status_payload=lambda: {"sessions": [
            {"name": "a20261029", "running": True, "cwd": "/tmp/x", "cli": "claude", "host": "local"},
            {"name": "ab20261029", "running": True, "cwd": "/tmp/y", "cli": "claude", "host": "local"}]})
        with mock.patch.object(ws, "find_sessions", lambda measure_cpu=False: []):
            views = _real_collect(settings.steward_config())
        got = {x.name: x.project for x in views}
        self.assertEqual(got["a20261029"], "a")                 # türetilmiş ad projeye çözülür
        self.assertEqual(got["ab20261029"], "ab20261029")        # salt önek komşusu başka projenin oturumu DEĞİL

    def test_remote_row_live_values_reach_the_view(self):
        v = ws._remote_view({"name": "a", "running": True, "live_model": "claude-fable-5-1", "live_effort": None},
                            "yuhem", 0.0)
        self.assertEqual((v.live_model, v.live_effort), ("claude-fable-5-1", ""))


_real_collect = ws._collect_views     # `_Engine` setUp'ı modül özniteliğini yamalamadan ÖNCE yakalanan gerçek işlev


if __name__ == "__main__":
    unittest.main()
