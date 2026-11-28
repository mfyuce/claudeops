"""disk_clean ARTIFACT düzeyi cargo süpürme (cargo-sweep benzeri): aktif target'ta <profil>/.fingerprint/<birim>/invoked.timestamp
yaşına göre eski birimlerin deps/build/examples/fingerprint çıktıları silinir; tüm dizin yaşlanmasa da."""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from claudeops import disk_clean as dc

DAY = 86400.0


def touch(path, age_days, size=10, now=None):
    now = now or time.time()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    t = now - age_days * DAY
    os.utime(path, (t, t))


class SweepTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sweep")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = time.time()
        self._guard_real_tmp()
        self.t = os.path.join(self.root, "target")
        open(os.path.join(self.root, "Cargo.toml"), "w").close()
        p = os.path.join(self.t, "debug")
        # eski birim (30 gün): serde-aaa (lib) + foo-bar-bbb (tireli paket, deps'te alt çizgi)
        for unit, files in (("serde-aaa", ["deps/libserde-aaa.rlib", "deps/libserde-aaa.rmeta", "deps/serde-aaa.d"]),
                            ("foo-bar-bbb", ["deps/libfoo_bar-bbb.rlib", "build/foo-bar-bbb/out"])):
            touch(os.path.join(p, ".fingerprint", unit, "invoked.timestamp"), 30, now=self.now)
            for f in files:
                touch(os.path.join(p, f), 30, size=1000, now=self.now)
        # taze birim (1 gün) ama artifact'ı ESKİ mtime'lı: cargo değişmeyen bağımlılığa dokunmaz; invoked.timestamp tazedir
        touch(os.path.join(p, ".fingerprint", "tokio-ccc", "invoked.timestamp"), 1, now=self.now)
        touch(os.path.join(p, "deps", "libtokio-ccc.rlib"), 90, size=5000, now=self.now)
        touch(os.path.join(p, "deps", "libother-zzz.rlib"), 90, size=7, now=self.now)     # parmak izsiz: dokunulmaz

    def _guard_real_tmp(self):
        """27 Kas dersi: `run(...)` tmp_root verilmeden GERÇEK /tmp/claude-<uid>/*/*/scratchpad altındaki 1 günden eski
        CACHEDIR.TAG'li dizinleri (başka oturumların derleme dizinleri ve içindekiler) siliyordu; günlük de canlı
        disk_cleanup.jsonl'e gidiyordu. Her test: tarayıcılara giden kök ve silinen her yol test kökünde olmalı."""
        root = os.path.realpath(self.root)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(dc, "LOG", os.path.join(self.root, "disk_cleanup.jsonl")).start()
        for name in ("scratch_candidates", "scratch_cargo_candidates"):
            orig = getattr(dc, name)

            def spy(idle, now, tmp_root="/tmp", held=None, _orig=orig, _name=name):
                if not os.path.realpath(tmp_root).startswith(root):
                    raise AssertionError(f"{_name} test kökü dışında tarıyor: {tmp_root}")
                return _orig(idle, now, tmp_root, held)
            mock.patch.object(dc, name, spy).start()
        orig_remove = dc._remove

        def remove(path):
            if not os.path.realpath(path).startswith(root):
                raise AssertionError(f"test kökü dışında silme: {path}")
            return orig_remove(path)
        mock.patch.object(dc, "_remove", remove).start()

    def test_candidates_by_invoked_timestamp(self):
        items = dc.cargo_sweep_candidates([self.root], 14, self.now)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertTrue(it["eligible"])
        self.assertEqual(it["units"], 2)
        self.assertGreaterEqual(it["bytes"], 4000)
        names = sorted(os.path.relpath(p, self.t) for p in it["paths"])
        self.assertIn("debug/.fingerprint/serde-aaa", names)
        self.assertIn("debug/deps/libfoo_bar-bbb.rlib", names)
        self.assertIn("debug/build/foo-bar-bbb", names)
        self.assertFalse([n for n in names if "tokio" in n or "other-zzz" in n])

    def test_run_dry_and_on(self):
        cfg = {"mode": "dry", "cargo": "off", "scratch": "off", "cargo_sweep": "on", "cargo_roots": [self.root],
               "cargo_idle_days": 14}
        r = dc.run(cfg, True, self.now, tmp_root=self.root, compilers=lambda: False)
        self.assertEqual(r["removed"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.t, "debug/deps/libserde-aaa.rlib")))
        self.assertGreater(r["candidate_bytes"], 0)
        cfg["mode"] = "on"
        r = dc.run(cfg, True, self.now, tmp_root=self.root, compilers=lambda: False)
        self.assertGreater(r["freed_bytes"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.t, "debug/deps/libserde-aaa.rlib")))
        self.assertFalse(os.path.exists(os.path.join(self.t, "debug/.fingerprint/serde-aaa")))
        self.assertTrue(os.path.exists(os.path.join(self.t, "debug/deps/libtokio-ccc.rlib")))      # taze birim kalır
        self.assertTrue(os.path.exists(os.path.join(self.t, "debug/deps/libother-zzz.rlib")))

    def test_compilers_running_skips(self):
        cfg = {"mode": "on", "cargo": "off", "scratch": "off", "cargo_sweep": "on", "cargo_roots": [self.root]}
        r = dc.run(cfg, True, self.now, tmp_root=self.root, compilers=lambda: True)
        self.assertEqual(r["removed"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.t, "debug/deps/libserde-aaa.rlib")))

    def test_sweep_off_by_default_value(self):
        cfg = {"mode": "on", "cargo": "off", "scratch": "off", "cargo_roots": [self.root]}      # cargo_sweep verilmedi: varsayılan dry
        r = dc.run(cfg, True, self.now, tmp_root=self.root, compilers=lambda: False)
        self.assertEqual(r["removed"], 0)

    def test_missing_invoked_timestamp_uses_newest_file(self):
        p = os.path.join(self.t, "release")
        touch(os.path.join(p, ".fingerprint", "old-ddd", "lib-old-ddd.json"), 40, now=self.now)
        touch(os.path.join(p, ".fingerprint", "new-eee", "lib-new-eee.json"), 2, now=self.now)
        items = dc.cargo_sweep_candidates([self.root], 14, self.now)
        rel = [os.path.relpath(x, self.t) for it in items for x in it["paths"]]
        self.assertIn("release/.fingerprint/old-ddd", rel)
        self.assertNotIn("release/.fingerprint/new-eee", rel)


