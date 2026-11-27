"""TBD#368 (b): bozuk kayıt atlanıp loglanır, planlayıcı/özet/maliyet düşmez; bozuk depoya yazım reddedilir."""
import dataclasses
import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review, steward as sw  # noqa: E402

T = review.ReviewTarget("evren", "m1", "m1")


class _Logged(unittest.TestCase):
    def setUp(self):
        getattr(review, "_BAD_SEEN", set()).clear()
        p = mock.patch.object(review, "diag_log", create=True)
        self.log = p.start()
        self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def whats(self):
        return [c.kwargs.get("what") for c in self.log.call_args_list]


class BadRecordTest(_Logged):
    def test_blocked_modes_skips_bad_until(self):
        hist = {"blocks": {"evren": {"until": "yarın"}, "codex": {"until": [1]}, "claude": {"until": 200}}}
        self.assertEqual(review.blocked_modes(hist, 100.0), ["claude"])
        self.assertEqual(self.whats(), ["blocks.until", "blocks.until"])

    def test_same_bad_record_logged_once(self):
        hist = {"blocks": {"evren": {"until": "x"}}}
        review.blocked_modes(hist, 1.0)
        review.blocked_modes(hist, 1.0)
        self.assertEqual(self.log.call_count, 1)

    def test_migrate_skips_bad_started_at(self):
        good = {"started_at": review.R10_SUB_SINCE + 1}
        hist = {"pairs": {"a|claude/s": {"started_at": "dün"}, "b|claude/s": good}}
        self.assertEqual(review.migrate_r10_sub(hist), 1)
        self.assertEqual(sorted(hist["pairs"]), ["a|claude/s", "b|claude/s-sub"])
        self.assertEqual(self.whats(), ["pairs.started_at"])

    def test_requeue_skips_bad_numbers(self):
        base = {"state": "verify_sent", "verify_session": "s"}
        data = {"a": dict(base, verify_sent_at="x"), "b": dict(base, verify_sent_at=1, verify_tries="iki"),
                "c": dict(base, verify_sent_at=1)}
        self.assertEqual(review.requeue_stale_verify(data, 10 ** 9), ["c"])
        self.assertEqual(data["a"]["state"], "verify_sent")
        self.assertEqual(data["b"]["state"], "verify_sent")
        self.assertEqual(self.whats(), ["findings.verify_sent_at", "findings.verify_tries"])

    def test_non_object_pair_record_is_not_an_attempt(self):
        for rec in ("abc", 5, [1]):
            self.assertFalse(review.counts_as_attempt(rec), rec)
        self.assertTrue(review.counts_as_attempt(None))      # kayıt yok: eski davranış
        self.assertIn("pairs.record", self.whats())

    def test_update_pair_replaces_non_object_record(self):
        paths = _tmp_paths(self.dir)
        review.save_history(paths, {"pairs": {review.pair_key("p", T): "bozuk"}, "runs": []})
        rec = review.update_pair(paths, "p", T, status="running", started_at=5.0)
        self.assertEqual((rec["status"], rec["attempts"]), ("running", 1))
        self.assertIn("pairs.record", self.whats())

    def test_reconcile_blocks_with_bad_until(self):
        hist = {"blocks": {"copilot": {"until": "x"}}}
        self.assertEqual(review.reconcile_copilot_blocks(hist, (99.0, 500.0, "d"), 95.0, 1.0), ["copilot"])
        self.assertEqual(hist["blocks"]["copilot"]["until"], 500.0)
        key = "agy/gemini-3-pro"
        hist = {"blocks": {key: {"until": "x"}}}
        usage = {review.agy_pool("gemini-3-pro"): {"weekly": (0.0, 900.0)}}
        self.assertEqual(review.reconcile_agy_blocks(hist, usage, [], 1.0), [key])
        self.assertEqual(hist["blocks"][key]["until"], 900.0)

    def _usage(self, lines):
        d = os.path.join(self.dir, "p", "anthropic", "m", "ts")
        os.makedirs(d)
        f = os.path.join(d, "ts.usage.jsonl")
        with open(f, "wb") as fh:
            fh.write(b"\n".join(lines) + b"\n")
        return f

    def test_usage_summary_skips_bad_seconds(self):
        def req(sec):
            return ('{"event":"request","seconds":%s,"usage":{"prompt_tokens":7}}' % sec).encode()
        self._usage([req('"uzun"'), req("[1]"), req("2"), b'{"event":"request","usage":{"prompt_tokens":Infinity}}'])
        row = review.usage_summary(self.dir)[0]
        self.assertEqual((row["requests"], row["seconds"], row["prompt_tokens"]), (1, 2.0, 7))
        self.assertIn("usage.record", self.whats())

    def test_usage_cost_skips_non_utf8_line(self):
        good = b'{"usage":{"input_tokens":1000000,"output_tokens":0}}'
        f = self._usage([b"\xff\xfe bozuk", good])
        self.assertAlmostEqual(review.usage_cost_usd(f, "sonnet-5-5"), 2.0)
        self.assertIn("usage.line", self.whats())


