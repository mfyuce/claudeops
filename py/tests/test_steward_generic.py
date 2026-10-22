"""generic değnekçi rolü (TODO 2026-10-22 (20)): normal kimlik (kendi projects.json'u, motor/beyin/kart/tur aynı) +
Sonnet medium varsayılanı + dinamik proje ekle/çıkar + tur maddesine otonom/karar-gerekir iş listesi + beynin üst model
(Opus/Fable, high/xhigh/max) isteğine sahibin onay kapısı.

Canlı servis/tmux/ağ/gerçek `~/.claude/claudeops/` YOK (`_Engine` = `_Tmp` + sahte oturum geri çağrıları; spawn_session
AssertionError'a bağlı, `_give_directive`/`_notify`/`_send` sahte).
Çalıştırma: python3 -m unittest discover -s py/tests"""
import dataclasses
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine  # noqa: E402
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cmd  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class _Generic(NoRealReviewMixin, _Engine):
    def setUp(self):
        super().setUp()
        settings.save_settings({
            "steward": {"enabled": "on", "mode": "act", "card_refresh": "off", "planned_model": "claude-opus-5-5",
                        "planned_effort": "high"},
            "stewards": {"gen": {"enabled": "on", "mode": "act", "role": "generic"},
                         "kitap": {"enabled": "on", "mode": "act"}}})
        os.makedirs(sw.paths_for("gen").root, exist_ok=True)
        sw.upsert_project("p", paths="gen", phase="planned")
        self.directives = []
        self.notified = []
        for p in (mock.patch.object(ws, "_give_directive",
                                    lambda proj, text, **kw: self.directives.append((proj.name, text, kw.get("model"),
                                                                                     kw.get("effort"))) or {"ok": True}),
                  mock.patch.object(ws, "_brain_directive_defer", lambda name, sid: None),
                  mock.patch.object(ws, "_notify", lambda cfg, body, click="": self.notified.append(body) or False)):
            p.start()
            self.addCleanup(p.stop)


class TestConfig(_Generic):
    def test_generic_defaults_to_sonnet_medium(self):
        cfg = settings.steward_config("gen")
        self.assertEqual(cfg.role, "generic")
        self.assertEqual((cfg.planning_model, cfg.planning_effort, cfg.planned_model, cfg.planned_effort),
                         (sw.GENERIC_MODEL, "medium", sw.GENERIC_MODEL, "medium"))
        self.assertEqual(sw.phase_model_effort(sw.load_projects("gen")["p"], cfg), (sw.GENERIC_MODEL, "medium"))
        # sıradan kimlik değişmedi (faz alanlarını `steward` bloğundan zaten miras almaz)
        k = settings.steward_config("kitap")
        self.assertEqual((k.role, k.planned_model, k.planned_effort), ("steward", "", ""))

    def test_own_block_is_the_owners_explicit_choice(self):
        settings.save_settings({"stewards": {"gen": {"planned_model": "claude-opus-5-5", "planned_effort": "high"}}})
        cfg = settings.steward_config("gen")
        self.assertEqual((cfg.planned_model, cfg.planned_effort), ("claude-opus-5-5", "high"))
        self.assertEqual(cfg.planning_model, sw.GENERIC_MODEL)

    def test_default_can_never_be_generic(self):
        settings.save_settings({"steward": {"role": "generic"}})
        self.assertEqual(settings.steward_config("default").role, "steward")


class TestCreate(NoRealReviewMixin, _Engine):
    def test_http_create_with_role_generic(self):
        r = ws.http_identity_create({"target": "genel", "role": "generic"})
        self.assertEqual(r, {"ok": True, "id": "genel", "role": "generic"})
        cfg = settings.steward_config("genel")
        self.assertEqual((cfg.role, cfg.enabled, cfg.mode), ("generic", False, "observe"))
        self.assertEqual(ws.http_identity_create({"target": "xx", "role": "boss"})["ok"], False)
        self.assertFalse(ws.http_identity_create({"target": "yy", "role": "generic", "actor": "brain"})["ok"])

    def test_cli_create_with_role_generic(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cmd.cmd_create(NS(target_sid="genel", label="G", role="generic")), 0)
        self.assertEqual(settings.load_settings()["stewards"]["genel"]["role"], "generic")

    def test_list_row_carries_role_generic(self):
        settings.save_settings({"stewards": {"gen": {"role": "generic"}}})
        rows = {r["id"]: r for r in ws.stewards_summary(running_names=set())}
        self.assertEqual(rows["gen"].get("role"), "generic")
        self.assertNotIn("role", rows["default"])


