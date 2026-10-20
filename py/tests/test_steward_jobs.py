"""Çoklu değnekçi P8b: pasif servis kaydı (`services.json`, watch/passive), dış iş kuyruğu İSTEMCİSİ (varaka sözleşmesi:
`varaka/PLAN_is_kuyrugu_api.md`) — gönderim (JSON + multipart, idempotency, yol kapısı, sahiplik), poll, `deliver_job`
(observe `would:`), beyin MCP araçları ve CLI.

SAHTE varaka: yerel loopback `http.server` (geçici port, thread). Gerçek varaka/ağ/tmux/docker/gerçek `~/.claude/claudeops/`
YOK; oturum açma/telefon bildirimi/iletim sahte (`_Engine` tabanı gerçek spawn'ı yasaklar). Gerçek `settings.json` sha256'sı
koşu öncesi/sonrası karşılaştırılır.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from claudeops import settings, steward as sw, steward_jobs as sj  # noqa: E402
from claudeops.commands import mcp_steward, steward as steward_cli, web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
TOKEN = "s3cr3t-tok3n-do-not-leak"


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


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeVaraka:
    """Varaka iş kuyruğunun sözleşmeye uyan en küçük taklidi: Bearer denetimi, POST /api/jobs (JSON/multipart,
    idempotency), GET /api/jobs/{id}, GET /api/jobs/kinds. `requests`: (yöntem, yol) listesi."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.jobs = {}
        self.requests = []
        self.posted = []           # çözümlenmiş POST gövdeleri: {"ctype", "meta", "files": [(ad, bayt)]}
        self.auth_seen = []
        self.next_id = 100
        self.approval_kinds = {"embed"}
        self.reject_kind = ""      # bu tür 422 unknown_kind
        self.force_status = 0      # sıfırdan farklıysa her isteğe bu durum
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _gate(self):
                outer.requests.append((self.command, self.path))
                outer.auth_seen.append(self.headers.get("Authorization", ""))
                if outer.force_status:
                    self._send(outer.force_status, {"error": "forced"})
                    return False
                if self.headers.get("Authorization") != "Bearer " + outer.token:
                    self._send(401, {"error": "auth_required"})
                    return False
                return True

            def do_GET(self):
                if not self._gate():
                    return
                if self.path == "/api/jobs/kinds":
                    return self._send(200, {"kinds": [{"kind": "noop"}, {"kind": "embed"}]})
                tail = self.path.rsplit("/", 1)[-1]
                if tail.isdigit() and int(tail) in outer.jobs:
                    return self._send(200, outer.jobs[int(tail)])
                self._send(404, {"error": "not_found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                if not self._gate():
                    return
                if self.path != "/api/jobs":
                    return self._send(404, {"error": "not_found"})
                ctype = self.headers.get("Content-Type", "")
                files = []
                if ctype.startswith("multipart/form-data"):
                    boundary = ctype.split("boundary=")[1].encode()
                    meta = {}
                    for part in raw.split(b"--" + boundary):
                        if b"Content-Disposition" not in part:
                            continue
                        head, _, body = part.partition(b"\r\n\r\n")
                        body = body[:-2] if body.endswith(b"\r\n") else body
                        if b'name="meta"' in head:
                            meta = json.loads(body.decode())
                        elif b'name="file"' in head:
                            fname = head.split(b'filename="')[1].split(b'"')[0].decode()
                            files.append((fname, body))
                else:
                    meta = json.loads(raw.decode())
                outer.posted.append({"ctype": ctype.split(";")[0], "meta": meta, "files": files})
                if meta.get("kind") == outer.reject_kind:
                    return self._send(422, {"error": "unknown_kind", "detail": meta.get("kind")})
                key = meta.get("idempotency_key")
                for j in outer.jobs.values():
                    if key and j.get("idempotency_key") == key:
                        return self._send(200, dict(j, deduplicated=True))
                jid = outer.next_id
                outer.next_id += 1
                state = "awaiting_approval" if meta.get("kind") in outer.approval_kinds else "queued"
                outer.jobs[jid] = {"id": jid, "kind": meta.get("kind"), "requester": meta.get("requester"),
                                   "state": state, "idempotency_key": key, "owner": "alice", "result": None}
                self._send(201, {"id": jid, "state": state, "position": 1, "deduplicated": False})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def paths(self, method=None):
        return [p for m, p in self.requests if method is None or m == method]


class _Jobs(_Engine):
    """`_Engine` + sahte varaka + kayıtlı servis + `mkt` projesi (proje klasörü geçici dizinde)."""

    def setUp(self):
        super().setUp()
        self.srv = FakeVaraka()
        self.addCleanup(self.srv.stop)
        sj.reset_backoff()
        self.addCleanup(sj.reset_backoff)
        self.token_file = os.path.join(self.dir.name, "varaka.token")
        with open(self.token_file, "w") as f:
            f.write(TOKEN + "\n")
        os.chmod(self.token_file, 0o600)
        sj.add_service("varaka", self.srv.url, self.token_file)
        self.proj = os.path.join(self.dir.name, "mkt_proj")
        os.makedirs(self.proj)
        with open(os.path.join(self.proj, "kitap.pdf"), "wb") as f:
            f.write(b"%PDF-fake-bytes")
        self.notes = []
        self.given = []
        patches = [
            mock.patch.object(ws, "_JOBS_BACKGROUND", False),
            mock.patch.object(ws, "_project_cwd", lambda name: self.proj if name == "mkt" else ""),
            mock.patch.object(ws, "notify_phone", lambda text, **kw: self.notes.append(text) or True),
            mock.patch.object(ws, "run_tour", lambda *a, **kw: {"ok": False, "error": "no brain here"}),
            mock.patch.object(ws, "_give_directive", self._give),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.settings(kitap={"enabled": "off"})
        sw.upsert_project("mkt", phase="planned", cadence_minutes=0)

    def _give(self, project, text, **kw):
        self.given.append((project.name, text, kw))
        return {"ok": True, "name": kw.get("session_name") or project.name}

    def submit(self, **kw):
        data = dict({"project": "mkt", "kind": "noop", "actor": "brain"}, **kw)
        return ws.http_job_submit(data, "default")

    def mkt_view(self, **kw):
        return _view("mkt", last_activity=time.time(), **kw)


# ── servis kaydı ───────────────────────────────────────────────────────────────

class TestServiceRegistry(_Jobs):
    def test_add_list_rm_without_token_in_records(self):
        svcs = sj.load_services()
        self.assertEqual(set(svcs), {"varaka"})
        rec = svcs["varaka"]
        self.assertEqual((rec["watch"], rec["passive"], rec["match"], rec["auth"]["kind"]), (True, True, "prefix", "bearer"))
        self.assertEqual(rec["auth"]["token_file"], self.token_file)
        with open(sw.services_path(), encoding="utf-8") as f:
            self.assertNotIn(TOKEN, f.read())                  # yalnız dosya YOLU saklanır
        self.assertTrue(sj.remove_service("varaka"))
        self.assertFalse(sj.remove_service("varaka"))
        self.assertEqual(sj.load_services(), {})

    def test_validation(self):
        bad = [("x1", "ftp://h", self.token_file), ("x2", "http://u:p@h", self.token_file),
               ("x3", "http://h/?q=1", self.token_file), ("x4", "http://h", "/nope/token"),
               ("degnekci", "http://h", self.token_file), ("varaka", "http://h", self.token_file),
               ("Bad Name", "http://h", self.token_file)]
        for name, url, tf in bad:
            with self.assertRaises(ValueError, msg=name):
                sj.add_service(name, url, tf)

    def test_service_name_cannot_shadow_a_project_and_projects_cannot_take_service_names(self):
        sw.upsert_project("lib", phase="planned")
        with self.assertRaises(ValueError):
            sj.add_service("li", "http://127.0.0.1:1", self.token_file)                 # prefix: `lib`i gölgelerdi
        sj.add_service("li", "http://127.0.0.1:1", self.token_file, match="exact")      # tam eşleme: sorun yok
        with self.assertRaises(ValueError):
            sw.upsert_project("varaka")
        with self.assertRaises(ValueError):
            sw.upsert_project("varaka20261020")                                         # prefix servisin öneki

    def test_token_file_permission_warning(self):
        self.assertEqual(sj.token_file_warning(self.token_file), "")
        os.chmod(self.token_file, 0o644)
        self.assertIn("chmod 600", sj.token_file_warning(self.token_file))


# ── watch/passive: servis oturumu hiçbir eylemin hedefi değil ─────────────────────

class TestPassiveService(_Jobs):
    def test_target_denies_everyone_for_service_sessions(self):
        for name in ("varaka", "varaka20261020", "varaka_2"):
            for sid in ("default", "kitap"):
                for actor in ("brain", "engine", ""):
                    res = ws._target(name, actor, kind="directive", sid=sid)
                    self.assertIsNotNone(res, (name, sid, actor))
                    self.assertFalse(res["ok"])
        # exact kayıtlı servisin uzantılı adı servis sayılmaz
        sj.add_service("zed", "http://127.0.0.1:1", self.token_file, match="exact")
        self.assertIsNotNone(ws._target("zed", "", sid="default"))
        self.assertIsNone(ws._target("zed2", "", sid="default"))          # kayıtsız ad hoc: insan default'ta serbest (eski davranış)

    def test_every_http_action_refuses_service_sessions(self):
        for fn, extra in ((ws.http_directive, {"text": "x"}), (ws.http_restart, {"text": "x", "reason": "r"}),
                          (ws.http_stop, {}), (ws.http_handover, {})):
            res = fn(dict({"name": "varaka"}, **extra), "default")
            self.assertFalse(res["ok"], fn.__name__)
            self.assertIn("target denied", res["error"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.given, [])

    def test_tick_never_touches_a_service_session(self):
        self.settings(default={"history_warn_at": "100", "context_warn_tokens": "1000"})
        self.views = [_view("varaka", history_size=99999, context_tokens=999999, needs_ho=True, stuck=True, busy=False,
                            last_assistant="STEWARD-ASK: servis sorusu?\nSTEWARD-IDEA: servis fikri"),
                      _view("varaka20261020", history_size=99999, busy=False, last_assistant="STEWARD-BLOCKED: takıldım"),
                      _view("mkt", history_size=99999, busy=False, last_activity=time.time())]
        ws.tick_once("manual", "default")
        self.assertEqual({n for _, n in self.calls}, {"mkt"})              # kontrol: proje oturumuna handover gider
        self.assertEqual(self.touched, [])
        self.assertEqual(sw.load_questions(), [])                          # servis oturumunun işaretleri soruya dönmez
        self.assertEqual(sw.load_ideas(), [])
        names = {e.get("name") for e in sw.tail_log(100) if e["event"] in ("action", "target_denied")}
        self.assertFalse(any(n and n.startswith("varaka") for n in names))


# ── gönderim ───────────────────────────────────────────────────────────────────

class TestSubmit(_Jobs):
    def test_json_submit_contract_and_local_record(self):
        res = self.submit(kind="noop", params={"seconds": 1}, spec_text="REQUEST metni", priority=3)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["id"], res["state"], res["deduplicated"]), (100, "queued", False))
        post = self.srv.posted[0]
        self.assertEqual(post["ctype"], "application/json")
        m = post["meta"]
        self.assertEqual((m["kind"], m["requester"], m["params"], m["spec_text"], m["priority"]),
                         ("noop", "mkt", {"seconds": 1}, "REQUEST metni", 3))
        self.assertEqual(m["meta"]["steward"], "default")
        self.assertTrue(m["idempotency_key"].startswith("cops:default:mkt:"))
        for forbidden in ("owner", "steward", "approved_by", "approval_state"):
            self.assertNotIn(forbidden, m)                                  # kimlik/onay gövdeden GİTMEZ (sunucu belirler)
        self.assertEqual(self.srv.auth_seen, ["Bearer " + TOKEN])
        rec = sj.load_jobs("default")[0]
        for k in ("id", "service", "project", "requester", "kind", "state", "created_at", "last_polled", "delivered",
                  "idempotency_key", "result_summary"):
            self.assertIn(k, rec)
        self.assertEqual((rec["service"], rec["project"], rec["requester"], rec["delivered"]), ("varaka", "mkt", "mkt", False))

    def test_same_request_is_idempotent_locally_and_on_the_server(self):
        a = self.submit(params={"x": 1})
        n = len(self.srv.requests)
        b = self.submit(params={"x": 1})
        self.assertTrue(b["deduplicated"])
        self.assertEqual((b["id"], len(self.srv.requests)), (a["id"], n))     # ağa hiç gidilmedi
        c = self.submit(params={"x": 2})
        self.assertNotEqual(c["id"], a["id"])
        self.assertEqual(len(sj.load_jobs("default")), 2)
        # yerel kayıt kaybolsa bile varaka aynı işi döner: yerelde tek kayıt
        os.remove(sw.paths_for("default").jobs)
        d = self.submit(params={"x": 1})
        self.assertEqual((d["id"], d["deduplicated"]), (a["id"], True))
        self.assertEqual(len(sj.load_jobs("default")), 1)

    def test_multipart_upload_with_project_files(self):
        os.makedirs(os.path.join(self.proj, "veri"))
        with open(os.path.join(self.proj, "veri", "a.txt"), "w") as f:
            f.write("merhaba")
        res = self.submit(kind="import_registry", files=["kitap.pdf", os.path.join(self.proj, "veri", "a.txt")], params={"d": 1})
        self.assertTrue(res["ok"], res)
        post = self.srv.posted[0]
        self.assertEqual(post["ctype"], "multipart/form-data")
        self.assertEqual(sorted(post["files"]), [("a.txt", b"merhaba"), ("kitap.pdf", b"%PDF-fake-bytes")])
        self.assertEqual((post["meta"]["kind"], post["meta"]["requester"]), ("import_registry", "mkt"))
        again = self.submit(kind="import_registry", files=["kitap.pdf", "veri/a.txt"], params={"d": 1})
        self.assertTrue(again["deduplicated"])                                 # içerik özeti aynı → aynı anahtar
        with open(os.path.join(self.proj, "kitap.pdf"), "ab") as f:
            f.write(b"+")
        changed = self.submit(kind="import_registry", files=["kitap.pdf", "veri/a.txt"], params={"d": 1})
        self.assertFalse(changed["deduplicated"])                              # dosya içeriği değişti → yeni iş

    def test_file_path_escape_is_refused(self):
        outside = os.path.join(self.dir.name, "outside.txt")
        with open(outside, "w") as f:
            f.write("secret")
        os.symlink(outside, os.path.join(self.proj, "link.txt"))
        os.makedirs(os.path.join(self.proj, "klasor"))
        for bad in ("../outside.txt", outside, "link.txt", "/etc/passwd", "klasor", "yok.txt", "a/../../outside.txt", ""):
            res = self.submit(files=[bad])
            self.assertFalse(res["ok"], bad)
        self.assertEqual(self.srv.requests, [])                                # hiçbiri servise gitmedi
        self.assertEqual(sj.load_jobs("default"), [])
        self.assertFalse(self.submit(files=["kitap.pdf"] * 51 + [f"f{i}" for i in range(60)])["ok"])

    def test_only_own_registered_projects(self):
        sw.upsert_project("k", paths="kitap", phase="planned")
        for project in ("k", "nobody", "../x", ""):
            res = ws.http_job_submit({"project": project, "kind": "noop", "actor": "brain"}, "default")
            self.assertFalse(res["ok"], project)
        res = ws.http_job_submit({"project": "mkt", "kind": "noop", "actor": "brain"}, "kitap")      # kitap'ın değil
        self.assertFalse(res["ok"])
        self.assertEqual(self.srv.requests, [])
        self.assertFalse(self.submit(kind="Bad Kind")["ok"])
        self.assertFalse(self.submit(params=["liste"])["ok"])

    def test_unregistered_service_and_server_errors(self):
        sj.remove_service("varaka")
        res = self.submit()
        self.assertFalse(res["ok"])
        self.assertIn("service", res["error"])
        sj.add_service("varaka", self.srv.url, self.token_file)
        self.srv.reject_kind = "bogus"
        res = self.submit(kind="bogus")
        self.assertFalse(res["ok"])
        self.assertIn("unknown_kind", res["error"])
        self.assertEqual(sj.load_jobs("default"), [])                          # reddedilen iş kaydedilmez

    def test_service_down_at_submit_is_reported_not_raised(self):
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{_free_port()}", self.token_file)
        res = self.submit()
        self.assertFalse(res["ok"])
        self.assertEqual(res.get("kind"), "unreachable")
        self.assertEqual(sj.load_jobs("default"), [])

    def test_observe_mode_brain_submit_is_only_recorded(self):
        self.settings(default={"mode": "observe"})
        res = self.submit()
        self.assertTrue(res["ok"] and res.get("dry"), res)
        self.assertEqual(self.srv.requests, [])
        self.assertEqual(sj.load_jobs("default"), [])
        self.assertEqual([e["event"] for e in sw.tail_log(20) if e["event"].startswith("would:")], ["would:job_submit"])
        human = ws.http_job_submit({"project": "mkt", "kind": "noop"}, "default")      # insan (actor yok) observe'da da uygular
        self.assertTrue(human["ok"] and not human.get("dry"))

    def test_awaiting_approval_is_surfaced_and_never_approved(self):
        res = self.submit(kind="embed")
        self.assertTrue(res["ok"] and res["awaiting_approval"], res)
        self.assertEqual(res["state"], "awaiting_approval")
        self.assertIn("HUMAN", res["message"])
        self.assertEqual(len(self.notes), 1)                                   # kullanıcıya tek telefon bildirimi
        self.assertIn("ONAY BEKLİYOR", self.notes[0])
        # poll tekrar etse de ikinci bildirim yok; proje oturumuna onay bildirimi bir kez
        self.views = [self.mkt_view()]
        for _ in range(3):
            ws.tick_once("manual", "default")
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(len([g for g in self.given if "ONAY BEKLİYOR" in g[1]]), 1)
        # onay uçları ASLA çağrılmadı
        self.assertFalse([p for p in self.srv.paths() if "approve" in p or "reject" in p])
        listed = ws.http_jobs("default")["jobs"][0]
        self.assertEqual(listed["state"], "awaiting_approval")
        self.assertIn("HUMAN", listed["note"])

    def test_token_never_reaches_logs_or_state_files(self):
        self.submit(kind="embed")
        self.srv.jobs[100]["state"] = "failed"
        self.srv.jobs[100]["error"] = "x"
        sj.poll_jobs("default", force=True)
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{_free_port()}", self.token_file)
        sj.poll_jobs("default", force=True)
        root = sw.STEWARD_DIR
        for dirpath, _, files in os.walk(root):
            for fn in files:
                with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
                    self.assertNotIn(TOKEN, f.read(), fn)


# ── poll ───────────────────────────────────────────────────────────────────────

class TestPoll(_Jobs):
    def test_poll_updates_record_and_respects_interval(self):
        self.submit()
        now = time.time()
        self.srv.jobs[100].update(state="done", result={"summary": "12 chunk eklendi", "files": []},
                                  artifacts=[{"name": "report.json"}])
        before = len(self.srv.requests)
        res = sj.poll_jobs("default", now=now)
        self.assertEqual((res["polled"], res["changed"]), (1, 1))
        rec = sj.load_jobs("default")[0]
        self.assertEqual((rec["state"], rec["result_summary"], rec["artifacts"]), ("done", "12 chunk eklendi", ["report.json"]))
        self.assertEqual(rec["last_polled"], now)
        self.assertEqual(len(self.srv.requests), before + 1)
        sj.poll_jobs("default", now=now + 5)                                   # bitmiş iş zaten yoklanmaz
        self.assertEqual(len(self.srv.requests), before + 1)

    def test_interval_limits_open_job_polling(self):
        self.submit()
        now = time.time()
        sj.poll_jobs("default", now=now)
        n = len(self.srv.requests)
        sj.poll_jobs("default", now=now + 10)
        self.assertEqual(len(self.srv.requests), n)                            # 45 sn dolmadı
        sj.poll_jobs("default", now=now + sj.JOB_POLL_SECONDS + 1)
        self.assertEqual(len(self.srv.requests), n + 1)
        sj.poll_jobs("default", now=now + sj.JOB_POLL_SECONDS + 2, force=True)
        self.assertEqual(len(self.srv.requests), n + 2)

    def test_summary_is_clipped_and_404_marks_lost_and_foreign_requester_ignored(self):
        self.submit()
        self.srv.jobs[100].update(state="done", result={"summary": "x" * 5000})
        sj.poll_jobs("default", force=True)
        self.assertEqual(len(sj.load_jobs("default")[0]["result_summary"]), sj.SUMMARY_CHARS)
        b = self.submit(params={"b": 1})
        self.srv.jobs[b["id"]]["requester"] = "baskasi"
        self.srv.jobs[b["id"]]["state"] = "done"
        sj.poll_jobs("default", force=True)
        self.assertEqual(sj.find_job(sj.load_jobs("default"), b["id"])["state"], "queued")   # requester uyuşmuyor: yok sayıldı
        self.assertIn("job_requester_mismatch", [e["event"] for e in sw.tail_log(50)])
        del self.srv.jobs[b["id"]]
        sj.poll_jobs("default", force=True)
        self.assertEqual(sj.find_job(sj.load_jobs("default"), b["id"])["state"], "lost")

    def test_unreachable_is_one_event_with_backoff_and_recovery(self):
        self.submit()
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{_free_port()}", self.token_file)
        t = time.time()
        for i in range(6):
            res = sj.poll_jobs("default", now=t + i * 700, force=False)
        events = [e["event"] for e in sw.tail_log(100)]
        self.assertEqual(events.count("service_unreachable"), 1)               # tekrarsız
        self.assertEqual(sj.load_jobs("default")[0]["state"], "queued")        # kayıt bozulmadı
        # geri çekilme: kesintide hemen ardından poll istek atmaz (skipped)
        res = sj.poll_jobs("default", now=t + 5 * 700 + 100, force=False)
        self.assertEqual(res["skipped"], 1)
        # servis döner
        sj.remove_service("varaka")
        sj.add_service("varaka", self.srv.url, self.token_file)
        sj.poll_jobs("default", now=t + 6 * 700 + 5000)
        self.assertEqual([e["event"] for e in sw.tail_log(200)].count("service_recovered"), 1)

    def test_auth_failure_is_swallowed_and_logged(self):
        self.submit()
        with open(self.token_file, "w") as f:
            f.write("wrong-token")
        res = sj.poll_jobs("default", force=True)
        self.assertEqual(res["errors"], 1)
        ev = [e for e in sw.tail_log(50) if e["event"] == "service_unreachable"]
        self.assertEqual(ev[0]["kind"], "auth")
        self.assertNotIn("wrong-token", json.dumps(ev))

    def test_down_service_does_not_break_the_tick(self):
        self.submit()
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{_free_port()}", self.token_file)
        self.views = [self.mkt_view()]
        res = ws.tick_once("manual", "default")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.given, [])

    def test_service_removed_leaves_jobs_untouched(self):
        self.submit()
        sj.remove_service("varaka")
        res = sj.poll_jobs("default", force=True)
        self.assertEqual((res["polled"], res["skipped"]), (0, 1))
        self.assertEqual(sj.load_jobs("default")[0]["state"], "queued")

    def test_redirects_are_not_followed(self):
        self.submit()
        class R(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/steal")
                self.end_headers()

            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), R)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{httpd.server_address[1]}", self.token_file)
        self.assertEqual(sj.poll_jobs("default", force=True)["errors"], 1)