def _tmp_paths(root):
    return dataclasses.replace(sw.paths_for("reviewer"), root=root, lock=os.path.join(root, ".lock"),
                               review_pool=os.path.join(root, "review_pool.json"),
                               review_history=os.path.join(root, "review_history.json"),
                               findings=os.path.join(root, "findings.json"), reviews=os.path.join(root, "reviews"))


class CorruptStoreTest(_Logged):
    """Bozuk (okunamayan ya da yanlış biçimli) depo okunurken boş sayılır, üstüne YAZILMAZ."""

    CASES = (("review_pool", b"{bozuk", "pool"), ("review_pool", b'{"projects": []}', "pool"),
             ("review_history", b"{bozuk", "history"), ("review_history", b"[1]", "history"),
             ("review_history", b'{"pairs": 3}', "history"), ("review_history", b'{"runs": {}}', "history"),
             ("review_history", b"\xff\xfe", "history"),
             ("findings", b"{bozuk", "findings"), ("findings", b"[]", "findings"))

    def test_write_refused_and_file_untouched(self):
        paths = _tmp_paths(self.dir)
        save = {"pool": lambda: review.save_pool(paths, {"projects": {}}),
                "history": lambda: review.save_history(paths, {"pairs": {}, "runs": []}),
                "findings": lambda: review.save_findings(paths, {})}
        for attr, raw, kind in self.CASES:
            with self.subTest(attr=attr, raw=raw):
                f = getattr(paths, attr)
                with open(f, "wb") as fh:
                    fh.write(raw)
                with self.assertRaises(review.StoreCorrupt):
                    save[kind]()
                with open(f, "rb") as fh:
                    self.assertEqual(fh.read(), raw)
        self.assertIn("store", self.whats())

    def test_decide_on_corrupt_findings_names_the_store_not_the_finding(self):
        paths = _tmp_paths(self.dir)
        for raw in (b"{bozuk", b"[]"):
            with open(paths.findings, "wb") as fh:
                fh.write(raw)
            res = review.decide_finding(paths, "f1", "approve", 1.0)
            self.assertFalse(res["ok"])
            self.assertIn("bozuk depo", res["error"])
            with open(paths.findings, "rb") as fh:
                self.assertEqual(fh.read(), raw)
        with open(paths.findings, "wb") as fh:
            fh.write(b"{}")
        self.assertEqual(review.decide_finding(paths, "f1", "approve", 1.0)["error"], "unknown finding: f1")

    def test_update_pair_refused_on_corrupt_history(self):
        paths = _tmp_paths(self.dir)
        with open(paths.review_history, "w") as fh:
            fh.write("{bozuk")
        with self.assertRaises(review.StoreCorrupt):
            review.update_pair(paths, "p", T, status="running", started_at=1.0)

    def test_missing_and_healthy_stores_are_written(self):
        paths = _tmp_paths(self.dir)
        for _ in range(2):      # ilk: dosya yok; ikinci: sağlam dosya
            review.save_pool(paths, {"projects": {}})
            review.save_history(paths, {"pairs": {}, "runs": []})
            review.save_findings(paths, {})
        with open(paths.findings, "w") as fh:
            fh.write("{}")
        review.save_findings(paths, {"a": {}})
        self.assertEqual(review.load_findings(paths), {"a": {}})

    def test_corrupt_backup_not_repeated(self):
        f = os.path.join(self.dir, "x.json")
        with open(f, "w") as fh:
            fh.write("{bozuk")
        with mock.patch.object(sw.time, "time", side_effect=[1000.0, 2000.0, 3000.0]):
            for _ in range(3):
                sw._corrupt_backup(f)
        self.assertEqual(len(glob.glob(f + ".corrupt-*")), 1)
        with open(f, "w") as fh:
            fh.write("{baska bozuk icerik")
        sw._corrupt_backup(f)
        self.assertEqual(len(glob.glob(f + ".corrupt-*")), 2)


if __name__ == "__main__":
    unittest.main()
