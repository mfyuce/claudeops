"""Yerel SearXNG otomasyonu (`searxng.py`, `commands/searxng.py`) — stdlib unittest.

Çalıştırma:  python3 py/tests/test_searxng.py -v

Kapsadığı iş (kullanıcı kararı 2026-10-16: "ucli web search yapacaksa docker da oto olsun şimdilik"): ucli oturumu
açılırken claudeops'un kendi yönettiği yerel SearXNG kapsayıcısı (docker) kendiliğinden kurulur/başlar. Gerçek docker'a,
ağa, panele ya da gerçek ayar dosyalarına DOKUNMAZ: docker CLI küçük bir sahte (`FakeDocker`), saat sahte, durum dizini
geçici. Her testin sonunda ortak bir güvenlik denetimi çalışır: yapılan HER docker çağrısı yalnız claudeops'un TAM
adlı kapsayıcısını adresler (ps/prune/kill/desen yok).
"""
import contextlib
import fcntl
import http.server
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import searxng as sx  # noqa: E402
from claudeops.commands import searxng as sx_cmd  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakeDocker:
    """docker CLI'nın küçük taklidi: yalnız searxng.py'nin kullandığı komutlar; başkası AssertionError."""

    def __init__(self):
        self.usable = True
        self.images = set()
        self.containers = {}        # ad -> {"labels": {}, "running": bool, "status": str, "port": int | None}
        self.calls = []
        self.pull_ok = True
        self.start_ok = True
        self.run_error = ""
        self.conflict_ports = set()   # bu portlarda `run` "port is already allocated" verir (Created kalıntısı bırakır)
        self.image_id = "sha256:feedbeef"

    @staticmethod
    def res(rc=0, out="", err=""):
        return subprocess.CompletedProcess(["docker"], rc, out, err)

    def add(self, name, *, ours=True, running=True, port=8888, status=None, ready_at=0.0):
        self.containers[name] = {"labels": {"claudeops.managed": "searxng"} if ours else {},
                                 "running": running, "port": port, "ready_at": ready_at,
                                 "status": status or ("running" if running else "exited")}

    def __call__(self, *args, timeout=10.0):
        if not self.usable:
            raise sx.DockerUnavailable("daemon yok")
        self.calls.append(args)
        verb = args[0]
        if verb == "version":
            return self.res(out="29.8.1\n")
        if args[:2] == ("container", "inspect"):
            c = self.containers.get(args[2])
            if c is None:
                return self.res(1, "[]\n", f"Error: No such container: {args[2]}\n")
            binds = {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(c["port"])}]} if c["port"] else {}
            return self.res(out=json.dumps([{"Config": {"Labels": c["labels"]},
                                             "State": {"Running": c["running"], "Status": c["status"]},
                                             "HostConfig": {"PortBindings": binds}}]))
        if args[:2] == ("image", "inspect"):
            if args[2] not in self.images:
                return self.res(1, "", "Error: No such image\n")
            return self.res(out=self.image_id + "\n" if "--format" in args else "[{}]")
        if verb == "pull":
            if not self.pull_ok:
                return self.res(1, "", "Error response from daemon: Get https://registry-1.docker.io: no such host\n")
            self.images.add(args[1])
            return self.res(out="Status: Downloaded newer image\n")
        if verb == "start":
            if not self.start_ok:
                return self.res(1, "", "Error: driver failed programming external connectivity: port is already allocated\n")
            self.containers[args[1]].update(running=True, status="running")
            return self.res(out=args[1] + "\n")
        if verb == "stop":
            self.containers[args[-1]].update(running=False, status="exited")
            return self.res(out=args[-1] + "\n")
        if verb == "rm":
            self.containers.pop(args[-1], None)
            return self.res(out=args[-1] + "\n")
        if verb == "logs":
            return self.res(out="SearXNG 2026\nboom: cannot read settings\n")
        if verb == "run":
            return self._run(args)
        raise AssertionError(f"beklenmeyen docker çağrısı: {args}")

    def _run(self, args):
        name = args[args.index("--name") + 1]
        labels = dict(a.split("=", 1) for i, a in enumerate(args) if i and args[i - 1] == "--label")
        publish = args[args.index("-p") + 1]
        port = int(publish.split(":")[1])
        if name in self.containers:
            return self.res(125, "", f'docker: Error response from daemon: Conflict. The container name "{name}" is already in use\n')
        if port in self.conflict_ports:
            self.containers[name] = {"labels": labels, "running": False, "status": "created", "port": port, "ready_at": 0.0}
            return self.res(125, "", f"docker: Error response from daemon: Bind for 127.0.0.1:{port} failed: port is already allocated.\n")
        if self.run_error:
            return self.res(125, "", self.run_error + "\n")
        self.containers[name] = {"labels": labels, "running": True, "status": "running", "port": port, "ready_at": 0.0}
        return self.res(out="0123456789abcdef\n")


class SxCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.docker = FakeDocker()
        self.clock = Clock()
        self.events = []
        self.listening = set()          # /healthz'e cevap veren, kapsayıcıdan bağımsız portlar
        self.host_busy_ports = set()    # başka bir sürecin dinlediği portlar
        self.children = 0
        self.json_result = (True, "")
        for p in (
            mock.patch.object(sx, "STATE_DIR", str(self.tmp / "searxng")),
            mock.patch.object(sx, "_docker", self.docker),
            mock.patch.object(sx, "_owner", lambda: "tester"),
            mock.patch.object(sx, "healthy", self._healthy),
            mock.patch.object(sx, "json_search_works", lambda port, timeout=25.0: self.json_result),
            mock.patch.object(sx, "_port_free", self._port_free),
            mock.patch.object(sx, "_now", self.clock.now),
            mock.patch.object(sx, "_wall", self.clock.now),
            mock.patch.object(sx, "_sleep", self.clock.sleep),
            mock.patch.object(sx, "_spawn_provision_child", self._spawn_child),
            mock.patch.object(sx, "diag_log", lambda event, **kw: self.events.append((event, kw))),
            mock.patch.object(sx, "_down_until", 0.0),
            mock.patch.object(sx, "_down_reason", ""),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.name = sx.container_name()

    def tearDown(self):
        self.assert_docker_calls_are_scoped()

    # -- yardımcılar --------------------------------------------------------------------------------
    def _healthy(self, port, timeout=1.5):
        if port in self.listening:
            return True
        return any(c["running"] and c["port"] == port and self.clock.now() >= c["ready_at"]
                   for c in self.docker.containers.values())

    def _port_free(self, port):
        return port not in self.host_busy_ports and not any(
            c["running"] and c["port"] == port for c in self.docker.containers.values())

    def _spawn_child(self):
        self.children += 1
        return True

    def names(self):
        return [e for e, _ in self.events]

    def verbs(self):
        return [" ".join(c[:2]) if c[0] in ("container", "image") else c[0] for c in self.docker.calls]

    def save_state(self, **kw):
        sx._update_state(**kw)

    @contextlib.contextmanager
    def other_process_holds_the_lock(self):
        os.makedirs(sx.STATE_DIR, exist_ok=True)
        fd = os.open(sx._lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            os.close(fd)

    def assert_docker_calls_are_scoped(self):
        """Her docker çağrısı yalnız claudeops'un TAM adlı kapsayıcısını (ya da imajını) adresler."""
        for c in self.docker.calls:
            self.assertNotIn(c[0], ("ps", "prune", "kill", "exec", "system", "volume", "network", "restart"), c)
            if c[0] in ("start", "stop", "logs", "rm"):
                self.assertEqual(c[-1], self.name, c)
            elif c[:2] == ("container", "inspect"):
                self.assertEqual(c[2], self.name, c)
            elif c[0] == "run":
                self.assertEqual(c[c.index("--name") + 1], self.name, c)
            elif c[0] in ("pull",) or c[:2] == ("image", "inspect"):
                self.assertEqual(c[2 if c[0] == "image" else 1], sx.IMAGE, c)
            else:
                self.assertEqual(c[0], "version", c)


# ── adlar, argümanlar, yapılandırma dosyası, port ───────────────────────────────────────────────────

class NamingTests(SxCase):
    def test_the_name_is_per_user(self):
        self.assertEqual(sx.container_name(), "claudeops-searxng-tester")

    def test_odd_user_names_are_made_docker_safe(self):
        for user, want in (("Fatih Yüce", "claudeops-searxng-fatih-y-ce"), ("DOMAIN\\bob", "claudeops-searxng-domain-bob"),
                           ("--", "claudeops-searxng-%d" % os.getuid())):
            with mock.patch.object(sx, "_owner", lambda u=user: u):
                self.assertEqual(sx.container_name(), want, user)
                self.assertRegex(sx.container_name(), r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")

    def test_an_isolated_state_dir_gets_its_own_container_name(self):
        with mock.patch.object(sx, "CLAUDEOPS_DIR", str(self.tmp / "copy")), \
             mock.patch.object(sx, "CLAUDE_DIR", str(self.tmp / "home" / ".claude")):
            iso = sx.container_name()
        with mock.patch.object(sx, "CLAUDEOPS_DIR", str(self.tmp / "home" / ".claude" / "claudeops")), \
             mock.patch.object(sx, "CLAUDE_DIR", str(self.tmp / "home" / ".claude")):
            live = sx.container_name()
        self.assertEqual(live, "claudeops-searxng-tester")
        self.assertRegex(iso, r"^claudeops-searxng-tester-[0-9a-f]{8}$")


class RunArgsTests(SxCase):
    def args(self, port=8888):
        return sx.run_args(port)

    def pairs(self, args):
        return [(args[i], args[i + 1]) for i in range(len(args) - 1)]

    def test_published_on_loopback_only(self):
        a = self.args(8890)
        publishes = [v for k, v in self.pairs(a) if k == "-p"]
        self.assertEqual(publishes, ["127.0.0.1:8890:8080"])
        self.assertNotIn("--network", a)
        self.assertNotIn("host", a)
        self.assertFalse(any(re.match(r"^(0\.0\.0\.0:|:|\d+:)", v) for v in publishes))

    def test_unprivileged_and_resource_limited(self):
        a = self.args()
        for flag, value in (("--user", "977:977"), ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"),
                            ("--memory", "1g"), ("--pids-limit", "512")):
            self.assertIn((flag, value), self.pairs(a), flag)
        self.assertNotIn("--privileged", a)
        self.assertNotIn("--cap-add", a)

    def test_it_never_comes_back_on_its_own_only_a_ucli_spawn_starts_it(self):
        """Kullanıcı: 'ucli varsa docker'; özellik kalkınca geride kendiliğinden dönen kalıntı kalmasın (TBD#88)."""
        self.assertIn(("--restart", "no"), self.pairs(self.args()))
        self.assertFalse([v for k, v in self.pairs(self.args()) if k == "--restart" and v in ("always", "unless-stopped")])

    def test_labelled_and_named_so_that_only_ours_is_ever_touched(self):
        a = self.args()
        self.assertIn(("--name", self.name), self.pairs(a))
        self.assertIn(("--label", "claudeops.managed=searxng"), self.pairs(a))

    def test_config_is_a_read_only_bind_and_the_cache_is_tmpfs(self):
        a = self.args()
        mounts = [v for k, v in self.pairs(a) if k == "--mount"]
        self.assertEqual(len(mounts), 1)
        self.assertIn("target=/etc/searxng", mounts[0])
        self.assertTrue(mounts[0].endswith(",readonly"))
        self.assertIn(f"source={sx._conf_dir()},", mounts[0])
        tmpfs = [v for k, v in self.pairs(a) if k == "--tmpfs"]
        self.assertEqual(len(tmpfs), 1)
        self.assertTrue(tmpfs[0].startswith("/var/cache/searxng:rw,uid=977,gid=977,"))
        self.assertFalse(any(k == "-v" for k, _ in self.pairs(a)), "anonim disk birimi açılmamalı")

    def test_the_image_entrypoint_is_told_not_to_chown_the_host_config_dir(self):
        self.assertIn(("-e", "FORCE_OWNERSHIP=false"), self.pairs(self.args()))

    def test_no_secret_reaches_argv(self):
        sx.ensure_settings_file()
        secret = re.search(r'secret_key: "([0-9a-f]+)"', Path(sx._conf_dir(), "settings.yml").read_text()).group(1)
        self.assertNotIn(secret, " ".join(self.args()))
        self.assertEqual(self.args()[-1], sx.IMAGE)


class SettingsFileTests(SxCase):
    def path(self):
        return Path(sx._conf_dir(), "settings.yml")

    def test_created_with_json_enabled_and_a_random_secret(self):
        sx.ensure_settings_file()
        text = self.path().read_text()
        self.assertIn("use_default_settings: true", text)
        self.assertRegex(text, r"(?m)^\s*-\s*json\s*$")
        self.assertRegex(text, r'secret_key: "[0-9a-f]{64}"')
        self.assertIn("limiter: false", text)

    def test_modes_let_the_container_user_read_it(self):
        sx.ensure_settings_file()
        self.assertEqual(stat.S_IMODE(os.stat(sx._conf_dir()).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o644)

    def test_a_valid_file_is_left_alone_so_hand_edits_survive(self):
        sx.ensure_settings_file()
        edited = self.path().read_text() + "outgoing:\n  request_timeout: 5.0\n"
        self.path().write_text(edited)
        sx.ensure_settings_file()
        self.assertEqual(self.path().read_text(), edited)

    def test_a_file_without_json_is_repaired_keeping_the_secret(self):
        sx.ensure_settings_file()
        secret = re.search(r'secret_key: "([0-9a-f]+)"', self.path().read_text()).group(1)
        self.path().write_text(self.path().read_text().replace("    - json\n", ""))
        sx.ensure_settings_file()
        text = self.path().read_text()
        self.assertRegex(text, r"(?m)^\s*-\s*json\s*$")
        self.assertIn(secret, text)

    def test_a_garbage_file_is_replaced_and_leaves_no_temp_file(self):
        Path(sx._conf_dir()).mkdir(parents=True)
        self.path().write_text("not: [yaml")
        sx.ensure_settings_file()
        self.assertRegex(self.path().read_text(), r'secret_key: "[0-9a-f]{64}"')
        self.assertEqual(sorted(p.name for p in Path(sx._conf_dir()).iterdir()), ["settings.yml"])


class PickPortTests(SxCase):
    def test_default_is_the_first_free_port_from_8888(self):
        self.assertEqual(sx.pick_port(), 8888)
        self.host_busy_ports = {8888, 8889}
        self.assertEqual(sx.pick_port(), 8890)

    def test_a_remembered_free_port_wins_so_running_sessions_keep_a_valid_address(self):
        self.assertEqual(sx.pick_port(8895), 8895)
        self.host_busy_ports = {8895}
        self.assertEqual(sx.pick_port(8895), 8888)

    def test_skip_list_and_exhaustion(self):
        self.assertEqual(sx.pick_port(None, skip=[8888]), 8889)
        self.host_busy_ports = set(range(8888, 8988))
        with self.assertRaises(RuntimeError):
            sx.pick_port()


class RealPortProbeTests(unittest.TestCase):
    def test_a_listener_blocks_the_port_but_time_wait_leftovers_do_not(self):
        import socket
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        self.assertFalse(sx._port_free(port))
        c = socket.create_connection(("127.0.0.1", port))
        a, _ = srv.accept()
        a.close()                       # sunucu tarafı önce kapatır → TIME_WAIT bizde kalır
        c.close()
        srv.close()
        self.assertTrue(sx._port_free(port))


# ── spawn yolu: ensure_search_url ───────────────────────────────────────────────────────────────────

class EnsureFastPathTests(SxCase):
    def test_a_healthy_remembered_port_answers_without_touching_docker(self):
        self.save_state(port=8888)
        self.listening.add(8888)
        self.assertEqual(sx.ensure_search_url("vc"), "http://127.0.0.1:8888/search")
        self.assertEqual(self.docker.calls, [])
        self.assertEqual(self.events, [])

    def test_the_address_shape_is_what_ucli_expects(self):
        self.assertEqual(sx.search_url(8891), "http://127.0.0.1:8891/search")


class EnsureSlowPathTests(SxCase):
    def test_docker_unavailable_returns_none_logs_once_and_is_cached(self):
        self.docker.usable = False
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.names(), ["searxng_unavailable"])
        self.assertEqual(self.docker.calls, [])
        self.clock.t += sx.DOCKER_DOWN_TTL_S + 1
        self.docker.usable = True
        self.docker.add(self.name)
        self.assertEqual(sx.ensure_search_url("vc"), "http://127.0.0.1:8888/search")

    def test_a_stopped_container_is_started_by_its_exact_name_and_waited_for(self):
        self.docker.add(self.name, running=False)
        self.assertEqual(sx.ensure_search_url("vc"), "http://127.0.0.1:8888/search")
        self.assertEqual(self.verbs(), ["container inspect", "start"])
        self.assertEqual(self.names(), ["searxng_started"])
        self.assertEqual(sx._read_state()["port"], 8888)

    def test_a_running_but_still_booting_container_is_waited_for_within_the_budget(self):
        self.docker.add(self.name, ready_at=self.clock.now() + 3.0)
        self.assertEqual(sx.ensure_search_url("vc"), "http://127.0.0.1:8888/search")
        self.assertEqual(self.verbs(), ["container inspect"])

    def test_a_container_that_never_gets_ready_gives_up_after_the_budget(self):
        self.docker.add(self.name, ready_at=self.clock.now() + 1e9)
        t0 = self.clock.now()
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertLessEqual(self.clock.now() - t0, sx.READY_WAIT_S + 1.0)
        self.assertEqual(self.names(), ["searxng_not_ready"])
        self.assertEqual(self.children, 0)

    def test_a_crash_looping_container_is_handed_to_the_provision_that_rebuilds_it(self):
        for status in ("restarting", "dead"):
            self.children = 0
            self.events.clear()
            self.save_state(provision_started_at=None)
            self.docker.add(self.name, status=status, ready_at=self.clock.now() + 1e9)
            self.assertIsNone(sx.ensure_search_url("vc"))
            self.assertEqual(self.children, 1, status)
            self.assertEqual(self.names(), ["searxng_not_ready", "searxng_provision_started"], status)

    def test_no_container_starts_the_detached_provision_and_returns_at_once(self):
        t0 = self.clock.now()
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.clock.now(), t0)                    # hiç beklemedi
        self.assertEqual(self.children, 1)
        self.assertEqual(self.names(), ["searxng_provision_started"])
        self.assertNotIn("pull", self.verbs())                    # spawn yolu ASLA imaj çekmez
        self.assertNotIn("run", self.verbs())

    def test_a_burst_of_spawns_starts_one_provision_not_one_per_spawn(self):
        for i in range(4):
            sx.ensure_search_url(f"s{i}")
        self.assertEqual(self.children, 1)
        self.clock.t += sx.KICK_WINDOW_S + 1                      # işaret eskidi, kimse kuramamış → yeniden dene
        sx.ensure_search_url("later")
        self.assertEqual(self.children, 2)

    def test_a_running_provision_holds_the_lock_and_blocks_new_ones(self):
        with self.other_process_holds_the_lock():
            self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.children, 0)

    def test_a_recent_failure_blocks_automatic_retries_until_the_cooldown_passes(self):
        self.save_state(provision_failed_at=self.clock.now() - 30)
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.children, 0)
        self.assertEqual(self.names(), ["searxng_provision_cooldown"])
        self.clock.t += sx.FAIL_COOLDOWN_S
        sx.ensure_search_url("vc")
        self.assertEqual(self.children, 1)

    def test_a_container_that_is_not_ours_is_never_touched(self):
        self.docker.add(self.name, ours=False, running=False)
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.verbs(), ["container inspect"])
        self.assertEqual(self.names(), ["searxng_name_conflict"])
        self.assertEqual(self.children, 0)

    def test_a_failing_start_hands_over_to_the_provision_that_rebuilds_it(self):
        self.docker.add(self.name, running=False)
        self.docker.start_ok = False
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.names(), ["searxng_start_failed", "searxng_provision_started"])
        self.assertEqual(self.children, 1)

    def test_a_container_without_a_port_binding_is_rebuilt(self):
        self.docker.add(self.name, port=None)
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.children, 1)

    def test_it_never_raises_whatever_goes_wrong(self):
        with mock.patch.object(sx, "_ensure", side_effect=RuntimeError("boom")):
            self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.names(), ["searxng_ensure_error"])
        with mock.patch.object(sx, "_ensure", side_effect=sx.DockerUnavailable("down")):
            self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.names()[-1], "searxng_unavailable")

    def test_a_docker_error_in_the_middle_marks_docker_down_for_a_while(self):
        self.docker.add(self.name, running=False)
        real = self.docker.__call__

        def flaky(*args, timeout=10.0):
            if args[0] == "start":
                raise sx.DockerUnavailable("zaman aşımı")
            return real(*args, timeout=timeout)
        with mock.patch.object(sx, "_docker", flaky):
            self.assertIsNone(sx.ensure_search_url("vc"))
            n = len(self.docker.calls)
            self.assertIsNone(sx.ensure_search_url("vc"))
            self.assertEqual(len(self.docker.calls), n, "negatif önbellek: ikinci çağrı docker'a gitmedi")


