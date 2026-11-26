"""TBD#366 P1-P3: tmux'ta TAM adla hedeflenemeyen ad (boş, `$` ile başlayan, `:` içeren) `=ad:` biçiminde BAŞKA bir
oturuma çözülüyordu (tmux 3.2a ölçümü: `=:` en son oturum, `=$0:` oturum kimliği $0, `=zeta:0:` display-message'ta
zeta). Böyle bir adla hiçbir tmux komutu çalışmaz; işlev kendi "olmadı" değerini döner."""
import os
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux

BAD = ["", "$0", "$1", "$x", "zeta:0", "alpha:0.0", "a:b"]
GOOD = ["alpha", "=eq", "@1", "%1", "a.b", "semi;", "x; kill-server", "we'ird name"]


def results(name):
    """Hedef alan her işlevin sonucu (ad sırası sabit)."""
    return {
        "has": tb.tmux_has_session(name),
        "capture": tb.tmux_capture(name, 10),
        "range": tb.tmux_capture_range(name, 0, 1),
        "send": tb.tmux_send_keys(name, "yanlis"),
        "send_multi": tb.tmux_send_keys(name, "yan\nlis"),
        "raw": tb.tmux_send_raw(name, "yanlis"),
        "key": tb.tmux_send_special_key(name, "Enter"),
        "resize": tb.tmux_resize_window(name, 100, 30),
        "release": tb.tmux_release_size(name),
        "ctx": tb.tmux_set_ctx(name, "ctx 1K"),
        "clients": tb.tmux_client_count(name),
        "size": tb.tmux_pane_size(name),
        "masked": tb.pane_is_masked_input(name),
        "snapshot": tb.tmux_pane_snapshot(name),
        "ghost": tb.tmux_ghost_session(name, now=1e12),
        "kill": tb.tmux_kill_session(name),
        "outer": tb._outer_bash_via_list_clients(name),
        "spawn": tb.tmux_spawn_direct(name, "/tmp", "sleep 60", dict(os.environ)),
    }


FAILED = {"has": False, "capture": None, "range": None, "send": False, "send_multi": False, "raw": False,
          "key": False, "resize": False, "release": False, "ctx": False, "clients": None, "size": None,
          "masked": None, "snapshot": None, "ghost": False, "kill": None, "outer": [], "spawn": False}


class AddressableTests(unittest.TestCase):
    def test_only_names_tmux_can_target_exactly_are_addressable(self):
        for name in BAD:
            self.assertFalse(tb._addressable(name), name)
            with self.assertRaises(ValueError):
                tb._exact(name)
        for name in GOOD:
            self.assertTrue(tb._addressable(name), name)
            self.assertEqual(tb._exact(name), f"={name}:")

    def test_unaddressable_name_never_reaches_tmux(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout="")
        with mock.patch.object(tb.subprocess, "run", run):
            for name in BAD:
                self.assertEqual(results(name), FAILED, name)
                self.assertEqual(tb.find_outer_bash_pids(name), [], name)
        self.assertEqual(calls, [])

    def test_shell_fragments_refuse_an_unaddressable_name(self):
        for name in BAD:
            with self.assertRaises(ValueError):
                tb.tmux_attach_shell_fragment(name)
            with self.assertRaises(ValueError):
                tb.tmux_new_session_shell_fragment(name, "/tmp", "claude")


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealTmuxTargetTests(unittest.TestCase):
    def test_unaddressable_names_touch_no_other_session(self):
        with IsoTmux() as t:
            for n in ("alpha", "beta", "zeta"):
                t.spawn(n)
            # Önemsiz eşitlik değil: tmux bu hedefleri gerçekten başka oturuma çözer.
            self.assertIn(t.raw("display-message", "-p", "-t", "=:", "#{session_name}").strip(), ("alpha", "beta", "zeta"))
            self.assertEqual(t.raw("display-message", "-p", "-t", "=$0:", "#{session_name}").strip(), "alpha")
            self.assertEqual(t.raw("display-message", "-p", "-t", "=zeta:0:", "#{session_name}").strip(), "zeta")
            for name in ("", "$0", "$1", "zeta:0"):
                res = results(name)
                res.pop("spawn")
                want = dict(FAILED)
                want.pop("spawn")
                self.assertEqual(res, want, name)
            self.assertEqual(t.sessions(), ["alpha", "beta", "zeta"])

    def test_names_tmux_keeps_verbatim_are_still_targeted_exactly(self):
        with IsoTmux() as t:
            for n in ("=eq", "@1", "%1", "eq"):
                t.spawn(n)
            for n in ("=eq", "@1", "%1"):
                self.assertTrue(tb.tmux_has_session(n), n)
                self.assertIs(tb.pane_is_masked_input(n), False, n)
            tb.tmux_kill_session("=eq")
            self.assertEqual(t.sessions(), ["%1", "@1", "eq"])


if __name__ == "__main__":
    unittest.main()
