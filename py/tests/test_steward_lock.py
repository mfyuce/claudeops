"""Değnekçi kilitleri ve sahiplik talebi (çoklu değnekçi P1b): kimlik başına `.lock` flock, `.ownership.lock`,
iki SÜREÇLİ yarış, çakışma, zaman aşımı. Hepsi geçici dizinde (`steward_testlib._Tmp`)."""
import fcntl
import multiprocessing
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

N = 25


def _raw(path):
    with open(path, "rb") as f:
        return f.read()


def _worker_projects(sid, tag, barrier, out):
    """Ayrı süreç: kendi adlarını + ortak bir projenin notunu güncelle (hepsi AYNI projects.json)."""
    try:
        barrier.wait(10)
        for i in range(N):
            sw.upsert_project(f"{tag}{i}", paths=sid, goal=f"g{i}")
        out.put("ok")
    except BaseException as e:   # noqa: BLE001
        out.put(f"err:{type(e).__name__}:{e}")


def _worker_questions(tag, barrier, out):
    try:
        barrier.wait(10)
        for i in range(N):
            sw.add_question("kitap", f"{tag} soru {i}?")
            sw.add_idea(f"{tag} fikir {i}")
        out.put("ok")
    except BaseException as e:   # noqa: BLE001
        out.put(f"err:{type(e).__name__}:{e}")


def _worker_claim(sid, name, barrier, out):
    try:
        barrier.wait(10)
        sw.upsert_project(name, paths=sid, goal=sid)
        out.put(("won", sid))
    except sw.OwnedElsewhere as e:
        out.put(("lost", sid, e.owner))
    except BaseException as e:   # noqa: BLE001
        out.put(("err", sid, f"{type(e).__name__}:{e}"))


