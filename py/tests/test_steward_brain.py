"""Çoklu değnekçi P5: BEYİN katmanı. Kimlik başına workspace + CLAUDE.md (kimlik bölümü; default BAYT BAYT aynı),
`brain_spec(sid)`, `brain_start` (default dışı yalnız `enabled` iken, kendi adı/cwd'si/MCP'siyle), `mcp-steward --steward`
(kimliği sunucu ekler, beyin değiştiremez), HTTP `_ctx_for` yönlendirmesi ve insan geçidi.

GERÇEK beyne/tmux'a/docker'a/servise/`~/.claude/claudeops/`a dokunmaz: spawn yolu sahte (`_Brain.setUp` gerçek `spawn_session`
ve `record_instance`ı HATAYA bağlar), ayarlar geçici dosyada. Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import mcp_queue, mcp_steward, web_steward as ws  # noqa: E402
from claudeops.providers import claude_provider  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402

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


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Başlangıçta P5 ÖNCESİ kodla (41428ce) üretilmişti; model kuralı eklemeleriyle bilerek güncellenir (default yapı değişmemeli ama kural metni değişebilir). Üretilmiş `build_workspace_claude_md` çıktılarının (bayt sayısı, sha256): default CLAUDE.md
# değişmemeli (her beyin açılışında yeniden yazıldığı için fark = gereksiz yeniden yazım). "PERSONA" ve paketlenmiş persona.
GOLDEN_MD = {
    ("tr", "PERSONA"): (5850, "d5eb5a1d935b73f5391bba6c18fc27938dbfb7cb151d919f141e33d648f5c3f2"),
    ("tr", "BUNDLED"): (9346, "32c27e34dc680920a65f9dbf42b7ccc3572ea21466ddc9152194cd88c0be22c8"),
    ("en", "PERSONA"): (4252, "bb8c0cec772d1460ab5f3d9c1ae5c18e69ab3ab04a9e130c9a66668d1775f768"),
    ("en", "BUNDLED"): (7748, "4506a6d1b22ea76edf055ea687430cb32ff0d51db3d50f66ea8128642091e5fc"),
}


class TestDefaultClaudeMdGolden(unittest.TestCase):
    def test_default_output_is_byte_identical_to_pre_p5(self):
        bundled = sw.persona_text("")
        for (lang, which), (size, digest) in GOLDEN_MD.items():
            persona = "PERSONA" if which == "PERSONA" else bundled
            for text in (sw.build_workspace_claude_md(persona, lang=lang),
                         sw.build_workspace_claude_md(persona, lang=lang, sid="default"),
                         sw.build_workspace_claude_md(persona, lang=lang, sid="default", label="Etiket")):
                self.assertEqual((len(text.encode("utf-8")), _sha_text(text)), (size, digest), (lang, which))

    def test_identity_section_only_for_non_default(self):
        self.assertEqual(sw.identity_section("default", "x", "tr"), "")
        for lang, marker in (("tr", "## Kimliğin"), ("en", "## Your identity")):
            default_md = sw.build_workspace_claude_md("P", lang=lang)
            md = sw.build_workspace_claude_md("P", lang=lang, sid="kitap", label="Kitaplar")
            self.assertNotIn(marker, default_md)
            self.assertIn(marker, md)
            self.assertIn("`kitap`", md)
            self.assertIn("Kitaplar", md)
            self.assertIn("degnekci*", md)
            self.assertIn("OTOMATİK" if lang == "tr" else "AUTOMATICALLY", md)
            # persona -> kimlik -> araçlar sırası; model kuralı ve tur protokolü her kimlikte
            tools = "## Araçların" if lang == "tr" else "## Your tools"
            self.assertLess(md.index("P\n\n"), md.index(marker))
            self.assertLess(md.index(marker), md.index(tools))
            self.assertIn(sw.MODEL_RULE_TR if lang == "tr" else sw.MODEL_RULE_EN, md)
            self.assertEqual(md.replace(sw.identity_section("kitap", "Kitaplar", lang), ""), default_md)


_real_verify = ws._verify_brain_mcp      # _Brain.setUp onu sahteler; gerçeği burada tutulur


class _Brain(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        ws._RECENT.clear()
        ws.invalidate_summary()
        self.addCleanup(ws._reset_contexts)
        self.spawns, self.records, self.calls = [], [], []

        def spawn(**kw):
            self.spawns.append(kw)
            return "new"

        @contextlib.contextmanager
        def lock(timeout=None):
            yield

        patches = [
            mock.patch.object(ws, "spawn_session", lambda **kw: spawn(**kw)),
            mock.patch.object(ws, "guard_lock", lock),
            mock.patch.object(ws, "detect_display", lambda: ":0"),
            mock.patch.object(ws, "_wait_ready", lambda name, cli, timeout=0: True),
            mock.patch.object(ws, "_verify_brain_mcp", lambda cfg, since: True),     # gerçek MCP nabzı yok; doğrulama TestBrainMcp'te
            mock.patch.object(ws, "_running", lambda name: None),
            mock.patch.object(ws.inst_mod, "record_instance", lambda name, **kw: self.records.append((name, kw))),
            mock.patch.object(ws.inst_mod, "mark_started", lambda *a, **k: None),
            mock.patch.object(ws.inst_mod, "get_instance", lambda name: None),
            mock.patch.object(ws, "find_sessions", lambda **kw: []),
            mock.patch.object(ws.web_ws, "notify_status_changed", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        def stop(name, lang="tr"):
            self.calls.append(("stop", name))
            return {"ok": True}

        ws.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: {}, stop=stop,
                     handover=lambda name, lang="tr": self.calls.append(("handover", name)) or {"ok": True},
                     register_project=lambda *a, **k: {"ok": True})

    def settings(self, default=None, kitap=None):
        settings.save_settings({
            "steward": dict({"enabled": "on", "mode": "act", "card_refresh": "off", "brain_model": "claude-sonnet-5-5"},
                            **(default or {})),
            "stewards": {"kitap": dict({"label": "Kitaplar", "enabled": "off", "mode": "act",
                                        "brain_model": "claude-sonnet-5-5"}, **(kitap or {}))}})


class TestWorkspace(_Brain):
    def test_default_workspace_claude_md_is_unchanged_and_not_rewritten(self):
        self.settings()
        cfg = settings.steward_config()
        path = ws.ensure_workspace(cfg)
        self.assertEqual(path, os.path.join(sw.paths_for("default").workspace, "CLAUDE.md"))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, sw.build_workspace_claude_md(sw.persona_text(""), lang="tr"))
        self.assertEqual(_sha_text(text), GOLDEN_MD[("tr", "BUNDLED")][1])
        before = os.stat(path).st_mtime_ns
        ws.ensure_workspace(cfg)
        self.assertEqual(os.stat(path).st_mtime_ns, before)           # aynı metin: yeniden yazım yok

    def test_default_persona_override_still_applies(self):
        settings.save_settings({"steward_persona_text": "ORTAK PERSONA", "steward": {"lang": "en"}})
        path = ws.ensure_workspace(settings.steward_config())
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), sw.build_workspace_claude_md("ORTAK PERSONA\n", lang="en"))

    def test_identity_workspace_is_separate_with_identity_and_model_rule(self):
        self.settings(kitap={"lang": "tr"})
        kcfg = settings.steward_config("kitap")
        path = ws.ensure_workspace(kcfg)
        self.assertEqual(path, os.path.join(sw.paths_for("kitap").workspace, "CLAUDE.md"))
        self.assertNotEqual(sw.paths_for("kitap").workspace, sw.paths_for("default").workspace)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Sen `kitap` (`Kitaplar`) değnekçisisin", text)
        self.assertIn(sw.MODEL_RULE_TR, text)
        self.assertFalse(os.path.exists(os.path.join(sw.paths_for("default").workspace, "CLAUDE.md")))   # default'a dokunulmadı
        kcfg.lang = "en"
        with open(ws.ensure_workspace(kcfg), encoding="utf-8") as f:
            en = f.read()
        self.assertIn("You are the steward `kitap` (`Kitaplar`)", en)
        self.assertIn(sw.MODEL_RULE_EN, en)

    def test_identity_persona_falls_back_to_shared(self):
        self.settings(kitap={"persona_text": "KITAP PERSONASI"})
        settings.save_settings({"steward_persona_text": "ORTAK"})
        with open(ws.ensure_workspace(settings.steward_config("kitap")), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("KITAP PERSONASI"))
        settings.save_settings({"stewards": {"kitap": {"persona_text": ""}}})
        with open(ws.ensure_workspace(settings.steward_config("kitap")), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("ORTAK"))


class TestBrainMcp(_Brain):
    """Beyin araçsız (cops-steward MCP bağlı değil) kalırsa motor bir kez yeniden açar: açılışta nabız, turda araçsız hüküm."""

    def test_verify_uses_connect_heartbeat(self):
        cfg = sw.Config(sid="default", brain_mcp_wait_seconds=0)
        self.assertFalse(_real_verify(cfg, 1000.0))
        sw.touch_brain_mcp("default", "connect", 1500.0)
        self.assertTrue(_real_verify(cfg, 1000.0))
        self.assertFalse(_real_verify(cfg, 2000.0))
        self.assertTrue(_real_verify(dataclasses.replace(cfg, brain_mcp_check=False), 9999.0))

    def test_start_without_mcp_restarts_once_then_gives_up(self):
        self.settings(kitap={"enabled": "on"})
        cfg = settings.steward_config("kitap")
        stops, notes = [], []
        with mock.patch.object(ws, "_verify_brain_mcp", lambda c, since: False), \
                mock.patch.object(ws, "brain_stop", lambda c=None: stops.append(1) or {"ok": True}), \
                mock.patch.object(ws, "_notify", lambda c, t, click="": notes.append(t) or True), \
                mock.patch.object(ws.time, "sleep", lambda *_: None):
            res = ws.brain_start(cfg)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("mcp_retried"))
        self.assertEqual((len(self.spawns), len(stops), len(notes)), (2, 1, 2))      # tek yeniden açma, döngü yok
        events = [e["event"] for e in sw.tail_log(10, "kitap")]
        self.assertEqual(events.count("brain_mcp_missing"), 2)

    def test_notools_verdict_pure(self):
        cfg = sw.Config()
        v = sw.brain_notools_verdict
        self.assertEqual(v(0.0, {"call_at": 0.0}, "", 0, cfg, 9000.0), (0, ""))                       # önceki tur yok
        self.assertEqual(v(8900.0, {"call_at": 0.0}, "", 0, cfg, 9000.0), (0, ""))                    # çok yeni
        self.assertEqual(v(1000.0, {"call_at": 1050.0}, "", 2, cfg, 9000.0), (0, ""))                 # çağrı var: sayaç sıfırlanır
        self.assertEqual(v(1000.0, {"call_at": 0.0}, "", 0, cfg, 9000.0), (1, ""))
        self.assertEqual(v(1000.0, {"call_at": 0.0}, "", 1, cfg, 9000.0), (2, ""))
        n, why = v(1000.0, {"call_at": 0.0}, "", 2, cfg, 9000.0)
        self.assertEqual(n, 0)
        self.assertIn("steward_*", why)
        n, why = v(1000.0, {"call_at": 5000.0}, "Araçlar yok, karar veremedim.", 0, cfg, 9000.0)    # işaret metni anında
        self.assertTrue(why)
        off = sw.Config(brain_nocall_tours=0)
        self.assertEqual(v(1000.0, {"call_at": 0.0}, "", 50, off, 9000.0)[1], "")
        self.assertTrue(sw.brain_tools_missing_text("No matching deferred tools found"))
        self.assertFalse(sw.brain_tools_missing_text("3 madde cevaplandı, steward_answer çağrıldı"))

    def test_recover_restarts_once_with_cooldown(self):
        cfg = sw.Config(sid="default")
        paths = sw.paths_for("default")
        sw.save_state({"last_tour": 1000.0, "tour_nocall": 2}, paths)
        notes, restarts = [], []
        with mock.patch.object(ws, "_brain_last_text", lambda c: ""), \
                mock.patch.object(ws, "brain_restart_for_stuck_input", lambda c: restarts.append(1) or {"ok": True}), \
                mock.patch.object(ws, "_notify", lambda c, t, click="": notes.append(t) or True):
            r = ws._brain_notools_recover(cfg, now=9000.0)
            self.assertTrue(r["ok"] and r["notools_restart"])
            self.assertEqual((len(restarts), len(notes)), (1, 1))
            self.assertNotIn("tour_nocall", sw.load_state(paths))
            sw.save_state(dict(sw.load_state(paths), last_tour=9100.0, tour_nocall=2), paths)
            self.assertIsNone(ws._brain_notools_recover(cfg, now=20000.0))                          # 6 sa soğuma içinde: ikinci açma YOK
            self.assertEqual(len(restarts), 1)

    def test_mcp_server_heartbeat_hook(self):
        from claudeops.commands import mcp_queue
        seen = []
        import io
        msgs = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        with mock.patch("sys.stdin", io.StringIO(msgs)), mock.patch.object(mcp_queue, "_send", lambda r: None):
            mcp_queue.run_server(1, on_message=lambda m: seen.append(m.get("method")))
        self.assertEqual(seen, ["ping", "notifications/initialized"])

    def test_touch_records_call_and_connect(self):
        sw.touch_brain_mcp("default", "call", 100.0)
        self.assertEqual(sw.read_brain_mcp(sw.paths_for("default")), {"connected_at": 100.0, "call_at": 100.0})
        sw.touch_brain_mcp("default", "connect", 200.0)
        self.assertEqual(sw.read_brain_mcp(sw.paths_for("default")), {"connected_at": 200.0, "call_at": 100.0})


class TestBrainStart(_Brain):
    def test_brain_spec_default_is_the_old_command_line(self):
        d, k = ws.brain_spec(), ws.brain_spec("kitap")
        self.assertEqual((d.name, tuple(d.args)), ("cops-steward", ("mcp-steward",)))
        self.assertEqual(tuple(ws.brain_spec("default").args), ("mcp-steward",))
        self.assertEqual((k.name, tuple(k.args)), ("cops-steward", ("mcp-steward", "--steward", "kitap")))
        self.assertEqual(d.command, k.command)

    def test_disabled_identity_never_starts_a_brain(self):
        self.settings()                                       # kitap enabled=off
        res = ws.brain_start(settings.steward_config("kitap"))
        self.assertFalse(res["ok"])
        self.assertIn("disabled", res["error"])
        self.assertEqual((self.spawns, self.records), ([], []))
        self.assertFalse(os.path.exists(sw.paths_for("kitap").workspace))     # workspace bile açılmadı
        # elle brain/tour uçları da aynı kapıdan geçer
        self.assertFalse(ws.http_post("/api/steward/brain", {"steward": "kitap", "action": "start"})["ok"])
        self.assertFalse(ws.http_post("/api/steward/tour", {"steward": "kitap"})["ok"])
        self.assertEqual(self.spawns, [])
        self.assertFalse(settings.steward_config("kitap").enabled)            # yeni kimlik varsayılan KAPALI
        settings.save_settings({"stewards": {"yenik": {"label": "Y"}}})
        self.assertFalse(settings.steward_config("yenik").enabled)
        self.assertFalse(ws.brain_start(settings.steward_config("yenik"))["ok"])
        self.assertEqual(self.spawns, [])

    def test_enabled_identity_starts_its_own_brain(self):
        self.settings(kitap={"enabled": "on", "brain_effort": "medium"})
        res = ws.brain_start(settings.steward_config("kitap"))
        self.assertTrue(res["ok"] and res["started"], res)
        self.assertEqual(res["name"], "degnekci_kitap")
        self.assertEqual(len(self.spawns), 1)
        kw = self.spawns[0]
        kwork = sw.paths_for("kitap").workspace
        self.assertEqual((kw["name"], kw["cwd"], kw["model"], kw["effort"]),
                         ("degnekci_kitap", kwork, "claude-sonnet-5-5", "medium"))
        self.assertEqual(tuple(kw["mcp_server"].args), ("mcp-steward", "--steward", "kitap"))
        name, rec = self.records[0]
        self.assertEqual((name, rec["cwd"], rec["origin"], rec["model"], rec["effort"]),
                         ("degnekci_kitap", kwork, "steward", "claude-sonnet-5-5", "medium"))
        self.assertTrue(os.path.isfile(os.path.join(kwork, "CLAUDE.md")))
        self.assertEqual([e["event"] for e in sw.tail_log(10, "kitap")], ["brain_start"])
        self.assertEqual(sw.tail_log(10), [])                                  # default logu kirlenmedi

    def test_default_brain_start_is_unchanged(self):
        self.settings(kitap={"enabled": "on"})
        res = ws.brain_start()
        self.assertTrue(res["ok"] and res["started"], res)
        kw = self.spawns[0]
        self.assertEqual((kw["name"], kw["cwd"], tuple(kw["mcp_server"].args)),
                         ("degnekci", sw.paths_for("default").workspace, ("mcp-steward",)))
        self.assertEqual(self.records[0][0], "degnekci")
        # default `enabled` kapalıyken de elle açılabilir (bugünkü davranış)
        self.settings(default={"enabled": "off"})
        self.spawns.clear()
        self.assertTrue(ws.brain_start()["ok"])
        self.assertEqual(len(self.spawns), 1)

    def test_running_brain_is_not_started_twice(self):
        self.settings(kitap={"enabled": "on"})
        with mock.patch.object(ws, "_running", lambda name: object()):
            res = ws.brain_start(settings.steward_config("kitap"))
        self.assertEqual((res["ok"], res["started"]), (True, False))
        self.assertEqual(self.spawns, [])

    def test_brain_stop_uses_only_the_act_stop_path_with_the_exact_name(self):
        self.settings(kitap={"enabled": "on"})
        with mock.patch.object(ws, "_running", lambda name: object()):
            ws.http_post("/api/steward/brain", {"steward": "kitap", "action": "stop"})
        self.assertEqual(self.calls, [("stop", "degnekci_kitap")])


class TestClaudeMcpConfigFile(unittest.TestCase):
    def test_identity_gets_its_own_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "orchestration", "mcp_config.json")
            with mock.patch.object(claude_provider, "MCP_CONFIG_PATH", base):
                dp = claude_provider._write_mcp_config_file(ws.brain_spec())
                kp = claude_provider._write_mcp_config_file(ws.brain_spec("kitap"))
                dp2 = claude_provider._write_mcp_config_file(ws.brain_spec())
                self.assertEqual(dp, base)
                self.assertEqual(dp2, base)
                self.assertEqual(kp, os.path.join(d, "orchestration", "mcp_config_kitap.json"))
                with open(dp, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["mcpServers"]["cops-steward"]["args"], ["mcp-steward"])
                with open(kp, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["mcpServers"]["cops-steward"]["args"],
                                     ["mcp-steward", "--steward", "kitap"])
                odd = McpServerSpec(name="x", command="c", args=("mcp-steward", "--steward", "../zz"))
                self.assertEqual(claude_provider._write_mcp_config_file(odd), base)    # yol kaçışı yok


class TestMcpIdentity(unittest.TestCase):
    def setUp(self):
        self.sent = []
        p = mock.patch.object(mcp_queue, "_api", lambda port, m, path, body=None: self.sent.append((m, path, body)) or {"ok": True})
        p.start()
        self.addCleanup(p.stop)

    def test_default_server_adds_nothing(self):
        self.assertEqual(mcp_steward._STEWARD, "default")
        mcp_steward._overview(1, {})
        mcp_steward._context(1, {"name": "p"})
        mcp_steward._ask(1, {"project": "p", "question": "?"})
        mcp_steward._directive(1, {"name": "p", "text": "t", "steward": "kitap"})
        self.assertEqual(self.sent[0], ("GET", "/api/steward/state", None))
        self.assertEqual(self.sent[1], ("GET", "/api/steward/context?name=p", None))
        self.assertNotIn("steward", self.sent[2][2])
        self.assertNotIn("steward", self.sent[3][2])           # araç argümanındaki `steward` zaten taşınmaz

    def test_identity_server_adds_it_to_every_call_and_the_brain_cannot_change_it(self):
        with mock.patch.object(mcp_steward, "_STEWARD", "kitap"):
            mcp_steward._overview(1, {"steward": "default"})
            mcp_steward._context(1, {"name": "p", "docs": True, "steward": "default"})
            mcp_steward._read_file(1, {"name": "p", "path": "a.md"})
            mcp_steward._questions(1, {"status": "all"})
            mcp_steward._log(1, {})
            mcp_steward._directive(1, {"name": "p", "text": "t", "steward": "default", "actor": "human"})
            mcp_steward._restart(1, {"name": "p", "directive": "d", "reason": "r"})
            mcp_steward._stop(1, {"name": "p", "reason": "r"})
            mcp_steward._handover(1, {"name": "p"})
            mcp_steward._set_project(1, {"name": "p", "phase": "planned", "steward": "default"})
            mcp_steward._register(1, {"name": "p", "cwd": "/x"})
            mcp_steward._ask(1, {"project": "p", "question": "?", "steward": "default"})
            mcp_steward._answer(1, {"id": "q", "answer": "a"})
            mcp_steward._note(1, {"project": "p", "text": "n"})
            mcp_steward._idea(1, {"text": "i"})
            mcp_steward._idea_update(1, {"id": "i", "status": "later"})
            mcp_steward._skip(1, {"name": "p", "reason": "r"})
        self.assertEqual(len(self.sent), 17)
        for method, path, body in self.sent:
            if method == "GET":
                self.assertEqual(path.count("steward=kitap"), 1, path)
                self.assertNotIn("steward=default", path)
            else:
                self.assertEqual(body.get("steward"), "kitap", path)
        self.assertEqual(self.sent[0][1], "/api/steward/state?steward=kitap")
        self.assertIn("name=p&docs=1&steward=kitap", self.sent[1][1])
        self.assertEqual(self.sent[5][2]["actor"], "brain")    # actor ezilmez: insan kimliğine bürünemez (sunucuda sabit)

    def test_run_validates_the_identity_and_sets_it(self):
        self.addCleanup(setattr, mcp_steward, "_STEWARD", "default")
        seen = []
        with mock.patch.object(mcp_queue, "run_server",
                               lambda port, tools=None, dispatch=None, server_name="", on_message=None: seen.append(mcp_steward._STEWARD)):
            self.assertEqual(mcp_steward.run(argparse.Namespace(port=1, steward="kitap")), 0)
            self.assertEqual(seen, ["kitap"])
            self.assertEqual(mcp_steward.run(argparse.Namespace(port=1)), 0)          # eski çağrı: parametresiz = default
            self.assertEqual(seen, ["kitap", "default"])
            for bad in ("../x", "degnekci_x", "Kitap", "all"):
                self.assertEqual(mcp_steward.run(argparse.Namespace(port=1, steward=bad)), 2, bad)
        self.assertEqual(seen, ["kitap", "default"])

    def test_cli_parses_the_flag(self):
        ap = argparse.ArgumentParser()
        mcp_steward.register(ap.add_subparsers())
        self.assertEqual(ap.parse_args(["mcp-steward"]).steward, "default")
        self.assertEqual(ap.parse_args(["mcp-steward", "--steward", "kitap"]).steward, "kitap")


class TestCtxFor(_Brain):
    def setUp(self):
        super().setUp()
        self.settings()

    def test_resolution(self):
        for src in ({}, {"steward": ""}, {"steward": None}, {"steward": "default"}, {"steward": ["default"]}, {"steward": []}, None):
            self.assertEqual(ws._ctx_for(src).sid, "default", src)
        for src in ({"steward": "kitap"}, {"steward": ["kitap"]}, {"steward": " kitap "}):
            self.assertEqual(ws._ctx_for(src).sid, "kitap", src)
        self.assertIs(ws._ctx_for({"steward": "kitap"}), ws._ctx("kitap"))
        for bad in ({"steward": "nope"}, {"steward": "../x"}, {"steward": "degnekci"}, {"steward": "all"}, {"steward": 5},
                    {"steward": ["nope"]}, {"steward": {"a": 1}}, {"steward": "Kitap"}):
            with self.assertRaises(ws.UnknownSteward, msg=bad):
                ws._ctx_for(bad)

    def test_unknown_identity_is_an_explicit_error_and_writes_nothing(self):
        for path, data in (("/api/steward/idea", {"text": "x"}), ("/api/steward/ask", {"project": "p", "text": "?"}),
                           ("/api/steward/stop", {"name": "a"}), ("/api/steward/tick", {}), ("/api/steward/brain", {})):
            self.assertEqual(ws.http_post(path, dict(data, steward="nope")), {"ok": False, "error": "unknown steward"}, path)
        for path in ("state", "questions", "log", "context", "projects"):
            self.assertEqual(ws.http_get("/api/steward/" + path, {"steward": ["nope"]}), {"ok": False, "error": "unknown steward"})
        self.assertEqual((sw.load_ideas(), sw.load_questions(), self.calls), ([], [], []))
        self.assertFalse(os.path.exists(os.path.join(sw.STEWARD_DIR, "stewards")))
        self.assertIsNone(ws.http_get("/api/steward/nothing", {"steward": ["nope"]}))       # bilinmeyen yol hâlâ 404
        self.assertIsNone(ws.http_post("/api/steward/nothing", {"steward": "nope"}))

    def test_no_param_means_default_and_old_callers_work(self):
        r = ws.http_post("/api/steward/idea", {"text": "eski"})
        self.assertTrue(r["ok"])
        self.assertEqual([i.text for i in sw.load_ideas()], ["eski"])
        self.assertEqual(sw.load_ideas("kitap"), [])
        self.assertEqual(ws.http_get("/api/steward/ideas", {})["ideas"][0]["text"], "eski")
        self.assertEqual(ws.http_get("/api/steward/state", {})["config"]["sid"], "default")

    def test_requests_reach_the_right_store(self):
        ws.http_post("/api/steward/idea", {"text": "k fikri", "steward": "kitap"})
        ws.http_post("/api/steward/idea", {"text": "q fikri"}, {"steward": ["kitap"]})          # sorgudan
        ws.http_post("/api/steward/idea", {"text": "gövde", "steward": "default"}, {"steward": ["kitap"]})   # gövde önce
        ws.http_post("/api/steward/project", {"name": "k", "phase": "planned", "steward": "kitap"})
        r = ws.http_post("/api/steward/ask", {"project": "k", "text": "soru?", "steward": "kitap"})
        self.assertTrue(r["ok"])
        self.assertEqual(sorted(i.text for i in sw.load_ideas("kitap")), ["k fikri", "q fikri"])
        self.assertEqual([i.text for i in sw.load_ideas()], ["gövde"])
        self.assertEqual(list(sw.load_projects("kitap")), ["k"])
        self.assertEqual(sw.load_projects(), {})
        self.assertEqual([q.project for q in sw.load_questions("kitap")], ["k"])
        self.assertEqual(sw.load_questions(), [])
        qid = sw.load_questions("kitap")[0].id
        self.assertFalse(ws.http_post("/api/steward/answer", {"id": qid, "answer": "x"})["ok"])    # default deposunda yok
        self.assertTrue(ws.http_post("/api/steward/answer", {"id": qid, "answer": "x", "steward": "kitap"})["ok"])
        # GET
        self.assertEqual([i["text"] for i in ws.http_get("/api/steward/ideas", {"steward": ["kitap"]})["ideas"]],
                         ["k fikri", "q fikri"])
        self.assertEqual([p["name"] for p in ws.http_get("/api/steward/projects", {"steward": ["kitap"]})["projects"]], ["k"])
        self.assertEqual(ws.http_get("/api/steward/projects", {})["projects"], [])
        self.assertEqual(ws.http_get("/api/steward/state", {"steward": ["kitap"]})["config"]["sid"], "kitap")
        evs = {e["event"] for e in ws.http_get("/api/steward/log", {"steward": ["kitap"]})["entries"]}
        self.assertTrue({"idea", "project_set", "ask", "answer"} <= evs)
        self.assertFalse({"project_set", "ask"} & {e["event"] for e in ws.http_get("/api/steward/log", {})["entries"]})

    def test_manual_tick_and_note_and_skip_use_the_identity(self):
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=0)
        before = dict(ws._LAST_TICK)
        with mock.patch.object(ws, "_collect_views", lambda cfg: []), mock.patch.object(ws, "maybe_daily_summary", lambda c, n: None):
            r = ws.http_post("/api/steward/tick", {"steward": "kitap"})
        self.assertTrue(r["ok"])
        self.assertEqual(ws._ctx("kitap").last_tick["trigger"], "manual")
        self.assertEqual(ws._LAST_TICK, before)                                     # default tick'lenmedi
        self.assertTrue(ws.http_post("/api/steward/note", {"project": "k", "text": "not", "steward": "kitap"})["ok"])
        self.assertEqual(sw.load_projects("kitap")["k"].notes, "not")
        self.assertFalse(ws.http_post("/api/steward/note", {"project": "k", "text": "not"})["ok"])   # default'ta k yok
        ws.http_post("/api/steward/skip", {"name": "k", "reason": "r", "steward": "kitap"})
        self.assertIn("k", sw.load_state("kitap")["last_directive_at"])
        self.assertNotIn("k", sw.load_state().get("last_directive_at", {}))


class TestHumanGate(_Brain):
    """Plan (e): insan çağrısı `default` bağlamında kayıtsız oturuma yazabilir; diğer bağlamlarda yalnız kendi projeleri."""

    def setUp(self):
        super().setUp()
        self.settings(kitap={"enabled": "on"})
        sw.upsert_project("a")
        sw.upsert_project("k", paths="kitap")

    def post(self, path, name, sid=None, **kw):
        data = dict({"name": name}, **kw)
        if sid:
            data["steward"] = sid
        return ws.http_post(path, data)

    def test_human_in_default_context_is_unrestricted(self):
        for name in ("a", "k", "adhocsess"):
            self.assertTrue(self.post("/api/steward/stop", name)["ok"], name)
        self.assertEqual(self.calls, [("stop", "a"), ("stop", "k"), ("stop", "adhocsess")])

    def test_human_in_other_context_only_own_projects_and_brain(self):
        self.assertTrue(self.post("/api/steward/stop", "k", "kitap")["ok"])
        self.assertTrue(self.post("/api/steward/handover", "degnekci_kitap", "kitap")["ok"])
        for path in ("stop", "handover", "directive", "restart"):
            for name in ("a", "degnekci", "adhocsess"):
                r = self.post("/api/steward/" + path, name, "kitap", text="t", directive="d")
                self.assertFalse(r["ok"], (path, name))
                self.assertIn("target denied", r["error"])
        self.assertEqual(self.calls, [("stop", "k"), ("handover", "degnekci_kitap")])
        self.assertEqual(sum(1 for e in sw.tail_log(50, "kitap") if e["event"] == "target_denied"), 12)
        self.assertEqual(sw.tail_log(50), [])

    def test_brain_in_identity_context(self):
        for name in ("a", "degnekci", "adhocsess"):
            self.assertFalse(self.post("/api/steward/stop", name, "kitap", actor="brain")["ok"], name)
        self.assertTrue(self.post("/api/steward/stop", "k", "kitap", actor="brain")["ok"])
        self.assertEqual(self.calls, [("stop", "k")])

    def test_reads_are_limited_to_own_projects_outside_default(self):
        with mock.patch.object(ws, "_git_short", lambda cwd: ""), mock.patch.object(ws, "_project_cwd", lambda name: ""):
            self.assertTrue(ws.http_get("/api/steward/context", {"name": ["k"], "steward": ["kitap"]})["ok"])
            for name in ("a", "degnekci", "adhocsess"):
                r = ws.http_get("/api/steward/context", {"name": [name], "steward": ["kitap"]})
                self.assertEqual(r, {"ok": False, "error": "not a project of this steward"}, name)
                r = ws.http_get("/api/steward/file", {"name": [name], "path": ["x.md"], "steward": ["kitap"]})
                self.assertEqual(r, {"ok": False, "error": "not a project of this steward"}, name)
            self.assertTrue(ws.http_get("/api/steward/context", {"name": ["a"]})["ok"])             # default: kısıtsız
            self.assertTrue(ws.http_get("/api/steward/context", {"name": ["adhocsess"]})["ok"])
            self.assertFalse(ws.http_get("/api/steward/card", {"name": ["a"], "steward": ["kitap"]})["ok"])
            self.assertEqual(ws.http_get("/api/steward/card", {"name": ["k"], "steward": ["kitap"]})["error"], "no card")


if __name__ == "__main__":
    unittest.main()
