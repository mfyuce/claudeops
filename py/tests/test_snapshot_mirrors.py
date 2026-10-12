"""Snapshot + mirror pencereleri (TBD#74 Faz 3) testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_snapshot_mirrors.py -v

Kapsadığı tasarım (TODO.md 2026-10-08 mirror tasarım notu, (c)): açık `cops watch` pencereleri snapshot'a
girmeli ve geri yüklemede açılmalı. `sessions` listesine KONMAZ (geri yükleme oradaki her ismi yerel
`_start` eder); ayrı `mirrors:[{host,name}]` alanı. İki tuzak: kapanış snapshot'ının "fleet aynı mı"
karşılaştırması mirror'ı da kapsamalı; yalnız-mirror snapshot "boş" sayılmamalı. Gerçek session'a,
pencereye, kullanıcının snapshot dosyasına DOKUNMAZ (geçici dizin, sahte süreç taraması/pencere).
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import snapshot  # noqa: E402
from claudeops.commands import web  # noqa: E402

S1 = {"name": "s1", "cwd": "/w/p", "model": "m", "permission_mode": "auto", "effort": "max", "cli": "claude"}
S2 = dict(S1, name="s2")
M1 = {"host": "ulak_31", "name": "rustrino20261009"}
M2 = {"host": "yuhem", "name": "hc20261001"}


class SnapshotFileCase(unittest.TestCase):
    """Her test kendi geçici `snapshots.json`'ıyla çalışır."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for p in (
            mock.patch.object(snapshot, "SNAPSHOTS_JSON", os.path.join(d.name, "snapshots.json")),
            mock.patch.object(snapshot, "SNAPSHOT_JSON", os.path.join(d.name, "last_snapshot.json")),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.dir = d.name

    def write_raw(self, entries):
        with open(snapshot.SNAPSHOTS_JSON, "w", encoding="utf-8") as f:
            json.dump(entries, f)


class NormalizeMirrorsTests(unittest.TestCase):
    def test_sorted_deduplicated_and_junk_dropped(self):
        out = snapshot.normalize_mirrors([M1, {"host": "a", "name": "y"}, dict(M1), {"host": "", "name": "z"},
                                          {"host": "h"}, "bad", None, 3, {"host": " yuhem ", "name": " hc "}])
        self.assertEqual(out, [{"host": "a", "name": "y"}, {"host": "ulak_31", "name": "rustrino20261009"},
                               {"host": "yuhem", "name": "hc"}])

    def test_none_and_non_list(self):
        self.assertEqual(snapshot.normalize_mirrors(None), [])
        self.assertEqual(snapshot.normalize_mirrors("x"), [])   # str iterable ama dict değil, hepsi düşer
        self.assertEqual(snapshot.normalize_mirrors([]), [])


class SaveSnapshotTests(SnapshotFileCase):
    def test_mirrors_are_stored_normalized_and_separate_from_sessions(self):
        entry = snapshot.save_snapshot([S1], kind="manual", mirrors=[M2, M1, M1])
        self.assertEqual(entry["mirrors"], [M2, M1] if M2["host"] < M1["host"] else [M1, M2])
        self.assertEqual(entry["sessions"], [S1])          # mirror yerel session listesine SIZMAZ
        self.assertEqual(snapshot.load_latest_snapshot()["mirrors"], entry["mirrors"])

    def test_default_is_an_empty_list(self):
        self.assertEqual(snapshot.save_snapshot([S1])["mirrors"], [])

    def test_get_snapshot_returns_the_mirrors(self):
        entry = snapshot.save_snapshot([S1], mirrors=[M1])
        self.assertEqual(snapshot.get_snapshot(entry["saved_at"])["mirrors"], [M1])

    def test_manual_always_appends(self):
        snapshot.save_snapshot([S1], mirrors=[M1])
        snapshot.save_snapshot([S1], mirrors=[M1])
        self.assertEqual(len(snapshot._load_all()), 2)