def _run(ctx, targets):
    """Her hedefi ayrı süreçte başlat; hepsi `barrier`de buluşur. Dönen: her sürecin `out` mesajı."""
    barrier = ctx.Barrier(len(targets))
    out = ctx.Queue()
    procs = [ctx.Process(target=t, args=a + (barrier, out)) for t, a in targets]
    for p in procs:
        p.start()
    res = [out.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(30)
        assert p.exitcode == 0, p.exitcode
    return res


class LockRaceTest(_Tmp):
    """Fork bağlamı: `_Tmp` yama sabitleri çocuk süreçlere geçer."""
    ctx = multiprocessing.get_context("fork")

    def test_two_processes_upsert_same_projects_json_lose_nothing(self):
        res = _run(self.ctx, [(_worker_projects, ("default", "a")), (_worker_projects, ("default", "b")),
                              (_worker_projects, ("default", "c"))])
        self.assertEqual(res, ["ok"] * 3)
        names = set(sw.load_projects())
        self.assertEqual(names, {f"{t}{i}" for t in "abc" for i in range(N)})

    def test_two_processes_questions_and_ideas_lose_nothing(self):
        sw.upsert_project("kitap")
        res = _run(self.ctx, [(_worker_questions, ("x",)), (_worker_questions, ("y",))])
        self.assertEqual(res, ["ok"] * 2)
        self.assertEqual({q.text for q in sw.load_questions()},
                         {f"{t} soru {i}?" for t in "xy" for i in range(N)})
        self.assertEqual({i.text for i in sw.load_ideas()},
                         {f"{t} fikir {i}" for t in "xy" for i in range(N)})

    def test_two_processes_claim_same_name_exactly_one_winner(self):
        for rnd in range(5):
            name = f"ortak{rnd}"
            res = _run(self.ctx, [(_worker_claim, ("default", name)), (_worker_claim, ("kitap", name))])
            won = [r for r in res if r[0] == "won"]
            lost = [r for r in res if r[0] == "lost"]
            self.assertEqual((len(won), len(lost)), (1, 1), res)
            self.assertEqual(lost[0][2], won[0][1])
            owners = [s for s in ("default", "kitap") if name in sw.load_projects(s)]
            self.assertEqual(owners, [won[0][1]])


class OwnershipTest(_Tmp):
    def test_default_behaviour_unchanged_single_identity(self):
        p = sw.upsert_project("kitap", phase="planning", goal="g")
        self.assertEqual((p.name, p.phase, p.goal), ("kitap", "planning", "g"))
        p2 = sw.upsert_project("kitap", goal="g2")          # aynı kimlikte yeniden yazım serbest
        self.assertEqual((p2.phase, p2.goal, p2.created_at), ("planning", "g2", p.created_at))
        self.assertTrue(sw.remove_project("kitap"))
        self.assertFalse(sw.remove_project("kitap"))

    def test_second_identity_cannot_claim_existing_name(self):
        sw.upsert_project("kitap", goal="default")
        with self.assertRaises(sw.OwnedElsewhere) as cm:
            sw.upsert_project("kitap", paths="dergi", goal="b")
        self.assertEqual(cm.exception.owner, "default")
        self.assertIsInstance(cm.exception, ValueError)
        self.assertEqual(sw.load_projects("dergi"), {})
        self.assertEqual(sw.load_projects()["kitap"].goal, "default")

    def test_default_cannot_claim_name_owned_by_other_identity(self):
        sw.upsert_project("dergi", paths="b")
        with self.assertRaises(sw.OwnedElsewhere) as cm:
            sw.upsert_project("dergi")
        self.assertEqual(cm.exception.owner, "b")
        self.assertEqual(sw.load_projects(), {})
        sw.upsert_project("dergi", paths="b", goal="yine")   # sahibi güncelleyebilir
        self.assertEqual(sw.load_projects("b")["dergi"].goal, "yine")

    def test_name_free_again_after_remove(self):
        sw.upsert_project("kitap")
        self.assertTrue(sw.remove_project("kitap"))
        sw.upsert_project("kitap", paths="b")
        self.assertIn("kitap", sw.load_projects("b"))

    def test_rejected_claim_writes_nothing_for_second_identity(self):
        sw.upsert_project("kitap")
        with self.assertRaises(sw.OwnedElsewhere):
            sw.upsert_project("kitap", paths="b")
        self.assertFalse(os.path.exists(sw.paths_for("b").projects))

    def test_project_owner_ignores_exclude_and_invalid_dirs(self):
        sw.upsert_project("kitap", paths="b")
        os.makedirs(os.path.join(sw.STEWARD_DIR, "stewards", "Bad1"))
        self.assertEqual(sw.project_owner("kitap"), "b")
        self.assertEqual(sw.project_owner("kitap", exclude="b"), "")
        self.assertEqual(sw.project_owner("yok"), "")


class LockTimeoutTest(_Tmp):
    def _hold(self, path):
        """Başka bir açık dosya tanımıyla kilidi tut (kilit sahibi süreç gibi davranır)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)
        return fd

    def test_timeout_raises_not_silent(self):
        self._hold(sw.paths_for().lock)
        t0 = time.monotonic()
        with self.assertRaises(sw.LockTimeout):
            with sw.steward_lock(timeout=0.3):
                self.fail("kilit alınmamalıydı")
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)
        self.assertLess(time.monotonic() - t0, 3)

    def test_write_paths_raise_and_leave_file_untouched(self):
        sw.upsert_project("kitap", goal="eski")
        before = _raw(sw.PROJECTS_JSON)
        self._hold(sw.paths_for().lock)
        with mock.patch.object(sw, "LOCK_TIMEOUT", 0.2):
            for call in (lambda: sw.upsert_project("kitap", goal="yeni"), lambda: sw.remove_project("kitap"),
                         lambda: sw.add_idea("x"), lambda: sw.add_question("kitap", "s?"),
                         lambda: sw.save_state({"a": 1}), lambda: sw.answer_question("q1", "c")):
                with self.assertRaises(sw.LockTimeout):
                    call()
        self.assertEqual(_raw(sw.PROJECTS_JSON), before)
        self.assertEqual((sw.load_ideas(), sw.load_questions(), sw.load_state()), ([], [], {}))

    def test_ownership_lock_timeout_blocks_upsert_of_any_identity(self):
        self._hold(os.path.join(sw.STEWARD_DIR, ".ownership.lock"))
        with mock.patch.object(sw, "LOCK_TIMEOUT", 0.2):
            for sid in (None, "b"):
                with self.assertRaises(sw.LockTimeout):
                    sw.upsert_project("kitap", paths=sid)
        self.assertEqual((sw.load_projects(), sw.load_projects("b")), ({}, {}))

    def test_locks_are_per_identity(self):
        self._hold(sw.paths_for("b").lock)
        with mock.patch.object(sw, "LOCK_TIMEOUT", 0.2):
            sw.add_idea("default akar")                  # başka kimliğin kilidi default'u bloklamaz
            with self.assertRaises(sw.LockTimeout):
                sw.add_idea("b", paths="b")

    def test_lock_released_after_timeout_and_after_exception(self):
        fd = self._hold(sw.paths_for().lock)
        with self.assertRaises(sw.LockTimeout):
            sw.steward_lock(timeout=0.1).__enter__()
        fcntl.flock(fd, fcntl.LOCK_UN)
        with self.assertRaises(KeyError):
            with sw.steward_lock(timeout=0.5):
                raise KeyError("x")
        with sw.steward_lock(timeout=0.5):               # istisnadan sonra kilit serbest
            pass


class ReentrancyTest(_Tmp):
    def test_same_thread_can_nest_same_lock(self):
        with sw.steward_lock(timeout=0.3):
            with sw.steward_lock(timeout=0.3):
                with sw.ownership_lock(timeout=0.3), sw.ownership_lock(timeout=0.3):
                    sw.upsert_project("kitap")           # içeride yine kilit alır: kilitlenmez
                    sw.add_idea("i")
        self.assertIn("kitap", sw.load_projects())

    def test_other_thread_blocked_until_release(self):
        got = []

        def other():
            try:
                with sw.steward_lock(timeout=0.3):
                    got.append("acquired")
            except sw.LockTimeout:
                got.append("timeout")

        with sw.steward_lock():
            with sw.steward_lock():
                t = threading.Thread(target=other)
                t.start()
                t.join()
            self.assertEqual(got, ["timeout"])           # iç çıkış dış kilidi bırakmaz
        t = threading.Thread(target=other)
        t.start()
        t.join()
        self.assertEqual(got, ["timeout", "acquired"])


if __name__ == "__main__":
    unittest.main()
