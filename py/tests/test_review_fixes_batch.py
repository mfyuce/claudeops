"""Doğrulanmış 12 review bulgusunun düzeltmeleri (2026-10-27): files.py (symlink silme/rename, izin korunması, salt-okunur meta
kökleri, list_dir symlink işareti), atomic_json (dizinsiz ad, tmp sızıntısı), settings kilidi, snapshot şema/kopya,
hosts kilit dosyası. Her test düzeltmeden ÖNCE kırmızıydı."""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json, files, hosts, settings, snapshot  # noqa: E402


class _Files(unittest.TestCase):
    def setUp(self):
        base = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(base, "proj")
        self.meta = os.path.join(base, "meta")
        os.makedirs(self.root)
        os.makedirs(self.meta)
        self.s = NS(cwd=self.root, cli="shell")
        self.base = base


class TestDeleteSymlink(_Files):
    def test_symlink_to_dir_removes_link_not_target(self):
        target = os.path.join(self.root, "data")
        os.makedirs(target)
        open(os.path.join(target, "keep.txt"), "w").write("x")
        link = os.path.join(self.root, "lnk")
        os.symlink(target, link)
        r = files.delete_path(self.s, link)
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isfile(os.path.join(target, "keep.txt")))      # hedef dizin ve içeriği duruyor

    def test_symlink_to_outside_removes_only_link(self):
        out = os.path.join(self.base, "out")
        os.makedirs(out)
        open(os.path.join(out, "v.txt"), "w").write("x")
        link = os.path.join(self.root, "lnk")
        os.symlink(out, link)
        self.assertTrue(files.delete_path(self.s, link)["ok"])
        self.assertTrue(os.path.isfile(os.path.join(out, "v.txt")))

    def test_regular_dir_still_removed(self):
        d = os.path.join(self.root, "d")
        os.makedirs(d)
        self.assertTrue(files.delete_path(self.s, d)["ok"])
        self.assertFalse(os.path.exists(d))


class TestRename(_Files):
    def test_dangling_symlink_at_new_name_not_overwritten(self):
        a = os.path.join(self.root, "a.txt")
        open(a, "w").write("A")
        os.symlink(os.path.join(self.root, "yok"), os.path.join(self.root, "b.txt"))
        r = files.rename_path(self.s, a, "b.txt")
        self.assertEqual((r["ok"], r.get("error")), (False, "exists"))
        self.assertTrue(os.path.exists(a))


class TestWriteTextMode(_Files):
    def test_mode_preserved(self):
        p = os.path.join(self.root, "run.sh")
        open(p, "w").write("old")
        os.chmod(p, 0o750)
        self.assertTrue(files.write_text(self.s, p, "new")["ok"])
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o750)
        self.assertEqual(open(p).read(), "new")

    def test_private_mode_preserved(self):
        p = os.path.join(self.root, "secret.txt")
        open(p, "w").write("old")
        os.chmod(p, 0o600)
        old = os.umask(0o022)
        try:
            self.assertTrue(files.write_text(self.s, p, "new")["ok"])
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)


class TestReadOnlyMetaRoots(_Files):
    def setUp(self):
        super().setUp()
        self.prov = mock.patch.object(files, "get_provider",
                                      lambda cli: NS(extra_file_roots=lambda cwd: [("claude-transcripts", self.meta)]))
        self.prov.start()
        self.addCleanup(self.prov.stop)
        self.f = os.path.join(self.meta, "t.jsonl")
        open(self.f, "w").write("x")

    def test_listing_and_reading_still_work(self):
        self.assertTrue(files.list_dir(self.s, self.meta)["ok"])
        self.assertEqual(files.read_text(self.s, self.f)[0], "x")

    def test_destructive_ops_refused(self):
        self.assertEqual(files.delete_path(self.s, self.f)["error"], "forbidden")
        self.assertEqual(files.rename_path(self.s, self.f, "u.jsonl")["error"], "forbidden")
        self.assertEqual(files.write_text(self.s, self.f, "y")["error"], "forbidden")
        self.assertEqual(files.make_folder(self.s, self.meta, "d")["error"], "forbidden")
        self.assertTrue(os.path.isfile(self.f))
        self.assertEqual(open(self.f).read(), "x")


