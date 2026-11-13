"""Kabuk oturumları (cli=shell: claudeops-shell) değnekçi için oturum DEĞİL (sahip 13 Kas): claude + kabuk = 2 oturum görünüp proje
manual/ambiguous diye günlerce ziyaret edilmemişti (tunnel). Canlı tmux YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


def _world(owned=None):
    return sw.world_for("default", sw.build_ownership_index({"default": ["tunnel"]}), "degnekci", owned=owned)


def _row(name, cli="claude", **kw):
    return dict({"name": name, "cli": cli, "running": True}, **kw)


def _view(name, cli="claude"):
    return sw.SessionView(name=name, running=True, cwd="/tmp/x", cli=cli, busy=False, tmux=True, started_at=1000.0, last_activity=1000.0)


class ShellIgnored(unittest.TestCase):
    def test_select_rows_drops_shell_local_and_remote(self):
        w = _world()
        rows = [_row("tunnel"), _row("tunnel20261110_1", cli="shell"), _row("tunnel20261110_2", cli="shell", host="")]
        self.assertEqual([r["name"] for r in sw.select_rows(rows, w)], ["tunnel"])
        remote = _row("tunnel20261110_1", cli="shell", host="ulak_31")
        self.assertEqual(sw.select_rows([remote], w, {"ulak_31"}), [])

    def test_other_clis_kept(self):
        w = _world()
        rows = [_row("tunnel1", cli="claude"), _row("tunnel2", cli="agy"), _row("tunnel3", cli="ucli")]
        self.assertEqual(len(sw.select_rows(rows, w)), 3)

    def test_claude_plus_shell_is_adopted_not_ambiguous(self):
        w = _world()
        rows = [_row("tunnel"), _row("tunnel20261110_1", cli="shell")]
        views = [_view(r["name"], r["cli"]) for r in sw.select_rows(rows, w)]
        new, ch = sw.update_owned({}, views, w, {"tunnel": sw.Project(name="tunnel")}, 0.0)
        self.assertEqual(new["tunnel"], "tunnel")
        self.assertEqual(ch[0]["how"], "adopt")

    def test_unfiltered_would_have_been_ambiguous(self):
        """Regresyon belgesi: süzme olmadan aynı girdi 'ambiguous' (boş kayıt = manual) verirdi."""
        w = _world()
        views = [_view("tunnel"), _view("tunnel20261110_1", "shell")]
        new, ch = sw.update_owned({}, views, w, {"tunnel": sw.Project(name="tunnel")}, 0.0)
        self.assertEqual(new["tunnel"], "")
        self.assertEqual(ch[0]["how"], "ambiguous")


if __name__ == "__main__":
    unittest.main()
