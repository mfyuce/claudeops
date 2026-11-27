"""TBD#422 (sahip, 27 Kas, (a)): inceleme API bütçe kapısı günlük dolar tavanıyla (`ucli_cost._ledger_problem`) aynı ret
kuralını uygular: sayılamayan harcama varsa anthropic hedefi planlanmaz. Olmayan dosya ve ayrıştırılamayan (yarım
yazılmış) satır sorun değildir. Bütçe kapalıyken davranış değişmez. Rust eşi: `cops-providers` `tests/usage_two_copies.rs`."""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv                       # noqa: E402
from claudeops.commands import web_review as wr          # noqa: E402

GOOD = json.dumps({"event": "request", "usage": {"input_tokens": 1000, "output_tokens": 500}}) + "\n"
ROOT = os.geteuid() == 0


class _Tree(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.reviews = os.path.join(self.dir, "reviews")
        os.makedirs(self.reviews)
        self.events = []
        for p in (mock.patch.object(rv, "diag_log", lambda *a, **k: None),
                  mock.patch.object(wr.sw, "log_event", lambda event, **k: self.events.append((event, k)))):
            p.start()
            self.addCleanup(p.stop)
        rv._BAD_SEEN.clear()
        self.addCleanup(rv._BAD_SEEN.clear)

    def path(self, *parts):
        return os.path.join(self.reviews, *parts)

    def log(self, data=GOOD, name="a.usage.jsonl", proj="p"):
        path = self.path(proj, "anthropic", "claude-sonnet-5-5", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def lock(self, path, mode=0):
        old = os.stat(path).st_mode & 0o7777
        os.chmod(path, mode)
        self.addCleanup(os.chmod, path, old)

    def gate(self, cap=100.0):
        """True = anthropic hedefi planlanabilir."""
        targets = [rv.ReviewTarget("anthropic", "claude-haiku-5-5", "claude-haiku-5-5", "low"),
                   rv.ReviewTarget("evren", "m", "m", "")]
        got = wr.anthropic_filter(types.SimpleNamespace(reviews=self.reviews),
                                  types.SimpleNamespace(review_anthropic_budget_usd=cap), targets)
        self.assertIn(targets[1], got)
        return targets[0] in got

    def refused(self, why, where):
        self.events.clear()
        self.assertFalse(self.gate(), why)
        self.assertEqual([e for e, _ in self.events], ["review_anthropic_budget_unverifiable"])
        data = self.events[0][1]
        self.assertEqual(data["reason"], f"{where}: {why}")
        self.assertIn(data["reason"], data["message"])
        self.assertNotIn("spent", data)              # anlamsız "harcama 1e18" yazılmaz
        self.assertEqual(rv.anthropic_spent_usd(self.reviews), rv._UNCOUNTABLE_SPENT_USD)
        self.assertFalse(self.gate(cap=1e30), why)   # sınır nöbetçi değerden büyük olsa da kapalı

    def open_(self, spent_positive=True):
        self.events.clear()
        self.assertTrue(self.gate())
        self.assertEqual(self.events, [])
        got = rv.anthropic_spent_usd(self.reviews)
        self.assertLess(got, 1)
        self.assertEqual(got > 0, spent_positive, got)


REL = os.path.join("p", "anthropic", "claude-sonnet-5-5")
FILE = os.path.join(REL, "a.usage.jsonl")


class Untrusted(_Tree):
    def test_an_invalid_counter(self):
        for bad in ("-1", '"5"', "true", "1e16", "NaN"):
            self.log(GOOD + '{"usage": {"input_tokens": %s}}\n' % bad)
            self.refused("geçersiz sayaç", FILE)

    def test_an_invalid_timestamp(self):
        for bad in ('"x"', "1e999", "[1]"):
            self.log('{"t": %s, "usage": {"input_tokens": 1}}\n' % bad)
            self.refused("geçersiz zaman damgası", FILE)

    def test_deep_long_number_and_long_line(self):
        for data, why in ((('{"d": ' + "[" * 600 + "]" * 600 + "}\n"), "çok derin satır"),
                          ('{"n": %s}\n' % ("9" * 4301), "çok uzun sayı"),
                          ("x" * (rv._MAX_LINE_BYTES + 1), "çok uzun satır")):
            self.log(data)
            self.refused(why, FILE)

    @unittest.skipIf(ROOT, "root dosya iznini aşar")
    def test_an_unopenable_file(self):
        self.lock(self.log())
        self.refused("okunamadı", FILE)

    @unittest.skipUnless(os.path.exists("/proc/self/mem"), "/proc yok")
    def test_a_log_that_opens_but_cannot_be_read(self):
        os.makedirs(self.path(REL))
        os.symlink("/proc/self/mem", self.path(FILE))      # normal dosya, 0. bayttan okuma EIO
        self.refused("okunamadı", FILE)

    def test_a_fifo_and_a_directory_in_place_of_a_log(self):
        os.makedirs(self.path(REL))
        os.mkfifo(self.path(FILE))
        self.refused("normal dosya değil", FILE)
        os.unlink(self.path(FILE))
        os.makedirs(self.path(FILE))
        self.refused("normal dosya değil", FILE)

    def test_a_symlink_loop_in_place_of_a_log(self):
        os.makedirs(self.path(REL))
        os.symlink("a.usage.jsonl", self.path(FILE))
        self.refused("okunamadı", FILE)

    @unittest.skipIf(ROOT, "root dizin iznini aşar")
    def test_unlistable_directories(self):
        self.log()
        for rel, where, why in ((REL, REL, "dizin okunamadı"),
                                (os.path.join("p", "anthropic"), os.path.join("p", "anthropic"), "dizin okunamadı"),
                                ("p", os.path.join("p", "anthropic"), "okunamadı"),
                                ("", "reviews", "dizin okunamadı")):
            full = self.path(rel) if rel else self.reviews
            os.chmod(full, 0)
            try:
                self.refused(why, where)
            finally:
                os.chmod(full, 0o700)

    def test_the_root_is_not_a_directory(self):
        os.rmdir(self.reviews)
        open(self.reviews, "w").close()
        self.refused("dizin okunamadı", "reviews")

    def test_anthropic_is_not_a_directory_or_loops(self):
        os.makedirs(self.path("p"))
        open(self.path("p", "anthropic"), "w").close()
        self.refused("dizin okunamadı", os.path.join("p", "anthropic"))
        os.unlink(self.path("p", "anthropic"))
        os.symlink("anthropic", self.path("p", "anthropic"))
        self.refused("dizin okunamadı", os.path.join("p", "anthropic"))

    def test_a_symlinked_directory_inside_the_tree_is_not_counted_so_refused(self):
        self.log()
        outside = os.path.join(self.dir, "dis")
        os.makedirs(outside)
        for name in ("claude-opus-5-5", "x.usage.jsonl"):
            link = self.path("p", "anthropic", name)
            os.symlink(outside, link)
            self.refused("bağlantı dizini sayılamıyor", os.path.join("p", "anthropic", name))
            os.unlink(link)

    @unittest.skipIf(ROOT, "root dizin iznini aşar")
    def test_a_link_whose_target_cannot_be_examined(self):
        self.log()
        hidden = os.path.join(self.dir, "kapali")
        os.makedirs(os.path.join(hidden, "ic"))
        os.symlink(os.path.join(hidden, "ic"), self.path(REL, "bag"))
        self.lock(hidden)
        self.refused("okunamadı", os.path.join(REL, "bag"))

    def test_a_non_utf8_name_still_gives_a_writable_reason(self):
        os.makedirs(self.path(REL))
        os.mkfifo(os.path.join(os.fsencode(self.path(REL)), b"\xff.usage.jsonl"))
        self.assertFalse(self.gate())
        self.events[0][1]["reason"].encode("utf-8")
        self.assertEqual(rv.anthropic_spent_usd(self.reviews), rv._UNCOUNTABLE_SPENT_USD)


class Trusted(_Tree):
    def test_no_root_and_an_empty_root(self):
        self.open_(spent_positive=False)
        os.rmdir(self.reviews)
        self.open_(spent_positive=False)

    def test_half_written_and_non_utf8_lines(self):
        self.log(GOOD.encode() + b'\xff\xfe\nbozuk\n[1]\n{"usage": {"input_tokens": 1')
        self.open_()

    def test_a_non_finite_value_outside_the_counters(self):
        self.log(GOOD + '{"usage": {"seconds": 1e999}}\n{"t": 1e999}\n')
        self.open_()

    def test_missing_and_stray_entries(self):
        self.log()
        os.symlink("yok", self.path(REL, "b.usage.jsonl"))              # olmayan dosya
        os.symlink("yok", self.path(REL, "bag"))
        os.symlink(self.log(name="c.txt"), self.path(REL, "dosya-bagi"))
        open(self.path("README"), "w").close()                          # proje olmayan dosya
        os.makedirs(self.path("q"))
        os.symlink("yok", self.path("q", "anthropic"))
        os.makedirs(self.path("r", "evren", "m"))
        os.mkfifo(self.path("r", "evren", "m", "a.usage.jsonl"))        # başka kip: kapının defteri değil
        self.open_()

    def test_linked_project_and_linked_log_are_counted(self):
        real = os.path.join(self.dir, "gercek")
        os.makedirs(os.path.join(real, "anthropic", "claude-sonnet-5-5"))
        outside = os.path.join(self.dir, "u.jsonl")
        with open(outside, "w") as f:
            f.write(GOOD)
        os.symlink(outside, os.path.join(real, "anthropic", "claude-sonnet-5-5", "a.usage.jsonl"))
        os.symlink(real, self.path("p"))
        self.open_()


class GateOffAndDisplay(_Tree):
    def test_no_budget_does_not_refuse(self):
        self.log('{"usage": {"input_tokens": -1}}\n')
        for cap in (0.0, 0, None, -5.0):
            self.events.clear()
            self.assertTrue(self.gate(cap=cap), cap)
            self.assertEqual(self.events, [])

    def test_a_countable_overspend_keeps_the_old_event(self):
        self.log()
        self.assertFalse(self.gate(cap=1e-9))
        self.assertEqual([e for e, _ in self.events], ["review_anthropic_budget_reached"])
        self.assertLess(self.events[0][1]["spent"], 1)

    def test_the_per_file_total_is_unchanged(self):
        path = self.log(GOOD + '{"usage": {"input_tokens": -1}}\n')
        one = rv.usage_cost_usd(self.log(name="b.usage.jsonl"), "claude-sonnet-5-5")
        self.assertEqual(rv.usage_cost_usd(path, "claude-sonnet-5-5"), one)


if __name__ == "__main__":
    unittest.main()
