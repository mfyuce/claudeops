"""TBD#365 (26 Kas, sahip kararı): süreç taramasında Python'un bozuk girdide düştüğü/yanlış davrandığı yerler.

Kural: bozuk kayıt atlanır ve modülün `_skipped` sayacına girer (tarama/toplam/karar düşmez); baseline atomik yazılır;
transkript yolunda `sid` yol parçası olarak süzülür; negatif pid'li oturum dosyası atlanır; başka kullanıcının süreç
içeriği (cmdline) okunmaz; arka plan iş parçacığı başlatılamazsa yol kilitli kalmaz; dolu dosya önbelleğinde küçülen
transkript başka girdiyi attırmaz. Rust karşılığı `rust/crates/cops-procscan` (`docs/rs-proc.md`).

Çalıştırma: cd py && python3 -m unittest tests.test_procscan_tbd365 -v
Gerçek ~/.claude, durum dizini, süreç sinyali ya da git KULLANILMAZ (hepsi geçici dizin ya da sahte).
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import discovery, mirrors, needs_ho, session_usage as su, tmux_backend  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402

UIDS = namedtuple("UIDS", "real effective saved")
ME = os.getuid()
OTHER = ME + 4242


def _reset(mod):
    """Sayaç düzeltmeden önce yoktu: kırmızı koşuda davranış denetimleri yine çalışsın."""
    getattr(mod, "_skipped", {}).clear()


def _tmpdir(case):
    t = tempfile.TemporaryDirectory()
    case.addCleanup(t.cleanup)
    return Path(t.name)


class SessionFilesTest(unittest.TestCase):
    """`_sessions_from_json`: nesne olmayan ya da `name`i dizgi olmayan dosya tüm taramayı düşürüyordu."""

    def setUp(self):
        self.home = _tmpdir(self)
        self.sess = self.home / ".claude" / "sessions"
        self.sess.mkdir(parents=True)
        _reset(discovery)
        self.killed = []
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        kill = mock.patch.object(discovery.os, "kill", lambda pid, sig: self.killed.append(pid))
        for p in (env, kill):
            p.start()
            self.addCleanup(p.stop)

    def _write(self, fname, obj):
        (self.sess / fname).write_text(json.dumps(obj))

    def test_bad_files_are_skipped_and_counted(self):
        me = os.getpid()
        self._write("a.json", [1, 2])
        self._write("b.json", "metin")
        self._write("c.json", {"pid": me, "name": 5, "cwd": "/tmp"})
        self._write("d.json", {"pid": me, "name": ["x"], "cwd": "/tmp"})
        self._write("e.json", {"pid": me, "name": "iyi", "cwd": "/tmp", "sessionId": "s1"})
        got = discovery._sessions_from_json()
        self.assertEqual(list(got), [("iyi", me)])
        self.assertEqual(got[("iyi", me)].sid, "s1")
        self.assertEqual(discovery._skipped["session_file"], 4)

    def test_negative_or_zero_pid_never_reaches_kill(self):
        for i, pid in enumerate([-1, -os.getpid(), "-5", 0]):
            self._write(f"n{i}.json", {"pid": pid, "name": f"neg{i}", "cwd": "/tmp"})
        self.assertEqual(discovery._sessions_from_json(), {})
        self.assertEqual([p for p in self.killed if p <= 0], [])


class _P:
    """`process_iter` öğesi: `.info` istenen alanlar; `cmdline()` başka kullanıcıda okunursa test düşer."""

    def __init__(self, pid, uid, cmd, attrs):
        self.pid = pid
        self._uid, self._cmd = uid, cmd
        self.info = {"pid": pid, "uids": UIDS(uid, uid, uid)}
        if "cmdline" in attrs:
            if uid != ME:
                raise AssertionError(f"başka kullanıcının cmdline'ı önceden istendi: {attrs}")
            self.info["cmdline"] = cmd

    def cmdline(self):
        if self._uid != ME:
            raise AssertionError("başka kullanıcının cmdline'ı okundu")
        return self._cmd

    def cwd(self):
        return "/tmp"


class ForeignCmdlineTest(unittest.TestCase):
    """`process_iter([... "cmdline" ...])` uid süzgecinden ÖNCE herkesin cmdline'ını okuyordu."""

    def _iter(self, attrs=None):
        attrs = attrs or []
        return iter([_P(10, OTHER, ["python3", "-m", "claudeops", "watch", "h:yabanci"], attrs),
                     _P(11, ME, ["python3", "-m", "claudeops", "watch", "h:benim"], attrs)])

    def test_find_sessions_reads_only_own_cmdline(self):
        out = {}
        with mock.patch.object(discovery.psutil, "process_iter", self._iter), \
                mock.patch.object(discovery, "_sessions_from_json", lambda: {}):
            discovery.find_sessions(measure_cpu=False, mirrors_out=out)
        self.assertEqual(out, {"h:benim": [11]})

    def test_running_mirrors_reads_only_own_cmdline(self):
        with mock.patch.object(mirrors.psutil, "process_iter", self._iter):
            self.assertEqual(mirrors.running_mirrors(), {"h:benim": [11]})