class TestBrainMd(unittest.TestCase):
    def test_generic_section_only_for_generic(self):
        for lang in ("tr", "en"):
            base = sw.build_workspace_claude_md("P", lang=lang, sid="gen", label="G")
            self.assertEqual(base, sw.build_workspace_claude_md("P", lang=lang, sid="gen", label="G", role="steward"))
            self.assertEqual(base, sw.build_workspace_claude_md("P", lang=lang, sid="gen", label="G", role="reviewer"))
            gen = sw.build_workspace_claude_md("P", lang=lang, sid="gen", label="G", role="generic")
            rule = sw.GENERIC_RULE_TR if lang == "tr" else sw.GENERIC_RULE_EN
            self.assertIn(rule, gen)
            self.assertEqual(gen.replace(rule, "", 1), base)
            self.assertIn("upper_model_needs_approval", gen)
            # bölüm model kuralından SONRA, hafızadan ÖNCE
            mr = sw.MODEL_RULE_TR if lang == "tr" else sw.MODEL_RULE_EN
            mem = sw.MEMORY_TR if lang == "tr" else sw.MEMORY_EN
            self.assertLess(gen.index(mr), gen.index(rule))
            self.assertLess(gen.index(rule), gen.index(mem))

    def test_ensure_workspace_writes_generic_section(self):
        class T(_Generic):
            def runTest(self_inner):
                pass
        t = T()
        t.setUp()
        try:
            path = ws.ensure_workspace(settings.steward_config("gen"))
            with open(path, encoding="utf-8") as f:
                self.assertIn(sw.GENERIC_RULE_TR, f.read())
            path = ws.ensure_workspace(settings.steward_config("kitap"))
            with open(path, encoding="utf-8") as f:
                self.assertNotIn(sw.GENERIC_RULE_TR, f.read())
        finally:
            t.doCleanups()


class TestBacklog(unittest.TestCase):
    TODO = ("# TODO\n- [ ] testleri hızlandır\n- [x] eski iş\n- ~~iptal~~\n* yeni sürümü push et\n"
            "1. README örneğini düzelt\nserbest paragraf satırı\n")
    TBD = ("# TBD\n- TBD#3 cache stratejisi? A/B\n- TBD#4 log biçimi. Karar: JSON satırı\n"
           "- TBD#5 eski dalı sil. Karar: evet\n")

    def test_classification(self):
        bl = sw.generic_backlog(self.TODO, self.TBD, {"open_tbds": ["TBD#9 lisans seçimi"]})
        self.assertEqual(bl["auto"], ["testleri hızlandır", "README örneğini düzelt", "TBD#4 log biçimi. Karar: JSON satırı"])
        self.assertEqual(bl["decide"], ["yeni sürümü push et", "TBD#3 cache stratejisi? A/B",
                                        "TBD#5 eski dalı sil. Karar: evet", "TBD#9 lisans seçimi"])

    def test_empty_and_dedup_and_cap(self):
        self.assertEqual(sw.generic_backlog(), {"auto": [], "decide": []})
        many = "\n".join(f"- iş {i}" for i in range(20)) + "\n- iş 1\n"
        bl = sw.generic_backlog(many)
        self.assertEqual(len(bl["auto"]), sw.GENERIC_BACKLOG_ITEMS)
        bl = sw.generic_backlog("", "TBD#1 x", {"open_tbds": ["TBD#1 x"]})
        self.assertEqual(bl["decide"], ["TBD#1 x"])

    def test_tour_prompt_renders_backlog_only_when_present(self):
        it = {"kind": "idle", "name": "p", "phase": "planned"}
        plain = sw.build_tour_prompt([dict(it)], "tr", now=0)
        self.assertNotIn("otonom ilerletilebilir", plain)
        t = sw.build_tour_prompt([dict(it, backlog={"auto": ["A1"], "decide": ["D1"]})], "tr", now=0)
        self.assertIn("otonom ilerletilebilir (sahibin cevabı gerekmez): A1", t)
        self.assertIn("karar gerekir (ATLA", t)
        self.assertIn("D1", t)
        e = sw.build_tour_prompt([dict(it, backlog={"auto": [], "decide": ["D1"]})], "en", now=0)
        self.assertNotIn("autonomous (", e)
        self.assertIn("needs a decision (SKIP", e)