class InspectTests(SxCase):
    def test_absent_exists_and_the_label_decides_ownership(self):
        self.assertEqual(sx.inspect_box(), sx.Box())
        self.docker.add(self.name, running=False, port=8893, status="exited")
        box = sx.inspect_box()
        self.assertEqual((box.exists, box.ours, box.running, box.port, box.status), (True, True, False, 8893, "exited"))
        self.docker.add(self.name, ours=False)
        self.assertFalse(sx.inspect_box().ours)

    def test_an_inspect_failure_that_is_not_no_such_container_is_not_mistaken_for_absent(self):
        """İzin hatası / daemon sorunu 'kapsayıcı yok' sayılırsa var olan kapsayıcının üstüne yenisi kurulmaya çalışılır."""
        def denied(*args, timeout=10.0):
            self.docker.calls.append(args)
            return FakeDocker.res(1, "", "permission denied while trying to connect to the Docker daemon socket")
        with mock.patch.object(sx, "_docker", denied):
            with self.assertRaises(sx.DockerUnavailable):
                sx.inspect_box()
            self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.children, 0)
        self.assertEqual(self.names(), ["searxng_unavailable"])

    def test_garbage_inspect_output_is_a_docker_problem_not_a_crash(self):
        def garbage(*args, timeout=10.0):
            self.docker.calls.append(args)
            return FakeDocker.res(0, "not json", "")
        with mock.patch.object(sx, "_docker", garbage), self.assertRaises(sx.DockerUnavailable):
            sx.inspect_box()

    def test_removal_re_checks_the_label_even_though_callers_already_did(self):
        self.docker.add(self.name, ours=False)
        sx._remove_ours()
        self.assertIn(self.name, self.docker.containers)
        self.assertEqual(self.verbs(), ["container inspect"])
        self.docker.add(self.name, ours=True)
        sx._remove_ours()
        self.assertNotIn(self.name, self.docker.containers)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen.append(self.path)
        path = self.path.split("?")[0]
        status, body = self.server.routes.get(path, (404, b""))
        delay = self.server.delays.get(path)
        if delay:
            time.sleep(delay)
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *a):
        pass