class ClosingSnapshotComparisonTests(SnapshotFileCase):
    def test_identical_sessions_and_mirrors_are_not_duplicated(self):
        first = snapshot.save_snapshot([S1, S2], kind="manual", mirrors=[M1, M2])
        again = snapshot.save_snapshot([S2, S1], kind="closing", mirrors=[M2, M1])   # sıra önemsiz
        self.assertEqual(again["saved_at"], first["saved_at"])
        self.assertEqual(len(snapshot._load_all()), 1)

    def test_only_a_window_change_still_records_a_closing_snapshot(self):
        # TODO tuzağı: mirror karşılaştırılmazsa yalnız pencere değişince kayıt atlanırdı
        snapshot.save_snapshot([S1], kind="manual", mirrors=[M1])
        added = snapshot.save_snapshot([S1], kind="closing", mirrors=[M1, M2])
        self.assertEqual(len(snapshot._load_all()), 2)
        self.assertEqual(added["kind"], "closing")
        removed = snapshot.save_snapshot([S1], kind="closing", mirrors=[M1])
        self.assertEqual(len(snapshot._load_all()), 3)
        self.assertEqual(removed["mirrors"], [M1])

    def test_changed_sessions_with_the_same_mirrors_record(self):
        snapshot.save_snapshot([S1], kind="manual", mirrors=[M1])
        snapshot.save_snapshot([S1, S2], kind="closing", mirrors=[M1])
        self.assertEqual(len(snapshot._load_all()), 2)

    def test_an_old_entry_without_the_field_equals_no_mirrors(self):
        self.write_raw([{"saved_at": 1.0, "kind": "manual", "sessions": [S1]}])     # eski biçim: `mirrors` yok
        same = snapshot.save_snapshot([S1], kind="closing", mirrors=[])
        self.assertEqual(same["saved_at"], 1.0)                                      # yeni kayıt YOK
        self.assertEqual(len(snapshot._load_all()), 1)

    def test_an_old_entry_vs_open_mirrors_records_a_new_one(self):
        self.write_raw([{"saved_at": 1.0, "kind": "manual", "sessions": [S1]}])
        new = snapshot.save_snapshot([S1], kind="closing", mirrors=[M1])
        self.assertNotEqual(new["saved_at"], 1.0)
        self.assertEqual(new["mirrors"], [M1])


class ListSnapshotsTests(SnapshotFileCase):
    def test_mirror_count_in_the_metadata_and_old_entries_count_zero(self):
        self.write_raw([{"saved_at": 1.0, "kind": "manual", "sessions": [S1]},
                        {"saved_at": 2.0, "kind": "closing", "sessions": [S1, S2], "mirrors": [M1, M2]},
                        {"saved_at": 3.0, "kind": "manual", "sessions": [], "mirrors": ["junk", M1]}])
        rows = snapshot.list_snapshots()                                             # en yeni önce
        self.assertEqual([(r["saved_at"], r["count"], r["mirrors"]) for r in rows],
                         [(3.0, 0, 1), (2.0, 2, 2), (1.0, 1, 0)])

    def test_legacy_single_record_migration_is_unaffected(self):
        with open(snapshot.SNAPSHOT_JSON, "w", encoding="utf-8") as f:
            json.dump({"saved_at": 5.0, "sessions": [S1]}, f)
        rows = snapshot.list_snapshots()
        self.assertEqual([(r["count"], r["mirrors"]) for r in rows], [(1, 0)])


class LiveMirrorEntriesTests(unittest.TestCase):
    def entries(self, running):
        with mock.patch.object(web.mirrors, "running_mirrors", lambda: running):
            return web._live_mirror_entries()

    def test_remote_hosts_only_sorted(self):
        out = self.entries({"yuhem:hc20261001": [1], "local:cops20261007": [2], "ulak_31:rustrino20261009": [3],
                            "ulak_31:alerting20261008": [4]})
        self.assertEqual(out, [{"host": "ulak_31", "name": "alerting20261008"},
                               {"host": "ulak_31", "name": "rustrino20261009"},
                               {"host": "yuhem", "name": "hc20261001"}])

    def test_nothing_open(self):
        self.assertEqual(self.entries({}), [])

    def test_a_failing_scan_returns_an_empty_list_instead_of_breaking_the_closing_snapshot(self):
        def boom():
            raise OSError("proc scan failed")

        with mock.patch.object(web.mirrors, "running_mirrors", boom):
            self.assertEqual(web._live_mirror_entries(), [])


