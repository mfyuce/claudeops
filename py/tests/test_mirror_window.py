"""Masaüstü mirror penceresi (TBD#74 Faz 2) testleri: `mirrors.py`, `spawn.open_mirror_window`,
`web._open_mirror_window` ve yerel-only `POST /api/term/mirror-window` (stdlib unittest).

Çalıştırma:  python3 py/tests/test_mirror_window.py -v

Gerçek pencere AÇMAZ (Popen sahte), gerçek `wmctrl` çağırmaz, canlı süreçleri taramaz (psutil sahte),
ağa yalnız 127.0.0.1'deki geçici bir HTTP sunucusuyla dokunur.
"""
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from collections import namedtuple
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil  # noqa: E402

from claudeops import mirrors, paths, spawn  # noqa: E402
from claudeops.commands import web, web_hosts  # noqa: E402
from claudeops.layout import ScreenGeometry, build_layout_plan  # noqa: E402

WATCH = ["python3", "-m", "claudeops", "watch"]


class SpecFromCmdlineTests(unittest.TestCase):
    def test_host_and_name(self):
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["ulak_31:rustrino20261009"]), "ulak_31:rustrino20261009")

    def test_bare_name_is_local(self):
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["cops20261007"]), "local:cops20261007")

    def test_flags_before_or_after_the_target(self):
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["--port", "9000", "yuhem:a"]), "yuhem:a")
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["yuhem:a", "--transport", "rest", "--no-resize"]), "yuhem:a")
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["--port=9000", "yuhem:a"]), "yuhem:a")

    def test_value_of_a_flag_is_not_mistaken_for_the_target(self):
        self.assertEqual(mirrors.spec_from_cmdline(WATCH + ["--transport", "ws", "yuhem:a"]), "yuhem:a")

    def test_once_is_not_a_window(self):
        self.assertIsNone(mirrors.spec_from_cmdline(WATCH + ["yuhem:a", "--once", "--plain"]))

    def test_other_commands_do_not_match(self):
        for cmdline in (None, [], ["claude", "--resume"], ["python3", "-m", "claudeops", "web", "--port", "8765"],
                        ["python3", "-m", "claudeops", "list"], ["bash", "-c", "py/cops watch yuhem:a"],
                        ["vim", "watch"], ["python3", "-m", "claudeops"]):
            self.assertIsNone(mirrors.spec_from_cmdline(cmdline), cmdline)

    def test_watch_without_a_target(self):
        self.assertIsNone(mirrors.spec_from_cmdline(WATCH))
        self.assertIsNone(mirrors.spec_from_cmdline(WATCH + ["--port", "9000"]))

    def test_empty_parts(self):
        self.assertIsNone(mirrors.spec_from_cmdline(WATCH + [":x"]))
        self.assertIsNone(mirrors.spec_from_cmdline(WATCH + ["x:"]))


UIDS = namedtuple("UIDS", "real effective saved")


class FakeProc:
    def __init__(self, pid, cmdline, uid=1000, denied=False):
        self.info = {"pid": pid, "cmdline": cmdline, "uids": None if denied else UIDS(uid, uid, uid)}


class RunningMirrorsTests(unittest.TestCase):
    def scan(self, procs, uid=1000):
        with mock.patch.object(mirrors.psutil, "process_iter", lambda attrs=None: iter(procs)):
            return mirrors.running_mirrors(uid=uid)

    def test_collects_pids_per_spec(self):
        found = self.scan([FakeProc(10, WATCH + ["yuhem:a"]), FakeProc(11, WATCH + ["yuhem:a", "--port", "9"]),
                           FakeProc(12, WATCH + ["ulak_31:b"]), FakeProc(13, ["python3", "-m", "claudeops", "web"])])
        self.assertEqual(found, {"yuhem:a": [10, 11], "ulak_31:b": [12]})

    def test_other_users_processes_are_ignored(self):
        self.assertEqual(self.scan([FakeProc(10, WATCH + ["yuhem:a"], uid=1001)]), {})

    def test_unreadable_processes_are_skipped(self):
        self.assertEqual(self.scan([FakeProc(10, WATCH + ["yuhem:a"], denied=True)]), {})

    def test_default_uid_is_the_current_user(self):
        with mock.patch.object(mirrors.psutil, "process_iter",
                               lambda attrs=None: iter([FakeProc(10, WATCH + ["yuhem:a"], uid=os.getuid())])):
            self.assertEqual(mirrors.running_mirrors(), {"yuhem:a": [10]})

    def test_a_process_vanishing_mid_scan_is_skipped(self):
        class Vanishing:
            @property
            def info(self):
                raise psutil.NoSuchProcess(99)

        self.assertEqual(self.scan([Vanishing(), FakeProc(10, WATCH + ["yuhem:a"])]), {"yuhem:a": [10]})