# ── iletim (deliver_job) ───────────────────────────────────────────────────────

class TestDeliver(_Jobs):
    def finish(self, jid=100, **kw):
        self.srv.jobs[jid].update(dict({"state": "done", "result": {"summary": "tamam: 3 eser"}}, **kw))
        sj.poll_jobs("default", force=True)

    def test_result_is_delivered_once_to_the_running_idle_session(self):
        self.submit()
        self.finish()
        self.views = [self.mkt_view()]
        res = ws.tick_once("manual", "default")
        self.assertEqual([a["kind"] for a in res["actions"]], ["deliver_job"])
        proj, text, kw = self.given[0]
        self.assertEqual(proj, "mkt")
        self.assertIn("tamam: 3 eser", text)
        self.assertIn("BİTTİ", text)
        self.assertFalse(kw["start_if_stopped"])
        self.assertTrue(sj.load_jobs("default")[0]["delivered"])
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 1)                                   # aynı iş iki kez iletilmez
        self.assertIn("job_delivered", [e["event"] for e in sw.tail_log(50)])

    def test_waits_when_session_busy_or_not_running_and_never_starts_one(self):
        self.submit()
        self.finish()
        self.views = [self.mkt_view(busy=True)]
        ws.tick_once("manual", "default")
        self.views = [self.mkt_view(running=False)]
        ws.tick_once("manual", "default")
        self.views = []
        ws.tick_once("manual", "default")
        self.assertEqual((self.given, self.touched), ([], []))
        self.assertFalse(sj.load_jobs("default")[0]["delivered"])
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "default")                                       # boşalınca gider
        self.assertEqual(len(self.given), 1)

    def test_observe_mode_logs_would_deliver_job_and_does_not_mark(self):
        self.settings(default={"mode": "observe"})
        self.submit_as_human = ws.http_job_submit({"project": "mkt", "kind": "noop"}, "default")
        self.finish()
        self.views = [self.mkt_view()]
        res = ws.tick_once("manual", "default")
        self.assertEqual([d["kind"] for d in res["dry"]], ["deliver_job"])
        self.assertEqual(self.given, [])
        self.assertFalse(sj.load_jobs("default")[0]["delivered"])
        w = [e for e in sw.tail_log(50) if e["event"] == "would:deliver_job"]
        self.assertEqual((len(w), w[0]["job_id"]), (1, 100))
        ws.tick_once("manual", "default")
        self.assertEqual(len([e for e in sw.tail_log(50) if e["event"] == "would:deliver_job"]), 1)   # tekrarsız

    def test_failed_and_cancelled_results_and_artifacts_in_message(self):
        a = self.submit(params={"a": 1})
        b = self.submit(params={"b": 1})
        self.srv.jobs[a["id"]].update(state="failed", error_code="gate_regression", error="fark var",
                                      artifacts=[{"name": "rollback.sql"}])
        self.srv.jobs[b["id"]].update(state="cancelled")
        sj.poll_jobs("default", force=True)
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "default")
        ws.tick_once("manual", "default")
        texts = "\n".join(g[1] for g in self.given)
        self.assertIn("BAŞARISIZ", texts)
        self.assertIn("gate_regression", texts)
        self.assertIn("rollback.sql", texts)
        self.assertIn("İPTAL", texts)

    def test_approval_notice_then_result_are_two_separate_deliveries(self):
        self.submit(kind="embed")
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 1)
        self.assertIn("ONAY BEKLİYOR", self.given[0][1])
        rec = sj.load_jobs("default")[0]
        self.assertFalse(rec["delivered"])                                      # onay bildirimi sonucu iletilmiş saymaz
        self.srv.jobs[100].update(state="done", result={"summary": "bitti"})
        sj.poll_jobs("default", force=True)
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 2)
        self.assertIn("bitti", self.given[1][1])
        self.assertTrue(sj.load_jobs("default")[0]["delivered"])

    def test_approval_notice_is_skipped_when_already_approved_before_delivery(self):
        self.submit(kind="embed")
        self.srv.jobs[100]["state"] = "running"
        sj.poll_jobs("default", force=True)
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])                                        # bayat onay bildirimi gönderilmez

    def test_only_the_owner_delivers_and_transfer_moves_the_jobs(self):
        self.submit()
        self.finish()
        self.settings(kitap={"enabled": "on"})
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "kitap")                                         # kitap'ın projesi değil
        self.assertEqual(self.given, [])
        self.assertEqual(sj.load_jobs("kitap"), [])
        sw.transfer_project("mkt", "kitap")                                     # P6: `project` alanı ile taşınır
        self.assertEqual((len(sj.load_jobs("default")), len(sj.load_jobs("kitap"))), (0, 1))
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])
        ws.tick_once("manual", "kitap")
        self.assertEqual(len(self.given), 1)
        self.assertTrue(sj.load_jobs("kitap")[0]["delivered"])

    def test_failed_send_is_retried_then_given_up(self):
        self.submit()
        self.finish()
        self.views = [self.mkt_view()]
        with mock.patch.object(ws, "_give_directive", lambda *a, **k: {"ok": False, "error": "send failed"}):
            for _ in range(sj.DELIVER_MAX_ATTEMPTS + 2):
                ws.tick_once("manual", "default")
        rec = sj.load_jobs("default")[0]
        self.assertFalse(rec["delivered"])
        self.assertEqual(rec["attempts"], sj.DELIVER_MAX_ATTEMPTS)
        self.assertIn("job_undeliverable", [e["event"] for e in sw.tail_log(100)])

    def test_tick_polls_in_background_slot_and_delivers_next_tick(self):
        self.submit()
        self.srv.jobs[100].update(state="done", result={"summary": "uçtan uca"})
        self.views = [self.mkt_view()]
        ws.tick_once("manual", "default")                                       # poll: done'ı görür
        self.assertEqual(self.given, [])
        ws.tick_once("manual", "default")                                       # sonraki tick iletir
        self.assertEqual(len(self.given), 1)
        self.assertIn("uçtan uca", self.given[0][1])

    def test_no_jobs_means_no_poll_and_no_files(self):
        before = set(os.listdir(sw.STEWARD_DIR)) if os.path.isdir(sw.STEWARD_DIR) else set()
        self.views = [self.mkt_view()]
        with mock.patch.object(sj, "poll_jobs", side_effect=AssertionError("poll without jobs")):
            ws.tick_once("manual", "default")
        self.assertNotIn("jobs.json", set(os.listdir(sw.STEWARD_DIR)) - before)


