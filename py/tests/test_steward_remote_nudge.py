"""Uzak host'ta API hatasında takılan oturuma "devam" (`nudge`): `/api/term/input {"exact": true}`, yerel yola düşmez, 2+ oturum
= red, tmux'suz = red. Sahte uzak host (`test_steward_remote_session_resolve.DatedHost`); gerçek ağ/tmux YOK.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_session_resolve import _Resolve, _facts  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

ERR = 'API Error: 500 {"type":"error","error":{"type":"api_error","message":"Internal server error"}}'


class TestRemoteNudge(_Resolve):
    def nudge(self, name="oiso"):
        return ws._apply(sw.Action("nudge", name, "t", {"text": "devam", "n": 1}), ws.steward_config(), sw.load_projects(),
                         ws._world(), rt=None)

    def test_nudge_posts_exact_devam_without_local_fallback(self):
        self.rows("oiso20261017")
        r = self.nudge("oiso")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["host"], HOST)
        inp = self.posts("/api/term/input")
        self.assertEqual([(p[2]["name"], p[2]["text"], p[2]["exact"]) for p in inp], [("oiso20261017", "devam", True)])
        self.assertNotIn("host", inp[0][2])
        self.assertEqual(self.calls, [])                                      # yerel `_send` yok
        self.assertEqual(self.posts("/api/start"), [])                        # asla başlatmaz

    def test_two_sessions_is_refused_and_nothing_is_sent(self):
        self.rows("oiso20261017", "oiso20261018")
        r = self.nudge("oiso")
        self.assertFalse(r["ok"])
        self.assertEqual(self.posts("/api/term/input"), [])

    def test_no_session_and_no_tmux_are_refused(self):
        self.rows()
        self.assertFalse(self.nudge("oiso")["ok"])
        self.fake.set(HOST, [_row("oiso20261017", cwd="/srv/oiso", tmux=False)])
        self.fake.facts["oiso20261017"] = _facts()
        self.assertFalse(self.nudge("oiso")["ok"])
        self.assertEqual(self.posts("/api/term/input"), [])

    def test_tick_wakes_a_stuck_remote_session_after_the_first_delay(self):
        self.fake.set(HOST, [_row("oiso20261017", cwd="/srv/oiso", cache={"age": 600})])
        self.fake.facts["oiso20261017"] = _facts(ERR)
        ws.tick_once("manual")
        self.assertEqual(self.posts("/api/term/input"), [])                   # ilk tick: yalnız kayıt, bekleme süresi dolmadı
        st = sw.load_state()
        for rec in st["api_err"].values():
            rec["since"] -= 120.0
        sw.save_state(st)
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"] if a["kind"] == "nudge"], [("nudge", True)], res)
        self.assertEqual([p[2]["text"] for p in self.posts("/api/term/input")], ["devam"])


if __name__ == "__main__":
    unittest.main()