class TestUpperTier(unittest.TestCase):
    def test_is_upper_tier(self):
        for m, e in (("claude-opus-5-5", ""), ("claude-fable-5-1", "medium"), ("", "high"), ("x", "XHIGH"), ("", "max")):
            self.assertTrue(sw.is_upper_tier(m, e), (m, e))
        for m, e in (("", ""), ("claude-sonnet-5-5", "medium"), ("claude-haiku-5-5", "low")):
            self.assertFalse(sw.is_upper_tier(m, e), (m, e))

    def test_approval_is_specific_to_project_model_effort(self):
        q = sw.Question(id="q1", project="", text=sw.upper_tier_question_text("p", "claude-opus-5-5", "high"),
                        created_at=0, status="answered", answer="onayla", source=sw.UPPER_MODEL_SOURCE)
        self.assertTrue(sw.upper_tier_approved([q], "p", "claude-opus-5-5", "high"))
        self.assertFalse(sw.upper_tier_approved([q], "p", "claude-fable-5-1", "high"))
        self.assertFalse(sw.upper_tier_approved([q], "r", "claude-opus-5-5", "high"))
        self.assertFalse(sw.upper_tier_approved([dataclasses.replace(q, answer="reddet")], "p", "claude-opus-5-5", "high"))
        self.assertFalse(sw.upper_tier_approved([dataclasses.replace(q, status="open")], "p", "claude-opus-5-5", "high"))
        self.assertFalse(sw.upper_tier_approved([dataclasses.replace(q, source="brain")], "p", "claude-opus-5-5", "high"))


class TestUpperGate(_Generic):
    def _qs(self):
        return [q for q in sw.load_questions("gen") if q.source == sw.UPPER_MODEL_SOURCE]

    def test_brain_directive_to_opus_refused_and_question_opened_once(self):
        body = {"name": "p", "text": "yaz", "model": "claude-opus-5-5", "effort": "high", "actor": "brain"}
        r = ws.http_directive(dict(body), "gen")
        self.assertEqual(r["code"], "upper_model_needs_approval")
        self.assertEqual(self.directives, [])
        qs = self._qs()
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].project, "")             # proje oturumuna iletilmez / oturum başlatmaz (beyin turunda görünür)
        self.assertIn(sw.upper_tier_tag("p", "claude-opus-5-5", "high"), qs[0].text)
        self.assertEqual(qs[0].options, ["onayla", "reddet"])
        self.assertFalse(qs[0].routine)
        ok, _ = sw.brain_may_answer(qs[0])
        self.assertFalse(ok)                            # beyin kendi onayını veremez
        self.assertEqual(ws.http_directive(dict(body), "gen")["question"], qs[0].id)
        self.assertEqual(len(self._qs()), 1)
        self.assertTrue(any(e["event"] == "upper_model_denied" for e in sw.tail_log(20, "gen")))
        # model vermeden (Sonnet medium) aynı iş sürer
        self.assertTrue(ws.http_directive({"name": "p", "text": "yaz", "actor": "brain"}, "gen")["ok"])
        self.assertEqual(self.directives, [("p", "yaz", "", "")])

    def test_owner_approval_opens_the_gate(self):
        body = {"name": "p", "text": "yaz", "model": "claude-opus-5-5", "effort": "high", "actor": "brain"}
        qid = ws.http_directive(dict(body), "gen")["question"]
        sw.answer_question(qid, "1", "gen")             # seçenek 1 = onayla
        self.assertTrue(ws.http_directive(dict(body), "gen")["ok"])
        self.assertEqual(self.directives, [("p", "yaz", "claude-opus-5-5", "high")])
        # başka model hâlâ kapalı
        self.assertFalse(ws.http_directive(dict(body, model="claude-fable-5-1"), "gen")["ok"])

    def test_owner_rejection_keeps_it_closed(self):
        body = {"name": "p", "text": "yaz", "effort": "max", "actor": "brain"}
        qid = ws.http_directive(dict(body), "gen")["question"]
        sw.answer_question(qid, "reddet", "gen")
        r = ws.http_directive(dict(body), "gen")
        self.assertFalse(r["ok"])
        self.assertIn("rejected", r["error"])

    def test_human_and_non_generic_are_free(self):
        self.assertTrue(ws.http_directive({"name": "p", "text": "t", "model": "claude-fable-5-1", "effort": "high"}, "gen")["ok"])
        sw.upsert_project("k", paths="kitap", phase="planned")
        self.assertTrue(ws.http_directive({"name": "k", "text": "t", "model": "claude-opus-5-5", "actor": "brain"}, "kitap")["ok"])
        self.assertEqual(self._qs(), [])

    def test_restart_refused_before_stop(self):
        with mock.patch.object(ws, "_running", lambda name: NS(name=name, cli="claude", pid=1)):
            r = ws.http_restart({"name": "p", "text": "d", "model": "claude-opus-5-5", "actor": "brain"}, "gen")
        self.assertEqual(r["code"], "upper_model_needs_approval")
        self.assertNotIn(("stop", "p"), self.calls)

    def test_set_project_gate(self):
        r = ws.http_project_upsert({"name": "p", "model": "claude-fable-5-1", "actor": "brain"}, "gen")
        self.assertEqual(r["code"], "upper_model_needs_approval")
        self.assertEqual(sw.load_projects("gen")["p"].model, "")
        self.assertFalse(ws.http_project_upsert({"name": "p", "effort": "high", "actor": "brain"}, "gen")["ok"])
        self.assertTrue(ws.http_project_upsert({"name": "p", "model": sw.GENERIC_MODEL, "effort": "medium",
                                                "actor": "brain"}, "gen")["ok"])
        # sahip (insan) üst modeli serbestçe verir; beyin sonra not yazarken bu değeri bozmaz
        self.assertTrue(ws.http_project_upsert({"name": "p", "model": "claude-opus-5-5"}, "gen")["ok"])
        self.assertTrue(ws.http_project_upsert({"name": "p", "notes": "n", "actor": "brain"}, "gen")["ok"])
        self.assertEqual(sw.load_projects("gen")["p"].model, "claude-opus-5-5")

    def test_register_gate_before_side_effects(self):
        cwd = os.path.join(self.dir.name, "yeni")
        r = ws.http_register({"name": "yeni", "cwd": cwd, "goal": "g", "model": "claude-opus-5-5", "actor": "brain"}, "gen")
        self.assertEqual(r["code"], "upper_model_needs_approval")
        self.assertFalse(os.path.exists(cwd))
        self.assertNotIn(("register", "yeni"), self.calls)


