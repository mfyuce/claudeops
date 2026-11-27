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
_REAL_KILL = os.kill       # setUp sahtesinden önce
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

    def test_overflowing_pid_is_skipped_and_counted(self):
        """Birleştirme kapısı: `os.kill(2**32, 0)` / `int(inf)` OverflowError ile tüm taramayı (/api/status, cops list) düşürüyordu."""
        def kill(pid, sig):
            if not -2**31 <= pid < 2**31:
                return _REAL_KILL(pid, sig)          # C int'e sığmayan pid: sinyal gönderilmeden OverflowError
            self.killed.append(pid)

        me = os.getpid()
        for i, pid in enumerate([2**32, 2**31, 2**63, 2**64 + 5, "99999999999999999999999"]):
            self._write(f"o{i}.json", {"pid": pid, "name": f"taşan{i}", "cwd": "/tmp"})
        (self.sess / "inf.json").write_text('{"pid": Infinity, "name": "sonsuz", "cwd": "/tmp"}')
        (self.sess / "big.json").write_text('{"pid": 1e400, "name": "dev", "cwd": "/tmp"}')
        self._write("ok.json", {"pid": me, "name": "iyi", "cwd": "/tmp"})
        with mock.patch.object(discovery.os, "kill", kill):
            got = discovery._sessions_from_json()
        self.assertEqual(list(got), [("iyi", me)])
        self.assertEqual(discovery._skipped["session_file"], 7)


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


CT = namedtuple("CT", "user system")


class _Q:
    """`process_iter` öğesi: başka kullanıcının sürecinde pid/uids dışında HİÇBİR öznitelik istenmemeli ya da okunmamalı."""

    def __init__(self, pid, uid, name, cmd, age=7200.0, cpu=0.0, parent=None, attrs=None):
        self.pid, self._uid, self._parent = pid, uid, parent
        self._vals = {"pid": pid, "uids": UIDS(uid, uid, uid), "name": name, "cmdline": cmd, "cwd": "/tmp",
                      "create_time": 1_000_000.0 - age, "cpu_times": CT(cpu, 0.0)}
        if attrs is not None:
            extra = set(attrs) - {"pid", "uids"}
            if uid != ME and extra:
                raise AssertionError(f"başka kullanıcının süreci için uid süzgecinden önce istendi: {sorted(extra)}")
            self.info = {k: self._vals[k] for k in attrs}

    def _read(self, k):
        if self._uid != ME:
            raise AssertionError(f"başka kullanıcının {k} değeri okundu")
        return self._vals[k]

    def uids(self):
        return self._vals["uids"]

    def cmdline(self):
        return self._read("cmdline")

    def name(self):
        return self._read("name")

    def cwd(self):
        return self._read("cwd")

    def create_time(self):
        return self._read("create_time")

    def cpu_times(self):
        return self._read("cpu_times")

    def parent(self):
        return self._parent


