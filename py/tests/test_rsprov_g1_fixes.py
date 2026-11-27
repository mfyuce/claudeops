"""rs/prov G1 (oturum kimliği ve devam) Python hataları: iki tarafta düzeldi (Rust `cops-providers`, `parity_resume`).

Her test düzeltmeden önce kırmızıydı (istisna, başka konuşmanın kimliği ya da ezilen belge).
Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_g1_fixes.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import statedocs  # noqa: E402
from claudeops.providers import agy_provider as ap  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers import codex_provider as xp  # noqa: E402
from claudeops.providers import copilot_provider as cop  # noqa: E402

U1 = "11111111-2222-3333-4444-555555555555"
U2 = "01234567-89ab-cdef-0123-456789abcdef"


def meta(cwd, **payload):
    return json.dumps({"type": "session_meta", "payload": {"cwd": cwd, **payload}}) + "\n"


class Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.cwd = os.path.join(self.root, "work")
        os.makedirs(self.cwd)

    def put(self, rel, data, mtime=None):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p


class CodexTest(Tmp):
    def setUp(self):
        super().setUp()
        self.sessions = os.path.join(self.root, "sessions")
        p = mock.patch.object(xp, "SESSIONS_DIR", self.sessions)
        p.start()
        self.addCleanup(p.stop)
        self.prov = xp.CodexProvider()
        self.roll = "sessions/2026/11/27"

    def test_one_broken_rollout_does_not_drop_the_search(self):        # aday 1
        good = meta(self.cwd)
        for body in (b"\xff\n", b"[1]\n", b'{"type":"session_meta","payload":[1]}\n'):
            with self.subTest(body=body):
                self.put(f"{self.roll}/rollout-a-{U1}.jsonl", good, 1000)
                self.put(f"{self.roll}/rollout-b-{U2}.jsonl", body, 2000)
                self.assertEqual(self.prov.resolve_resume_id(self.cwd), U1)

    def test_only_the_first_line_must_be_utf8(self):
        self.put(f"{self.roll}/rollout-b-{U2}.jsonl", meta(self.cwd).encode() + b"\xff\n", 2000)
        self.assertEqual(self.prov.resolve_resume_id(self.cwd), U2)

    def test_newest_file_without_text_id_means_no_resume(self):          # aday 2 uygulanmadı; 11
        self.put(f"{self.roll}/rollout-a-{U1}.jsonl", meta(self.cwd), 1000)
        for extra in ({}, {"id": 7}, {"id": ["x"]}, {"id": ""}, {"session_id": ""}):
            with self.subTest(extra=extra):
                self.put(f"{self.roll}/adsiz.jsonl", meta(self.cwd, **extra), 2000)
                self.assertIsNone(self.prov.resolve_resume_id(self.cwd))

    def test_held_newest_file_is_still_skipped(self):
        self.put(f"{self.roll}/rollout-a-{U1}.jsonl", meta(self.cwd), 1000)
        self.put(f"{self.roll}/rollout-b-{U2}.jsonl", meta(self.cwd), 2000)
        self.assertEqual(self.prov.resolve_resume_id(self.cwd, in_use=frozenset({U2})), U1)

    def test_rollout_path_needs_the_exact_id(self):                        # aday 4
        own = self.put(f"{self.roll}/rollout-a-{U1}.jsonl", meta(self.cwd), 1000)
        other = self.put(f"{self.roll}/rollout-b-{U2}.jsonl", meta("/baska"), 2000)
        self.assertEqual(self.prov._rollout_path(self.cwd, U2), other)
        for sid in ("[0-9]", "*", "cdef", U2[-12:], "x/" + U2):
            with self.subTest(sid=sid):     # kısmi/joker kimlik başka konuşmayı vermez: cwd'nin kendi dosyası
                self.assertEqual(self.prov._rollout_path(self.cwd, sid), own)

    def test_rollout_without_uuid_name_matches_whole_id(self):
        p = self.put(f"{self.roll}/rollout-x-sid.1_a.jsonl", meta(self.cwd), 1000)
        self.assertEqual(self.prov._rollout_path(self.cwd, "sid.1_a"), p)
        self.assertEqual(self.prov._rollout_path("/yok", "id.1_a"), None)


class CopilotTest(Tmp):
    def db(self, rows):
        p = os.path.join(self.root, "session-store.db")
        c = sqlite3.connect(p)
        c.execute("CREATE TABLE sessions (id, cwd, updated_at)")
        c.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [(i, w, n) for n, (i, w) in enumerate(rows)])
        c.commit()
        c.close()
        return p

    def resolve(self, rows, **kw):
        p = self.db(rows)
        try:
            with mock.patch.object(cop, "SESSION_STORE_DB", p), \
                    mock.patch.object(cop, "_connect_ro", lambda: sqlite3.connect(p)):
                return cop.CopilotProvider().resolve_resume_id(self.cwd, **kw)
        finally:
            os.remove(p)

    def test_newest_row_without_text_id_means_no_resume(self):             # aday 3 uygulanmadı; 11
        for bad in (None, 7, "", b"x"):
            with self.subTest(bad=bad):
                self.assertIsNone(self.resolve([("eski", self.cwd), (bad, self.cwd)]))

    def test_held_newest_row_is_still_skipped(self):
        rows = [("eski", self.cwd), ("yeni", self.cwd)]
        self.assertEqual(self.resolve(rows, in_use=frozenset({"yeni"})), "eski")


class AgyBase(Tmp):
    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.root, "state")
        os.makedirs(self.state)
        self.conv = os.path.join(self.root, "conversations")
        os.makedirs(self.conv)
        self.cache = os.path.join(self.root, "last_conversations.json")
        self.sids = os.path.join(self.state, "agy_sids.json")
        self.diags = []
        for p in (mock.patch.object(ap, "CONVERSATIONS_DIR", self.conv),
                  mock.patch.object(ap, "CONVERSATIONS_CACHE", self.cache),
                  mock.patch.object(ap, "AGY_SIDS_JSON", self.sids),
                  mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.state),
                  mock.patch.object(ap, "diag_log", lambda ev, **kw: self.diags.append((ev, kw))),
                  mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "files"})):
            p.start()
            self.addCleanup(p.stop)
        statedocs._SYNCED.clear()
        self.prov = ap.AgyProvider()

    def write_cache(self, sid):
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump({self.cwd: sid}, f)

    def write_sids(self, doc):
        with open(self.sids, "w", encoding="utf-8") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))


class AgyTest(AgyBase):
    def test_cached_id_learned_by_another_name_is_not_taken(self):         # aday 5
        self.write_cache("c1")
        self.write_sids({"baska": "c1"})
        self.assertIsNone(self.prov.resolve_resume_id(self.cwd, session_name="yeni"))
        self.assertIsNone(self.prov.resolve_resume_id(self.cwd))
        self.assertEqual(self.prov.resolve_resume_id(self.cwd, session_name="baska"), "c1")

    def test_learned_id_whose_database_is_gone_is_not_resumed(self):       # aday 6
        self.write_cache("c1")
        self.write_sids({"inst": "gone"})
        self.assertEqual(self.prov.resolve_resume_id(self.cwd, session_name="inst"), "c1")
        open(os.path.join(self.conv, "gone.db"), "w").close()
        self.assertEqual(self.prov.resolve_resume_id(self.cwd, session_name="inst"), "gone")

    def test_non_text_learned_id_falls_back_to_the_cache(self):            # aday 11
        self.write_cache("c1")
        self.write_sids({"inst": 7})
        self.assertEqual(self.prov.resolve_resume_id(self.cwd, session_name="inst"), "c1")

    def test_absolute_learned_id_never_opens_outside(self):               # yol parçası
        outside = os.path.join(self.root, "dis")
        open(outside + ".db", "w").close()
        self.write_sids({"inst": outside})
        self.assertIsNone(self.prov.sid_for_stopped_session(self.cwd, "inst"))
        self.assertIsNone(self.prov.resolve_resume_id(self.cwd, session_name="inst"))
        self.assertEqual(self.prov._transcript_steps(self.cwd, outside), [])

    def test_valid_ids_still_resolve(self):
        for sid in ("abc", "a.b-c_1", "2026-11-27", "ğü"):
            with self.subTest(sid=sid):
                open(os.path.join(self.conv, f"{sid}.db"), "w").close()
                self.write_sids({"inst": sid})
                self.assertEqual(self.prov.sid_for_stopped_session(self.cwd, "inst"), sid)
                self.assertEqual(self.prov.resolve_resume_id(self.cwd, session_name="inst"), sid)

    def test_non_utf8_cache_is_no_cache(self):                             # aday 8
        with open(self.cache, "wb") as f:
            f.write(b"{\xff}")
        self.assertIsNone(self.prov.resolve_resume_id(self.cwd))
        info = self.prov.extract_info(["agy"], cwd=self.cwd, session_name="inst")
        self.assertIsNone(info["sid"])

    def test_broken_document_is_not_overwritten(self):                     # aday 7
        for doc in ("{bozuk", "[1]", "", "\udcff"):
            with self.subTest(doc=doc):
                self.diags.clear()
                if doc == "\udcff":
                    with open(self.sids, "wb") as f:
                        f.write(b'{"a": "\xff"}')
                    before = b'{"a": "\xff"}'
                else:
                    self.write_sids(doc)
                    before = doc.encode()
                ap._remember_agy_sid("yeni", "s1")
                with open(self.sids, "rb") as f:
                    self.assertEqual(f.read(), before)
                self.assertEqual(self.diags, [("agy_sids_unreadable", {"name": "yeni"})])

    def test_missing_document_is_created(self):
        ap._remember_agy_sid("yeni", "s1")
        with open(self.sids, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"yeni": "s1"})
        self.assertEqual(self.diags, [])


class ClaudeTest(Tmp):
    def setUp(self):
        super().setUp()
        self.projects = os.path.join(self.root, "projects")
        os.makedirs(self.projects)
        for p in (mock.patch.object(cp, "PROJECTS_DIR", self.projects),
                  mock.patch.object(cp, "SESSIONS_DIR", os.path.join(self.root, "sessions"))):
            p.start()
            self.addCleanup(p.stop)

    def test_project_path_that_is_a_file_means_nothing(self):              # aday 9
        Path(self.projects, cp._encode_cwd(self.cwd)).write_text("dosya")
        self.assertIsNone(cp.ClaudeProvider().resolve_resume_id(self.cwd))
        self.assertIsNone(cp.find_latest_jsonl(self.cwd))

    def test_overlong_sid_means_no_transcript(self):
        d = Path(self.projects, cp._encode_cwd(self.cwd))
        d.mkdir()
        (d / "z.jsonl").write_text("")
        self.assertIsNone(cp.jsonl_path_for(self.cwd, "s" * 300))
        self.assertIsNone(cp.ClaudeProvider().last_request_epoch(self.cwd, "s" * 300))

    def test_infinite_pid_in_session_file(self):                           # aday 10
        self.put("sessions/42.json", '{"pid": Infinity, "sessionId": "s", "procStart": "1"}')
        self.assertIsNone(cp.session_file_sid(42))


if __name__ == "__main__":
    unittest.main()
