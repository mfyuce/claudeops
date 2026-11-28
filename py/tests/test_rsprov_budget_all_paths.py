"""TBD#429 (sahip (a), 28 Kas): inceleme API bütçe denetimi (`anthropic_filter`: bütçe doldu ya da harcama sayılamıyor,
TBD#422) üç yolda da uygulanır: yuvalı otomatik tur (zaten), TEK yuvalı otomatik tur ve elle koşu (`manual_run`; bütçe
dolunca reddedilir). Tek yuvalı turda `review_anthropic_projects` dışındaki proje de anthropic hedefiyle koşmaz.
Sahte koşucu (`_Tick`), gerçek süreç/API YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_web_review_tick import _Tick, NOW, T1  # noqa: E402
from claudeops import review as rv, settings  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

AN = rv.ReviewTarget("anthropic", "claude-haiku-5-5", "claude-haiku-5-5", "low")


class _Budget(_Tick):
    def setUp(self):
        super().setUp()
        self.spend = (0.0, "")
        settings.save_settings({"stewards": {"rev": {"review_anthropic_projects": "a",
                                                     "review_anthropic_budget_usd": "100"}}})
        p = mock.patch.object(rv, "_anthropic_spend", lambda reviews: self.spend)
        p.start()
        self.addCleanup(p.stop)
        self.targets = [AN]


class SingleSlotTickTest(_Budget):
    def test_budget_reached_starts_nothing(self):
        self.own("a")
        self.spend = (150.0, "")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(self.started, [])

    def test_uncountable_spend_starts_nothing(self):
        self.own("a")
        self.spend = (0.0, "okunamadı")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(self.started, [])

    def test_other_modes_still_run_when_budget_is_reached(self):
        self.own("a")
        self.spend = (150.0, "")
        self.targets = [AN, T1]
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual([k.split("/")[0] for _p, k in self.started], [T1.mode])

    def test_project_outside_the_allow_list_is_not_run(self):
        self.own("b")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(self.started, [])

    def test_allowed_project_under_budget_runs(self):
        self.own("a")
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual([p for p, _k in self.started], ["a"])


class ManualRunTest(_Budget):
    def test_explicit_target_refused_when_budget_is_reached(self):
        self.own("a")
        self.spend = (150.0, "")
        with mock.patch.object(wr, "prepare_project", return_value=(True, "")):
            res = wr.manual_run(self.cfg(), "a", AN.mode, AN.model + "@" + AN.effort)
        self.assertFalse(res["ok"])
        self.assertIn("budget", res["error"])
        self.assertEqual(self.started, [])

    def test_explicit_target_refused_when_spend_is_uncountable(self):
        self.own("a")
        self.spend = (0.0, "okunamadı")
        with mock.patch.object(wr, "prepare_project", return_value=(True, "")):
            res = wr.manual_run(self.cfg(), "a", AN.mode, AN.model + "@" + AN.effort)
        self.assertFalse(res["ok"])
        self.assertEqual(self.started, [])

    def test_picked_target_skips_anthropic_when_budget_is_reached(self):
        self.own("a")
        self.spend = (150.0, "")
        self.targets = [AN, T1]
        with mock.patch.object(wr, "prepare_project", return_value=(True, "")):
            res = wr.manual_run(self.cfg(), "a")
        self.assertTrue(res["ok"], res)
        self.assertEqual([k.split("/")[0] for _p, k in self.started], [T1.mode])

    def test_under_budget_runs(self):
        self.own("a")
        with mock.patch.object(wr, "prepare_project", return_value=(True, "")):
            res = wr.manual_run(self.cfg(), "a", AN.mode, AN.model + "@" + AN.effort)
        self.assertTrue(res["ok"], res)
        self.assertEqual([p for p, _k in self.started], ["a"])


if __name__ == "__main__":
    unittest.main()
