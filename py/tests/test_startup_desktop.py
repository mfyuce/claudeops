"""TBD#409: yeni CLI penceresi hedef masaüstünde doğrudan açılsın. Gerçek X'e ve wmctrl'e DOKUNMAZ."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import spawn, startup_desktop as sd  # noqa: E402


class ResolveTest(unittest.TestCase):
    def test_target_exists(self):
        self.assertEqual(sd.resolve_desktop(1, 30), 1)
        self.assertEqual(sd.resolve_desktop(5, 6), 5)
        self.assertEqual(sd.resolve_desktop(0, 1), 0)

    def test_missing_falls_to_1_then_0(self):
        self.assertEqual(sd.resolve_desktop(7, 3), 1)
        self.assertEqual(sd.resolve_desktop(3, 1), 0)
        self.assertEqual(sd.resolve_desktop(1, 1), 0)

    def test_off_or_unknown(self):
        self.assertIsNone(sd.resolve_desktop(None, 4))
        self.assertIsNone(sd.resolve_desktop(-1, 4))
        self.assertIsNone(sd.resolve_desktop(1, None))
        self.assertIsNone(sd.resolve_desktop(1, 0))
        self.assertIsNone(sd.resolve_desktop("x", 4))

    def test_wanted_desktop(self):
        self.assertEqual(sd.wanted_desktop({}), 1)
        self.assertEqual(sd.wanted_desktop({"spawn_desktop": 3}), 3)
        self.assertEqual(sd.wanted_desktop({"spawn_desktop": "2"}), 2)
        self.assertIsNone(sd.wanted_desktop({"spawn_desktop": -1}))
        self.assertIsNone(sd.wanted_desktop({"spawn_desktop": True}))
        self.assertEqual(sd.wanted_desktop({"spawn_desktop": "bozuk"}), 1)


class MessageTest(unittest.TestCase):
    def test_message_and_chunks(self):
        msg = sd.build_message('id"1', "rs\\x", 2)
        self.assertEqual(msg, b'new: ID="id\\"1" NAME="rs\\\\x" SCREEN=0 DESKTOP=2\0')
        parts = sd.chunks(msg)
        self.assertTrue(all(len(p) == 20 for p in parts))
        self.assertEqual(b"".join(parts).rstrip(b"\0"), msg.rstrip(b"\0"))
        self.assertIn(b"_TIME", sd.new_startup_id(1000.0).encode())

    def test_client_message_layout_matches_xlib(self):
        # 64 bit Xlib: XClientMessageEvent.data 56. baytta (long hizalı), XEvent 192 bayt.
        import ctypes
        if ctypes.sizeof(ctypes.c_long) == 8:
            self.assertEqual(sd._XClientMessageEvent.data.offset, 56)
            self.assertEqual(ctypes.sizeof(sd._XEvent), 192)

    def test_desktop_count(self):
        ok = subprocess.CompletedProcess([], 0, stdout="0 * DG\n1 - DG\n\n", stderr="")
        self.assertEqual(sd.desktop_count(":1", run=lambda *a, **k: ok), 2)
        bad = subprocess.CompletedProcess([], 1, stdout="", stderr="x")
        self.assertIsNone(sd.desktop_count(":1", run=lambda *a, **k: bad))

        def boom(*a, **k):
            raise FileNotFoundError("wmctrl")
        self.assertIsNone(sd.desktop_count(":1", run=boom))


class StartupEnvTest(unittest.TestCase):
    def _env(self, settings, count=30, send_ok=True, env=None):
        sent = []

        def send(display, msg):
            sent.append((display, msg))
            return send_ok
        out = sd.startup_env(env if env is not None else {"DISPLAY": ":1"}, "rsprov", settings=settings,
                             count_fn=lambda d: count, send_fn=send)
        return out, sent

    def test_sets_startup_id_and_desktop(self):
        out, sent = self._env({"spawn_desktop": 1})
        self.assertIn("DESKTOP_STARTUP_ID", out)
        self.assertEqual(len(sent), 1)
        self.assertIn(b"DESKTOP=1", sent[0][1])
        self.assertIn(out["DESKTOP_STARTUP_ID"].encode(), sent[0][1])

    def test_fallback_desktop(self):
        _, sent = self._env({"spawn_desktop": 9}, count=4)
        self.assertIn(b"DESKTOP=1", sent[0][1])

    def test_disabled_no_display_send_fail(self):
        for out, sent in (self._env({"spawn_desktop": -1}), self._env({}, env={}), self._env({}, count=None)):
            self.assertNotIn("DESKTOP_STARTUP_ID", out)
        out, _ = self._env({}, send_ok=False)
        self.assertNotIn("DESKTOP_STARTUP_ID", out)

    def test_never_raises(self):
        def boom(display, msg):
            raise RuntimeError("x11")
        env = {"DISPLAY": ":1"}
        self.assertIs(sd.startup_env(env, "a", settings={}, count_fn=lambda d: 3, send_fn=boom), env)

    def test_real_x_untouched_under_tests(self):
        with mock.patch.object(sd, "desktop_count") as cnt:
            env = {"DISPLAY": ":1"}
            self.assertIs(sd.startup_env(env, "a", settings={}), env)
            cnt.assert_not_called()


class LaunchTest(unittest.TestCase):
    def test_launch_passes_startup_env(self):
        with mock.patch.object(sd, "startup_env", side_effect=lambda env, name: dict(env, DESKTOP_STARTUP_ID="S")) as se, \
                mock.patch.object(spawn.subprocess, "Popen") as popen, \
                mock.patch.object(spawn.threading, "Thread"):
            self.assertTrue(spawn._launch_gnome_terminal("rsx", "/tmp", "true", {"DISPLAY": ":1"}))
        se.assert_called_once()
        self.assertEqual(popen.call_args.kwargs["env"]["DESKTOP_STARTUP_ID"], "S")


if __name__ == "__main__":
    unittest.main()