class ForeignProcessContentTest(unittest.TestCase):
    """Birleştirme kapısı: `orphan_watch.scan_procs`/`scan_cpu_hogs` ve `web._find_gnome_terminal_server` uid süzgecinden
    ÖNCE herkesin cmdline'ını istiyordu (başka kullanıcının eski claude süreci yetim listesine pid+cmdline ile düşebilirdi)."""

    def _iter(self, procs):
        return lambda attrs=None, *a, **k: iter([p(attrs) for p in procs])

    def test_orphans_only_own_and_foreign_ancestor_not_read(self):
        from claudeops import orphan_watch as ow
        root_parent = _Q(1, OTHER, "sshd", ["sshd: x"])          # ata başka kullanıcının: cmdline'ı okunmamalı
        procs = [lambda a: _Q(10, OTHER, "claude", ["claude", "--resume", "gizli"], attrs=a),
                 lambda a: _Q(11, ME, "claude", ["claude"], parent=root_parent, attrs=a)]
        with mock.patch("psutil.process_iter", self._iter(procs)):
            got = ow.scan_procs([], now=1_000_000.0, pane_pids=set())
        self.assertEqual([p["pid"] for p in got], [11])

    def test_cpu_hogs_only_own(self):
        from claudeops import orphan_watch as ow
        prev = {"10": [0.0, 1_000_000.0 - 600, 1_000_000.0 - 7200], "11": [0.0, 1_000_000.0 - 600, 1_000_000.0 - 7200]}
        procs = [lambda a: _Q(10, OTHER, "bench", ["bench", "--gizli"], cpu=6000.0, attrs=a),
                 lambda a: _Q(11, ME, "bench", ["bench"], cpu=6000.0, attrs=a)]
        with mock.patch("psutil.process_iter", self._iter(procs)):
            hogs, _ = ow.scan_cpu_hogs(prev, now=1_000_000.0)
        self.assertEqual([h["pid"] for h in hogs], [11])

    def test_gnome_terminal_server_cmdline_read_only_for_own(self):
        from claudeops.commands import web
        gts = ["/usr/libexec/gnome-terminal-server"]
        procs = [lambda a: _Q(20, OTHER, "gnome-terminal-", gts, attrs=a),
                 lambda a: _Q(21, ME, "gnome-terminal-", gts, attrs=a)]
        with mock.patch.object(web.psutil, "process_iter", self._iter(procs)):
            self.assertEqual(web._find_gnome_terminal_server().pid, 21)


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

    def test_invalid_or_missing_sid_file_never_guesses(self):
        """Birleştirme kapısı: geçersiz sid (ya da dosyası olmayan sid) `find_latest_jsonl` tahminine düşüyordu; ortak cwd'de
        başka oturumun transkripti döner, needs_ho/usage yanlış olurdu. `find_latest_jsonl` SAHTELENMEZ: aynı dizinde gerçek
        bir "en yeni" dosya var. Tahmin yalnız sid gerçekten yokken."""
        root = _tmpdir(self)
        proj = root / cp._encode_cwd("/w/p")
        proj.mkdir()
        (proj / "ok.jsonl").write_text("")
        other = proj / "baska-oturum.jsonl"
        other.write_text("{}\n")
        os.utime(other, (2_000_000_000, 2_000_000_000))      # en yeni dosya: tahmin bunu döndürürdü
        with mock.patch.object(cp, "PROJECTS_DIR", str(root)):
            self.assertEqual(cp.jsonl_path_for("/w/p", "ok"), proj / "ok.jsonl")
            for sid in ["../baska-oturum", "a/b", "a\x00b", "yok-boyle-sid"]:
                with self.subTest(sid=sid):
                    self.assertIsNone(cp.jsonl_path_for("/w/p", sid))
            for sid in [None, ""]:
                with self.subTest(sid=sid):
                    self.assertEqual(cp.jsonl_path_for("/w/p", sid), other)


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

    def test_overflowing_token_count_does_not_blank_total(self):
        """Birleştirme kapısı (aynı taşma sınıfı): `int(inf)` OverflowError `usage_for_path`i tümden `None` yapıyordu."""
        self._main(_urow("m1", out=3) + _urow("m2").replace('"output_tokens": 5', '"output_tokens": 1e400')
                   + _urow("m3").replace('"output_tokens": 5', '"output_tokens": Infinity'))
        u = su.usage_for_path(self.main)
        self.assertIsNotNone(u)
        self.assertEqual((u["turns"], u["out"]), (3, 3))

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


