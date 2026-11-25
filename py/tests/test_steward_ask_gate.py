"""ASK kapısı A (25 Kas 2026, direktif e30d51b17d2b): beyin STEWARD-ASK sorularını da görür; cevabı `register_answer_gate`
kancasından geçer. `ask_gate=off` (varsayılan) iken davranış eskisiyle aynıdır. Sahibe ait sınıflar beyne hiç gitmez."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import extensions, settings, steward as sw, steward_ask as sa  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

ALLOW = {"allow": True, "agree": True, "confidence": 0.9, "risk": "routine", "predicted": "ikisi de"}


def _q(text="Bölümleri sırayla mı yazayım?", project="p", **kw):
    return sw.Question(id=kw.pop("id", "q1"), project=project, text=text, created_at=kw.pop("created_at", time.time()), **kw)


class OwnerClassTest(unittest.TestCase):
    def test_plain_process_question_is_eligible(self):
        self.assertEqual(sa.owner_class(_q()), "")

    def test_owner_only_classes(self):
        cases = {
            "credentials": ["Siteye giriş yapar mısın?", "API anahtarı gerekiyor, verir misin?", "Please log in to the portal"],
            "spend": ["Bu iş için 20 USD kredi harcansın mı?", "Ücretli plana geçelim mi?", "Should we buy the license?"],
            "destructive": ["Eski veriler silinsin mi?", "force-push yapayım mı?", "sudo ile paket kurayım mı?"],
            "external": ["HF formunu dolduralım mı?", "Makale arXiv'e gönderilsin mi?", "Başvuruyu yollayayım mı?",
                         "E-posta ile yazara soralım mı?", "Should I publish the release?"],
            "owner_hands": ["Maya ekranını telefonda dener misin?", "Taslağı okuyup onaylar mısın?"],
        }
        for cls, texts in cases.items():
            for t in texts:
                self.assertTrue(sa.owner_class(_q(t)), f"{cls}: {t}")

    def test_scans_options_detail_and_previous_texts(self):
        self.assertTrue(sa.owner_class(_q(options=["sil", "tut"])))
        self.assertTrue(sa.owner_class(_q(detail="Bu seçenek 40 USD harcar.")))
        self.assertTrue(sa.owner_class(_q(prev_texts=["Parola gerekiyor"])))

    def test_structural_classes(self):
        self.assertTrue(sa.owner_class(_q(project="")))
        for src in ("reviewer-where", "upper_model", "dry-report", "job-red"):
            self.assertTrue(sa.owner_class(_q(source=src)), src)
        self.assertTrue(sa.owner_class(_q(extra_texts=["bir de şu"])))
        self.assertTrue(sa.owner_class(_q(deferred_until=time.time() + 60)))
        self.assertTrue(sa.owner_class(_q(sw.JOB_REQUEST_PREFIX + "ocr x")))

    def test_owner_projects_setting_and_project_note(self):
        self.assertTrue(sa.owner_class(_q(project="runikppr"), owner_projects="x, runikppr"))
        self.assertTrue(sa.owner_class(_q(), note="Yönteme dokunmadan önce sahibe sor."))
        self.assertEqual(sa.owner_class(_q(), owner_projects="runikppr", note="normal"), "")


class _Gate(_Tmp):
    def setUp(self):
        super().setUp()
        sw.upsert_project("p", cwd="/tmp/p", phase="planned")
        saved = extensions.answer_gate()
        self.addCleanup(extensions.set_answer_gate, saved)
        extensions.set_answer_gate(None)
        self.sent = []
        pn = mock.patch.object(ws, "_notify", lambda cfg, msg, *a, **k: self.sent.append(msg) or True)
        pn.start()
        self.addCleanup(pn.stop)
        pp = mock.patch.object(ws, "_persist_if_due", lambda q, sid: {})
        pp.start()
        self.addCleanup(pp.stop)
        self.calls = []

    def _mode(self, mode):
        settings.save_settings({"steward": {"ask_gate": mode}})

    def _hook(self, reply):
        def gate(payload):
            self.calls.append(payload)
            if isinstance(reply, Exception):
                raise reply
            return dict(reply)
        extensions.ExtensionAPI().register_answer_gate(gate)

    def _brain(self, q, answer="sırayla"):
        return ws.http_answer({"id": q.id, "answer": answer, "actor": "brain"})

    def _ask(self, text="Bölümleri sırayla mı yazayım?"):
        return sw.add_question("p", text, source="p20261125")


class ConfigTest(_Gate):
    def test_defaults_and_validation(self):
        cfg = settings.steward_config()
        self.assertEqual((cfg.ask_gate, cfg.ask_gate_threshold, cfg.ask_gate_owner_projects), ("off", 0.7, ""))
        self._mode("bogus")
        self.assertEqual(settings.steward_config().ask_gate, "off")
        self.assertTrue(ws.http_config({"key": "ask_gate", "value": "shadow"})["ok"])
        self.assertEqual(settings.steward_config().ask_gate, "shadow")
        self.assertFalse(ws.http_config({"key": "ask_gate", "value": "maybe"})["ok"])


class AnswerPathTest(_Gate):
    def test_off_is_unchanged_owner_only_and_hook_not_called(self):
        self._hook(ALLOW)
        q = self._ask()
        r = self._brain(q)
        self.assertEqual((r["ok"], r["code"]), (False, "owner_only"))
        self.assertEqual(self.calls, [])
        self.assertIn(q.id, sw.load_state()["brain_denied"])

    def test_on_allowed_closes_question_with_brain_prefix(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask()
        self.assertTrue(self._brain(q)["ok"])
        got = sw.find_question(q.id)
        self.assertEqual((got.status, got.answered_by), ("answered", "brain"))
        self.assertEqual(got.answer, sw.BRAIN_ASK_PREFIX + "sırayla")
        self.assertEqual(self.calls[0]["question"]["id"], q.id)
        self.assertEqual(self.calls[0]["answer"], "sırayla")

    def test_on_denied_keeps_open_notifies_once_and_calls_gate_once(self):
        self._mode("on")
        self._hook(dict(ALLOW, allow=False, agree=False, predicted="paralel"))
        q = self._ask()
        self.assertEqual(self._brain(q)["code"], "gate_denied")
        self.assertEqual(self._brain(q, "paralel")["code"], "gate_denied")      # uyana kadar yeniden deneyemez
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sw.find_question(q.id).status, "open")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("paralel", self.sent[0])
        self.assertIn(q.id, self.sent[0])
        self.assertIn(q.id, sw.load_state()["brain_denied"])

    def test_core_rechecks_the_three_conditions(self):
        self._mode("on")
        for i, bad in enumerate(({"agree": False}, {"confidence": 0.69}, {"risk": "high"}, {"confidence": "x"})):
            self._hook(dict(ALLOW, **bad))
            sw.upsert_project(f"p{i}", cwd="/tmp/p", phase="planned")
            q = sw.add_question(f"p{i}", f"Konu{i} hangi biçimde yazılsın?", source=f"s{i}")
            self.assertFalse(self._brain(q)["ok"], bad)
            self.assertEqual(sw.find_question(q.id).status, "open")

    def test_missing_or_failing_hook_fails_closed(self):
        self._mode("on")
        q = self._ask()
        self.assertEqual(self._brain(q)["code"], "gate_denied")
        self._hook(RuntimeError("x"))
        q2 = sw.add_question("p", "Tablo biçimi nasıl olsun acaba?", source="other")
        self.assertEqual(self._brain(q2)["code"], "gate_denied")
        self.assertEqual(sw.find_question(q2.id).status, "open")

    def test_shadow_records_only(self):
        self._mode("shadow")
        self._hook(ALLOW)
        q = self._ask()
        r = self._brain(q)
        self.assertEqual((r["ok"], r["shadow"]), (True, True))
        self.assertEqual(sw.find_question(q.id).status, "open")
        self.assertEqual(self.sent, [])
        self.assertNotIn(q.id, sw.load_state().get("brain_denied") or {})
        ev = [e for e in sw.log_entries_for_date(time.strftime("%Y-%m-%d")) if e.get("event") == "ask_gate"]
        self.assertEqual((ev[0]["id"], ev[0]["mode"], ev[0]["applied"], ev[0]["allow"]), (q.id, "shadow", False, True))

    def test_panic_turns_on_into_shadow(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask()
        with mock.patch.object(sw, "panic_active", lambda: True):
            self.assertTrue(self._brain(q)["shadow"])
        self.assertEqual(sw.find_question(q.id).status, "open")

    def test_owner_class_never_reaches_gate(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask("Eski çıktılar silinsin mi?")
        self.assertEqual(self._brain(q)["code"], "owner_only")
        self.assertEqual(self.calls, [])

    def test_brain_cannot_defer_owner_question(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask()
        self.assertFalse(self._brain(q, "sonra")["ok"])
        self.assertEqual(sw.find_question(q.id).deferred_until, 0.0)
        self.assertEqual(self.calls, [])

    def test_owner_answer_in_between_is_not_overwritten(self):
        self._mode("on")
        q = self._ask()

        def gate(payload):
            sw.answer_question(q.id, "paralel", by="owner_phone")      # sahip kapı çalışırken cevapladı
            return dict(ALLOW)
        extensions.set_answer_gate(gate)
        self.assertEqual(self._brain(q)["code"], "already_answered")
        got = sw.find_question(q.id)
        self.assertEqual((got.answer, got.answered_by), ("paralel", "owner_phone"))

    def test_answered_question_is_refused_without_gate_call(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask()
        sw.answer_question(q.id, "paralel", by="owner_phone")
        self.assertEqual(self._brain(q)["code"], "already_answered")
        self.assertEqual(self.calls, [])


class TourTest(_Gate):
    def _items(self, mode, state=None, now=None):
        cfg = sw.Config(ask_gate=mode)
        return sw.review_items([], sw.load_projects(), cfg, now or time.time(), sw.load_questions(), [], state=state or {})

    def test_off_has_no_ask_items(self):
        self._ask()
        self.assertEqual(self._items("off"), [])

    def test_eligible_ask_listed_owner_class_not(self):
        q = self._ask()
        sw.add_question("p", "Parola gerekiyor, girer misin?", source="z")
        items = self._items("shadow")
        self.assertEqual([(i["kind"], i["id"], i["name"]) for i in items], [("ask", q.id, "p")])

    def test_seen_limits_and_gated(self):
        q = self._ask()
        now = time.time()
        recent = {"ask_seen": {q.id: {"n": 1, "at": now - 60}}}
        self.assertEqual(self._items("on", recent, now), [])
        later = {"ask_seen": {q.id: {"n": 1, "at": now - 1801}}}
        self.assertEqual(len(self._items("on", later, now)), 1)
        self.assertEqual(self._items("on", {"ask_seen": {q.id: {"n": 2, "at": 0}}}, now), [])
        self.assertEqual(self._items("on", {"ask_gated": {q.id: now}}, now), [])

    def test_tour_prompt_mentions_ask_item(self):
        q = sw.add_question("p", "Hangi biçim?", source="s", options=["a", "b"])
        text = sw.build_tour_prompt(self._items("on"), lang="tr")
        self.assertIn("SAHİP SORUSU", text)
        self.assertIn(q.id, text)
        self.assertIn("a | b", text)

    def test_cut_question_items_16_others_8(self):
        items = [{"kind": "idle", "name": f"i{n}"} for n in range(12)] + \
                [{"kind": "ask", "id": f"a{n}"} for n in range(20)] + [{"kind": "routine", "id": "r"}]
        cut = sw.cut_tour_items(items, "on")
        kinds = [i["kind"] for i in cut]
        self.assertEqual((kinds.count("routine"), kinds.count("ask"), kinds.count("idle")), (1, 15, 8))
        self.assertEqual(kinds[0], "routine")
        off = sw.cut_tour_items([i for i in items if i["kind"] != "ask"], "off")
        self.assertEqual(len(off), sw.TOUR_MAX_ITEMS)

    def test_plan_tick_sends_ask_and_records_seen(self):
        q = self._ask()
        q_old = sw.load_questions()
        cfg = sw.Config(enabled=True, ask_gate="shadow", mode="act", auto_start=False)
        brain = sw.SessionView(name=cfg.brain_name, running=True, busy=False)
        now = time.time()
        actions, st = sw.plan_tick([brain], sw.load_projects(), {"last_tour": now - 120}, cfg, now, q_old, [])[:2]
        tours = [a for a in actions if a.kind == "tour"]
        self.assertEqual([i["id"] for i in tours[0].payload["items"] if i["kind"] == "ask"], [q.id])
        self.assertEqual(st["ask_seen"][q.id]["n"], 1)


class DecisionsAndSummaryTest(_Gate):
    def test_owner_decisions_appended_to_brain_claude_md(self):
        cfg = settings.steward_config()
        before = Path(ws.ensure_workspace(cfg)).read_text(encoding="utf-8")
        self.assertNotIn("Sahibin güncel kalıcı kararları", before)
        with open(sa.decisions_path(), "w", encoding="utf-8") as f:
            f.write("- Kurum verisi kullanılabilir.\n" + "x" * 9000)
        after = Path(ws.ensure_workspace(cfg)).read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before.rstrip()))
        self.assertIn("Sahibin güncel kalıcı kararları", after)
        self.assertIn("Kurum verisi kullanılabilir.", after)
        self.assertLess(len(after) - len(before), 8200)

    def test_summary_lists_brain_answers_override_and_shadow(self):
        self._mode("on")
        self._hook(ALLOW)
        q = self._ask()
        self._brain(q)
        sw.answer_question(q.id, "paralel", by="owner_cli")
        self._mode("shadow")
        q2 = sw.add_question("p", "Kapak rengi hangisi olsun dersin?", source="k")
        self._brain(q2, "mavi")
        text = sw.summary_text(lang="tr")
        self.assertIn("beyin sahip adına", text)
        self.assertIn(q.id, text)
        self.assertIn("sahip ezdi", text)
        self.assertIn("gölge 1", text)


if __name__ == "__main__":
    unittest.main()