# ── HTTP + MCP ─────────────────────────────────────────────────────────────────

class TestHttpAndMcp(_Jobs):
    def test_routes_and_jobs_listing(self):
        res = ws.http_post("/api/steward/job/submit", {"project": "mkt", "kind": "noop", "actor": "brain"})
        self.assertTrue(res["ok"], res)
        listed = ws.http_get("/api/steward/jobs", {"state": ["open"]})
        self.assertEqual([j["id"] for j in listed["jobs"]], [100])
        self.assertEqual(ws.http_get("/api/steward/jobs", {"state": ["done"]})["jobs"], [])
        self.assertEqual(ws.http_get("/api/steward/jobs", {"id": ["100"], "state": ["all"]})["jobs"][0]["kind"], "noop")
        self.assertFalse(ws.http_get("/api/steward/jobs", {"steward": ["nope"]})["ok"])
        kinds = ws.http_get("/api/steward/jobs", {"kinds": ["1"]})
        self.assertEqual([k["kind"] for k in kinds["kinds"]["kinds"]], ["noop", "embed"])
        self.assertEqual(sw.paths_for("kitap").jobs, os.path.join(sw.STEWARD_DIR, "stewards", "kitap", "jobs.json"))

    def test_list_refresh_polls_now(self):
        ws.http_job_submit({"project": "mkt", "kind": "noop"}, "default")
        self.srv.jobs[100].update(state="done", result={"summary": "s"})
        out = ws.http_jobs("default", state="all", refresh=True)
        self.assertEqual(out["jobs"][0]["state"], "done")

    def test_mcp_tools_exist_and_have_no_approve_tool(self):
        names = {t["name"] for t in mcp_steward.TOOLS}
        self.assertTrue({"steward_job_submit", "steward_jobs"} <= names)
        self.assertFalse([n for n in names if "approve" in n or "reject" in n])
        self.assertEqual(names, set(mcp_steward.DISPATCH))
        for t in mcp_steward.TOOLS:
            if t["name"] == "steward_job_submit":
                self.assertEqual(t["inputSchema"]["required"], ["project", "kind"])
                self.assertNotIn("owner", t["inputSchema"]["properties"])      # sahip istek gövdesinden gelmez

    def test_mcp_submit_goes_through_panel_api_as_brain(self):
        calls = []
        with mock.patch.object(mcp_steward, "_api", lambda port, m, path, body=None: calls.append((m, path, body)) or {"ok": True}):
            mcp_steward.DISPATCH["steward_job_submit"](8765, {"project": "mkt", "kind": "embed", "params": {"a": 1},
                                                              "files": ["x.pdf"], "owner": "evil"})
            mcp_steward.DISPATCH["steward_jobs"](8765, {"status": "all", "refresh": True})
            self.assertFalse(mcp_steward.DISPATCH["steward_job_submit"](8765, {"project": "mkt"})["ok"])
        (m1, p1, b1), (m2, p2, _) = calls
        self.assertEqual((m1, p1, b1["actor"], b1["files"]), ("POST", "/api/steward/job/submit", "brain", ["x.pdf"]))
        self.assertNotIn("owner", b1)
        self.assertEqual((m2, "state=all" in p2, "refresh=1" in p2), ("GET", True, True))

    def test_kitap_brain_cannot_submit_default_projects_through_mcp_identity(self):
        with mock.patch.object(mcp_steward, "_STEWARD", "kitap"):
            with mock.patch.object(mcp_steward.mcp_queue, "_api",
                                   lambda port, m, path, body=None: ws.http_post(path, body or {}, {})):
                res = mcp_steward.DISPATCH["steward_job_submit"](8765, {"project": "mkt", "kind": "noop"})
        self.assertFalse(res["ok"])
        self.assertEqual(self.srv.requests, [])