class TestListDirSymlinkMarker(_Files):
    def test_symlink_flagged(self):
        os.symlink(self.meta, os.path.join(self.root, "lnk"))
        open(os.path.join(self.root, "f"), "w").write("x")
        ents = {e["name"]: e for e in files.list_dir(self.s, None)["entries"]}
        self.assertTrue(ents["lnk"]["symlink"])
        self.assertFalse(ents["f"]["symlink"])


class TestAtomicJson(unittest.TestCase):
    def test_bare_filename_works(self):
        d = tempfile.mkdtemp()
        old = os.getcwd()
        os.chdir(d)
        try:
            atomic_json.atomic_write_json("plain.json", {"a": 1})
            self.assertEqual(json.load(open("plain.json")), {"a": 1})
        finally:
            os.chdir(old)

    def test_tmp_removed_on_failure_and_fsync_called(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.json")
        with self.assertRaises(TypeError):
            atomic_json.atomic_write_json(p, {"a": object()})
        self.assertEqual(os.listdir(d), [])                                   # tmp sızmadı
        with mock.patch.object(atomic_json.os, "fsync") as fs:
            atomic_json.atomic_write_json(p, {"a": 1})
        self.assertTrue(fs.called)


class TestSettingsLock(unittest.TestCase):
    def test_concurrent_patches_not_lost(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d, "settings.json")):
            errs = []

            def patch(i):
                try:
                    settings.save_settings({"default_model": {f"cli{i}": f"m{i}"}})
                except Exception as e:           # noqa: BLE001
                    errs.append(e)
            ts = [threading.Thread(target=patch, args=(i,)) for i in range(16)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(errs, [])
            dm = settings.load_settings()["default_model"]
            self.assertEqual(sorted(dm), sorted(f"cli{i}" for i in range(16)))


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(snapshot, "SNAPSHOTS_JSON", os.path.join(self.d, "snapshots.json"))
        p2 = mock.patch.object(snapshot, "SNAPSHOT_JSON", os.path.join(self.d, "last.json"))
        p.start(); p2.start()
        self.addCleanup(p.stop); self.addCleanup(p2.stop)

    def test_closing_survives_malformed_last_entry(self):
        for bad in (["x"], [{"saved_at": 1}], [{"sessions": "no"}]):
            with open(snapshot.SNAPSHOTS_JSON, "w") as f:
                json.dump(bad, f)
            e = snapshot.save_snapshot([{"name": "a", "cwd": "/w"}], kind="closing")
            self.assertEqual(e["kind"], "closing")

    def test_duplicate_pair_is_a_change(self):
        a = {"name": "a", "cwd": "/w", "model": "m"}
        self.assertFalse(snapshot._same_sessions([a, dict(a)], [a]))
        self.assertTrue(snapshot._same_sessions([a, {"name": "b"}], [{"name": "b"}, a]))


class TestHostsLock(unittest.TestCase):
    def test_symlinked_lock_file_not_followed(self):
        d = tempfile.mkdtemp()
        victim = os.path.join(d, "victim-created-by-follow")
        hj = os.path.join(d, "hosts.json")
        os.symlink(victim, hj + ".lock")                 # dangling: O_CREAT onu izlerse hedef OLUŞUR
        with mock.patch.object(hosts, "HOSTS_JSON", hj):
            with hosts._write_txn():                     # kilit alınamaz; thread kilidiyle devam
                pass
        self.assertFalse(os.path.exists(victim))
        self.assertTrue(os.path.islink(hj + ".lock"))


if __name__ == "__main__":
    unittest.main()
