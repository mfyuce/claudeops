"""TBD#366 P5: UTF-8 olmayan yerelde (`LC_ALL=C`) tmux `-F` çıktısındaki sekmeyi `_` yapar: `tmux_client_session`
(`#{client_name}\\t#{client_session}`) ve `tmux_ghost_session` (`komut\\toluşma\\tpid`) hiçbir şey bulamıyordu.
Bu iki sorgu `tmux -u` ile çalışır (sunucu başlatmazlar; `is_tmux_backed` sunucu argv'sine bakar)."""
import os
import subprocess
import time
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux


class Utf8FlagArgvTests(unittest.TestCase):
    def argv_of(self, call):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=1, stdout="")
        with mock.patch.object(tb.subprocess, "run", run):
            call()
        return calls

    def test_tab_separated_queries_force_utf8(self):
        for call in (lambda: tb.tmux_client_session("/dev/pts/1"), lambda: tb.tmux_ghost_session("g")):
            argv = self.argv_of(call)[0]
            self.assertEqual(argv[:4], ["tmux", "-u", "-L", tb.TMUX_SOCKET])

    def test_other_queries_and_the_server_starting_spawn_do_not(self):
        for call in (lambda: tb.tmux_client_count("g"), lambda: tb.tmux_has_session("g"),
                     lambda: tb.tmux_spawn_direct("g", "/tmp", "x", {})):
            self.assertNotIn("-u", self.argv_of(call)[0])


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class CLocaleRealTmuxTests(unittest.TestCase):
    def test_client_session_and_ghost_are_found_in_the_c_locale(self):
        with IsoTmux() as t, IsoTmux() as outer:
            c_env = {"LC_ALL": "C", "LANG": "C", "TMUX_TMPDIR": t.dir}
            t.spawn("m")
            t.spawn("g", "exec bash --norc --noprofile")
            # Gerçek bağlı istemci: dış sunucudaki pane bu sunucuya bağlanır.
            outer.spawn("o", f"exec env -u TMUX TMUX_TMPDIR={t.dir} tmux -u -L {t.socket} attach-session -t =m:")
            t.wait(lambda: t.raw("list-clients", "-F", "#{client_name}").strip() != "", "istemci")
            client = t.raw("list-clients", "-F", "#{client_name}").strip()
            later = time.time() + 100
            with mock.patch.dict(os.environ, c_env), mock.patch.object(tb, "TMUX_SOCKET", t.socket):
                # Önemsiz değil: bu yerelde `-u`suz tmux sekmeyi gerçekten `_` yapar.
                raw = subprocess.run(["tmux", "-L", t.socket, "list-clients", "-F", "#{client_name}\t#{client_session}"],
                                     capture_output=True, text=True).stdout
                self.assertNotIn("\t", raw)
                self.assertEqual(tb.tmux_client_session(client), "m")
                self.assertTrue(tb.tmux_ghost_session("g", now=later))


if __name__ == "__main__":
    unittest.main()