class _Anc:
    def __init__(self, uid, cmd, parent=None):
        self._uid, self._cmd, self._parent = uid, cmd, parent

    def parent(self):
        return self._parent

    def uids(self):
        return UIDS(self._uid, self._uid, self._uid)

    def cmdline(self):
        if self._uid != ME:
            raise AssertionError("başka kullanıcının atasının cmdline'ı okundu")
        return self._cmd


class TmuxAncestorTest(unittest.TestCase):
    def test_foreign_ancestor_stops_walk_without_reading_it(self):
        tmux = ["tmux", "-L", tmux_backend.TMUX_SOCKET, "new-session"]
        foreign = _Anc(OTHER, tmux)
        leaf = _Anc(ME, ["claude"], parent=_Anc(ME, ["bash"], parent=foreign))
        with mock.patch("psutil.Process", lambda pid: leaf):
            self.assertFalse(tmux_backend.is_tmux_backed(123))
        own = _Anc(ME, ["claude"], parent=_Anc(ME, ["bash"], parent=_Anc(ME, tmux)))
        with mock.patch("psutil.Process", lambda pid: own):
            self.assertTrue(tmux_backend.is_tmux_backed(123))


def _jl(rows):
    return "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows)


class TranscriptRowsTest(unittest.TestCase):
    """Beklenmeyen tipte satır `needs_ho`yu istisnayla bitiriyordu (ho kararı hiç verilmiyordu)."""

    def setUp(self):
        self.dir = _tmpdir(self)
        _reset(needs_ho)

    def _file(self, rows):
        p = self.dir / f"t{len(list(self.dir.iterdir()))}.jsonl"
        p.write_text(_jl(rows))
        return str(p)

    def test_bad_rows_skipped(self):
        rfh = {"type": "assistant", "message": {"content": [{"type": "text", "text": "## READY FOR HANDOVER"}]}}
        user = {"type": "user", "message": {"content": "iş"}}
        cases = [
            # (satırlar, has_real_user_turn, handover_done)
            (["[]", user], True, False),
            ([user, "123", rfh], True, True),
            ([{"type": "user", "message": None}], False, False),
            ([{"type": "user", "message": "x"}, rfh], False, True),
            ([{"type": "user", "message": {"content": [{"type": "text", "text": 1}]}}], False, False),
            ([user, {"type": "assistant", "message": {"content": [{"type": "text", "text": None}]}}], True, False),
            # dizgi olmayan metin bloğu yok sayılır, aynı satırın dizgi bloğu sayılır
            ([user, {"type": "assistant", "message": {"content": [{"type": "text", "text": 5},
                                                                 {"type": "text", "text": "\nREADY FOR HANDOVER"}]}}],
             True, True),
            ([{"type": "user", "message": {"content": [{"type": "text", "text": "y"}, {"type": "text", "text": 1}]}}],
             True, False),
        ]
        for rows, real, done in cases:
            p = self._file(rows)
            with self.subTest(rows=rows):
                self.assertEqual(needs_ho.has_real_user_turn(p), real)
                self.assertEqual(needs_ho.handover_done(p), done)
        self.assertGreater(needs_ho._skipped["transcript_row"], 0)

    def test_needs_ho_decides_instead_of_raising(self):
        p = self._file(["[]", {"type": "user", "message": {"content": "iş"}}])
        with mock.patch.object(needs_ho, "repo_dirty", lambda cwd: False), \
                mock.patch.object(needs_ho, "repo_untracked_count", lambda cwd: 0), \
                mock.patch.object(needs_ho, "repo_committed_since", lambda cwd: False):
            self.assertTrue(needs_ho.needs_ho("s", "/x", p))


class BaselineAtomicTest(unittest.TestCase):
    def test_baseline_written_via_replace(self):
        d = _tmpdir(self) / "baselines"
        git = {("rev-parse", "--show-toplevel"): "/repo", ("rev-parse", "HEAD"): "abc123"}
        real_replace = os.replace
        seen = []

        def spy(src, dst):
            seen.append(str(dst))
            return real_replace(src, dst)

        with mock.patch.object(needs_ho, "_BASELINE_DIR", d), \
                mock.patch.object(needs_ho, "_git", lambda cwd, *a: git.get(a, "")), \
                mock.patch("os.replace", spy):
            needs_ho.repo_baseline_set("/repo")
            self.assertEqual(needs_ho._repo_baseline_get("/repo"), "abc123")
        key = hashlib.sha1(b"/repo").hexdigest()
        self.assertEqual([p.name for p in d.iterdir()], [key])     # geçici dosya kalmadı
        self.assertEqual(seen, [str(d / key)])


