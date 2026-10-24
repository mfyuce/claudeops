import unittest
from unittest import mock

from claudeops import audio_stream as au


class _FakeHandler:
    def __init__(self):
        self.out = None

    def _json(self, obj, status=200):
        self.out = (status, obj)


class AudioStreamTest(unittest.TestCase):
    def setUp(self):
        au._listeners = 0

    def test_default_monitor_appends_monitor_suffix(self):
        r = mock.Mock(returncode=0, stdout="alsa_output.x\n")
        with mock.patch.object(au.subprocess, "run", return_value=r):
            self.assertEqual(au.default_monitor(), "alsa_output.x.monitor")

    def test_default_monitor_empty_on_failure(self):
        with mock.patch.object(au.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="")):
            self.assertEqual(au.default_monitor(), "")
        with mock.patch.object(au.subprocess, "run", side_effect=OSError):
            self.assertEqual(au.default_monitor(), "")

    def test_status_reports_missing_tools_without_probing_source(self):
        with mock.patch.object(au, "missing_tools", return_value=["parec"]), \
                mock.patch.object(au, "default_monitor", side_effect=AssertionError("must not probe")):
            st = au.status()
        self.assertFalse(st["available"])
        self.assertEqual(st["missing"], ["parec"])
        self.assertEqual(st["source"], "")

    def test_stream_refuses_when_tools_missing(self):
        h = _FakeHandler()
        with mock.patch.object(au, "missing_tools", return_value=["ffmpeg"]):
            au.stream(h)
        self.assertEqual(h.out[0], 503)
        self.assertEqual(au._listeners, 0)

    def test_stream_refuses_without_default_output(self):
        h = _FakeHandler()
        with mock.patch.object(au, "missing_tools", return_value=[]), mock.patch.object(au, "default_monitor", return_value=""):
            au.stream(h)
        self.assertEqual(h.out[0], 503)

    def test_listener_cap_returns_429_and_releases(self):
        h = _FakeHandler()
        with mock.patch.object(au, "missing_tools", return_value=[]), \
                mock.patch.object(au, "default_monitor", return_value="x.monitor"):
            self.assertTrue(au._acquire() and au._acquire())
            au.stream(h)
            self.assertEqual(h.out[0], 429)
            au._release()
            au._release()
        self.assertEqual(au._listeners, 0)

    def test_release_never_goes_negative(self):
        au._release()
        self.assertEqual(au._listeners, 0)


if __name__ == "__main__":
    unittest.main()
