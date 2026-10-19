"""Mirror pencere boyutunu uzak pane'e uygulama (2026-10-19): `watch.SizeFollower`, `Viewer` kancası ve panelin `_term_resize`i.

Çalıştırma:  python3 py/tests/test_term_resize.py -v
Ağa, gerçek panele ve canlı tmux'a DOKUNMAZ (sahte saat/urlopen/tmux). Gerçek tmux'ta `resize-window` davranışı
ayrıca elle, izole bir `tmux -L` sunucusunda doğrulandı (3.2a: window-size manual olur, `set-option -wu` geri alır).
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402
from claudeops.commands import web, web_hosts, watch  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def follower(clock, reply=None, **kw):
    posts = []

    def urlopen(req, timeout=None):
        posts.append(json.loads(req.data))
        return FakeResp(json.dumps(reply or {"ok": True}).encode())

    f = watch.SizeFollower(8765, "yuhem", "s1", read_token=lambda: "tok", urlopen=urlopen, clock=clock,
                           start=lambda fn: fn(), **kw)
    return f, posts


class SizeFollowerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def test_a_window_matching_the_pane_never_posts(self):
        f, posts = follower(self.clock)
        for _ in range(5):
            f.observe((100, 31), (100, 31))
            self.clock.now += 1
        self.assertEqual(posts, [])

    def test_a_stable_different_size_posts_once_with_the_status_bar_row_removed(self):
        f, posts = follower(self.clock)
        f.observe((140, 41), (100, 31))      # aday
        self.clock.now += 0.5
        f.observe((140, 41), (100, 31))      # henüz kararlı değil
        self.assertEqual(posts, [])
        self.clock.now += 0.4
        f.observe((140, 41), (100, 31))
        f.observe((140, 41), (100, 31))
        self.assertEqual(len(posts), 1)
        self.assertEqual((posts[0]["cols"], posts[0]["rows"]), (140, 40))
        self.assertEqual((posts[0]["name"], posts[0]["host"]), ("s1", "yuhem"))

    def test_a_changing_size_restarts_the_wait_and_arriving_at_the_expected_size_cancels(self):
        f, posts = follower(self.clock)
        f.observe((110, 35), (100, 31))
        self.clock.now += 0.7
        f.observe((120, 36), (100, 31))      # yeni aday: bekleme yeniden
        self.clock.now += 0.7
        f.observe((120, 36), (100, 31))
        self.assertEqual(posts, [])
        f.observe((100, 31), (100, 31))      # pencere pane'e ulaştı
        self.clock.now += 5
        f.observe((100, 31), (100, 31))
        self.assertEqual(posts, [])

    def test_a_rejected_request_disables_following_for_the_window_lifetime(self):
        f, posts = follower(self.clock, reply={"ok": False, "error": "attached"})
        for _ in range(4):
            f.observe((140, 41), (100, 31))
            self.clock.now += 1
        self.assertEqual(len(posts), 1)
        self.assertTrue(f.disabled)
        self.assertEqual(f.last_error, "attached")

    def test_release_posts_only_after_a_size_was_sent(self):
        f, posts = follower(self.clock)
        f.release()
        self.assertEqual(posts, [])
        f.observe((140, 41), (100, 31))
        self.clock.now += 1
        f.observe((140, 41), (100, 31))
        f.release()
        self.assertEqual(posts[-1].get("release"), True)

    def test_the_same_size_is_not_sent_twice(self):
        f, posts = follower(self.clock)
        for _ in range(6):
            f.observe((140, 41), (100, 31))
            self.clock.now += 1
        self.assertEqual(len(posts), 1)


class ViewerHookTests(unittest.TestCase):
    def make(self, **kw):
        out = io.StringIO()
        dims = {"size": (80, 24)}
        screen = watch.Screen(out, title="yuhem:s1", size_fn=lambda: dims["size"])
        viewer = watch.Viewer("yuhem", "s1", screen, **kw)
        viewer.follow = mock.Mock()
        return viewer, dims

    def frame(self, cols, rows):
        return {"ok": True, "text": "x", "cols": cols, "rows": rows, "lite": True, "history_size": 0,
                "alternate_screen": False, "masked": False, "mode": None, "urls": [], "paths": []}

    def test_observed_after_the_window_was_asked_to_match_the_pane(self):
        viewer, dims = self.make()
        viewer.apply_frame(self.frame(100, 30))
        viewer.render()
        viewer.follow.observe.assert_called_with((80, 24), (100, 31))

    def test_not_observed_when_resize_is_disabled_or_pane_unknown(self):
        viewer, _ = self.make(resize=False)
        viewer.apply_frame(self.frame(100, 30))
        viewer.render()
        viewer.follow.observe.assert_not_called()
        viewer2, _ = self.make()
        viewer2.apply_frame(self.frame(None, None))
        viewer2.render()
        viewer2.follow.observe.assert_not_called()


class ServerSideTests(unittest.TestCase):
    def setUp(self):
        sess = mock.Mock()
        sess.name = "s1"
        self.patches = [
            mock.patch.object(web, "_term_resolve", return_value=(sess, None)),
            mock.patch.object(web, "tmux_client_count", return_value=0),
            mock.patch.object(web, "tmux_resize_window", return_value=True),
            mock.patch.object(web, "tmux_release_size", return_value=True),
            mock.patch.object(web.web_ws, "notify_term_activity"),
        ]
        self.m = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def test_resizes_a_session_without_attached_clients(self):
        out = web._term_resize("s1", 140, 40, lang="en")
        self.assertEqual(out["ok"], True)
        self.m[2].assert_called_once_with("s1", 140, 40)

    def test_refuses_when_a_client_is_attached_or_unknown(self):
        for count in (1, None):
            self.m[1].return_value = count
            out = web._term_resize("s1", 140, 40, lang="en")
            self.assertFalse(out["ok"])
            self.assertIn("attached", out["error"])
        self.m[2].assert_not_called()

    def test_rejects_out_of_range_and_non_integer_sizes(self):
        for cols, rows in ((10, 40), (140, 2), (600, 40), ("140", 40), (True, 40), (None, None)):
            self.assertFalse(web._term_resize("s1", cols, rows, lang="en")["ok"], (cols, rows))
        self.m[2].assert_not_called()

    def test_release_does_not_need_a_size_and_skips_the_client_check(self):
        self.m[1].return_value = 3
        out = web._term_resize("s1", None, None, release=True, lang="en")
        self.assertTrue(out["ok"])
        self.m[3].assert_called_once_with("s1")

    def test_the_route_is_host_routed(self):
        self.assertIn("/api/term/resize", web_hosts.HOST_ROUTED_PATHS)


class TmuxArgvTests(unittest.TestCase):
    def test_bounds_are_enforced_before_any_subprocess(self):
        with mock.patch.object(tmux_backend.subprocess, "run") as run:
            self.assertFalse(tmux_backend.tmux_resize_window("s1", 5, 40))
            self.assertFalse(tmux_backend.tmux_resize_window("s1", 140, 500))
            run.assert_not_called()

    def test_argv_uses_the_exact_target(self):
        with mock.patch.object(tmux_backend.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(tmux_backend.tmux_resize_window("s1", 140, 40))
            argv = run.call_args[0][0]
            self.assertIn("resize-window", argv)
            self.assertEqual(argv[argv.index("-t") + 1], "=s1:")
            tmux_backend.tmux_release_size("s1")
            argv = run.call_args[0][0]
            self.assertIn("-wu", argv)
            self.assertEqual(argv[-1], "window-size")


if __name__ == "__main__":
    unittest.main()
