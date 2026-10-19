"""`cops cache`: transkriptlerden soğuk uyanış ölçümü (stdlib unittest).

Çalıştırma:  python3 py/tests/test_cache_report.py -v

Kapsadığı iş (TBD#87 öneri A'nın ölçüm kısmı): iki gerçek istek arası TTL'i (1 saat) geçen bir oturumun sonraki isteği
bağlamı yeniden yazar. Rapor bunu transkriptlerden sayar: soğuk uyanış, yeniden yazılan token, boşluk kovası, model,
oturum. Sentetik transkriptlerle sınanır; gerçek ~/.claude/projects'e, filoya ya da ağa DOKUNMAZ.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import cache_report as cr  # noqa: E402

T0 = 1_800_000_000.0


def iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def assistant(epoch, *, model="claude-sonnet-5-5", write=0, read=0, fresh=2, req="r", sidechain=False, usage=True):
    msg = {"role": "assistant", "model": model, "content": []}
    if usage:
        msg["usage"] = {"input_tokens": fresh, "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
                        "output_tokens": 5}
    return {"type": "assistant", "timestamp": iso(epoch), "isSidechain": sidechain, "requestId": req, "message": msg}


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row, separators=(",", ":"))) + "\n")


class ReadTranscriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def read(self, rows):
        p = self.dir / "proj" / "abcdef12-0000.jsonl"
        write_jsonl(p, rows)
        return cr.read_transcript(p)

    def test_real_requests_are_collected_in_file_order_with_the_session_title(self):
        tr = self.read([{"type": "custom-title", "customTitle": "ilkad"},
                        assistant(T0, write=100, req="a"), assistant(T0 + 60, read=100, req="b"),
                        {"type": "custom-title", "customTitle": "sonad"}])
        self.assertEqual(tr.name, "sonad")                              # son başlık kazanır
        self.assertEqual([(r.t, r.write, r.read) for r in tr.reqs], [(T0 + 0.0, 100, 0), (T0 + 60.0, 0, 100)])

    def test_without_a_title_the_name_is_the_sid_prefix(self):
        self.assertEqual(self.read([assistant(T0, write=1)]).name, "abcdef12")

    def test_subagent_synthetic_and_usageless_rows_are_skipped(self):
        tr = self.read([assistant(T0, write=1, req="main"),
                        assistant(T0 + 5, write=999, sidechain=True, req="sub"),
                        assistant(T0 + 6, model="<synthetic>", write=999, req="syn"),
                        assistant(T0 + 7, usage=False, req="nou"),
                        assistant(T0 + 8, write=0, read=0, fresh=0, req="zero")])
        self.assertEqual(len(tr.reqs), 1)

    def test_the_blocks_of_one_response_count_as_one_request(self):
        """Bir yanıtın düşünme/metin/araç blokları ayrı satır, aynı requestId ve usage: TEK istek."""
        tr = self.read([assistant(T0, write=500, req="same"), assistant(T0 + 1, write=500, req="same"),
                        assistant(T0 + 2, write=500, req="same"), assistant(T0 + 30, read=500, req="next")])
        self.assertEqual(len(tr.reqs), 2)

    def test_garbage_and_non_assistant_lines_are_tolerated(self):
        tr = self.read(["{not json", '{"type":"assistant"', json.dumps({"type": "user", "note": '"type":"assistant"'}),
                        assistant(T0, write=3, req="ok")])
        self.assertEqual(len(tr.reqs), 1)

    def test_a_missing_file_gives_an_empty_transcript(self):
        self.assertEqual(cr.read_transcript(self.dir / "yok.jsonl").reqs, [])


class AnalyzeTests(unittest.TestCase):
    def transcript(self, name, reqs):
        return cr.Transcript(path=f"/p/{name}.jsonl", name=name, reqs=[cr.Req(*r) for r in reqs])

    def test_a_gap_of_one_hour_or_more_is_a_cold_wake_that_rewrites_the_context(self):
        tr = self.transcript("s", [(T0, "m", 2, 50_000, 0),
                                   (T0 + 120, "m", 2, 100, 50_000),                 # sıcak
                                   (T0 + 120 + 3599, "m", 2, 100, 50_100),         # kıl payı: hâlâ sıcak
                                   (T0 + 120 + 3599 + 3600, "m", 2, 60_000, 0)])   # tam TTL: soğuk
        rep = cr.analyze([tr])
        t = rep.total
        self.assertEqual((t.requests, t.cold, t.cold_write, t.warm_write, t.read), (3, 1, 60_000, 200, 100_100))
        self.assertEqual(rep.transcripts, 1)

    def test_the_first_request_of_a_file_is_never_counted(self):
        rep = cr.analyze([self.transcript("s", [(T0, "m", 2, 1_000_000, 0)])])
        self.assertEqual(rep.total.requests, 0)

    def test_a_model_switch_while_warm_is_its_own_category_not_a_cold_wake(self):
        """Önbellek modele özgü: sıcakken `/model` yeniden yazdırır, ama zamandan değil geçişten."""
        tr = self.transcript("s", [(T0, "a", 2, 10, 0), (T0 + 60, "b", 2, 80_000, 0), (T0 + 120, "b", 2, 50, 80_000)])
        t = cr.analyze([tr]).total
        self.assertEqual((t.cold, t.switch, t.switch_write, t.cold_write), (0, 1, 80_000, 0))

    def test_a_cold_gap_with_a_model_change_counts_once_as_cold(self):
        tr = self.transcript("s", [(T0, "a", 2, 10, 0), (T0 + 7200, "b", 2, 90_000, 0)])
        t = cr.analyze([tr]).total
        self.assertEqual((t.cold, t.switch, t.cold_write), (1, 0, 90_000))

    def test_requests_are_ordered_by_time_before_pairing(self):
        tr = self.transcript("s", [(T0 + 7200, "m", 2, 70_000, 0), (T0, "m", 2, 10, 0)])
        self.assertEqual(cr.analyze([tr]).total.cold, 1)

    def test_a_custom_ttl_moves_the_cliff(self):
        tr = self.transcript("s", [(T0, "m", 2, 10, 0), (T0 + 400, "m", 2, 5_000, 0)])
        self.assertEqual(cr.analyze([tr], ttl=300).total.cold, 1)
        self.assertEqual(cr.analyze([tr], ttl=3600).total.cold, 0)

    def test_totals_split_by_model_gap_bucket_and_session(self):
        a = self.transcript("a", [(T0, "x", 2, 10, 0), (T0 + 7200, "x", 2, 100, 0), (T0 + 7200 + 30, "x", 2, 1, 100)])
        b = self.transcript("b", [(T0, "y", 2, 10, 0), (T0 + 200_000, "y", 2, 300, 0)])
        rep = cr.analyze([a, b])
        self.assertEqual((rep.by_model["x"].cold, rep.by_model["x"].cold_write), (1, 100))
        self.assertEqual((rep.by_model["y"].cold, rep.by_model["y"].cold_write), (1, 300))
        self.assertEqual(rep.by_gap["2-12 sa (SOĞUK)"][:2], [1, 100])
        self.assertEqual(rep.by_gap["> 48 sa (SOĞUK)"][:2], [1, 300])
        self.assertEqual(rep.by_gap["< 5 dk"][:3], [1, 1, 100])
        self.assertEqual(rep.by_session["a\t/p/a.jsonl"].cold, 1)

    def test_bucket_edges(self):
        table = [(0, "< 5 dk"), (299, "< 5 dk"), (300, "5-30 dk"), (3299, "30-55 dk"), (3599, "55-60 dk (kıl payı)"),
                 (3600, "1-2 sa (SOĞUK)"), (7200, "2-12 sa (SOĞUK)"), (172_800, "> 48 sa (SOĞUK)")]
        for gap, label in table:
            with self.subTest(gap=gap):
                self.assertEqual(cr.bucket_label(gap), label)


class ScanAndRenderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def make(self, project, sid, rows, age_days=0.0):
        p = self.root / project / f"{sid}.jsonl"
        write_jsonl(p, rows)
        old = T0 - age_days * 86400
        os.utime(p, (old, old))
        return p

    def rows(self, title="oturum"):
        return [{"type": "custom-title", "customTitle": title}, assistant(T0, write=10, req="a"),
                assistant(T0 + 7200, write=70_000, req="b"), assistant(T0 + 7230, read=70_000, req="c")]

    def test_only_recently_changed_transcripts_with_a_request_pair_are_scanned(self):
        self.make("-p-one", "s1", self.rows("taze"))
        self.make("-p-one", "s2", self.rows("eski"), age_days=30)
        self.make("-p-two", "s3", [assistant(T0, write=5, req="solo")])            # tek istek: çift yok
        names = sorted(t.name for t in cr.scan(root=str(self.root), days=7, now=T0 + 10))
        self.assertEqual(names, ["taze"])

    def test_the_project_filter_matches_the_directory_name(self):
        self.make("-home-x-alpha", "s1", self.rows("a"))
        self.make("-home-x-beta", "s2", self.rows("b"))
        names = [t.name for t in cr.scan(root=str(self.root), days=7, now=T0 + 10, project="beta")]
        self.assertEqual(names, ["b"])

    def test_exclude_remote_skips_imported_remote_transcripts_only_when_asked(self):
        self.make("-home-x-remote-ulak31-alpha", "s1", self.rows("uzak"))
        self.make("-home-x-alpha", "s2", self.rows("yerel"))
        both = sorted(t.name for t in cr.scan(root=str(self.root), days=7, now=T0 + 10))
        self.assertEqual(both, ["uzak", "yerel"])
        local = [t.name for t in cr.scan(root=str(self.root), days=7, now=T0 + 10, exclude_remote=True)]
        self.assertEqual(local, ["yerel"])

    def test_a_missing_root_scans_nothing(self):
        self.assertEqual(list(cr.scan(root=str(self.root / "yok"), days=7, now=T0)), [])

    def test_the_report_names_the_numbers_and_the_worst_session(self):
        self.make("-p", "s1", self.rows("pahali"))
        text = cr.render(cr.analyze(cr.scan(root=str(self.root), days=7, now=T0 + 10)), days=7)
        self.assertIn("1 transkript", text)
        self.assertIn("pahali", text)
        self.assertIn("70K", text)                      # soğukta yeniden yazılan
        self.assertIn("2-12 sa (SOĞUK)", text)
        self.assertIn("%100", text)                     # tüm yazmanın soğuk payı: 70000 / (70000 + 0 warm_write)

    def test_an_empty_report_says_so_instead_of_crashing(self):
        text = cr.render(cr.analyze([]), days=7)
        self.assertIn("hiç istek çifti bulunamadı", text)

    def test_human_numbers(self):
        self.assertEqual([cr.human(n) for n in (0, 999, 1000, 23_400_000, 3_800_000_000)], ["0", "999", "1K", "23.4M", "3.8G"])


if __name__ == "__main__":
    unittest.main()
