"""Çok kullanıcı kipinde taban ad geri düşüşü kapalı (rs-state, TODO "taban adla istekte yetki istenen ada veriliyor").

Yetki (K2 `_gate`) İSTEKTEKİ ada göre verilir. `_find_running_for_action` tam ad yoksa taban adı aynı olan TEK kayıtsız
süreci de hedefliyordu: `x` oturumunun sahibi, kayıtsız `x7`yi (başkasının) `x` adıyla okuyabilir/yönetebilirdi. Authorizer
kayıtlıyken yalnız tam ad hedeflenir (kapalı yöne); tek kullanıcıda davranış aynı kalır.
"""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import authz  # noqa: E402
from claudeops.commands import web  # noqa: E402


def _sess(name, base, pid):
    return NS(name=name, base=base, pid=pid, cli="claude")


class BaseNameAuthzTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(authz.reset)
        procs = [_sess("x7", "x", 77)]
        p1 = mock.patch.object(web, "find_sessions", return_value=procs)
        p2 = mock.patch.object(web.inst_mod, "get_instance", return_value=None)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_single_user_keeps_base_fallback(self):
        kind, procs = web._find_running_for_action("x")
        self.assertEqual(kind, "unique_base")
        self.assertEqual([s.name for s in procs], ["x7"])

    def test_multi_user_no_base_fallback(self):
        authz.set_authorizer(lambda p, a, r: r.name == "x")     # kullanıcı yalnız `x`in sahibi
        kind, procs = web._find_running_for_action("x")
        self.assertEqual((kind, procs), ("none", []))

    def test_multi_user_no_ambiguity_leak(self):
        authz.set_authorizer(lambda p, a, r: True)
        with mock.patch.object(web, "find_sessions", return_value=[_sess("x7", "x", 77), _sess("x8", "x", 88)]):
            kind, procs = web._find_running_for_action("x")
        self.assertEqual((kind, procs), ("none", []))       # aday adları hata metnine düşmesin

    def test_multi_user_exact_still_found(self):
        authz.set_authorizer(lambda p, a, r: True)
        with mock.patch.object(web, "find_sessions", return_value=[_sess("x", "x", 5), _sess("x7", "x", 77)]):
            kind, procs = web._find_running_for_action("x")
        self.assertEqual((kind, [s.name for s in procs]), ("exact", ["x"]))

    def test_term_output_multi_user_does_not_read_base_match(self):
        authz.set_authorizer(lambda p, a, r: r.name == "x")
        web._term_output_resolve_cache.pop("x", None)
        self.addCleanup(web._term_output_resolve_cache.pop, "x", None)
        with mock.patch.object(web, "is_tmux_backed", return_value=True), \
                mock.patch.object(web, "tmux_has_session", return_value=True), \
                mock.patch.object(web, "tmux_capture", return_value="GIZLI") as cap:
            out = web._term_output("x")
        self.assertFalse(out.get("ok"))
        cap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
