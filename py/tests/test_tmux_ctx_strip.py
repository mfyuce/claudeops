"""Yerel tmux pencere şeridinde bağlam (`@cops_ctx`): etiket biçimi, tmux'a yazım (sahte subprocess.run, gerçek tmux/Popen
yok), değişmeyene yazmama ve tmux-strip.conf'un seçeneği okuması. Çalıştırılmadı (yazıldığı oturumda test koşturulamadı)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import tmux_backend as tb  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "claudeops", "data")


class Done:
    def __init__(self, rc=0):
        self.returncode = rc


class CtxLabelTests(unittest.TestCase):
    def test_with_and_without_threshold(self):
        self.assertEqual(tb.ctx_label(120000, 300000), "ctx 120K/300K")
        self.assertEqual(tb.ctx_label(120000, 0), "ctx 120K")

    def test_unknown_is_empty(self):
        for v in (None, 0, -5, True, "x"):
            self.assertEqual(tb.ctx_label(v, 300000), "")

    def test_label_has_no_strftime_or_format_chars(self):
        lab = tb.ctx_label(123456, 300000)
        self.assertNotIn("%", lab)
        self.assertNotIn("#", lab)


class SetCtxTests(unittest.TestCase):
    def setUp(self):
        tb._CTX_PUSHED.clear()

    def test_set_and_unset_argv(self):
        with mock.patch.object(tb.subprocess, "run", return_value=Done()) as run:
            self.assertTrue(tb.tmux_set_ctx("ab", "ctx 1K"))
            self.assertTrue(tb.tmux_set_ctx("ab", ""))
        a, b = run.call_args_list[0][0][0], run.call_args_list[1][0][0]
        self.assertEqual(a[-4:], ["-t", "=ab:", "@cops_ctx", "ctx 1K"][-4:])
        self.assertIn("set-option", a)
        self.assertEqual(b[-2:], ["-u", "@cops_ctx"])

    def test_failure_and_oserror_are_quiet(self):
        with mock.patch.object(tb.subprocess, "run", return_value=Done(1)):
            self.assertFalse(tb.tmux_set_ctx("ab", "x"))
        with mock.patch.object(tb.subprocess, "run", side_effect=OSError):
            self.assertFalse(tb.tmux_set_ctx("ab", "x"))

    def test_push_skips_unchanged_and_rewrites_on_new_pid_or_value(self):
        with mock.patch.object(tb.subprocess, "run", return_value=Done()) as run:
            tb.push_ctx("ab", 10, "ctx 1K")
            tb.push_ctx("ab", 10, "ctx 1K")
            self.assertEqual(run.call_count, 1)
            tb.push_ctx("ab", 10, "ctx 2K")
            tb.push_ctx("ab", 11, "ctx 2K")
            self.assertEqual(run.call_count, 3)

    def test_failed_push_is_retried(self):
        with mock.patch.object(tb.subprocess, "run", return_value=Done(1)) as run:
            tb.push_ctx("ab", 10, "ctx 1K")
            tb.push_ctx("ab", 10, "ctx 1K")
            self.assertEqual(run.call_count, 2)


class StripConfTests(unittest.TestCase):
    def test_strip_reads_cops_ctx_and_main_conf_stays_plain(self):
        strip = open(os.path.join(DATA, "tmux-strip.conf"), encoding="utf-8").read()
        self.assertIn("#{@cops_ctx}", strip)
        main = open(os.path.join(DATA, "tmux.conf"), encoding="utf-8").read()
        self.assertNotIn("cops_ctx", main)   # yeni özellik yalnız sürüm kapılı ayrı dosyada (tmux 3.0a'yı bozmasın)


if __name__ == "__main__":
    unittest.main()