class SidPathTest(unittest.TestCase):
    """`jsonl_path_for`: `sid` içindeki `/`/`..` transkript dizininin dışına çıkıyordu."""

    def test_sid_with_path_parts_is_not_joined(self):
        root = _tmpdir(self)
        proj = root / cp._encode_cwd("/w/p")
        proj.mkdir()
        (root / "x.jsonl").write_text("")
        (proj / "ok.jsonl").write_text("")
        (proj / "sub").mkdir()
        (proj / "sub" / "y.jsonl").write_text("")
        with mock.patch.object(cp, "PROJECTS_DIR", str(root)), \
                mock.patch.object(cp, "find_latest_jsonl", lambda cwd: None):
            self.assertEqual(cp.jsonl_path_for("/w/p", "ok"), proj / "ok.jsonl")
            for sid in ["../x", "sub/y", "/abs", "..", ".", "a\x00b"]:
                with self.subTest(sid=sid):
                    self.assertIsNone(cp.jsonl_path_for("/w/p", sid))


def _urow(mid, model="claude-sonnet-5-5", out=5, rid="r", **extra):
    r = {"type": "assistant", "requestId": rid,
         "message": {"id": mid, "model": model, "usage": {"input_tokens": 1, "output_tokens": out}}}
    r.update(extra)
    return json.dumps(r) + "\n"


class UsageRowsTest(unittest.TestCase):
    """Dizgi olmayan model / hashlenemeyen tur anahtarı / alt ajan dosyasındaki bozuk satır tüm toplamı `None` yapıyordu."""

    def setUp(self):
        su._files.clear()
        su._summaries.clear()
        _reset(su)
        self.addCleanup(su._files.clear)
        self.addCleanup(su._summaries.clear)
        self.dir = _tmpdir(self)
        self.main = str(self.dir / "s.jsonl")

    def _main(self, text):
        Path(self.main).write_text(text)

    def test_bad_rows_skipped_on_first_call(self):
        cases = {
            "model": (_urow("m1") + _urow("m2", model=5) + _urow("m3"), 2),
            "list_id": (_urow("m1") + _urow([1]), 1),
            "list_rid": (_urow("m1", rid=[1]) + _urow("m2"), 1),
            "dict_uuid": (_urow(None, uuid={"a": 1}) + _urow("m2"), 1),
        }
        for name, (text, turns) in cases.items():
            with self.subTest(name):
                su._files.clear()
                self._main(text)
                u = su.usage_for_path(self.main)
                self.assertIsNotNone(u)
                self.assertEqual(u["turns"], turns)
                self.assertEqual(su.usage_for_path(self.main)["turns"], turns)
        self.assertEqual(su._skipped["usage_row"], 4)

    def test_bad_subagent_row_does_not_blank_total(self):
        self._main(_urow("m1"))
        sub = self.dir / "s" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.jsonl").write_text(_urow("q", model=[1]) + _urow("q2", out=7))
        u = su.usage_for_path(self.main)
        self.assertEqual((u["turns"], u["subagents"]["n"], u["subagents"]["turns"], u["subagents"]["out"]), (1, 1, 1, 7))

    def test_day_usage_file_survives_bad_row(self):
        from claudeops import day_usage
        from datetime import datetime, timedelta
        now = datetime.now()
        ts = now.astimezone().isoformat()
        p = self.dir / "d.jsonl"
        p.write_text(_urow("a", timestamp=ts) + _urow("b", model={"x": 1}, timestamp=ts) + _urow("c", timestamp=ts))
        turns = day_usage._file_turns(str(p), now - timedelta(hours=1), now + timedelta(hours=1))
        self.assertEqual(len(turns), 2)

    def test_thread_start_failure_does_not_lock_path(self):
        self._main(_urow("m1"))
        with mock.patch.object(su.threading.Thread, "start", side_effect=RuntimeError("can't start new thread")):
            self.assertIsNone(su.cached_usage_for_path(self.main))
        self.assertFalse(su._summaries[self.main]["running"])
        done = threading.Event()
        real_refresh = su._refresh

        def refresh(main):
            real_refresh(main)
            done.set()

        with mock.patch.object(su, "_refresh", refresh):
            su.cached_usage_for_path(self.main)
            self.assertTrue(done.wait(5), "yenileme hiç başlamadı")
        self.assertEqual(su.cached_usage_for_path(self.main)["turns"], 1)

    def test_shrinking_file_does_not_evict_another_when_full(self):
        paths = [str(self.dir / f"f{i}.jsonl") for i in range(3)]
        for p in paths:
            Path(p).write_text(_urow("a") + _urow("b"))
        with mock.patch.object(su, "_MAX_CACHED_FILES", 3):
            for p in paths:
                su.usage_for_path(p)
            Path(paths[1]).write_text(_urow("z"))
            self.assertEqual(su.usage_for_path(paths[1])["turns"], 1)
            self.assertEqual(list(su._files), paths)


if __name__ == "__main__":
    unittest.main()
