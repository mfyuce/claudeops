import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tempfile, unittest
from unittest import mock
from claudeops import statedocs as sd, store as S

ROSTER = "name\tcwd\tmodel\tcli\n# yorum satiri\n\ncops\t/home/x/cops\tclaude-sonnet-5-5\tclaude\n#kapali\t/home/x/k\tm\tucli\nson\t/a b/c\tm2"


class TsvTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-tsv-")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.ps = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                   mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "dual", "CLAUDEOPS_DIAG_LOG": os.path.join(self.d, "diag.log")})]
        [p.start() for p in self.ps]
        sd._SYNCED.clear()
        self.p = os.path.join(self.d, "roster.tsv")

    def tearDown(self):
        [p.stop() for p in self.ps]; self.st.close()

    def test_roundtrip_exact_and_rows(self):
        self.st.replace_tsv("roster.tsv", ROSTER)
        self.assertEqual(self.st.tsv_text("roster.tsv"), ROSTER)                  # eksik son satır sonu dahil birebir
        rows = {r["name"]: r for r in self.st.tsv_rows("roster.tsv")}
        self.assertTrue(rows["cops"]["active"]); self.assertEqual(rows["cops"]["rest"], ["/home/x/cops", "claude-sonnet-5-5", "claude"])
        self.assertFalse(rows["kapali"]["active"]); self.assertEqual(rows["son"]["rest"], ["/a b/c", "m2"])
        self.assertEqual([r["name"] for r in self.st.tsv_rows("roster.tsv", active=False)], ["yorum satiri", "kapali"])  # '# yorum' _read_tsv_raw gibi satır sayılır

    def test_replace_overwrites_and_files_isolated(self):
        self.st.replace_tsv("roster.tsv", ROSTER); self.st.replace_tsv("models.tsv", "a\tm\n")
        self.st.replace_tsv("roster.tsv", "x\t/y\tm\tclaude\n")
        self.assertEqual(self.st.tsv_text("roster.tsv"), "x\t/y\tm\tclaude\n"); self.assertEqual(self.st.tsv_text("models.tsv"), "a\tm\n")
        self.assertIsNone(self.st.tsv_text("none.tsv"))

    def test_deleted_file_clears_shadow_and_empty_file_not_rewritten(self):
        open(self.p, "w").write(ROSTER)
        sd.shadow_tsv(self.p, force=True)
        self.assertEqual(self.st.tsv_text("roster.tsv"), ROSTER)
        os.remove(self.p)
        sd.shadow_tsv(self.p, force=True)
        self.assertIsNone(self.st.tsv_text("roster.tsv"))          # silinen dosyanın gölgesi kalmaz
        open(self.p, "w").write("")
        with mock.patch.object(self.st, "replace_tsv") as rp:
            sd.shadow_tsv(self.p, force=True)                       # boş dosya + boş gölge: gereksiz yazım yok
            rp.assert_not_called()

    def test_shadow_syncs_on_change_only(self):
        open(self.p, "w").write(ROSTER)
        sd.shadow_tsv(self.p); self.assertEqual(self.st.tsv_text("roster.tsv"), ROSTER)
        self.st.replace_tsv("roster.tsv", "bozuk\n")                                # DB bozuldu, dosya imzası aynı -> dokunma
        sd.shadow_tsv(self.p); self.assertEqual(self.st.tsv_text("roster.tsv"), "bozuk\n")
        open(self.p, "a").write("\nyeni\t/z\tm\tclaude\n")                          # elle düzenleme -> eşitle
        sd.shadow_tsv(self.p); self.assertIn("yeni", self.st.tsv_text("roster.tsv"))

    def test_files_mode_and_outside_dir_and_other_names_skip(self):
        open(self.p, "w").write(ROSTER)
        with mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "files"}):
            sd.shadow_tsv(self.p, force=True)
        other = tempfile.mkdtemp(prefix="cops-tsv-o-"); q = os.path.join(other, "roster.tsv"); open(q, "w").write(ROSTER)
        sd.shadow_tsv(q, force=True)
        r = os.path.join(self.d, "other.tsv"); open(r, "w").write(ROSTER); sd.shadow_tsv(r, force=True)
        self.assertIsNone(self.st.tsv_text("roster.tsv")); self.assertIsNone(self.st.tsv_text("other.tsv"))

    def test_web_write_functions_shadow(self):
        from claudeops.commands import web
        open(self.p, "w").write("")
        web._append_tsv_line(self.p, ["a", "/x", "m", "claude"])
        self.assertEqual(self.st.tsv_text("roster.tsv"), "a\t/x\tm\tclaude\n")
        self.assertTrue(web._replace_tsv_line(self.p, "a", ["b", "/y", "m", "claude"]))
        self.assertEqual([r["name"] for r in self.st.tsv_rows("roster.tsv")], ["b"])
        self.assertEqual([r["name"] for r in web._read_tsv_raw(self.p)], ["b"])


if __name__ == "__main__":
    unittest.main()