class FocusWindowTests(unittest.TestCase):
    def test_uses_exact_title_matching_and_the_given_display(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0)

        self.assertTrue(mirrors.focus_window("ulak_31:rustrino", ":7", run=run))
        argv, kw = calls[0]
        self.assertEqual(argv, ["wmctrl", "-F", "-a", "ulak_31:rustrino"])   # -F: alt-dize DEĞİL, tam başlık
        self.assertEqual(kw["env"]["DISPLAY"], ":7")
        self.assertLessEqual(kw["timeout"], 5)

    def test_failures_are_false_not_exceptions(self):
        self.assertFalse(mirrors.focus_window("x:y", ":1", run=lambda *a, **k: subprocess.CompletedProcess(a, 1)))

        def missing(*a, **k):
            raise FileNotFoundError("wmctrl")

        def slow(*a, **k):
            raise subprocess.TimeoutExpired("wmctrl", 3)

        self.assertFalse(mirrors.focus_window("x:y", ":1", run=missing))
        self.assertFalse(mirrors.focus_window("x:y", ":1", run=slow))


class OpenMirrorWindowSpawnTests(unittest.TestCase):
    def launch(self, host="ulak_31", name="rustrino", port=8765, display=":7", extra_env=None):
        with mock.patch.object(spawn.subprocess, "Popen") as popen, \
                mock.patch.dict(os.environ, extra_env or {}, clear=False):
            ok = spawn.open_mirror_window(host, name, port, display=display)
        argv, kwargs = popen.call_args
        return ok, argv[0], kwargs

    def test_gnome_terminal_argv(self):
        ok, argv, kwargs = self.launch()
        self.assertTrue(ok)
        self.assertEqual(argv[:3], ["gnome-terminal", "--window", "--title=ulak_31:rustrino"])
        self.assertEqual(argv[argv.index("--") + 1:argv.index("--") + 3], ["bash", "-c"])
        self.assertIn("--geometry=100x30", argv)

    def test_the_command_runs_cops_watch_against_this_panels_port(self):
        _, argv, _ = self.launch(port=8790)
        window_cmd = argv[-1]
        self.assertTrue(window_cmd.startswith(f"{os.path.join(paths.REPO_DIR, 'py', 'cops')} watch ulak_31:rustrino --port 8790;"),
                        window_cmd)

    def test_a_failing_viewer_keeps_the_window_open_and_a_clean_exit_closes_it(self):
        _, argv, _ = self.launch()
        window_cmd = argv[-1]
        self.assertIn('if [ "$rc" -ne 0 ]', window_cmd)       # hata: kodu göster, Enter bekle
        self.assertIn("read -r", window_cmd)
        self.assertNotIn("exec bash", window_cmd)             # q ile (kod 0) pencere KAPANIR

    def test_arguments_are_shell_quoted(self):
        _, argv, _ = self.launch(host="h", name="a b;rm")
        self.assertIn("'h:a b;rm'", argv[-1])

    def test_environment(self):
        _, _, kwargs = self.launch(display=":9", extra_env={"CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_FOO": "x"})
        env = kwargs["env"]
        self.assertEqual(env["DISPLAY"], ":9")
        self.assertEqual(env["CLAUDEOPS_DIR"], paths.CLAUDEOPS_DIR)   # süpürme bunu da atıyor, açıkça geri konur
        self.assertNotIn("CLAUDE_CODE_CHILD_SESSION", env)            # claude-içinden-claude sızıntısı yok
        self.assertNotIn("CLAUDE_FOO", env)

    def test_popen_failure_is_false(self):
        with mock.patch.object(spawn.subprocess, "Popen", side_effect=OSError("no gnome-terminal")):
            self.assertFalse(spawn.open_mirror_window("h", "n", 8765, display=":1"))


