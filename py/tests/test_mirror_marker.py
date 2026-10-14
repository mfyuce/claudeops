"""Uzak satırlardaki "masaüstünde mirror penceresi açık mı" işaretçisinin (`mirror_open`) testleri:
`mirrors.note_mirror`, `discovery.find_sessions(mirrors_out=...)`, `web_hosts.merge_status(open_mirrors=...)` ve
`web._status_payload`'ın bunları bağlaması (stdlib unittest).

Çalıştırma:  python3 py/tests/test_mirror_marker.py -v

Canlı süreçleri taramaz (psutil sahte; tek istisna: kendi başlattığı çocuk sürecin gerçek taramada görüldüğünü
doğrulayan test), ağa çıkmaz, pencere açmaz.
"""
import os
import subprocess
import sys
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import discovery, mirrors  # noqa: E402
from claudeops.commands import web, web_hosts  # noqa: E402
from claudeops.providers.shell_provider import PROC_TAG, ShellProvider  # noqa: E402

WATCH = ["python3", "-m", "claudeops", "watch"]
UIDS = namedtuple("UIDS", "real effective saved")
ME = os.getuid()


class FakeProc:
    """`psutil.Process`ın `find_sessions`ın dokunduğu yüzeyi: `.pid`, `.info`, `.cwd()`, `.environ()`."""

    def __init__(self, pid, cmdline, uid=ME, cops_name=None):
        self.pid = pid
        self.info = {"pid": pid, "cmdline": cmdline, "uids": UIDS(uid, uid, uid)}
        self._env = {"COPS_NAME": cops_name} if cops_name else {}

    def cwd(self):
        return "/tmp"

    def environ(self):
        return self._env

    def cpu_percent(self, interval=None):
        return 0.0


class NoteMirrorTests(unittest.TestCase):
    def test_records_the_pid_under_the_spec(self):
        found = {}
        mirrors.note_mirror(found, 10, WATCH + ["ulak_31:alerting"])
        self.assertEqual(found, {"ulak_31:alerting": [10]})

    def test_same_spec_accumulates_pids(self):
        found = {}
        mirrors.note_mirror(found, 10, WATCH + ["yuhem:a"])
        mirrors.note_mirror(found, 11, WATCH + ["--port", "9", "yuhem:a"])
        self.assertEqual(found, {"yuhem:a": [10, 11]})

    def test_anything_else_leaves_the_dict_alone(self):
        found = {}
        for cmdline in (None, [], ["claude", "--resume"], WATCH + ["yuhem:a", "--once"],
                        ["python3", "-m", "claudeops", "web"], WATCH):
            mirrors.note_mirror(found, 1, cmdline)
        self.assertEqual(found, {})


class FindSessionsMirrorsOutTests(unittest.TestCase):
    def scan(self, procs, **kw):
        calls = []

        def fake_iter(attrs=None):
            calls.append(attrs)
            return iter(procs)

        with mock.patch.object(discovery.psutil, "process_iter", fake_iter), \
                mock.patch.object(discovery, "_sessions_from_json", lambda: {}), \
                mock.patch.object(discovery, "PROVIDERS", {"shell": ShellProvider()}):
            sessions = discovery.find_sessions(measure_cpu=False, **kw)
        return sessions, calls

    def procs(self):
        return [
            FakeProc(500, [PROC_TAG], cops_name="zzz1"),                  # gerçek bir (shell) session
            FakeProc(10, WATCH + ["yuhem:a"]),                            # iki açık pencere, aynı session
            FakeProc(11, WATCH + ["yuhem:a", "--port", "9"]),
            FakeProc(12, WATCH + ["ulak_31:b"]),
            FakeProc(13, WATCH + ["yuhem:c", "--once"]),                  # tek kare basıp çıkan: pencere DEĞİL
            FakeProc(14, WATCH + ["yuhem:d"], uid=ME + 1),                # başka kullanıcının süreci
            FakeProc(15, ["python3", "-m", "claudeops", "web"]),
        ]

    def test_viewers_are_collected_in_the_same_pass(self):
        out = {}
        sessions, calls = self.scan(self.procs(), mirrors_out=out)
        self.assertEqual(out, {"yuhem:a": [10, 11], "ulak_31:b": [12]})
        self.assertEqual(len(calls), 1)                                   # ek tarama YOK: tek process_iter turu

    def test_viewers_are_not_sessions_and_fleet_result_is_unchanged(self):
        sessions_default, _ = self.scan(self.procs())
        sessions_with_out, _ = self.scan(self.procs(), mirrors_out={})
        key = lambda ss: sorted((s.name, s.pid, s.cli) for s in ss)  # noqa: E731
        self.assertEqual(key(sessions_default), [("zzz1", 500, "shell")])
        self.assertEqual(key(sessions_with_out), key(sessions_default))

    def test_default_does_not_collect_anything(self):
        # Çağıranların HİÇBİRİ değişmedi: `mirrors_out` verilmezse davranış eskisiyle aynı, fırlatma yok.
        sessions, calls = self.scan(self.procs())
        self.assertEqual([s.name for s in sessions], ["zzz1"])
        self.assertEqual(len(calls), 1)

    def test_a_real_viewer_process_is_seen_by_the_real_scan(self):
        spec = f"zzmarkerhost:zzmarker{os.getpid()}"
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "claudeops", "watch", spec])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        out = {}
        with mock.patch.object(discovery, "PROVIDERS", {}), mock.patch.object(discovery, "_sessions_from_json", lambda: {}):
            discovery.find_sessions(measure_cpu=False, mirrors_out=out)
        self.assertEqual(out.get(spec), [child.pid])
        # `running_mirrors` (ayrı tarama) ile AYNI cevabı verir: iki yol birbirine ters düşemez.
        self.assertEqual(mirrors.running_mirrors().get(spec), out[spec])


