"""TBD#366 P4, P6: `;` ile biten tmux argv elemanı komut ayıracıdır. `tmux_spawn_direct` (ve kabuk parçası) `;` ile
biten ad ya da cwd ile oturum açamıyordu ("unknown command: -c"); `tmux_set_ctx` etiketin sondaki `;`ini
kaybediyordu. Bu argümanlar `\\;` ile kaçırılır (tmux bir ters bölüyü soyar)."""
import os
import shlex
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux


class EscapeTests(unittest.TestCase):
    def test_only_a_trailing_semicolon_is_escaped(self):
        self.assertEqual(tb._tmux_arg("semi;"), "semi\\;")
        self.assertEqual(tb._tmux_arg("a;b"), "a;b")
        self.assertEqual(tb._tmux_arg("bar\\;"), "bar\\\\;")
        self.assertEqual(tb._tmux_arg(";"), "\\;")
        self.assertEqual(tb._tmux_arg(""), "")

    def test_spawn_direct_argv_escapes_name_and_cwd(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run):
            self.assertTrue(tb.tmux_spawn_direct("semi;", "/t;", "x", {}))
        argv = calls[0]
        self.assertEqual(argv[argv.index("-s") + 1], "semi\\;")
        self.assertEqual(argv[argv.index("-c") + 1], "/t\\;")

    def test_shell_fragment_escapes_name_cwd_and_inner(self):
        frag = tb.tmux_new_session_shell_fragment("semi;", "/t;", "x;")
        argv = shlex.split(frag)
        self.assertEqual(argv[argv.index("-s") + 1], "semi\\;")
        self.assertEqual(argv[argv.index("-c") + 1], "/t\\;")
        self.assertEqual(argv[-1], "x\\;")

    def test_set_ctx_argv_escapes_the_label(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run):
            self.assertTrue(tb.tmux_set_ctx("x", "a;"))
        self.assertEqual(calls[0][-2:], ["@cops_ctx", "a\\;"])


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealTmuxSemicolonTests(unittest.TestCase):
    def test_spawn_with_semicolon_name_and_cwd_opens_that_session(self):
        with IsoTmux() as t:
            cwd = os.path.join(t.dir, "w;")
            os.mkdir(cwd)
            self.assertTrue(tb.tmux_spawn_direct("semi;", cwd, "sleep 60", dict(os.environ)))
            self.assertTrue(tb.tmux_spawn_direct("ok", cwd, "sleep 60", dict(os.environ)))
            self.assertEqual(t.sessions(), ["ok", "semi;"])
            for name in ("semi;", "ok"):
                path = t.raw("display-message", "-p", "-t", f"={name}:", "#{pane_current_path}").strip()
                self.assertEqual(path, cwd, name)

    def test_ctx_label_keeps_its_trailing_semicolon(self):
        with IsoTmux() as t:
            t.spawn("c")
            for label in ("a;", "x;y;", "ctx 1K"):
                self.assertTrue(tb.tmux_set_ctx("c", label))
                self.assertEqual(t.raw("show-options", "-q", "-v", "-t", "=c:", "@cops_ctx").strip(), label)


if __name__ == "__main__":
    unittest.main()
