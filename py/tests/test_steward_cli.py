"""Çoklu değnekçi P6: CLI (`-s/COPS_STEWARD`, `list/create/remove/transfer`, kimlik başına `config`), ntfy (başlık/önek/topic),
`/q/<id>?k=&s=` kimlik taşıma, kimlik başına günlük özet + log sıkıştırma, `/api/steward/list` ve `stewards` dilimi.

Gerçek oturum/tmux/docker/ağ/servis YOK: `_Tmp` geçici dizin (settings + steward dizini), `notify_phone`/`urlopen`/`mcp_queue._api`/
`_project_running` sahte, bu dosyada hiçbir spawn yolu çağrılmaz (motor tick'i yok). Gerçek settings.json sha256'sı modül
başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cli, web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def setUpModule():
    global _HASH_BEFORE
    _HASH_BEFORE = _sha(_REAL_SETTINGS)


def tearDownModule():
    if _sha(_REAL_SETTINGS) != _HASH_BEFORE:
        raise AssertionError("gerçek ~/.claude/claudeops/settings.json test sırasında değişti")


class _Cli(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        ws.invalidate_summary()
        self.addCleanup(ws._reset_contexts)
        self.api_calls = []
        self.running = set()

        def fake_api(port, method, path, body=None):
            self.api_calls.append((method, path, body))
            return {"ok": True}

        for p in (mock.patch.object(cli.mcp_queue, "_api", fake_api),
                  mock.patch.object(cli, "_project_running", lambda name: name in self.running),
                  mock.patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(cli.ENV_STEWARD, None)

    def run_cli(self, *argv):
        ap = argparse.ArgumentParser()
        cli.register(ap.add_subparsers())
        args = ap.parse_args(["steward", *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = args.func(args)
        return rc, out.getvalue()

    def make(self, sid="kitap", **extra):
        settings.save_settings({"stewards": {sid: dict({"label": "Kitaplar", "enabled": "off", "mode": "observe"}, **extra)}})
        os.makedirs(sw.paths_for(sid).root, exist_ok=True)


class TestSidResolution(_Cli):
    def test_flag_env_default_and_unknown(self):
        self.make()
        self.assertIn("kimlik: kitap", self.run_cli("-s", "kitap", "status")[1])
        self.assertNotIn("kimlik:", self.run_cli("status")[1])                     # default: bugünkü çıktı, kimlik satırı yok
        os.environ[cli.ENV_STEWARD] = "kitap"
        self.assertIn("kimlik: kitap", self.run_cli("status")[1])
        self.assertNotIn("kimlik:", self.run_cli("-s", "default", "status")[1])    # bayrak ortamı ezer
        os.environ[cli.ENV_STEWARD] = "nope"
        rc, out = self.run_cli("status")
        self.assertEqual(rc, 1)
        self.assertIn("bilinmeyen değnekçi kimliği", out)
        rc, out = self.run_cli("-s", "BAD!", "status")
        self.assertEqual(rc, 1)
        self.assertIn("geçersiz değnekçi kimliği", out)

    def test_data_commands_use_selected_store_only(self):
        self.make()
        self.assertEqual(self.run_cli("-s", "kitap", "idea", "kitap fikri")[0], 0)
        self.assertEqual(self.run_cli("idea", "default fikri")[0], 0)
        self.assertEqual([i.text for i in sw.load_ideas("kitap")], ["kitap fikri"])
        self.assertEqual([i.text for i in sw.load_ideas()], ["default fikri"])
        self.assertIn("kitap fikri", self.run_cli("-s", "kitap", "ideas")[1])
        self.assertNotIn("kitap fikri", self.run_cli("ideas")[1])
        self.run_cli("-s", "kitap", "set", "kp", "--phase", "planned")
        self.assertEqual(set(sw.load_projects("kitap")), {"kp"})
        self.assertEqual(sw.load_projects(), {})
        self.assertTrue([e for e in sw.tail_log(20, "kitap") if e["event"] == "project_set"])
        self.assertFalse([e for e in sw.tail_log(20) if e["event"] == "project_set"])

    def test_api_body_default_unchanged_other_gets_steward(self):
        self.make()
        self.run_cli("tick")
        self.run_cli("-s", "kitap", "tick")
        self.run_cli("-s", "kitap", "directive", "kp", "merhaba")
        self.assertEqual(self.api_calls[0], ("POST", "/api/steward/tick", {}))                  # default: gövde kimliksiz
        self.assertEqual(self.api_calls[1], ("POST", "/api/steward/tick", {"steward": "kitap"}))
        self.assertEqual(self.api_calls[2][2]["steward"], "kitap")


class TestIdentityCommands(_Cli):
    def test_create_list_and_defaults_off(self):
        rc, out = self.run_cli("create", "kitap", "--label", "Kitaplar")
        self.assertEqual(rc, 0)
        cfg = settings.steward_config("kitap")
        self.assertEqual((cfg.enabled, cfg.mode, cfg.label), (False, "observe", "Kitaplar"))
        self.assertTrue(os.path.isdir(sw.paths_for("kitap").root))
        self.assertEqual(self.run_cli("create", "kitap")[0], 1)                     # tekrar: reddedilir
        for bad in ("a", "default", "degnekci", "Kitap", "kitap2"):
            self.assertEqual(self.run_cli("create", bad)[0], 1, bad)
        rc, out = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("default", out)
        self.assertRegex(out, r"kitap\s+kapalı\s+observe\s+0\s+degnekci_kitap\s+Kitaplar")

    def test_remove_refuses_with_projects_then_moves_dir(self):
        self.make()
        self.make("diger")
        sw.upsert_project("kp", paths="kitap", phase="planned")
        rc, out = self.run_cli("remove", "kitap")
        self.assertEqual(rc, 1)
        self.assertIn("projesi var", out)
        self.assertIn("kitap", settings.steward_ids())
        self.assertEqual(self.run_cli("remove", "default")[0], 1)
        self.assertEqual(self.run_cli("remove", "yokyok")[0], 1)
        sw.remove_project("kp", "kitap")
        self.assertEqual(self.run_cli("remove", "kitap")[0], 0)
        self.assertEqual(settings.steward_ids(), ["default", "diger"])               # diğer kimlik bloğu durur
        self.assertFalse(os.path.exists(sw.paths_for("kitap").root))
        removed = os.path.join(sw.STEWARD_DIR, "stewards", ".removed")
        self.assertEqual(len(os.listdir(removed)), 1)
        self.assertNotIn(".removed", sw.discover_steward_ids())

    def test_transfer_moves_record_questions_and_logs(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        q_open = sw.add_question("kp", "açık soru?")
        q_other = sw.add_question("baska", "başka projenin sorusu")
        rc, out = self.run_cli("transfer", "kp", "kitap")
        self.assertEqual(rc, 0, out)
        self.assertEqual(set(sw.load_projects("kitap")), {"kp"})
        self.assertEqual(sw.load_projects(), {})
        self.assertEqual([q.id for q in sw.load_questions("kitap")], [q_open.id])
        self.assertEqual([q.id for q in sw.load_questions()], [q_other.id])
        self.assertEqual(sw.project_owner("kp"), "kitap")
        self.assertTrue([e for e in sw.tail_log(20) if e["event"] == "transfer" and e["to"] == "kitap"])
        self.assertTrue([e for e in sw.tail_log(20, "kitap") if e["event"] == "transfer" and e["frm"] == "default"])
        rc, out = self.run_cli("transfer", "kp", "--to", "default")                  # geri: --to biçimi
        self.assertEqual(rc, 0, out)
        self.assertEqual(sw.project_owner("kp"), "default")

    def test_transfer_refusals(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        self.running.add("kp")
        rc, out = self.run_cli("transfer", "kp", "kitap")
        self.assertEqual(rc, 1)
        self.assertIn("ÇALIŞIYOR", out)
        self.assertEqual(sw.project_owner("kp"), "default")
        self.assertEqual(self.run_cli("transfer", "kp", "kitap", "--force")[0], 0)   # insan zorlar
        self.assertEqual(self.run_cli("transfer", "kp", "kitap")[0], 1)              # zaten orada
        self.assertEqual(self.run_cli("transfer", "yok", "kitap")[0], 1)
        self.assertEqual(self.run_cli("transfer", "kp", "nope")[0], 1)
        self.assertEqual(self.run_cli("transfer", "kp")[0], 1)                       # hedef yok

    def test_transfer_moves_pending_jobs(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        jp = sw.paths_for().jobs
        os.makedirs(os.path.dirname(jp), exist_ok=True)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump([{"local_id": "j1", "project": "kp"}, {"local_id": "j2", "project": "z"}], f)
        self.assertEqual(self.run_cli("transfer", "kp", "kitap")[0], 0)
        with open(sw.paths_for("kitap").jobs, encoding="utf-8") as f:
            self.assertEqual([j["local_id"] for j in json.load(f)], ["j1"])
        with open(jp, encoding="utf-8") as f:
            self.assertEqual([j["local_id"] for j in json.load(f)], ["j2"])


class TestConfigAndStatus(_Cli):
    def test_config_machine_key_warns_and_is_not_written(self):
        self.make()
        rc, out = self.run_cli("-s", "kitap", "config", "tick_seconds", "30")
        self.assertEqual(rc, 1)
        self.assertIn("MAKİNE GENELİ", out)
        self.assertNotIn("tick_seconds", settings.load_settings()["stewards"]["kitap"])
        self.assertEqual(self.run_cli("-s", "kitap", "config", "brain_name", "x")[0], 1)   # türetilir
        self.assertEqual(self.run_cli("-s", "kitap", "config", "max_active", "2")[0], 0)
        self.assertEqual(settings.steward_config("kitap").max_active, 2)
        self.assertEqual(self.run_cli("config", "tick_seconds", "60")[0], 0)               # default'ta serbest
        self.assertEqual(settings.steward_config().tick_seconds, 60)

    def test_on_off_per_identity_and_off_all(self):
        self.make()
        self.run_cli("on")
        self.run_cli("-s", "kitap", "on")
        self.assertTrue(settings.steward_config().enabled and settings.steward_config("kitap").enabled)
        self.run_cli("-s", "kitap", "off")
        self.assertTrue(settings.steward_config().enabled)                                  # default'a dokunmadı
        self.assertFalse(settings.steward_config("kitap").enabled)
        self.run_cli("-s", "kitap", "on")
        self.assertEqual(self.run_cli("off", "--all")[0], 0)
        self.assertFalse(settings.steward_config().enabled or settings.steward_config("kitap").enabled)

    def test_status_prints_ownership_conflict_for_this_identity(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        sw._save_json(sw.paths_for("kitap").projects, {"kp": {"name": "kp", "phase": "planned"}})   # elle düzenleme: iki dosyada aynı ad
        out = self.run_cli("status")[1]
        self.assertIn("sahiplik ÇAKIŞMASI 'kp'", out)
        self.assertIn("sahiplik ÇAKIŞMASI 'kp'", self.run_cli("-s", "kitap", "status")[1])

    def test_default_status_output_has_no_new_lines(self):
        settings.save_settings({"steward": {"enabled": "off"}})
        sw.upsert_project("p", phase="planned")
        out = self.run_cli("status")[1].splitlines()
        self.assertTrue(out[0].startswith("değnekçi: KAPALI  mod=observe"))
        self.assertTrue(out[1].startswith("projeler: "))
        self.assertTrue(any(l.endswith("hiçbir şey kendiliğinden başlamaz") and "py/cops steward on " in l for l in out))


class TestNtfy(_Cli):
    def setUp(self):
        super().setUp()
        self.notes = []

        def fake(text, click="", title="claudeops degnekci", topic=""):
            self.notes.append({"text": text, "click": click, "title": title, "topic": topic})
            return True

        p = mock.patch.object(ws, "notify_phone", fake)
        p.start()
        self.addCleanup(p.stop)
        with open(ws.TUNNEL_URL_FILE, "w", encoding="utf-8") as f:
            f.write("https://tun.example.com\n")

    def test_default_ask_is_byte_identical_to_before(self):
        r = ws.http_ask({"project": "p", "text": "A mı B mi?", "options": ["A", "B"]})
        q = sw.find_question(r["id"])
        n = self.notes[0]
        self.assertEqual((n["title"], n["topic"]), ("claudeops degnekci", ""))             # kwargs'a title/topic hiç girmez
        self.assertEqual(n["text"], f"[p] A mı B mi?\n1) A\n2) B\n→ cevapla: https://tun.example.com/q/{q.id}?k={q.key}")
        self.assertEqual(r["link"], f"https://tun.example.com/q/{q.id}?k={q.key}")        # `&s=` YOK

    def test_other_identity_title_prefix_and_link(self):
        self.make("kitap", ntfy_topic="")
        r = ws.http_ask({"project": "kp", "text": "Soru?"}, "kitap")
        q = sw.find_question(r["id"], "kitap")
        n = self.notes[0]
        self.assertEqual((n["title"], n["topic"]), ("claudeops degnekci:kitap", ""))      # ortak topic
        self.assertTrue(n["text"].startswith("[kitap/kp] Soru?"))
        self.assertEqual(r["link"], f"https://tun.example.com/q/{q.id}?k={q.key}&s=kitap")
        self.assertEqual(n["click"], r["link"])
        with open(ws.TUNNEL_URL_FILE, "w"):
            pass
        sw.add_question("kp", "tünelsiz", paths="kitap")
        ws.http_ask({"project": "kp", "text": "tünelsiz?"}, "kitap")
        self.assertIn("py/cops steward -s kitap answer ", self.notes[-1]["text"])         # CLI ipucu kimlikli

    def test_per_identity_topic_reaches_urlopen(self):
        self.make("kitap", ntfy_topic="kitap-topic")
        done, seen = threading.Event(), {}

        class _Resp:
            def read(self):
                return b""

        def fake_open(req, timeout=0):
            seen.update(url=req.full_url, headers=dict(req.headers))
            done.set()
            return _Resp()

        # setUp'taki sahteyi geçersiz kıl: gerçek notify_phone + sahte urlopen (ağa çıkılmaz)
        with mock.patch.object(ws, "notify_phone", _real_notify), mock.patch.object(ws.urllib.request, "urlopen", fake_open):
            with open(ws.NTFY_TOPIC_FILE, "w", encoding="utf-8") as f:
                f.write("ortak\n")
            self.assertTrue(ws._notify(settings.steward_config("kitap"), "x"))
            self.assertTrue(done.wait(5))
            self.assertEqual(seen["url"], "https://ntfy.sh/kitap-topic")
            self.assertEqual(seen["headers"].get("Title"), "claudeops degnekci:kitap")
            done.clear()
            self.assertTrue(ws._notify(settings.steward_config(), "y"))
            self.assertTrue(done.wait(5))
            self.assertEqual(seen["url"], "https://ntfy.sh/ortak")                         # default: ortak topic, eski başlık
            self.assertEqual(seen["headers"].get("Title"), "claudeops degnekci")


_real_notify = ws.notify_phone      # TestNtfy.setUp mock'larından ÖNCE yakalanan gerçek işlev


class TestSummaryPerIdentity(_Cli):
    def test_daily_summary_and_compact_are_per_identity(self):
        self.make("kitap", summary_hour="0", enabled="on")
        notes = []
        day = "2026-10-19"
        for sid, n in (("default", 2), ("kitap", 3)):
            os.makedirs(os.path.dirname(sw.paths_for(sid).log), exist_ok=True)
            with open(sw.paths_for(sid).log, "w", encoding="utf-8") as f:
                for i in range(n):
                    f.write(json.dumps({"ts": f"{day}T10:0{i}:00", "event": "tick", "trigger": "timer", "mode": "observe",
                                        "n": 0, "dry": 0, "error": ""}) + "\n")
        now = time.mktime(time.strptime("2026-10-20 12:00:00", "%Y-%m-%d %H:%M:%S"))
        with mock.patch.object(ws, "notify_phone", lambda text, **kw: notes.append((text, kw)) or True):
            p_k = ws.maybe_daily_summary(settings.steward_config("kitap"), now)
        self.assertEqual(p_k, os.path.join(sw.paths_for("kitap").daily, "2026-10-20.md"))  # kendi daily/'i
        late = os.path.join(sw.paths_for("kitap").daily, f"{day}.md")                       # kaçan gün de kimliğin kendi logundan
        self.assertTrue(os.path.isfile(p_k) and os.path.isfile(late))
        self.assertFalse(os.path.isdir(sw.paths_for().daily))                              # default'a dokunulmadı
        with open(late, encoding="utf-8") as f:
            self.assertIn("Tick: 3", f.read())
        self.assertTrue(notes[0][0].startswith("[kitap] "))
        self.assertEqual(notes[0][1].get("title"), "claudeops degnekci:kitap")
        with open(sw.paths_for("kitap").log, encoding="utf-8") as f:
            k_lines = [json.loads(l) for l in f]
        self.assertEqual([e["event"] for e in k_lines if e["event"] == "ticks"], ["ticks"])  # kitap logu katlandı
        with open(sw.paths_for().log, encoding="utf-8") as f:
            self.assertEqual(sum(1 for _ in f), 2)                                          # default logu olduğu gibi
        self.assertEqual(sw.load_state("kitap")["summary_date"], "2026-10-20")
        self.assertNotIn("summary_date", sw.load_state())

    def test_default_summary_unchanged_call_shape(self):
        notes = []
        settings.save_settings({"steward": {"enabled": "on", "summary_hour": "0"}})
        now = time.mktime(time.strptime("2026-10-20 12:00:00", "%Y-%m-%d %H:%M:%S"))
        with mock.patch.object(ws, "notify_phone", lambda text: notes.append(text) or True):      # yalnız `text` alır
            path = ws.maybe_daily_summary(settings.steward_config(), now)
        self.assertEqual(path, os.path.join(sw.STEWARD_DIR, "daily", "2026-10-20.md"))
        self.assertFalse(notes[0].startswith("["))
        self.assertEqual(sw.load_state()["summary_date"], "2026-10-20")


class TestQuestionPage(_Cli):
    def test_s_param_and_legacy_search(self):
        self.make()
        qd = sw.add_question("p", "default sorusu?")
        qk = sw.add_question("kp", "kitap sorusu?", paths="kitap")
        page = lambda q, key, sid="", token=False, form=None: ws.http_question_page(q.id, key, token, form, sid)  # noqa: E731
        st, html_text = page(qk, qk.key, "kitap")
        self.assertEqual(st, 200)
        self.assertIn(f"action='/q/{qk.id}?k={qk.key}&amp;s=kitap'", html_text)             # form kimliği taşır
        self.assertEqual(page(qk, qk.key)[0], 200)                                           # eski bağlantı: tüm kimliklerde ara
        self.assertEqual(page(qk, qk.key, "default")[0], 200)                                # P9 Y1: yanlış/eski kimlik, doğru anahtar: anahtarla bulunur
        self.assertEqual(page(qk, "", "default", token=True)[0], 404)                        # anahtarsız geri düşüş yok
        self.assertEqual(page(qk, qk.key, "nope")[0], 404)
        self.assertEqual(page(qk, qk.key, "../x")[0], 404)
        self.assertEqual(page(qk, "yanlış", "kitap")[0], 401)
        self.assertEqual(page(qk, qd.key, "kitap")[0], 401)                                  # başka kimliğin anahtarı
        self.assertEqual(page(qk, "", "kitap", token=True)[0], 200)
        st, html_text = page(qd, qd.key)
        self.assertEqual(st, 200)
        self.assertIn(f"action='/q/{qd.id}?k={qd.key}'", html_text)                          # default: biçim DEĞİŞMEDİ
        self.assertNotIn("s=", html_text.split("action=")[1].split(">")[0])

    def test_post_answers_into_owning_store(self):
        self.make()
        qk = sw.add_question("kp", "kitap sorusu?", paths="kitap", options=["A", "B"])
        st, html_text = ws.http_question_page(qk.id, qk.key, False, {"answer": "2"})         # `s` yok (eski bağlantı)
        self.assertEqual(st, 200)
        self.assertEqual(sw.find_question(qk.id, "kitap").answer, "B")
        self.assertIsNone(sw.find_question(qk.id))                                           # default deposuna yazılmadı
        self.assertTrue([e for e in sw.tail_log(10, "kitap") if e["event"] == "answer" and e["source"] == "phone"])
        self.assertFalse([e for e in sw.tail_log(10) if e["event"] == "answer"])

    def test_keys_do_not_collide_across_identities(self):
        self.make()
        sw.add_question("p", "d?")
        taken = sw.load_questions()[0].key
        seq = iter([taken, taken, "f" * 16])
        with mock.patch.object(sw.secrets, "token_hex", lambda n=None: next(seq) if n == 8 else "abcd"):
            q = sw.add_question("kp", "k?", paths="kitap")
        self.assertEqual(q.key, "f" * 16)

    def test_same_id_in_two_stores_prefers_matching_key(self):
        self.make()
        a = sw.add_question("p", "d?")
        qs = [sw.Question(id=a.id, project="kp", text="k?", created_at=time.time(), key="b" * 16)]
        sw.save_questions(qs, "kitap")
        sid, q = ws._find_question_any(a.id, "b" * 16)
        self.assertEqual((sid, q.text), ("kitap", "k?"))
        sid, q = ws._find_question_any(a.id, a.key)
        self.assertEqual((sid, q.text), ("default", "d?"))


class TestListAndStatusSlice(_Cli):
    def test_list_endpoint_and_stewards_slice(self):
        self.make("kitap", enabled="on", mode="act")
        sw.upsert_project("kp", paths="kitap", phase="planned")
        sw.add_question("kp", "?", paths="kitap")
        res = ws.http_get("/api/steward/list", {})
        self.assertTrue(res["ok"])
        self.assertEqual([r["id"] for r in res["stewards"]], ["default", "kitap"])
        k = res["stewards"][1]
        self.assertEqual((k["label"], k["enabled"], k["mode"], k["project_count"], k["open_questions"]),
                         ("Kitaplar", True, "act", 1, 1))
        self.assertEqual(k["brain"]["name"], "degnekci_kitap")
        self.assertEqual(ws.http_get("/api/steward/list", {"steward": ["nope"]})["ok"], True)   # liste kimlik süzmez
        ws.invalidate_summary()
        rows = ws.stewards_summary(running_names={"degnekci_kitap"})
        self.assertTrue(rows[1]["brain"]["running"])

    def test_default_summary_keys_unchanged(self):
        self.assertEqual(sorted(ws.summary()), sorted(["enabled", "mode", "tick_seconds", "projects", "open_questions",
                                                       "ideas_new", "pending_items", "last_tick", "last_tour", "brain", "recent"]))


if __name__ == "__main__":
    unittest.main()
