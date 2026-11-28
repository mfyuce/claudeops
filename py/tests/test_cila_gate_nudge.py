"""Fable cila ters kapısı (sahip q20261128_005532_8db8 = b): projede açık iş YALNIZ `Fable cila` maddeleri ve açık TBD varken dürtü,
keepwarm ve no_work yolları iş görmesin (hve TBD#112 her turda soruyordu); cila + TBD 0 = cila hazır, iş sayılır."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from claudeops import steward as sw
from claudeops.commands import web_steward as ws


class CilaGatedOpenWork(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.projects = {"p": sw.Project(name="p", phase="planned")}
        for pt in (mock.patch.object(ws, "_cwd_resolver", lambda: (lambda name: self.d)),
                   mock.patch.object(ws, "_todo_owned_by_other", lambda *a, **k: False)):
            pt.start()
            self.addCleanup(pt.stop)

    def write(self, todo, tbd=None):
        with open(os.path.join(self.d, "TODO.md"), "w") as f:
            f.write(todo)
        path = os.path.join(self.d, "TOBEDECIDED.md")
        if tbd is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w") as f:
                f.write(tbd)

    def count(self):
        return ws._open_work_gated_of(self.projects)("p")

    CILA = "- [ ] Fable cila: bölüm 3 (üslup)\n- [ ] Fable cila: özet\n"
    OPEN_TBD = "## Açık\n### 1) Hangi dergi?\na mı b mi?\n"

    def test_only_cila_and_open_tbd_is_no_work(self):
        self.write(self.CILA, self.OPEN_TBD)
        self.assertGreater(sw.count_open_tbd(self.OPEN_TBD), 0)
        self.assertEqual(self.count(), 0)

    def test_only_cila_and_no_open_tbd_is_cila_ready(self):
        self.write(self.CILA, "")
        self.assertEqual(self.count(), 2)
        self.write(self.CILA)                      # TBD dosyası yok
        self.assertEqual(self.count(), 2)

    def test_real_work_counts_without_cila(self):
        self.write("- [ ] testi yaz\n" + self.CILA, self.OPEN_TBD)
        self.assertEqual(self.count(), 1)

    def test_unknown_stays_unknown(self):
        self.assertIsNone(ws._open_work_gated_of({"p": sw.Project(name="p", host="uzak")})("p"))


if __name__ == "__main__":
    unittest.main()