HOST_ROWS = [
    {"name": "s1", "running": True, "tmux": True, "host": "yuhem"},
    {"name": "plain", "running": True, "tmux": False, "host": "yuhem"},
    {"name": "stopped", "running": False, "tmux": True, "host": "yuhem"},
]


class OpenMirrorWindowBackendTests(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self.focused = []
        self.state = {"mirrors": {}, "x11": True, "launch_ok": True, "cache": {"ok": True, "sessions": HOST_ROWS}}

        def fake_spawn(host, name, port, display=None):
            self.spawned.append((host, name, port, display))
            return self.state["launch_ok"]

        def fake_focus(spec, display):
            self.focused.append((spec, display))
            return True

        for p in (
            mock.patch.object(web, "get_host", lambda h: {"name": h} if h in ("yuhem", "ulak_31") else None),
            mock.patch.object(web.web_hosts, "get_cached", lambda h: self.state["cache"]),
            mock.patch.object(web, "detect_display", lambda: ":1"),
            mock.patch.object(web, "_x11_display_ok", lambda d: self.state["x11"]),
            mock.patch.object(web.mirrors, "running_mirrors", lambda: self.state["mirrors"]),
            mock.patch.object(web.mirrors, "focus_window", fake_focus),
            mock.patch.object(web, "open_mirror_window", fake_spawn),
        ):
            p.start()
            self.addCleanup(p.stop)

    def call(self, name="s1", host="yuhem", port=8765, lang="en", force=False):
        return web._open_mirror_window(name, host, port, lang=lang, force=force)

    def test_success_spawns_once_with_the_panels_port(self):
        self.assertEqual(self.call(port=8790), {"ok": True, "already_open": False})
        self.assertEqual(self.spawned, [("yuhem", "s1", 8790, ":1")])

    def test_local_sessions_are_rejected(self):
        for host in ("local", ""):
            res = self.call(host=host)
            self.assertFalse(res["ok"])
            self.assertIn("local session", res["error"])
        self.assertEqual(self.spawned, [])

    def test_bad_characters_never_reach_the_command_line(self):
        for name, host in (("a b", "yuhem"), ("a;b", "yuhem"), ("../x", "yuhem"), ("s1", "yu hem"), ("-rf", "yuhem"),
                           ("s1\n", "yuhem"), ("", "yuhem"), ("s1", "yuhem/x")):
            res = self.call(name=name, host=host)
            self.assertFalse(res["ok"], (name, host))
        self.assertEqual(self.spawned, [])

    def test_unknown_host(self):
        res = self.call(host="nohost")
        self.assertFalse(res["ok"])
        self.assertIn("not a registered remote host", res["error"])

    def test_session_must_be_in_the_hosts_last_known_state(self):
        for name in ("missing", "stopped"):
            res = self.call(name=name)
            self.assertFalse(res["ok"], name)
            self.assertIn("not running", res["error"])
        self.state["cache"] = None                      # host hiç poll edilmemiş
        self.assertIn("not running", self.call()["error"])
        self.state["cache"] = {"ok": False, "error": "x"}   # poll başarısız, session listesi yok
        self.assertIn("not running", self.call()["error"])
        self.assertEqual(self.spawned, [])

    def test_a_session_without_tmux_has_no_terminal_to_mirror(self):
        res = self.call(name="plain")
        self.assertFalse(res["ok"])
        self.assertIn("not tmux-backed", res["error"])

    def test_no_x11_display(self):
        self.state["x11"] = False
        res = self.call()
        self.assertFalse(res["ok"])
        self.assertIn("X11", res["error"])
        self.assertEqual(self.spawned, [])

    def test_an_open_mirror_is_focused_not_duplicated(self):
        self.state["mirrors"] = {"yuhem:s1": [4242]}
        self.assertEqual(self.call(), {"ok": True, "already_open": True, "focused": True})
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.focused, [("yuhem:s1", ":1")])

    def test_force_opens_a_second_one(self):
        self.state["mirrors"] = {"yuhem:s1": [4242]}
        self.assertEqual(self.call(force=True), {"ok": True, "already_open": False})
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.focused, [])

    def test_another_sessions_mirror_does_not_count(self):
        self.state["mirrors"] = {"yuhem:s2": [1], "ulak_31:s1": [2]}
        self.assertEqual(self.call()["already_open"], False)
        self.assertEqual(len(self.spawned), 1)

    def test_launch_failure(self):
        self.state["launch_ok"] = False
        res = self.call()
        self.assertFalse(res["ok"])
        self.assertIn("couldn't open the mirror window", res["error"])

    def test_messages_follow_the_language(self):
        tr = self.call(host="local", lang="tr")["error"]
        en = self.call(host="local", lang="en")["error"]
        self.assertNotEqual(tr, en)
        self.assertIn("yerel session", tr)


