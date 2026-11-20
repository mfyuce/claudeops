"""disk_clean: yalnız eski + kendi uid'imizin + süreç tutmayan; kuru çalıştırma silmez; derleyici çalışırken cargo atlanır."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import disk_clean as dc  # noqa: E402
from claudeops import periodic  # noqa: E402

DAY = 86400


def _touch(path, age_days, data=b"x" * 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.d = self.td.name
        p = mock.patch.object(dc, "LOG", os.path.join(self.d, "disk_cleanup.jsonl"))
        p.start(); self.addCleanup(p.stop)

    def cfg(self, **kw):
        c = dict(periodic.DEFAULT_DISK_CLEAN)
        c.update({"cargo_roots": [os.path.join(self.d, "proj")], "docker": "off"}, **kw)
        return c

    def run_dc(self, apply=True, running=False, **kw):
        return dc.run(self.cfg(**kw), apply, tmp_root=os.path.join(self.d, "tmp"), compilers=lambda: running)


class Cargo(Base):
    def test_old_target_removed_recent_kept(self):
        _touch(f"{self.d}/proj/old/Cargo.toml", 100)
        _touch(f"{self.d}/proj/old/target/debug/a.o", 30)
        _touch(f"{self.d}/proj/new/Cargo.toml", 100)
        _touch(f"{self.d}/proj/new/target/debug/a.o", 30)
        _touch(f"{self.d}/proj/new/target/debug/b.o", 1)        # yakın zamanda derlenmiş
        r = self.run_dc()
        self.assertFalse(os.path.exists(f"{self.d}/proj/old/target"))
        self.assertTrue(os.path.exists(f"{self.d}/proj/new/target/debug/b.o"))
        self.assertTrue(os.path.exists(f"{self.d}/proj/old/Cargo.toml"))     # kaynak dokunulmaz
        self.assertEqual(r["removed"], 1)
        self.assertGreater(r["freed_bytes"], 0)

    def test_dry_run_deletes_nothing_but_logs(self):
        _touch(f"{self.d}/proj/o/Cargo.toml", 100)
        _touch(f"{self.d}/proj/o/target/a", 30)
        r = self.run_dc(apply=True, mode="dry")
        self.assertTrue(os.path.exists(f"{self.d}/proj/o/target/a"))
        self.assertEqual((r["applied"], r["candidates"], r["removed"]), (False, 1, 0))
        self.assertIn("o/target", open(dc.LOG).read())
        r2 = self.run_dc(apply=False)
        self.assertEqual(r2["removed"], 0)

    def test_compiler_running_skips_cargo(self):
        _touch(f"{self.d}/proj/o/Cargo.toml", 100)
        _touch(f"{self.d}/proj/o/target/a", 30)
        r = self.run_dc(running=True)
        self.assertTrue(os.path.exists(f"{self.d}/proj/o/target/a"))
        self.assertTrue(any("cargo/rustc" in n for n in r["notes"]))

    def test_non_cargo_target_dir_untouched(self):
        _touch(f"{self.d}/proj/web/target/a", 100)               # Cargo.toml/CACHEDIR.TAG yok
        self.run_dc()
        self.assertTrue(os.path.exists(f"{self.d}/proj/web/target/a"))

    def test_cargo_target_home_glob(self):
        _touch(f"{self.d}/.cargo-target-x/release/a", 40)
        _touch(f"{self.d}/.cargo-target-y/release/a", 2)
        r = self.run_dc(cargo_roots=[f"{self.d}/.cargo-target*"])
        self.assertFalse(os.path.exists(f"{self.d}/.cargo-target-x"))
        self.assertTrue(os.path.exists(f"{self.d}/.cargo-target-y"))
        self.assertEqual(r["removed"], 1)

    def test_symlink_not_followed(self):
        _touch(f"{self.d}/real/Cargo.toml", 100)
        _touch(f"{self.d}/real/target/a", 100)
        os.makedirs(f"{self.d}/proj")
        os.symlink(f"{self.d}/real", f"{self.d}/proj/link")
        self.run_dc()
        self.assertTrue(os.path.exists(f"{self.d}/real/target/a"))

    def test_foreign_uid_files_block(self):
        _touch(f"{self.d}/proj/o/Cargo.toml", 100)
        _touch(f"{self.d}/proj/o/target/a", 100)
        with mock.patch.object(dc, "uid", return_value=os.getuid() + 1):
            c = dc.cargo_candidates([f"{self.d}/proj"], 14, time.time())
        self.assertEqual([x["eligible"] for x in c], [False])


class Scratch(Base):
    def root(self):
        return f"{self.d}/tmp/claude-{os.getuid()}"

    def test_old_session_removed_new_and_held_kept(self):
        _touch(f"{self.root()}/p/old/scratchpad/a", 10)
        _touch(f"{self.root()}/p/new/scratchpad/a", 1)
        _touch(f"{self.root()}/p/held/scratchpad/a", 10)
        real = dc._held_by_process
        with mock.patch.object(dc, "_held_by_process", lambda p, proc="/proc": p.endswith("held")):
            r = self.run_dc(cargo="off")
        self.assertFalse(os.path.exists(f"{self.root()}/p/old"))
        self.assertTrue(os.path.exists(f"{self.root()}/p/new"))
        self.assertTrue(os.path.exists(f"{self.root()}/p/held"))
        self.assertEqual(r["removed"], 1)
        self.assertTrue(callable(real))

    def test_process_cwd_inside_is_held(self):
        _touch(f"{self.root()}/p/s/a", 10)
        cwd0 = os.getcwd()
        os.chdir(f"{self.root()}/p/s")
        try:
            self.assertTrue(dc._held_by_process(f"{self.root()}/p/s"))
        finally:
            os.chdir(cwd0)
        self.assertFalse(dc._held_by_process(f"{self.root()}/p/s"))


class Docker(Base):
    def test_off_by_default_and_on_parses(self):
        self.assertEqual(periodic.DEFAULT_DISK_CLEAN["docker"], "off")
        out = mock.Mock(returncode=0, stdout="Deleted build cache objects:\nTotal reclaimed space: 14.8GB\n", stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            r = dc.docker_prune(True, runner=lambda *a, **k: out)
        self.assertTrue(r["ran"])
        self.assertAlmostEqual(r["bytes"], 14.8e9, delta=1e6)
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            self.assertFalse(dc.docker_prune(False)["ran"])


class Periodic(unittest.TestCase):
    def test_registered_and_validated(self):
        self.assertIn("disk_clean", periodic.JOBS)
        with self.assertRaises(ValueError):
            periodic._validate({"mode": "bogus"})
        periodic._validate({"mode": "dry", "cargo_idle_days": 7})

    def test_hot_disk_raises_frequency(self):
        cfg = dict(periodic.DEFAULT_DISK_CLEAN)
        now = periodic.datetime.datetime.now()
        st = {"last_start": (now - periodic.datetime.timedelta(minutes=90)).timestamp()}
        full = mock.Mock(total=100, used=95)
        ok = mock.Mock(total=100, used=50)
        with mock.patch("shutil.disk_usage", return_value=full):
            self.assertTrue(periodic.is_due(cfg, st, now))
        with mock.patch("shutil.disk_usage", return_value=ok):
            self.assertFalse(periodic.is_due(cfg, st, now))

    def test_summary_shape(self):
        s = periodic.disk_summary()
        self.assertIn("pct", s)
        self.assertIn("enabled", s)


if __name__ == "__main__":
    unittest.main()
