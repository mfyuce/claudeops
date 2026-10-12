"""`web._term_fetch_fn` / `web._term_remote_query` testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_web_term_fetch.py -v

Kapsadığı tasarım (TODO.md "Uzak host'a `lite` iletilsin", 2026-10-12): `/ws/term?lite=1` isteği
uzak host'a da `lite` olarak iletilsin ki host↔host hop küçük kare taşısın; ama `lite`'ı bilmeyen
eski bir host tam kare yolladığında yerel `to_lite` sarmalayıcısı kırpmaya devam etsin, `lite:true`
gelen kare de ikinci kez kırpılmasın. Ağa / tmux'a DOKUNMAZ.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402

FULL_TEXT = "scroll-1\nscroll-2\nv1\nv2\nv3\n"   # rows=3: ilk iki satır scrollback


def full_frame(**extra):
    base = {"ok": True, "text": FULL_TEXT, "cols": 80, "rows": 3, "history_size": 2,
            "alternate_screen": False, "masked": False, "mode": None}
    base.update(extra)
    return base


def lite_frame():
    return {"ok": True, "text": "v1\nv2\nv3", "cols": 80, "rows": 3, "history_size": 2,
            "alternate_screen": False, "masked": False, "mode": None,
            "lite": True, "urls": ["https://remote-computed.example/x"], "paths": []}


class RemoteQueryTests(unittest.TestCase):
    def test_lite_is_only_added_when_requested(self):
        self.assertEqual(web._term_remote_query("s1", "en", False), {"name": "s1", "lang": "en"})
        self.assertEqual(web._term_remote_query("s1", "en", True), {"name": "s1", "lang": "en", "lite": "1"})


class FetchFnTests(unittest.TestCase):
    def setUp(self):
        self.proxy_calls = []
        self.relay_calls = []
        self.proxy_result = full_frame()
        self.relay_result = full_frame()
        self.tier = "rest"

        def fake_proxy_get(path, host, query):
            self.proxy_calls.append((path, host, dict(query)))
            return self.proxy_result, 200

        def fake_relay(host, name, lang, lite=False):
            self.relay_calls.append((host, name, lang, lite))
            return lambda: self.relay_result

        for p in (
            mock.patch.object(web.web_hosts, "get_tier", lambda host: self.tier),
            mock.patch.object(web.web_hosts, "proxy_get", fake_proxy_get),
            mock.patch.object(web.web_hosts, "term_output_relay", fake_relay),
            mock.patch.object(web, "_term_output", lambda name, lang="tr": full_frame()),
        ):
            p.start()
            self.addCleanup(p.stop)

    # ── yerel ────────────────────────────────────────────────────────────

    def test_local_plain_frame_is_untouched(self):
        out = web._term_fetch_fn(web.LOCAL_HOST_NAME, "s1", "en", False)()
        self.assertEqual(out, full_frame())

    def test_local_lite_frame_is_trimmed_to_the_visible_rows(self):
        out = web._term_fetch_fn(web.LOCAL_HOST_NAME, "s1", "en", True)()
        self.assertTrue(out["lite"])
        self.assertEqual(out["text"], "v1\nv2\nv3")
        self.assertEqual(self.proxy_calls, [])
        self.assertEqual(self.relay_calls, [])

    # ── uzak, REST tier ─────────────────────────────────────────────────

    def test_remote_rest_lite_forwards_lite_to_the_host(self):
        self.proxy_result = lite_frame()
        web._term_fetch_fn("yuhem", "s1", "en", True)()
        self.assertEqual(self.proxy_calls,
                         [("/api/term/output", "yuhem", {"name": "s1", "lang": "en", "lite": "1"})])

    def test_remote_rest_plain_does_not_send_lite(self):
        out = web._term_fetch_fn("yuhem", "s1", "en", False)()
        self.assertEqual(self.proxy_calls, [("/api/term/output", "yuhem", {"name": "s1", "lang": "en"})])
        self.assertEqual(out, full_frame())  # sarmalayıcı yok

    def test_remote_lite_frame_is_not_trimmed_twice(self):
        self.proxy_result = lite_frame()
        out = web._term_fetch_fn("yuhem", "s1", "en", True)()
        self.assertEqual(out, lite_frame())  # uzağın çıkardığı `urls` aynen kaldı

    def test_old_remote_that_ignores_lite_is_trimmed_locally(self):
        self.proxy_result = full_frame()  # `lite=1`'i yok sayan eski host tam kare döndü
        out = web._term_fetch_fn("yuhem", "s1", "en", True)()
        self.assertTrue(out["lite"])
        self.assertEqual(out["text"], "v1\nv2\nv3")

    def test_remote_error_frames_pass_through_untouched(self):
        err = {"ok": False, "error": "yuhem unreachable: timed out"}
        self.proxy_result = err
        self.assertEqual(web._term_fetch_fn("yuhem", "s1", "en", True)(), err)
        self.assertEqual(web._term_fetch_fn("yuhem", "s1", "en", False)(), err)

    # ── uzak, ws/grpc tier (relay) ────────────────────────────────────────

    def test_remote_ws_tier_asks_the_relay_for_lite(self):
        self.tier = "ws"
        self.relay_result = lite_frame()
        out = web._term_fetch_fn("ulak_31", "s1", "en", True)()
        self.assertEqual(self.relay_calls, [("ulak_31", "s1", "en", True)])
        self.assertEqual(self.proxy_calls, [])
        self.assertEqual(out, lite_frame())

    def test_remote_ws_tier_plain_uses_the_plain_relay_and_no_wrapper(self):
        self.tier = "ws"
        out = web._term_fetch_fn("ulak_31", "s1", "en", False)()
        self.assertEqual(self.relay_calls, [("ulak_31", "s1", "en", False)])
        self.assertEqual(out, full_frame())

    def test_grpc_tier_full_frames_are_still_trimmed_locally(self):
        # gRPC proto'su `lite` taşımıyor: relay tam kare verir, yerel sarmalayıcı kırpar.
        self.tier = "grpc"
        self.relay_result = full_frame()
        out = web._term_fetch_fn("ulak_31", "s1", "en", True)()
        self.assertEqual(self.relay_calls, [("ulak_31", "s1", "en", True)])
        self.assertTrue(out["lite"])
        self.assertEqual(out["text"], "v1\nv2\nv3")


if __name__ == "__main__":
    unittest.main()