class TestDynamicProjects(_Generic):
    def test_remove_is_human_only_and_logged(self):
        self.assertFalse(ws.http_project_remove({"name": "p", "actor": "brain"}, "gen")["ok"])
        self.assertIn("p", sw.load_projects("gen"))
        self.assertTrue(ws.http_project_remove({"name": "p"}, "gen")["ok"])
        self.assertNotIn("p", sw.load_projects("gen"))
        self.assertFalse(ws.http_project_remove({"name": "p"}, "gen")["ok"])
        self.assertTrue(any(e["event"] == "project_remove" for e in sw.tail_log(20, "gen")))

    def test_cli_drop(self):
        with mock.patch("builtins.print"):
            self.assertEqual(cmd.cmd_drop(NS(name="p", sid="gen")), 0)
            self.assertEqual(cmd.cmd_drop(NS(name="p", sid="gen")), 1)
        self.assertEqual(sw.load_projects("gen"), {})

    def test_panel_add_then_tick_treats_it_as_normal_project(self):
        self.assertTrue(ws.http_project_upsert({"name": "q", "phase": "planned"}, "gen")["ok"])
        self.assertEqual(sw.project_owner("q"), "gen")


class TestTourBacklog(_Generic):
    def _tour(self, sid):
        proj = os.path.join(self.dir.name, "proj")
        os.makedirs(proj, exist_ok=True)
        with open(os.path.join(proj, "TODO.md"), "w", encoding="utf-8") as f:
            f.write("- otonom iş\n- push et\n")
        with open(os.path.join(proj, "TOBEDECIDED.md"), "w", encoding="utf-8") as f:
            f.write("- TBD#1 hangi kütüphane?\n")
        sent = []
        with mock.patch.object(ws, "brain_start", lambda cfg=None, fresh=False: {"ok": True}), \
                mock.patch.object(ws, "_running", lambda name: NS(name=name, cli="claude", pid=1)), \
                mock.patch.object(ws, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(ws, "_enrich_item", lambda it, projects, world: dict(it)), \
                mock.patch.object(ws, "_project_cwd", lambda name: proj), \
                mock.patch.object(sw, "tour_delivery", lambda prompt, ws_, now, lang="tr": (prompt, "")), \
                mock.patch.object(ws, "_send", lambda name, cli, msg: sent.append(msg) or True):
            r = ws.run_tour([{"kind": "idle", "name": "p" if sid == "gen" else "k"}], cfg=settings.steward_config(sid))
        self.assertTrue(r["ok"], r)
        return sent[0]

    def test_generic_tour_item_has_backlog(self):
        msg = self._tour("gen")
        self.assertIn("otonom ilerletilebilir (sahibin cevabı gerekmez): otonom iş", msg)
        self.assertIn("push et", msg.split("karar gerekir", 1)[1])
        self.assertIn("TBD#1 hangi kütüphane?", msg)

    def test_plain_steward_tour_is_unchanged(self):
        sw.upsert_project("k", paths="kitap", phase="planned")
        self.assertNotIn("otonom ilerletilebilir", self._tour("kitap"))


if __name__ == "__main__":
    unittest.main()