class LongLineTest(unittest.TestCase):
    """Birleştirme kapısı: transkript satırı sınırsız okunuyordu (tek dev satır belleği doldurur). Sınırı aşan satır atlanır
    ve sayılır; bellek de sınırlı (satır önce tümüyle okunmaz). Sınırda kabul, sınır+1 atlanır; dosya sonundaki yarım uzun satır
    offset'i bozmaz. Gerçek sınır 64 MiB (ölçülen en uzun satır 13.234.801 bayt); testte küçük."""

    LIMIT = 200

    def setUp(self):
        self.dir = _tmpdir(self)
        su._files.clear()
        self.addCleanup(su._files.clear)
        for mod in (su, needs_ho):
            _reset(mod)
            p = mock.patch.object(mod, "_MAX_LINE_BYTES", self.LIMIT, create=True)
            p.start()
            self.addCleanup(p.stop)

    def _pad(self, row, total):
        """`row` (sonda `}` ile biten JSON) satır içeriği `total` bayt olacak biçimde doldurulur (satır sonu hariç)."""
        base = row.rstrip("\n")
        pad = total - len(base.encode()) - len(',"p":""')
        self.assertGreaterEqual(pad, 0)
        return base[:-1] + ',"p":"' + "x" * pad + '"}'

    def test_usage_limit_boundary_and_partial_tail(self):
        main = self.dir / "s.jsonl"
        at = self._pad(_urow("a", out=1), self.LIMIT)
        over = self._pad(_urow("b", out=10), self.LIMIT + 1)
        main.write_text(at + "\n" + over + "\n" + _urow("c", out=100))
        u = su.usage_for_path(str(main))
        self.assertEqual((u["turns"], u["out"]), (2, 101))
        self.assertEqual(su._skipped["usage_line_too_long"], 1)
        st = su._files[str(main)]
        self.assertEqual(st["offset"], main.stat().st_size)
        # dosya sonunda yazımı süren uzun satır: atlanır (bir kez sayılır), tamamlanınca sonrası okunur
        long_row = self._pad(_urow("d", out=1000), self.LIMIT * 5)
        with open(main, "a") as f:
            f.write(long_row[: self.LIMIT * 3])
        self.assertEqual(su.usage_for_path(str(main))["turns"], 2)
        self.assertEqual(su._skipped["usage_line_too_long"], 2)
        with open(main, "a") as f:
            f.write(long_row[self.LIMIT * 3:] + "\n" + _urow("e", out=7))
        u = su.usage_for_path(str(main))
        self.assertEqual((u["turns"], u["out"]), (3, 108))
        self.assertEqual(su._skipped["usage_line_too_long"], 2)
        # sınırda yarım satır henüz "uzun" değildir: offset başında kalır, tamamlanınca sayılır
        with open(main, "a") as f:
            f.write(self._pad(_urow("f", out=1), self.LIMIT))
        size_before = su._files[str(main)]["offset"]
        self.assertEqual(su.usage_for_path(str(main))["turns"], 3)
        self.assertEqual(su._files[str(main)]["offset"], size_before)
        with open(main, "a") as f:
            f.write("\n")
        self.assertEqual(su.usage_for_path(str(main))["turns"], 4)

    def test_usage_memory_is_bounded(self):
        main = self.dir / "m.jsonl"
        main.write_text(_urow("a") + "y" * (self.LIMIT * 50) + "\n" + _urow("b"))
        real_open = open
        sizes = []

        class Spy:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.f.close()

            def seek(self, *a):
                return self.f.seek(*a)

            def readline(self, size=-1):
                sizes.append(size)
                return self.f.readline(size)

        with mock.patch("builtins.open", lambda p, m="r", *a, **k: Spy(real_open(p, m, *a, **k))):
            u = su.usage_for_path(str(main))
        self.assertEqual(u["turns"], 2)
        bound = max(self.LIMIT + 1, su._SKIP_CHUNK)     # gerçekte parça (1 MiB) sınırın (64 MiB) altında
        self.assertTrue(sizes and all(0 < s <= bound for s in sizes), sizes[:5])

    def test_needs_ho_long_line_skipped_and_counted(self):
        user = json.dumps({"type": "user", "message": {"content": "iş"}})
        rfh = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "READY FOR HANDOVER"}]}})
        at = self._pad(user + "\n", self.LIMIT)
        over = self._pad(rfh + "\n", self.LIMIT + 1)
        p = self.dir / "t.jsonl"
        p.write_text(at + "\n" + over + "\n")
        self.assertTrue(needs_ho.has_real_user_turn(str(p)))
        self.assertFalse(needs_ho.handover_done(str(p)))         # tek RFH satırı sınırı aşıyor: atlandı
        self.assertEqual(needs_ho._skipped["transcript_line_too_long"], 1)
        p.write_text(at + "\n" + self._pad(rfh + "\n", self.LIMIT) + "\n")
        self.assertTrue(needs_ho.handover_done(str(p)))
        # yalnız uzun ve yarım son satır; ondan önceki karar korunur
        p.write_text(at + "\n" + "z" * (self.LIMIT * 3))
        self.assertTrue(needs_ho.has_real_user_turn(str(p)))
        # CR ile ayrılmış satırlar (metin kipi) sınır içinde yine ayrı satır
        p.write_text(user + "\r" + rfh + "\n")
        self.assertTrue(needs_ho.handover_done(str(p)))


class DiagSkippedTest(unittest.TestCase):
    """Birleştirme kapısı: `_skipped` sayaçları hiçbir yerde görünmüyordu. Tanılama (`/api/status` `diag`) tek bir `skipped`
    sözlüğü taşır (yeni uç yok; anahtarlar modüller arasında çakışmaz)."""

    def test_diag_carries_all_skip_counters(self):
        from claudeops.commands import web
        for mod in (discovery, needs_ho, su):
            _reset(mod)
            self.addCleanup(_reset, mod)
        discovery._skipped["session_file"] += 2
        needs_ho._skipped["transcript_row"] += 3
        needs_ho._skipped["transcript_line_too_long"] += 1
        su._skipped["usage_row"] += 4
        with mock.patch.object(web, "find_sessions", return_value=[]):
            got = web._diag_status([])["skipped"]
        self.assertEqual(got, {"session_file": 2, "transcript_row": 3, "transcript_line_too_long": 1, "usage_row": 4})
        _reset(discovery)
        _reset(needs_ho)
        _reset(su)
        with mock.patch.object(web, "find_sessions", return_value=[]):
            self.assertEqual(web._diag_status([])["skipped"], {})

    def test_diag_survives_counter_growing_while_read(self):
        """Kapı 2. tur D1: arka plan iplikleri sayacı artırırken `items()` dolaşılırsa "dictionary changed size during
        iteration" fırlar ve `skipped` sessizce boş dönerdi; sayaç kopyalanıp okunmalı."""
        from collections import Counter

        from claudeops.commands import web

        class Growing(Counter):
            def items(self):                        # dolaşım sırasında başka iplik yeni anahtar eklemiş gibi
                for k, v in super().items():
                    self["usage_line_too_long"] += 1
                    yield k, v

        for mod in (discovery, needs_ho):
            _reset(mod)
            self.addCleanup(_reset, mod)
        with mock.patch.object(su, "_skipped", Growing(usage_row=4)), \
                mock.patch.object(web, "find_sessions", return_value=[]):
            got = web._diag_status([])["skipped"]
        self.assertEqual(got, {"usage_row": 4})


if __name__ == "__main__":
    unittest.main()