class SaveWiringTests(SnapshotFileCase):
    def test_manual_save_records_the_open_windows(self):
        with mock.patch.object(web, "_live_snapshot_entries", lambda: [S1]), \
                mock.patch.object(web, "_live_mirror_entries", lambda: [M1, M2]):
            res = web._snapshot_save()
        self.assertEqual((res["ok"], res["count"], res["mirrors"]), (True, 1, 2))
        self.assertEqual(snapshot.load_latest_snapshot()["mirrors"], [M2, M1] if M2["host"] < M1["host"] else [M1, M2])

    def test_closing_snapshot_records_the_open_windows_and_skips_an_unchanged_state(self):
        with mock.patch.object(web, "_live_snapshot_entries", lambda: [S1]), \
                mock.patch.object(web, "_live_mirror_entries", lambda: [M1]):
            web._save_closing_snapshot()
            web._save_closing_snapshot()                       # aynı durum: kopya YOK
        self.assertEqual(len(snapshot._load_all()), 1)
        self.assertEqual(snapshot.load_latest_snapshot()["mirrors"], [M1])
        with mock.patch.object(web, "_live_snapshot_entries", lambda: [S1]), \
                mock.patch.object(web, "_live_mirror_entries", lambda: []):
            web._save_closing_snapshot()                       # pencere kapandı: yeni kayıt
        self.assertEqual(len(snapshot._load_all()), 2)

    def test_status_info_carries_the_mirror_count(self):
        snapshot.save_snapshot([S1], mirrors=[M1, M2])
        info = web._snapshot_info()
        self.assertEqual((info["count"], info["mirrors"], info["kind"]), (1, 2, "manual"))

    def test_status_info_of_an_old_entry(self):
        with open(snapshot.SNAPSHOTS_JSON, "w", encoding="utf-8") as f:
            json.dump([{"saved_at": 1.0, "kind": "manual", "sessions": [S1]}], f)
        self.assertEqual(web._snapshot_info()["mirrors"], 0)


class MirrorWindowRestoreModeTests(unittest.TestCase):
    """`_open_mirror_window(require_running=False, focus=False)`: geri yükleme modu."""

    def setUp(self):
        self.spawned, self.focused = [], []
        self.state = {"mirrors": {}, "x11": True, "cache": {"ok": True, "sessions": []}}   # session YOK
        for p in (
            mock.patch.object(web, "get_host", lambda h: {"name": h} if h in ("yuhem", "ulak_31") else None),
            mock.patch.object(web.web_hosts, "get_cached", lambda h: self.state["cache"]),
            mock.patch.object(web, "detect_display", lambda: ":1"),
            mock.patch.object(web, "_x11_display_ok", lambda d: self.state["x11"]),
            mock.patch.object(web.mirrors, "running_mirrors", lambda: self.state["mirrors"]),
            mock.patch.object(web.mirrors, "focus_window", lambda s, d: self.focused.append(s) or True),
            mock.patch.object(web, "open_mirror_window",
                              lambda host, name, port, display=None: self.spawned.append((host, name, port)) or True),
        ):
            p.start()
            self.addCleanup(p.stop)

    def restore(self, host="ulak_31", name="rustrino20261009"):
        return web._open_mirror_window(name, host, 8765, lang="en", require_running=False, focus=False)

    def test_opens_even_though_the_remote_session_is_not_running_yet(self):
        self.assertEqual(self.restore(), {"ok": True, "already_open": False})
        self.assertEqual(self.spawned, [("ulak_31", "rustrino20261009", 8765)])

    def test_the_normal_route_still_requires_a_running_session(self):
        res = web._open_mirror_window("rustrino20261009", "ulak_31", 8765, lang="en")
        self.assertFalse(res["ok"])
        self.assertIn("not running", res["error"])

    def test_the_other_checks_still_apply(self):
        self.assertIn("not a registered remote host", self.restore(host="nohost")["error"])
        self.assertIn("invalid host/name", self.restore(name="a;b")["error"])
        self.assertIn("local session", self.restore(host="local")["error"])
        self.state["x11"] = False
        self.assertIn("X11", self.restore()["error"])
        self.assertEqual(self.spawned, [])

    def test_an_open_window_is_not_duplicated_and_not_raised(self):
        self.state["mirrors"] = {"ulak_31:rustrino20261009": [7]}
        self.assertEqual(self.restore(), {"ok": True, "already_open": True, "focused": False})
        self.assertEqual((self.spawned, self.focused), ([], []))