# ── CLI ────────────────────────────────────────────────────────────────────────

class TestCli(_Jobs):
    def run_cli(self, *argv):
        p = argparse.ArgumentParser()
        steward_cli.register(p.add_subparsers(dest="cmd"))
        args = p.parse_args(["steward", *argv])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = args.func(args)
        return rc, buf.getvalue()

    def test_service_add_list_rm(self):
        sj.remove_service("varaka")
        rc, out = self.run_cli("service", "list")
        self.assertEqual(rc, 0)
        self.assertIn("kayıtlı servis yok", out)
        os.chmod(self.token_file, 0o644)
        rc, out = self.run_cli("service", "add", "varaka", "--url", self.srv.url, "--token-file", self.token_file)
        self.assertEqual(rc, 0, out)
        self.assertIn("chmod 600", out)
        self.assertNotIn(TOKEN, out)
        rc, out = self.run_cli("service", "list")
        self.assertIn("varaka", out)
        self.assertNotIn(TOKEN, out)
        self.assertEqual(self.run_cli("service", "add", "varaka", "--url", self.srv.url, "--token-file", self.token_file)[0], 1)
        self.assertEqual(self.run_cli("service", "rm", "varaka")[0], 0)
        self.assertEqual(self.run_cli("service", "rm", "varaka")[0], 1)

    def test_service_does_not_need_a_steward_identity(self):
        with mock.patch.dict(os.environ, {"COPS_STEWARD": "olmayan"}):
            self.assertEqual(self.run_cli("service", "list")[0], 0)

    def test_jobs_list_show_poll_ack(self):
        self.submit(kind="embed")
        rc, out = self.run_cli("jobs")
        self.assertEqual(rc, 0)
        self.assertIn("varaka#100", out)
        self.assertIn("awaiting_approval", out)
        rc, out = self.run_cli("jobs", "show", "100")
        self.assertEqual(json.loads(out)["kind"], "embed")
        self.assertEqual(self.run_cli("jobs", "show", "999")[0], 1)
        self.srv.jobs[100].update(state="done", result={"summary": "ok"})
        rc, out = self.run_cli("jobs", "poll")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sj.load_jobs("default")[0]["state"], "done")
        n = len(self.srv.requests)
        self.assertEqual(self.run_cli("jobs", "ack", "100")[0], 0)
        self.assertTrue(sj.load_jobs("default")[0]["delivered"])
        self.assertEqual(len(self.srv.requests), n)                             # ack YEREL: varaka'ya yazmaz
        self.assertIn("iş kuyruğu", self.run_cli("status")[1])

    def test_jobs_poll_with_service_down_reports_error(self):
        self.submit()
        sj.remove_service("varaka")
        sj.add_service("varaka", f"http://127.0.0.1:{_free_port()}", self.token_file)
        rc, out = self.run_cli("jobs", "poll")
        self.assertEqual(rc, 1)
        self.assertIn("hata: 1", out)

    def test_identity_selection_for_jobs(self):
        self.submit()
        rc, out = self.run_cli("-s", "kitap", "jobs")
        self.assertEqual(rc, 0)
        self.assertIn("iş yok", out)
        self.assertEqual(self.run_cli("-s", "yokk", "jobs")[0], 1)


if __name__ == "__main__":
    unittest.main()