if __name__ == "__main__":
    unittest.main()


class ScratchCargoTest(unittest.TestCase):
    """22 Kas: /tmp/claude-<uid>/<proje>/<oturum>/scratchpad/tgt-* (CACHEDIR.TAG'li ortak derleme dizinleri) 3 günlük scratch
    kuralını beklemesin: yeniden üretilebilir derleme önbelleği, >1 gün boşta + süreç tutmuyor + cargo çalışmıyorsa silinir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scr")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.now = time.time()
        sp = os.path.join(self.tmp, f"claude-{os.getuid()}", "-proj", "sess1", "scratchpad")
        self.old = os.path.join(sp, "tgt-old")
        self.new = os.path.join(sp, "tgt-new")
        self.plain = os.path.join(sp, "notes")
        touch(os.path.join(self.old, "CACHEDIR.TAG"), 2, now=self.now)
        touch(os.path.join(self.old, "debug", "deps", "a.rlib"), 2, size=500, now=self.now)
        touch(os.path.join(self.new, "CACHEDIR.TAG"), 0.1, now=self.now)
        touch(os.path.join(self.new, "debug", "deps", "b.rlib"), 0.1, now=self.now)
        touch(os.path.join(self.plain, "x.txt"), 2, now=self.now)          # CACHEDIR.TAG yok: scratch_cargo DOKUNMAZ

    def cands(self, held=lambda p: False):
        return dc.scratch_cargo_candidates(1, self.now, self.tmp, held=held)

    def test_old_cachedir_dirs_are_eligible_only(self):
        c = {os.path.basename(i["path"]): i for i in self.cands()}
        self.assertTrue(c["tgt-old"]["eligible"])
        self.assertFalse(c["tgt-new"]["eligible"])
        self.assertNotIn("notes", c)

    def test_held_by_process_not_eligible(self):
        c = {os.path.basename(i["path"]): i for i in self.cands(held=lambda p: True)}
        self.assertFalse(c["tgt-old"]["eligible"])
        self.assertIn("süreç", c["tgt-old"]["why"])

    def test_run_dry_then_on(self):
        cfg = {"mode": "dry", "cargo": "off", "scratch": "off", "cargo_sweep": "dry", "cargo_roots": [], "scratch_cargo_idle_days": 1}
        r = dc.run(cfg, True, self.now, tmp_root=self.tmp, compilers=lambda: False)
        self.assertEqual(r["removed"], 0)
        self.assertGreater(r["candidate_bytes"], 0)
        self.assertTrue(os.path.isdir(self.old))
        cfg.update(mode="on", cargo_sweep="on")
        r = dc.run(cfg, True, self.now, tmp_root=self.tmp, compilers=lambda: False)
        self.assertFalse(os.path.exists(self.old))
        self.assertTrue(os.path.isdir(self.new))
        self.assertTrue(os.path.isdir(self.plain))

    def test_compilers_running_protects(self):
        cfg = {"mode": "on", "cargo": "off", "scratch": "off", "cargo_sweep": "on", "cargo_roots": []}
        dc.run(cfg, True, self.now, tmp_root=self.tmp, compilers=lambda: True)
        self.assertTrue(os.path.isdir(self.old))