class HttpProbeTests(unittest.TestCase):
    """Gerçek `healthy` / `json_search_works` / `_http_get`, gerçek bir yerel HTTP sunucusuna karşı."""

    def serve(self, routes, delays=None):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.routes, srv.delays, srv.seen = routes, delays or {}, []
        threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True).start()   # shutdown() 0.5 sn beklemesin
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv, srv.server_address[1]

    def test_healthz_200_is_healthy_and_the_probe_sends_no_search(self):
        srv, port = self.serve({"/healthz": (200, b"OK")})
        self.assertTrue(sx.healthy(port))
        self.assertEqual(srv.seen, ["/healthz"])

    def test_anything_but_200_or_no_listener_is_unhealthy(self):
        for status in (404, 500, 503, 302):
            _, port = self.serve({"/healthz": (status, b"x")})
            self.assertFalse(sx.healthy(port), status)
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        self.assertFalse(sx.healthy(dead))

    def test_a_slow_server_is_cut_off_by_the_timeout(self):
        _, port = self.serve({"/healthz": (200, b"OK")}, delays={"/healthz": 1.5})
        t0 = time.monotonic()
        self.assertFalse(sx.healthy(port, timeout=0.2))
        self.assertLess(time.monotonic() - t0, 1.2)

    def test_environment_proxies_are_ignored_for_loopback(self):
        _, port = self.serve({"/healthz": (200, b"OK")})
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
                                          "no_proxy": ""}):
            self.assertTrue(sx.healthy(port))

    def test_json_search_ok_requires_200_and_a_results_list(self):
        good = json.dumps({"query": "claudeops", "results": [{"url": "https://x"}]}).encode()
        srv, port = self.serve({"/search": (200, good)})
        self.assertEqual(sx.json_search_works(port), (True, ""))
        self.assertEqual(srv.seen, ["/search?q=claudeops&format=json"])
        self.assertEqual(sx.json_search_works(self.serve({"/search": (200, b'{"results": []}')})[1]), (True, ""))

    def test_json_search_failure_reasons(self):
        cases = ((403, b"forbidden", "json_disabled"), (500, b"", "http_500"), (200, b"<html>", "bad_json"),
                 (200, b'{"nope": 1}', "bad_json"), (200, b"[1, 2]", "bad_json"), (200, b'{"results": "x"}', "bad_json"))
        for status, body, why in cases:
            _, port = self.serve({"/search": (status, body)})
            self.assertEqual(sx.json_search_works(port), (False, why), (status, body))

    def test_json_search_without_a_listener_reports_http_0(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        self.assertEqual(sx.json_search_works(dead, timeout=0.5), (False, "http_0"))


# ── kurulum (yavaş yol) ─────────────────────────────────────────────────────────────────────────────

class ProvisionTests(SxCase):
    def test_fresh_machine_pulls_then_configures_then_runs_then_verifies(self):
        res = sx.provision()
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["state"], res["port"], res["url"]), ("ready", 8888, "http://127.0.0.1:8888/search"))
        v = self.verbs()
        self.assertEqual(v[:5], ["version", "container inspect", "image inspect", "pull", "run"])
        self.assertTrue(Path(sx._conf_dir(), "settings.yml").is_file())
        st = sx._read_state()
        self.assertEqual((st["port"], st["image_id"]), (8888, "sha256:feedbeef"))
        self.assertNotIn("provision_failed_at", st)
        self.assertIn(("searxng_pull_started"), self.names())
        self.assertEqual(self.names()[-1], "searxng_provision")

    def test_the_image_is_pulled_only_when_missing(self):
        self.docker.images.add(sx.IMAGE)
        self.assertTrue(sx.provision()["ok"])
        self.assertNotIn("pull", self.verbs())

    def test_pull_failure_runs_nothing_and_arms_the_cooldown(self):
        self.docker.pull_ok = False
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "pull_failed"))
        self.assertIn("no such host", res["detail"])
        self.assertNotIn("run", self.verbs())
        self.assertIn("provision_failed_at", sx._read_state())
        self.assertIsNone(sx.ensure_search_url("vc"))
        self.assertEqual(self.children, 0)

    def test_docker_unavailable_is_reported_not_raised(self):
        self.docker.usable = False
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "docker_unavailable"))
        self.assertIn("provision_failed_at", sx._read_state())

    def test_a_port_conflict_removes_the_leftover_and_retries_on_the_next_port(self):
        self.docker.images.add(sx.IMAGE)
        self.docker.conflict_ports = {8888}
        res = sx.provision()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["port"], 8889)
        self.assertEqual(self.verbs().count("run"), 2)
        self.assertEqual(self.verbs().count("rm"), 1)             # "Created" kalıntısı silindi
        self.assertTrue(self.docker.containers[self.name]["running"])

    def test_a_conflict_on_every_try_gives_up_with_run_failed(self):
        self.docker.images.add(sx.IMAGE)
        self.docker.conflict_ports = set(range(8888, 8995))
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "run_failed"))
        self.assertEqual(self.verbs().count("run"), 3)
        self.assertNotIn(self.name, self.docker.containers)

    def test_any_other_run_error_is_reported_and_cleaned_up(self):
        self.docker.images.add(sx.IMAGE)
        self.docker.run_error = "docker: Error response from daemon: no space left on device"
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "run_failed"))
        self.assertIn("no space left", res["detail"])
        self.assertEqual(self.verbs().count("run"), 1)

    def test_an_existing_stopped_container_is_started_not_recreated(self):
        self.docker.add(self.name, running=False, port=8893)
        res = sx.provision()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["port"], 8893)
        self.assertNotIn("run", self.verbs())
        self.assertNotIn("pull", self.verbs())

    def test_a_stopped_container_that_cannot_start_is_rebuilt(self):
        self.docker.images.add(sx.IMAGE)
        self.docker.add(self.name, running=False, port=8893)
        self.docker.start_ok = False
        t0 = self.clock.now()
        res = sx.provision()
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.verbs().count("run"), 1)
        self.assertIn("rm", self.verbs())
        self.assertLess(self.clock.now() - t0, 5.0, "başarısız start'tan sonra boşuna sağlık beklenmemeli")

    def test_an_already_healthy_container_is_a_no_op(self):
        self.docker.images.add(sx.IMAGE)
        self.docker.add(self.name)
        res = sx.provision()
        self.assertTrue(res["ok"], res)
        self.assertNotIn("run", self.verbs())
        self.assertNotIn("rm", self.verbs())

    def test_a_foreign_container_with_our_name_is_reported_and_left_alone(self):
        self.docker.add(self.name, ours=False)
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "name_conflict"))
        self.assertEqual(self.verbs(), ["version", "container inspect"])

    def test_a_second_provision_while_one_runs_does_nothing(self):
        with self.other_process_holds_the_lock():
            res = sx.provision()
        self.assertEqual(res["state"], "busy")
        self.assertEqual(self.docker.calls, [])
        self.assertNotIn("provision_failed_at", sx._read_state())

    def test_json_disabled_is_reported_and_the_port_is_not_advertised(self):
        self.docker.images.add(sx.IMAGE)
        self.json_result = (False, "json_disabled")
        res = sx.provision()
        self.assertEqual((res["ok"], res["state"], res["detail"]), (False, "json_probe_failed", "json_disabled"))
        self.assertNotIn("port", sx._read_state())

    def test_a_container_that_never_becomes_healthy_reports_its_log_tail(self):
        self.docker.images.add(sx.IMAGE)
        real_run = self.docker._run

        def slow(args):
            out = real_run(args)
            self.docker.containers[self.name]["ready_at"] = self.clock.now() + 1e9
            return out
        with mock.patch.object(self.docker, "_run", slow):
            res = sx.provision(wait_s=5.0)
        self.assertEqual((res["ok"], res["state"]), (False, "not_ready"))
        self.assertIn("cannot read settings", res["detail"])

    def test_unexpected_errors_are_contained(self):
        with mock.patch.object(sx, "_provision_locked", side_effect=ValueError("boom")):
            res = sx.provision()
        self.assertEqual((res["ok"], res["state"]), (False, "error"))

    def test_success_clears_an_old_failure_mark(self):
        self.save_state(provision_failed_at=1.0, provision_started_at=2.0)
        self.docker.images.add(sx.IMAGE)
        self.assertTrue(sx.provision()["ok"])
        st = sx._read_state()
        self.assertNotIn("provision_failed_at", st)
        self.assertNotIn("provision_started_at", st)

    def test_recreation_keeps_the_remembered_port(self):
        self.docker.images.add(sx.IMAGE)
        self.save_state(port=8893)
        res = sx.provision()
        self.assertEqual(res["port"], 8893)


