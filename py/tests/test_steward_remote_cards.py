"""Uzak host'taki projeyi yönetme, A6 (TODO 2026-10-20 (14)): uzak projede proje kartı (belge başları host-routed
`files/read`den, kart YEREL `steward/cards/`a), fikir aktarımı (önce oku, yazmadan hemen önce tekrar oku, çakışmada bırak,
yazma host-routed `files/write`), uzak kayıt benimseme (`http_register`). Hepsi `remote_actions` açık + taze host iken;
uzak projede YEREL dosya sistemi ASLA okunmaz/yazılmaz (aynı yolda yerel klasör kurulup dokunulmadığı kanıtlanır).

Gerçek ağ/uzak host/spawn YOK: `ws._remote` sahte host (`FilesHost`), `web_hosts._http_json`/`_http_raw` ve `ws.spawn_session`
AssertionError'a bağlı, `hosts.HOSTS_JSON` ve değnekçi dizini geçici. Gerçek settings.json sha256'sı modül başında/sonunda
karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import FakeHost, HOST, _Remote, _row  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
CWD = "/srv/oiso"


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


class FilesHost(FakeHost):
    """FakeHost + uzak dosyalar: `files` {mutlak yol: metin} (`files/read` yalnız var olanı verir, yoksa 404),
    `files/write` YALNIZ var olan dosyayı değiştirir (gerçek `files.write_text` gibi). `on_read` her okumadan sonra
    çağrılır (okuma-yazma arası değişiklik simülasyonu); `down` = taşıma hatası."""

    def __init__(self):
        super().__init__()
        self.files = {}
        self.reads = []
        self.writes = []
        self.on_read = None
        self.down = False

    def get(self, path, host, query, timeout=None):
        if path != "/api/files/read":
            return super().get(path, host, query, timeout)
        self.gets.append((path, host, dict(query)))
        if self.down:
            return {"ok": False, "error": f"{host} unreachable: timeout"}, 200
        p = query["path"]
        self.reads.append(p)
        text = self.files.get(p)
        out = ({"ok": True, "text": text}, 200) if text is not None else ({"ok": False, "error": "yol bulunamadı"}, 404)
        if self.on_read:
            self.on_read(p, len(self.reads))
        return out

    def post(self, path, host, body, timeout=None):
        self.posts.append((path, host, dict(body), timeout))
        if path != "/api/files/write":
            raise AssertionError("beklenmeyen uzak eylem: " + path)
        if body["path"] not in self.files:
            return {"ok": False, "error": "yol bulunamadı"}, 404
        self.files[body["path"]] = body["content"]
        self.writes.append((body["path"], body["content"]))
        return {"ok": True}, 200


PARSED = {"goal": "uzak amac", "phase_guess": "planned", "next_step": "siradaki", "open_tbds": [], "blockers": [],
          "recent_done": []}


class _Files(_Remote):
    def setUp(self):
        super().setUp()
        self.fake = FilesHost()
        p = mock.patch.object(ws, "_remote", self.fake)
        p.start()
        self.addCleanup(p.stop)
        ws._REMOTE_CARD_CHECKED.clear()
        # Aynı adlı, aynı yolda YEREL klasör: uzak projenin değil, hiçbir sebeple okunmamalı/yazılmamalı.
        self.local_dir = os.path.join(self.dir.name, "oiso")
        os.makedirs(self.local_dir)
        for f in ("TODO.md", "GOAL.md"):
            with open(os.path.join(self.local_dir, f), "w", encoding="utf-8") as fh:
                fh.write("# yerel\n")
        self.fleet = {"oiso": {"cwd": self.local_dir, "cli": "claude"}}
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)])
        self.fake.files = {f"{CWD}/GOAL.md": "# uzak hedef\n", f"{CWD}/TODO.md": "# uzak todo\n"}
        sw.upsert_project("oiso", phase="planned", cadence_minutes=60, host=HOST)
        self.summaries = []

        def summarize(raw, name="", project=None, cfg=None):
            self.summaries.append((name, raw))
            return dict(PARSED), {"cli": "claude", "model": "m"}
        p = mock.patch.object(ws, "summarize_card", summarize)
        p.start()
        self.addCleanup(p.stop)

    def on(self, **kw):
        self.settings(**dict({"remote_actions": "on", "card_refresh": "on"}, **kw))

    def local_untouched(self):
        for f in ("TODO.md", "GOAL.md"):
            with open(os.path.join(self.local_dir, f), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "# yerel\n")
        self.assertEqual(sorted(os.listdir(self.local_dir)), ["GOAL.md", "TODO.md"])


# ── kartlar ───────────────────────────────────────────────────────────────────

class TestRemoteCards(_Files):
    def test_card_built_from_remote_reads_and_written_locally(self):
        self.on()
        res = ws.refresh_due_cards(settings.steward_config(), limit=10)
        self.assertEqual([(r["name"], r["ok"]) for r in res], [("oiso", True)])
        card = sw.load_card("oiso")
        self.assertEqual(card["goal"], "uzak amac")
        # Ham kart: yalnız UZAK belgeler (yerel "# yerel" yok), git bilgisi yok.
        raw = self.summaries[0][1]
        self.assertEqual(raw["docs"], {"GOAL.md": "# uzak hedef", "TODO.md": "# uzak todo"})
        self.assertEqual((raw["git_log"], raw["git_unknown"]), ([], True))
        self.assertIn("remote: bilinmiyor", sw.build_card_prompt("oiso", raw, None, lang="tr"))
        # Okumalar host-routed ve mutlak uzak yolla; hiçbir uzak yazma yok; yerel klasör bozulmadı.
        self.assertTrue(all(g[1] == HOST for g in self.fake.gets if g[0] == "/api/files/read"))
        self.assertEqual(sorted(set(self.fake.reads)), sorted(f"{CWD}/{d}" for d in sw.CARD_DOCS))
        self.assertEqual(self.fake.posts, [])
        self.local_untouched()
        # Kaynak değişmedi → ikinci turda yenileme yok.
        self.assertEqual(ws.refresh_due_cards(settings.steward_config(), limit=10), [])

    def test_manual_refresh_card_uses_remote(self):
        self.on()
        r = ws.refresh_card("oiso", settings.steward_config(), reason="manual")
        self.assertTrue(r["ok"], r)
        self.assertEqual(sw.load_card("oiso")["goal"], "uzak amac")
        self.local_untouched()

    def test_skipped_when_off_or_host_unavailable(self):
        cfg = lambda: settings.steward_config()      # noqa: E731
        self.settings(card_refresh="on")             # remote_actions KAPALI
        self.assertEqual(ws.refresh_due_cards(cfg(), limit=10), [])
        self.assertFalse(ws.refresh_card("oiso", cfg())["ok"])
        self.on()
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)], ok=False)            # host kapalı
        self.assertEqual(ws.refresh_due_cards(cfg(), limit=10), [])
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)], age=500)             # bayat
        self.assertEqual(ws.refresh_due_cards(cfg(), limit=10), [])
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD, api=0)])               # api:0 satırı da okunur (files/read eskiden beri var)
        self.fake.down = True                                                            # okuma taşıma hatası
        self.assertEqual(ws.refresh_due_cards(cfg(), limit=10), [])
        self.fake.files = {}                                                             # hiçbir belge okunamıyor
        self.fake.down = False
        self.assertEqual(ws.refresh_due_cards(cfg(), limit=10), [])
        self.assertIsNone(sw.load_card("oiso"))
        self.assertEqual(self.summaries, [])
        self.assertEqual(self.fake.posts, [])
        self.local_untouched()

    def test_running_remote_project_is_skipped(self):
        self.on()
        self.fake.set(HOST, [_row("oiso", running=True, cwd=CWD)])
        self.assertEqual(ws.refresh_due_cards(settings.steward_config(), limit=10), [])
        self.assertEqual(self.fake.reads, [])

    def test_one_remote_card_per_tick_oldest_checked_first(self):
        self.on()
        sw.upsert_project("zeta", phase="planned", cadence_minutes=60, host=HOST)
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD), _row("zeta", running=False, cwd="/srv/zeta")])
        self.fake.files["/srv/zeta/GOAL.md"] = "# zeta\n"
        cfg = settings.steward_config()
        first = ws.refresh_due_cards(cfg, limit=10)
        self.assertEqual(len(first), 1)
        second = ws.refresh_due_cards(cfg, limit=10)
        self.assertEqual(len(second), 1)
        self.assertEqual({first[0]["name"], second[0]["name"]}, {"oiso", "zeta"})        # ikincisi açıkta kalmaz
        self.assertEqual(len(self.summaries), 2)
        # Üçüncü tur: ikisi de güncel → yalnız en eskisi denetlenir, yenileme yok.
        self.fake.reads.clear()
        self.assertEqual(ws.refresh_due_cards(cfg, limit=10), [])
        self.assertEqual(len({p.rsplit("/", 2)[1] for p in self.fake.reads}), 1)

    def test_remote_card_budget_stops_reads(self):
        self.on()
        # Bütçe bitmişse okuma başlamaz: kart yok, istek yok.
        self.assertEqual(ws.refresh_due_cards(settings.steward_config(), limit=10, remote_budget=0.0), [])
        self.assertEqual(self.fake.reads, [])
        self.assertIsNone(sw.load_card("oiso"))


# ── fikir aktarımı ────────────────────────────────────────────────────────────

class TestRemoteIdeaExport(_Files):
    def setUp(self):
        super().setUp()
        self.idea = sw.add_idea("uzak fikir", source="oiso")

    def export(self, **kw):
        return ws.http_post("/api/steward/idea/export", dict({"id": self.idea.id, "kind": "todo"}, **kw))

    def test_reads_first_then_writes_to_remote_path(self):
        self.on(mode="act")
        r = self.export()
        self.assertEqual((r["ok"], r["written"], r["skipped"]), (True, ["oiso"], []), r)
        path = f"{CWD}/TODO.md"
        self.assertEqual(self.fake.reads, [path, path])                       # yazmadan önce ve hemen önce: iki okuma
        self.assertEqual(len(self.fake.writes), 1)
        wpath, content = self.fake.writes[0]
        self.assertEqual(wpath, path)
        self.assertTrue(content.startswith("# uzak todo\n\n## Değnekçi fikirleri"))
        self.assertIn(f"- [ ] (değnekçi fikri {self.idea.id}) uzak fikir", content)
        self.assertEqual(self.fake.posts[0][:3], ("/api/files/write", HOST, {"name": "oiso", "path": path, "content": content}))
        self.local_untouched()
        self.assertEqual(sw.load_ideas()[0].status, "exported")
        # Aynı fikir ikinci kez: zaten var → yazma yok.
        r = self.export()
        self.assertEqual((r["written"], r["already"]), ([], ["oiso"]))
        self.assertEqual(len(self.fake.writes), 1)

    def test_tbd_target_file(self):
        self.on()
        self.fake.files[f"{CWD}/TOBEDECIDED.md"] = ""
        r = self.export(kind="tbd")
        self.assertEqual(r["written"], ["oiso"])
        self.assertEqual(self.fake.writes[0][0], f"{CWD}/TOBEDECIDED.md")

    def test_missing_remote_file_is_not_created(self):
        self.on()
        del self.fake.files[f"{CWD}/TODO.md"]
        r = self.export()
        self.assertEqual((r["ok"], r["skipped"], r["remote"]), (False, ["oiso"], {"oiso": "unreadable"}))
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(sw.load_ideas()[0].status, "new")

    def test_conflict_between_reads_leaves_file_alone(self):
        self.on()

        def other_writer(path, n):
            if n == 1:        # ilk okumadan sonra uzakta biri dosyayı değiştirir
                self.fake.files[path] = "# uzak todo\n- biri araya yazdi\n"
        self.fake.on_read = other_writer
        r = self.export()
        self.assertEqual((r["ok"], r["remote"]), (False, {"oiso": "remote_conflict"}))
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(self.fake.files[f"{CWD}/TODO.md"], "# uzak todo\n- biri araya yazdi\n")
        self.assertEqual(sw.load_ideas()[0].status, "new")

    def test_observe_brain_is_dry_but_human_http_writes(self):
        self.on(mode="observe")
        r = self.export(actor="brain")
        self.assertEqual((r["ok"], r.get("dry"), r["would"]), (True, True, ["oiso"]), r)
        self.assertEqual((self.fake.writes, self.fake.posts), ([], []))
        self.assertEqual(sw.load_ideas()[0].status, "new")
        self.assertTrue(self.log("would:idea_export"))
        r = self.export()                       # insan HTTP çağrısı: observe'da da yazar (yerel ilkeyle aynı)
        self.assertEqual(r["written"], ["oiso"])
        self.assertEqual(len(self.fake.writes), 1)

    def test_gate_off_stale_down_skip_without_any_request(self):
        self.settings()                                                  # remote_actions kapalı
        r = self.export()
        self.assertEqual((r["ok"], r["remote"]), (False, {"oiso": "denied"}))
        self.on()
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)], ok=False)
        self.assertEqual(self.export()["remote"], {"oiso": "denied"})
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)])
        self.fake.down = True
        self.assertEqual(self.export()["remote"], {"oiso": "unreadable"})
        self.assertEqual((self.fake.writes, self.fake.posts), ([], []))
        self.local_untouched()

    def test_write_failure_reported(self):
        self.on()
        orig = self.fake.post
        self.fake.post = lambda path, host, body, timeout=None: ({"ok": False, "error": "forbidden"}, 403)
        r = self.export()
        self.fake.post = orig
        self.assertEqual((r["ok"], r["remote"]), (False, {"oiso": "write_failed"}))
        self.assertEqual(sw.load_ideas()[0].status, "new")


# ── kayıt ─────────────────────────────────────────────────────────────────────

class TestRemoteRegister(_Files):
    def register(self, **kw):
        return ws.http_post("/api/steward/register", dict({"name": "yeni", "host": HOST}, **kw))

    def test_adopts_existing_remote_roster_row_without_creating_anything(self):
        self.on()
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)], closed=[_row("yeni", running=False, cwd="/srv/yeni")])
        newdir = os.path.join(self.dir.name, "yeni")
        r = self.register(cwd=newdir, goal="amac")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["adopted"], r["project"]["host"], r["host"]), (True, HOST, HOST))
        self.assertEqual(sw.load_projects()["yeni"].host, HOST)
        self.assertFalse(os.path.exists(newdir))                       # yerel klasör/GOAL.md/git init YOK
        self.assertEqual((self.calls, self.fake.posts, self.fake.writes), ([], [], []))
        # Zaten kayıtlı uzak proje (host verilmeden) de aynı yoldan tekrar benimsenir.
        self.assertTrue(ws.http_post("/api/steward/register", {"name": "oiso", "cwd": self.local_dir})["ok"])
        self.local_untouched()

    def test_missing_remote_row_or_gate_gives_clear_error(self):
        self.on()
        r = self.register()
        self.assertFalse(r["ok"])
        self.assertIn("proxy /api/register", r["error"])
        self.assertIn("remote project", r["error"])
        self.assertNotIn("yeni", sw.load_projects())
        self.fake.set(HOST, [_row("yeni", running=False)], closed=[])
        self.settings(remote_actions="off")                            # kapalı → benimseme yok
        r = self.register()
        self.assertFalse(r["ok"])
        self.assertNotIn("yeni", sw.load_projects())
        self.on()
        self.fake.set(HOST, [_row("yeni", running=False)], ok=False)   # host kapalı
        self.assertFalse(self.register()["ok"])
        self.assertEqual((self.calls, self.fake.posts), ([], []))

    def test_conflicting_host_refused(self):
        self.on()
        r = ws.http_post("/api/steward/register", {"name": "oiso", "host": "yuhem"})
        self.assertFalse(r["ok"])
        self.assertIn("not 'yuhem'", r["error"])


if __name__ == "__main__":
    unittest.main()