def _remote_row(name, **extra):
    return {"name": name, "cwd": f"/w/{name}", "host": "yuhem", "running": True, "tmux": True, **extra}


class MergeStatusMarkerTests(unittest.TestCase):
    def setUp(self):
        self.caches = {}
        for p in (
            mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: [{"name": h} for h in self.caches]),
            mock.patch.object(web_hosts, "get_cached", lambda h: self.caches.get(h)),
            mock.patch.object(web_hosts, "load_settings", lambda: {}),
        ):
            p.start()
            self.addCleanup(p.stop)

    def cache(self, host, sessions, closed=(), retired=()):
        self.caches[host] = {"ok": True, "error": None, "sessions": list(sessions), "closed": list(closed),
                             "retired": list(retired), "cli_list": [], "cli_options": {}, "dups": []}

    def payload(self, local=()):
        return {"sessions": list(local), "closed": [], "retired": []}

    def rows(self, merged, host="yuhem"):
        return {r["name"]: r for r in merged["sessions"] if r.get("host") == host}

    def test_open_and_closed_are_stamped_per_remote_row(self):
        self.cache("yuhem", [_remote_row("a"), _remote_row("b")])
        merged = web_hosts.merge_status(self.payload(), open_mirrors={"yuhem:a"})
        rows = self.rows(merged)
        self.assertIs(rows["a"]["mirror_open"], True)
        self.assertIs(rows["b"]["mirror_open"], False)

    def test_same_name_on_two_hosts_is_told_apart(self):
        self.cache("yuhem", [_remote_row("a")])
        self.cache("ulak_31", [_remote_row("a", host="ulak_31")])
        merged = web_hosts.merge_status(self.payload(), open_mirrors={"ulak_31:a"})
        self.assertIs(self.rows(merged, "yuhem")["a"]["mirror_open"], False)
        self.assertIs(self.rows(merged, "ulak_31")["a"]["mirror_open"], True)

    def test_match_is_exact_not_a_prefix(self):
        self.cache("yuhem", [_remote_row("ab"), _remote_row("a")])
        merged = web_hosts.merge_status(self.payload(), open_mirrors={"yuhem:ab"})   # `a` DEĞİL yalnız `ab` açık
        rows = self.rows(merged)
        self.assertIs(rows["ab"]["mirror_open"], True)
        self.assertIs(rows["a"]["mirror_open"], False)

    def test_cached_rows_are_copied_not_mutated(self):
        original = _remote_row("a")
        self.cache("yuhem", [original])
        merged = web_hosts.merge_status(self.payload(), open_mirrors={"yuhem:a"})
        self.assertNotIn("mirror_open", original)                 # poller önbelleğiyle paylaşımlı dict'e DOKUNULMADI
        self.assertIsNot(self.rows(merged)["a"], original)
        self.assertNotIn("mirror_open", self.caches["yuhem"]["sessions"][0])

    def test_stale_value_from_upstream_is_overwritten(self):
        self.cache("yuhem", [_remote_row("a", mirror_open=True)])           # uzak paneldeki (başka masaüstü) değer
        merged = web_hosts.merge_status(self.payload(), open_mirrors=set())
        self.assertIs(self.rows(merged)["a"]["mirror_open"], False)

    def test_no_marker_at_all_when_the_state_is_unknown(self):
        self.cache("yuhem", [_remote_row("a")])
        merged = web_hosts.merge_status(self.payload())                    # open_mirrors verilmedi: bilinmiyor
        self.assertNotIn("mirror_open", self.rows(merged)["a"])

    def test_empty_set_means_known_and_closed(self):
        self.cache("yuhem", [_remote_row("a")])
        merged = web_hosts.merge_status(self.payload(), open_mirrors=frozenset())
        self.assertIs(self.rows(merged)["a"]["mirror_open"], False)        # None ile KARIŞMAZ

    def test_local_closed_and_retired_rows_are_not_stamped(self):
        local = {"name": "loc", "cwd": "/w/loc", "host": "local", "running": True, "tmux": True}
        self.cache("yuhem", [_remote_row("a")], closed=[{"name": "c", "cwd": "/w/c", "host": "yuhem"}],
                   retired=[{"name": "r", "cwd": "/w/r", "host": "yuhem"}])
        merged = web_hosts.merge_status(self.payload([local]), open_mirrors={"yuhem:a", "local:loc", "yuhem:c"})
        self.assertNotIn("mirror_open", self.rows(merged, "local")["loc"])
        self.assertNotIn("mirror_open", merged["closed"][0])
        self.assertNotIn("mirror_open", merged["retired"][0])

    def test_a_dict_works_as_the_container_like_find_sessions_hands_it_over(self):
        self.cache("yuhem", [_remote_row("a")])
        merged = web_hosts.merge_status(self.payload(), open_mirrors={"yuhem:a": [4242]})
        self.assertIs(self.rows(merged)["a"]["mirror_open"], True)

    def test_unpolled_host_adds_no_rows_and_no_crash(self):
        self.caches["yuhem"] = None
        with mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: [{"name": "yuhem"}]):
            merged = web_hosts.merge_status(self.payload(), open_mirrors={"yuhem:a"})
        self.assertEqual(merged["sessions"], [])
        self.assertEqual(merged["hosts"][0]["error"], "not polled yet")