class EndToEndWithTheFakeTests(SxCase):
    def test_absent_then_provisioned_then_fast(self):
        self.assertIsNone(sx.ensure_search_url("first"))           # kurulum başlatıldı, bu oturum aramasız
        self.assertEqual(self.children, 1)
        self.assertTrue(sx.provision()["ok"])                      # ayrık süreç işini yaptı
        self.docker.calls.clear()
        self.assertEqual(sx.ensure_search_url("second"), "http://127.0.0.1:8888/search")
        self.assertEqual(self.docker.calls, [])                    # hızlı yol: docker'a dokunmadı


# ── CLI / durum / durdur / sil ──────────────────────────────────────────────────────────────────────

class ControlTests(SxCase):
    def test_status_describes_the_container(self):
        self.docker.add(self.name, port=8891)
        st = sx.status()
        self.assertEqual((st["container"], st["exists"], st["running"], st["healthy"], st["port"], st["url"]),
                         (self.name, True, True, True, 8891, "http://127.0.0.1:8891/search"))
        self.assertTrue(st["docker"].startswith("sürüm"))

    def test_status_does_not_advertise_a_url_that_does_not_answer(self):
        self.docker.add(self.name, port=8891, ready_at=self.clock.now() + 1e9)
        st = sx.status()
        self.assertEqual((st["running"], st["healthy"], st["port"], st["url"]), (True, False, 8891, None))

    def test_status_without_docker_says_so(self):
        self.docker.usable = False
        st = sx.status()
        self.assertTrue(st["docker"].startswith("kullanılamıyor"))
        self.assertFalse(st["exists"])

    def test_stop_and_remove_act_on_ours_only(self):
        self.docker.add(self.name)
        self.assertTrue(sx.stop()["ok"])
        self.assertFalse(self.docker.containers[self.name]["running"])
        self.assertTrue(sx.remove()["ok"])
        self.assertNotIn(self.name, self.docker.containers)
        rm = [c for c in self.docker.calls if c[0] == "rm"][0]
        self.assertEqual(rm, ("rm", "-f", "-v", self.name))        # anonim disk birimi de gitsin

    def test_absent_is_ok_and_foreign_is_refused(self):
        self.assertEqual(sx.remove()["state"], "absent")
        self.docker.add(self.name, ours=False)
        res = sx.remove()
        self.assertEqual((res["ok"], res["state"]), (False, "name_conflict"))
        self.assertIn(self.name, self.docker.containers)

    def test_stop_with_docker_down_is_reported(self):
        self.docker.usable = False
        self.assertEqual(sx.stop()["state"], "docker_unavailable")