class SnapshotResumeTests(unittest.TestCase):
    def setUp(self):
        self.log = []                      # sıralı olay günlüğü: ("start", ad) / ("mirror", host, ad, port)
        self.mirror_outcomes = {}          # (host, ad) -> dönecek sonuç
        self.snap = {"saved_at": 9.0, "kind": "manual", "sessions": [S1, S2], "mirrors": [M1, M2]}

        def fake_start(name, **kw):
            self.log.append(("start", name))
            return {"ok": True}

        def fake_mirror(name, host, port, lang="tr", force=False, require_running=True, focus=True):
            self.log.append(("mirror", host, name, port, require_running, focus))
            return self.mirror_outcomes.get((host, name), {"ok": True, "already_open": False})

        for p in (
            mock.patch.object(web, "MIRROR_RESTORE_SPACING_SECONDS", 0),      # testler uyumasın
            mock.patch.object(web, "get_snapshot", lambda saved_at: self.snap),
            mock.patch.object(web, "load_latest_snapshot", lambda: self.snap),
            mock.patch.object(web, "_fleet_status", lambda: {"s1": {"state": "active"}, "s2": {"state": "active"}}),
            mock.patch.object(web, "find_sessions", lambda measure_cpu=False: []),
            mock.patch.object(web, "_start", fake_start),
            mock.patch.object(web, "_open_mirror_window", fake_mirror),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_windows_open_after_every_session_started(self):
        res = web._snapshot_resume(saved_at=9.0, lang="en", port=8790)
        kinds = [e[0] for e in self.log]
        self.assertEqual(kinds, ["start", "start", "mirror", "mirror"])
        self.assertTrue(res["ok"])
        self.assertEqual((res["started"], res["mirrors_opened"], res["mirrors_failed"]), (2, 2, 0))

    def test_mirrors_are_opened_in_restore_mode_with_this_panels_port(self):
        web._snapshot_resume(saved_at=9.0, port=8790)
        mirror_calls = [e for e in self.log if e[0] == "mirror"]
        # (host, ad, port, require_running, focus): uzak session çalışmıyor olabilir, açık pencere öne getirilmez
        self.assertEqual(mirror_calls, [("mirror", "ulak_31", "rustrino20261009", 8790, False, False),
                                        ("mirror", "yuhem", "hc20261001", 8790, False, False)])

    def test_default_port_when_the_caller_gives_none(self):
        web._snapshot_resume(saved_at=9.0)
        self.assertEqual([e[3] for e in self.log if e[0] == "mirror"], [web.DEFAULT_PORT] * 2)

    def test_a_mirror_only_snapshot_is_not_empty(self):
        self.snap = {"saved_at": 9.0, "kind": "closing", "sessions": [], "mirrors": [M1]}
        res = web._snapshot_resume(saved_at=9.0, lang="en")
        self.assertTrue(res["ok"])
        self.assertEqual((res["started"], res["mirrors_opened"]), (0, 1))
        self.assertEqual([e[0] for e in self.log], ["mirror"])

    def test_a_truly_empty_snapshot_is_still_rejected(self):
        for snap in ({"saved_at": 9.0, "kind": "manual", "sessions": []},
                     {"saved_at": 9.0, "kind": "manual", "sessions": [], "mirrors": []},
                     {"saved_at": 9.0, "kind": "manual", "sessions": [], "mirrors": ["junk", {"host": ""}]}):
            self.snap = snap
            res = web._snapshot_resume(saved_at=9.0, lang="en")
            self.assertFalse(res["ok"], snap)
            self.assertIn("no saved snapshot", res["error"])
        self.assertEqual(self.log, [])

    def test_an_old_snapshot_without_the_field_behaves_as_before(self):
        self.snap = {"saved_at": 9.0, "kind": "manual", "sessions": [S1]}
        res = web._snapshot_resume(saved_at=9.0)
        self.assertEqual((res["started"], res["mirrors"], res["mirrors_opened"]), (1, [], 0))
        self.assertEqual([e[0] for e in self.log], ["start"])

    def test_hidden_start_opens_no_windows(self):
        res = web._snapshot_resume(saved_at=9.0, hidden=True)
        self.assertEqual([e[0] for e in self.log], ["start", "start"])
        self.assertEqual((res["mirrors_skipped"], res["mirrors_opened"]), (2, 0))
        self.assertEqual({m["status"] for m in res["mirrors"]}, {"skipped_hidden"})

    def test_one_failing_mirror_does_not_stop_the_others(self):
        self.mirror_outcomes[("ulak_31", "rustrino20261009")] = {"ok": False, "error": "ulak_31: not a registered remote host"}
        res = web._snapshot_resume(saved_at=9.0)
        by = {(m["host"], m["name"]): m for m in res["mirrors"]}
        self.assertEqual(by[("ulak_31", "rustrino20261009")]["status"], "failed")
        self.assertIn("not a registered", by[("ulak_31", "rustrino20261009")]["error"])
        self.assertEqual(by[("yuhem", "hc20261001")]["status"], "opened")
        self.assertEqual((res["mirrors_opened"], res["mirrors_failed"]), (1, 1))
        self.assertEqual(res["started"], 2)                         # session'lar bundan etkilenmez

    def test_an_already_open_window_is_counted_separately(self):
        self.mirror_outcomes[("yuhem", "hc20261001")] = {"ok": True, "already_open": True, "focused": False}
        res = web._snapshot_resume(saved_at=9.0)
        self.assertEqual((res["mirrors_opened"], res["mirrors_already_open"], res["mirrors_failed"]), (1, 1, 0))

    def test_junk_mirror_entries_are_ignored(self):
        self.snap = {"saved_at": 9.0, "kind": "manual", "sessions": [S1], "mirrors": ["junk", None, {"host": "yuhem"}, M2]}
        res = web._snapshot_resume(saved_at=9.0)
        self.assertEqual([(m["host"], m["name"]) for m in res["mirrors"]], [("yuhem", "hc20261001")])

    def test_a_gap_is_kept_only_after_a_window_was_actually_opened(self):
        # opened, already_open, opened, failed, opened: boşluk 2. ve 4. çağrıdan ÖNCE (önceki adım pencere açtıysa)
        names = [("yuhem", f"s{i}") for i in range(5)]
        self.snap = {"saved_at": 9.0, "kind": "manual", "sessions": [],
                     "mirrors": [{"host": h, "name": n} for h, n in names]}
        self.mirror_outcomes = {("yuhem", "s1"): {"ok": True, "already_open": True},
                                ("yuhem", "s3"): {"ok": False, "error": "nope"}}
        sleeps = []
        with mock.patch.object(web, "MIRROR_RESTORE_SPACING_SECONDS", 0.25), \
                mock.patch.object(web.time, "sleep", lambda s: sleeps.append(s)):
            res = web._snapshot_resume(saved_at=9.0)
        self.assertEqual([m["status"] for m in res["mirrors"]], ["opened", "already_open", "opened", "failed", "opened"])
        self.assertEqual(sleeps, [0.25, 0.25])                     # s1 ve s4'ten önce; sondaki açılıştan SONRA yok

    def test_hidden_start_never_sleeps(self):
        sleeps = []
        with mock.patch.object(web, "MIRROR_RESTORE_SPACING_SECONDS", 0.25), \
                mock.patch.object(web.time, "sleep", lambda s: sleeps.append(s)):
            web._snapshot_resume(saved_at=9.0, hidden=True)
        self.assertEqual(sleeps, [])

    def test_latest_snapshot_is_used_when_no_saved_at(self):
        res = web._snapshot_resume()
        self.assertEqual(res["mirrors_opened"], 2)

    def test_session_results_keep_their_shape(self):
        res = web._snapshot_resume(saved_at=9.0)
        self.assertEqual(res["results"], [{"name": "s1", "status": "started"}, {"name": "s2", "status": "started"}])


class ResumeRouteHttpTests(unittest.TestCase):
    """Gerçek HTTP: `/api/snapshot/resume` bu panelin portunu `_snapshot_resume`a iletir."""

    def test_the_handler_passes_the_servers_port(self):
        calls = []

        def fake(**kw):
            calls.append(kw)
            return {"ok": True, "results": [], "mirrors": []}

        with mock.patch.object(web, "_snapshot_resume", fake), mock.patch.object(web._Handler, "token", "tok"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            port = server.server_address[1]
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/snapshot/resume", method="POST",
                                         data=json.dumps({"saved_at": 9.5, "hidden": True, "lang": "en"}).encode(),
                                         headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.status, 200)
        self.assertEqual(calls, [{"saved_at": 9.5, "hidden": True, "lang": "en", "port": port}])


if __name__ == "__main__":
    unittest.main()
