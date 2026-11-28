"""tmux `new-session -s/-c` değerlerini BİÇİM olarak genişletir: `#(komut)` kabukta çalışır, `ad#{?0,x,}` var olan
oturuma bağlanır. `#` ya da denetim karakteri içeren adla oturum açılmaz; dizin adındaki `#` literal kalır."""
import os
import shlex
import subprocess
import time
import unittest

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux


class NameRuleTests(unittest.TestCase):
    def test_hash_and_control_characters_are_not_addressable(self):
        for name in ["a#b", "p#(touch X)", "victim#{?0,x,}", "a\nb", "a\tb", "a\x00b", "a\x7fb", "a\x85b"]:
            self.assertFalse(tb._addressable(name), repr(name))
        for name in ["alpha", "ad ile boşluk", "ğüş", "a.b", "semi;"]:
            self.assertTrue(tb._addressable(name), repr(name))

    def test_format_literal(self):
        cases = {"a#b": "a##b", "a##b": "a####b", "x#(y)": "x##(y)", "a#[x]": "a#[x]", "a##[x": "a##[x",
                 "#[#(z)": "#[##(z)", "end#": "end##", "duz": "duz"}
        for raw, want in cases.items():
            self.assertEqual(tb._tmux_format_literal(raw), want, raw)


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealTmuxFormatTests(unittest.TestCase):
    def test_hostile_name_runs_nothing_and_attaches_nowhere(self):
        with IsoTmux() as iso:
            iso.spawn("victim")
            mark = os.path.join(iso.dir, "calisti")
            for name in [f"p#(touch {mark})", "victim#{?0,x,}"]:
                self.assertFalse(tb.tmux_spawn_direct(name, iso.dir, "sleep 60", dict(os.environ)), name)
                with self.assertRaises(ValueError):
                    tb.tmux_new_session_shell_fragment(name, iso.dir, "sleep 60")
            time.sleep(1.0)
            self.assertFalse(os.path.exists(mark))
            self.assertEqual(iso.sessions(), ["victim"])

    def test_directory_with_hash_is_opened_literally_and_runs_nothing(self):
        with IsoTmux() as iso:
            iso.spawn("keep")
            mark = os.path.join(iso.dir, "Y")
            names = ["d#(touch Y)", "a#b", "a##b", "a#{y}", "a#[x]", "a##[x", "#[#(touch Y)]", "son#", "n#;"]
            for i, base in enumerate(names):
                cwd = os.path.join(iso.dir, base)
                os.mkdir(cwd)
                for via in ("direct", "shell"):
                    sess = f"s{i}{via}"
                    if via == "direct":
                        self.assertTrue(tb.tmux_spawn_direct(sess, cwd, "sleep 60", dict(os.environ)), base)
                    else:   # parçanın argv'si, pencere yerine `-d` ile
                        argv = shlex.split(tb.tmux_new_session_shell_fragment(sess, cwd, "sleep 60"))
                        argv.insert(argv.index("new-session") + 1, "-d")
                        env = dict(os.environ)
                        while "=" in argv[0]:       # `PATH=... tmux` öneki (TBD#450): kabuk ataması, çevreye taşınır
                            k, _, v = argv.pop(0).partition("=")
                            env[k] = v
                        subprocess.run(argv, check=True, capture_output=True, env=env)
                    got = iso.raw("display-message", "-p", "-t", f"={sess}:", "#{session_path}").rstrip("\n")
                    self.assertEqual(got, cwd, f"{via} {base}")
            time.sleep(1.0)
            self.assertFalse(os.path.exists(mark))
            self.assertFalse(os.path.exists(os.path.join(os.getcwd(), "Y")))


if __name__ == "__main__":
    unittest.main()