class StatusPayloadWiringTests(unittest.TestCase):
    """`_status_payload` fleet taramasını `mirrors_out` ile çağırıp sonucu `merge_status`a vermeli; ayrı bir tarama YOK."""

    def setUp(self):
        self.find_calls = []
        self.state = {"viewers": {"yuhem:a": [4242]}}

        def fake_find(measure_cpu=True, mirrors_out=None):
            self.find_calls.append((measure_cpu, mirrors_out))
            if mirrors_out is not None:
                mirrors_out.update(self.state["viewers"])
            return []

        def no_second_scan(*a, **k):
            raise AssertionError("panel tick'inde ayrı mirrors.running_mirrors() taraması YOK, fleet taramasından toplanır")

        remote = {"ok": True, "error": None, "sessions": [_remote_row("a"), _remote_row("b")], "closed": [],
                  "retired": [], "cli_list": [], "cli_options": {}, "dups": []}
        for p in (
            mock.patch.object(web, "find_sessions", fake_find),
            mock.patch.object(web, "_fleet_status", lambda: {}),
            mock.patch.object(web, "PROVIDERS", {}),            # model_choices() alt süreç açabilir (agy), burada gerekmez
            mock.patch.object(web.mirrors, "running_mirrors", no_second_scan),
            mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: [{"name": "yuhem"}]),
            mock.patch.object(web_hosts, "get_cached", lambda h: remote if h == "yuhem" else None),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_remote_rows_carry_the_marker_from_the_fleet_scan(self):
        payload = web._status_payload()
        rows = {r["name"]: r for r in payload["sessions"] if r["host"] == "yuhem"}
        self.assertIs(rows["a"]["mirror_open"], True)
        self.assertIs(rows["b"]["mirror_open"], False)

    def test_exactly_one_scan_carries_the_collector(self):
        # `_diag_status` kendi (ölçümsüz) `find_sessions` çağrısını ayrıca yapıyor (TODO.md 2026-10-13 (6), kalan
        # kaldıraç (b)); toplayıcıyı yalnız ANA fleet taraması (measure_cpu=True) taşır, diğeri değil.
        web._status_payload()
        carrying = [(m, out) for m, out in self.find_calls if out is not None]
        self.assertEqual(len(carrying), 1)
        measure_cpu, mirrors_out = carrying[0]
        self.assertTrue(measure_cpu)
        self.assertIsInstance(mirrors_out, dict)

    def test_a_closed_window_flips_the_marker_on_the_next_tick(self):
        first = {r["name"]: r for r in web._status_payload()["sessions"] if r["host"] == "yuhem"}
        self.assertIs(first["a"]["mirror_open"], True)
        self.state["viewers"] = {}                                           # kullanıcı pencereyi kapattı
        second = {r["name"]: r for r in web._status_payload()["sessions"] if r["host"] == "yuhem"}
        self.assertIs(second["a"]["mirror_open"], False)


if __name__ == "__main__":
    unittest.main()