class MirrorRouteHttpTests(unittest.TestCase):
    """Gerçek HTTP: route yerel allowlist'te ve YEREL-only (uzak host'a proxy'lenmiyor)."""

    def setUp(self):
        self.calls = []

        def fake(name, host, port, lang="tr", force=False):
            self.calls.append({"name": name, "host": host, "port": port, "lang": lang, "force": force})
            return {"ok": True, "already_open": False}

        def no_proxy(*a, **k):
            raise AssertionError("mirror-window must NOT be proxied to a remote host")

        for p in (
            mock.patch.object(web, "_open_mirror_window", fake),
            mock.patch.object(web.web_hosts, "proxy_action", no_proxy),
            mock.patch.object(web._Handler, "token", "tok"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body, token="tok"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/term/mirror-window",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_route_is_declared_local_only(self):
        self.assertNotIn("/api/term/mirror-window", web_hosts.HOST_ROUTED_PATHS)

    def test_post_with_a_remote_host_field_is_handled_locally(self):
        status, body = self.post({"name": "s1", "host": "ulak_31", "lang": "en"})
        self.assertEqual((status, body), (200, {"ok": True, "already_open": False}))
        self.assertEqual(self.calls, [{"name": "s1", "host": "ulak_31", "port": self.port, "lang": "en", "force": False}])

    def test_force_flag_is_passed_through(self):
        self.post({"name": "s1", "host": "ulak_31", "force": True})
        self.assertTrue(self.calls[0]["force"])

    def test_name_is_required(self):
        status, _ = self.post({"host": "ulak_31"})
        self.assertEqual(status, 400)
        self.assertEqual(self.calls, [])

    def test_token_is_required(self):
        status, _ = self.post({"name": "s1", "host": "ulak_31"}, token="wrong")
        self.assertEqual(status, 401)
        self.assertEqual(self.calls, [])


class LayoutRecognisesMirrorWindowsTests(unittest.TestCase):
    """`layout` pencereyi başlığın `known_names` ile TAM eşleşmesiyle tanır; mirror başlığı `host:ad`."""

    def plan(self, known):
        screen = ScreenGeometry(0, 0, 1920, 1080, cols=2, rows=2)
        windows = {"0x1": "ulak_31:rustrino20261009", "0x2": "cops20261007", "0x3": "vim notes.txt"}
        plan, name_to_wid = build_layout_plan(windows, screen, claude_only=True, known_names=known)
        return plan, name_to_wid

    def test_a_mirror_window_is_tiled_once_its_spec_is_known(self):
        plan, names = self.plan({"cops20261007", "ulak_31:rustrino20261009"})
        self.assertEqual(names, {"cops20261007": "0x2", "ulak_31:rustrino20261009": "0x1"})
        self.assertEqual((plan.total, plan.skipped), (2, 1))

    def test_without_the_spec_it_is_skipped_as_before(self):
        plan, names = self.plan({"cops20261007"})
        self.assertNotIn("ulak_31:rustrino20261009", names)
        self.assertEqual((plan.total, plan.skipped), (1, 2))

    def test_title_from_the_viewer_survives_list_windows_cleaning(self):
        # `_list_windows`: baştaki alfanümerik olmayan karakterler sıyrılır; `host:ad` harfle başlar, dokunulmaz
        import re
        self.assertEqual(re.sub(r"^[^A-Za-z0-9~/]+ ?", "", "ulak_31:rustrino20261009"), "ulak_31:rustrino20261009")


if __name__ == "__main__":
    unittest.main()
