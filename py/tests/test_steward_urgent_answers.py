"""11 Kas acil: tur loop_guard kesintisi süreli + yeni madde hemen sıfırlar; iletilemeyen cevap TOBEDECIDED.md'ye yazılır; uzak/klasörsüz = bildirim."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


def _tour(items):
    return [sw.Action("tour", "brain", f"{len(items)} madde", {"items": items})]


V = [sw.SessionView(name="brain", running=True, cwd="/w", cli="claude", last_assistant="tamam")]
SAME = [{"kind": "routine", "id": "q1", "name": "p"}]


class TourPause(unittest.TestCase):
    def _fill(self):
        st, t = {}, 1000.0
        for i in range(9):
            out, st = sw.loop_guard(_tour(SAME), V, st, t + i)
        return st, t + 9

    def test_break_is_short_and_retries(self):
        st, t = self._fill()
        rec = st["loop_guard"]["tour|brain"]
        self.assertAlmostEqual(rec["until"] - (t - 1), sw.LOOP_PAUSE_TOUR_SECONDS, delta=2)
        self.assertLessEqual(sw.LOOP_PAUSE_TOUR_SECONDS, 3600)
        out, _ = sw.loop_guard(_tour(SAME), V, st, t + 60)                   # kesinti içinde: atlanır
        self.assertEqual(out, [])
        out, st2 = sw.loop_guard(_tour(SAME), V, st, t + sw.LOOP_PAUSE_TOUR_SECONDS + 10)   # süre doldu: tekrar dener, sayaç 0'dan
        self.assertEqual([a.kind for a in out], ["tour"])
        self.assertEqual(st2["loop_guard"]["tour|brain"]["n"], 1)

    def test_new_item_resumes_immediately(self):
        st, t = self._fill()
        out, st2 = sw.loop_guard(_tour(SAME + [{"kind": "routine", "id": "q2", "name": "p"}]), V, st, t + 5)
        self.assertEqual([a.kind for a in out], ["tour"])
        self.assertFalse(st2["loop_guard"]["tour|brain"].get("until"))

    def test_break_payload_has_minutes(self):
        acts = []
        st = {}
        for i in range(9):
            out, st = sw.loop_guard(_tour(SAME), V, st, 1000.0 + i)
            acts += [a for a in out if a.kind == "loop_break"]
        self.assertEqual(acts[0].payload["pause_min"], int(sw.LOOP_PAUSE_TOUR_SECONDS // 60))

    def test_other_kinds_keep_long_pause(self):
        v = [sw.SessionView(name="s", running=True, cwd="/w", cli="claude", last_assistant="x")]
        st = {}
        for i in range(9):
            _, st = sw.loop_guard([sw.Action("directive", "s", "r", {})], v, st, 1000.0 + i)
        self.assertGreater(st["loop_guard"]["directive|s"]["until"] - 1008, 3600)


class TbdInsert(unittest.TestCase):
    DOC = "# TBD\n\n## Açık\n- [ ] TBD#12: Redis parolası?\n  - seçenek a\n  - seçenek b\n- [ ] TBD#13: başka\n\n## Kapalı\n"

    def test_under_matching_item(self):
        new = sw.tbd_insert_answer(self.DOC, "q1", "TBD#12 için ne yapalım?", "a olsun", "2026-11-11")
        lines = new.split("\n")
        i = next(k for k, l in enumerate(lines) if "Sahip cevabı" in l)
        self.assertIn("TBD#12", lines[i - 3])
        self.assertIn("seçenek b", lines[i - 1])
        self.assertTrue(lines[i + 1].startswith("- [ ] TBD#13"))
        self.assertIn("(2026-11-11, değnekçi) [q1]: a olsun", lines[i])

    def test_append_when_not_found_and_idempotent(self):
        new = sw.tbd_insert_answer(self.DOC, "q2", "bilinmeyen konu", "evet", "2026-11-11")
        self.assertTrue(new.rstrip().endswith("evet"))
        self.assertIn("soru: bilinmeyen konu", new)
        self.assertIsNone(sw.tbd_insert_answer(new, "q2", "bilinmeyen konu", "evet", "2026-11-11"))
        self.assertTrue(sw.tbd_insert_answer("", "q3", "x", "y", "d").startswith("- Sahip cevabı"))


class Preserve(_Tmp):
    def _q(self, project="hittite"):
        return sw.Question(id="q9", project=project, text="TBD#5 yapalım mı?", answer="evet yapalım", status="answered", created_at=1.0)

    def test_local_written_and_committed_only_that_file(self):
        with tempfile.TemporaryDirectory() as d:
            for c in (["git", "init", "-q", d], ["git", "-C", d, "config", "user.email", "a@b"], ["git", "-C", d, "config", "user.name", "n"]):
                subprocess.run(c, check=True)
            open(os.path.join(d, "TOBEDECIDED.md"), "w").write("- [ ] TBD#5: karar\n")
            open(os.path.join(d, "other.txt"), "w").write("x")
            subprocess.run(["git", "-C", d, "add", "TOBEDECIDED.md"], check=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", "i"], check=True)
            open(os.path.join(d, "other.txt"), "w").write("dirty-not-committed")
            saved = ws._cwd_resolver
            ws._cwd_resolver = lambda: (lambda n: d)
            try:
                r = ws._preserve_undelivered_answer(self._q(), sw.Config(), None, {})
            finally:
                ws._cwd_resolver = saved
            self.assertEqual(r, "written")
            txt = open(os.path.join(d, "TOBEDECIDED.md")).read()
            self.assertIn("Sahip cevabı", txt)
            self.assertIn("evet yapalım", txt)
            files = subprocess.run(["git", "-C", d, "show", "--stat", "--format=%s", "HEAD"], capture_output=True, text=True).stdout
            self.assertIn("TOBEDECIDED.md", files)
            self.assertNotIn("other.txt", files)
            self.assertEqual(subprocess.run(["git", "-C", d, "status", "--porcelain"], capture_output=True, text=True).stdout.strip(), "?? other.txt")

    def test_remote_and_no_folder_notify(self):
        sent = []
        saved = (ws._notify, ws._cwd_resolver)
        ws._notify = lambda cfg, text, click="": sent.append(text) or True
        ws._cwd_resolver = lambda: (lambda n: "")
        try:
            self.assertEqual(ws._preserve_undelivered_answer(self._q(), sw.Config(), None, {}), "no_folder")
            rem = {"hittite": sw.Project(name="hittite", host="ulak_31")}
            self.assertEqual(ws._preserve_undelivered_answer(self._q(), sw.Config(), None, rem), "remote")
        finally:
            ws._notify, ws._cwd_resolver = saved
        self.assertEqual(len(sent), 2)
        self.assertTrue(all("YAZILMADI" in t and "evet yapalım" in t for t in sent))


if __name__ == "__main__":
    unittest.main()