class CommandTests(SxCase):
    def run_cmd(self, action):
        parser = __import__("argparse").ArgumentParser()
        sx_cmd.register(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["searxng", action])
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = args.func(args)
        return rc, json.loads(buf.getvalue())

    def test_registered_in_the_cli(self):
        from claudeops import cli
        self.assertIn(sx_cmd, cli.COMMANDS)

    def test_exit_codes_follow_the_result(self):
        self.docker.images.add(sx.IMAGE)
        rc, out = self.run_cmd("provision")
        self.assertEqual((rc, out["ok"]), (0, True))
        rc, out = self.run_cmd("status")
        self.assertEqual((rc, out["running"]), (0, True))
        rc, out = self.run_cmd("rm")
        self.assertEqual((rc, out["ok"]), (0, True))
        self.docker.pull_ok = False
        self.docker.images.clear()
        rc, out = self.run_cmd("provision")
        self.assertEqual((rc, out["state"]), (1, "pull_failed"))

    def test_unknown_actions_are_rejected_by_the_parser(self):
        parser = __import__("argparse").ArgumentParser()
        sx_cmd.register(parser.add_subparsers(dest="command"))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            parser.parse_args(["searxng", "prune"])


class DetachedChildTests(unittest.TestCase):
    """Gerçek `_spawn_provision_child`: ayrık süreç doğru komutla, doğru dizinden, kendi oturumunda başlar."""

    def test_the_child_command_and_isolation(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(sx, "STATE_DIR", os.path.join(d, "searxng")), \
             mock.patch.object(sx.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            self.assertTrue(sx._spawn_provision_child())
            argv = popen.call_args[0][0]
            kw = popen.call_args[1]
            self.assertEqual(argv, [sys.executable, "-m", "claudeops", "searxng", "provision"])
            self.assertTrue(kw["start_new_session"])
            self.assertEqual(kw["stdin"], subprocess.DEVNULL)
            self.assertTrue(os.path.isfile(os.path.join(kw["cwd"], "claudeops", "searxng.py")))

    def test_a_spawn_failure_is_contained(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(sx, "STATE_DIR", os.path.join(d, "searxng")), \
             mock.patch.object(sx.subprocess, "Popen", side_effect=OSError("no fork")), \
             mock.patch.object(sx, "diag_log"):
            self.assertFalse(sx._spawn_provision_child())


class RealDockerWrapperTests(unittest.TestCase):
    """`_docker`un kendi sözleşmesi (docker'ı sahte bir betikle değiştirir; gerçek docker'a dokunmaz)."""

    def fake_docker(self, d, body):
        p = Path(d) / "docker"
        p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        p.chmod(0o755)

    def test_missing_cli_is_docker_unavailable(self):
        with mock.patch.object(sx.shutil, "which", return_value=None):
            with self.assertRaises(sx.DockerUnavailable):
                sx._docker("version")

    def test_a_command_failure_is_a_result_not_an_exception(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_docker(d, 'echo "no such thing" >&2; exit 3')
            with mock.patch.dict(os.environ, {"PATH": d}):
                res = sx._docker("anything")
        self.assertEqual((res.returncode, res.stderr.strip()), (3, "no such thing"))

    def test_a_hung_cli_is_cut_off_by_the_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_docker(d, "sleep 30")
            with mock.patch.dict(os.environ, {"PATH": d + ":/usr/bin:/bin"}):
                with self.assertRaises(sx.DockerUnavailable) as cm:
                    sx._docker("ps", timeout=0.3)
        self.assertIn("bitmedi", str(cm.exception))

    def test_non_utf8_output_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_docker(d, "printf 'ok \\377\\376 bytes'")
            with mock.patch.dict(os.environ, {"PATH": d}):
                self.assertIn("bytes", sx._docker("version").stdout)


if __name__ == "__main__":
    unittest.main()
