"""`scripts/install-ucli.sh` testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_install_ucli_script.py -v

Ağa / gerçek cargo'ya / gerçek ucli'ye DOKUNMAZ: kaynak proje geçici dizinde taklit edilir
(sahte `ucli` kabuk betiği), hedef `CLAUDEOPS_UCLI_DEST` ile geçici dizine çevrilir, `--build`
için PATH'e sahte bir `cargo` konur.

Kapsadığı karar (2026-10-09, kullanıcı: "claudeops ucli'yi kendi reposunda tutsun, gerektiğinde
release'i/debug'ı oraya gönderelim"): claudeops'un kullandığı ikili `bin/ucli`'de TEK aktif kopya
olarak durur; betik bayat/bozuk build'i teslim etmez ve çalışan oturumları bozmamak için yerinde
üzerine yazmak yerine yer değiştirir.
"""
import hashlib
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-ucli.sh"

WORKING_UCLI = "#!/bin/sh\nexit 0\n"
BROKEN_UCLI = "#!/bin/sh\nexit 1\n"
# `cargo build [--release] --locked` taklidi: çağrı argümanlarını günlüğe yazar, profile göre
# target/<profil>/ucli üretir. İkilinin mtime'ı bilerek ESKİ bırakılır: gerçek cargo, yalnız
# `cfg(test)` kodu değişmişse ikiliyi yeniden bağlamaz ("up to date") ve kaynak dosya ikiliden
# yeni görünür. `--build` sonrası bayatlık kontrolü açık olsaydı bu durum yanlışlıkla reddedilirdi.
FAKE_CARGO = """#!/bin/sh
echo "$*" >> "$CARGO_LOG"
dir=debug
for a in "$@"; do [ "$a" = "--release" ] && dir=release; done
mkdir -p "target/$dir"
printf '#!/bin/sh\\nexit 0\\n# built by fake cargo\\n' > "target/$dir/ucli"
chmod +x "target/$dir/ucli"
touch -d "1 hour ago" "target/$dir/ucli"
"""


def set_age(path, seconds_ago):
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


class InstallUcliScriptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src_root = self.root / "unified-cli"
        self.dest = self.root / "claudeops" / "bin" / "ucli"
        src_dir = self.src_root / "crates" / "ucli" / "src"
        src_dir.mkdir(parents=True)
        (self.src_root / "Cargo.toml").write_text("[workspace]\n")
        (self.src_root / "Cargo.lock").write_text("")
        self.main_rs = src_dir / "main.rs"
        self.main_rs.write_text("fn main() {}\n")
        for source in (self.main_rs, self.src_root / "Cargo.toml", self.src_root / "Cargo.lock"):
            set_age(source, 3600)

    def _binary(self, profile, body=WORKING_UCLI):
        path = self.src_root / "target" / profile / "ucli"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)
        set_age(path, 60)
        return path

    def _run(self, *args, path_prefix=None, extra_env=None):
        env = {
            **os.environ,
            "UNIFIED_CLI_DIR": str(self.src_root),
            "CLAUDEOPS_UCLI_DEST": str(self.dest),
        }
        if path_prefix:
            env["PATH"] = f"{path_prefix}:{env['PATH']}"
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60
        )

    def _info(self):
        pairs = (line.split("=", 1) for line in Path(f"{self.dest}.info").read_text().splitlines())
        return dict(pairs)

    def test_release_is_delivered_as_an_executable_copy_with_provenance(self):
        source = self._binary("release")
        result = self._run("release")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dest.read_text(), WORKING_UCLI)
        self.assertTrue(os.access(self.dest, os.X_OK))
        info = self._info()
        self.assertEqual(info["profile"], "release")
        self.assertEqual(info["source"], str(source))
        self.assertEqual(info["sha256"], hashlib.sha256(WORKING_UCLI.encode()).hexdigest())
        self.assertEqual(info["size_bytes"], str(len(WORKING_UCLI)))

    def test_default_profile_is_release_and_debug_replaces_the_single_slot(self):
        self._binary("release", WORKING_UCLI + "# release\n")
        self._binary("debug", WORKING_UCLI + "# debug\n")

        self.assertEqual(self._run().returncode, 0)
        self.assertIn("# release", self.dest.read_text())
        self.assertEqual(self._info()["profile"], "release")

        self.assertEqual(self._run("debug").returncode, 0)
        self.assertIn("# debug", self.dest.read_text())
        self.assertNotIn("# release", self.dest.read_text())
        self.assertEqual(self._info()["profile"], "debug")

    def test_replacement_swaps_the_inode_so_running_sessions_keep_the_old_binary(self):
        self._binary("release")
        self.assertEqual(self._run("release").returncode, 0)
        first_inode = self.dest.stat().st_ino
        self._binary("release", WORKING_UCLI + "# second\n")
        self.assertEqual(self._run("release").returncode, 0)
        self.assertNotEqual(self.dest.stat().st_ino, first_inode)
        self.assertIn("# second", self.dest.read_text())

    def test_no_temp_files_are_left_next_to_the_delivered_binary(self):
        self._binary("release")
        self.assertEqual(self._run("release").returncode, 0)
        leftovers = sorted(p.name for p in self.dest.parent.iterdir())
        self.assertEqual(leftovers, ["ucli", "ucli.info"])

    def test_a_stale_source_binary_is_refused_unless_forced(self):
        binary = self._binary("release")
        set_age(binary, 600)
        set_age(self.main_rs, 5)  # kaynak ikiliden YENİ

        refused = self._run("release")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("BAYAT", refused.stderr)
        self.assertIn("main.rs", refused.stderr)
        self.assertFalse(self.dest.exists())

        forced = self._run("release", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertTrue(self.dest.exists())

    def test_test_only_files_do_not_make_the_binary_stale(self):
        self._binary("release")
        tests_dir = self.src_root / "crates" / "ucli" / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "cli.rs").write_text("// test\n")
        (self.main_rs.parent / "tests.rs").write_text("// test\n")
        result = self._run("release")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_broken_binary_is_not_delivered(self):
        self._binary("release", BROKEN_UCLI)
        result = self._run("release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("chat --help", result.stderr)
        self.assertFalse(self.dest.exists())

    def test_a_missing_source_binary_explains_how_to_build(self):
        result = self._run("release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cargo build --release --locked", result.stderr)
        self.assertFalse(self.dest.exists())

    def test_build_flag_runs_cargo_with_the_profile_arguments_and_skips_the_staleness_check(self):
        bin_dir = self.root / "fakebin"
        bin_dir.mkdir()
        cargo = bin_dir / "cargo"
        cargo.write_text(FAKE_CARGO)
        cargo.chmod(0o755)
        log = self.root / "cargo.log"
        env = {"CARGO_LOG": str(log)}
        # Eski bir ikili + yeni kaynak: --build olmadan reddedilecek durum.
        stale = self._binary("release")
        set_age(stale, 600)
        set_age(self.main_rs, 5)

        release = self._run("release", "--build", path_prefix=str(bin_dir), extra_env=env)
        self.assertEqual(release.returncode, 0, release.stderr)
        self.assertIn("# built by fake cargo", self.dest.read_text())
        self.assertEqual(self._info()["profile"], "release")

        debug = self._run("debug", "--build", path_prefix=str(bin_dir), extra_env=env)
        self.assertEqual(debug.returncode, 0, debug.stderr)
        self.assertEqual(self._info()["profile"], "debug")

        self.assertEqual(log.read_text().splitlines(), ["build --release --locked", "build --locked"])

    def test_from_delivers_an_arbitrary_binary_and_skips_the_staleness_check(self):
        elsewhere = self.root / "elsewhere" / "ucli"
        elsewhere.parent.mkdir()
        elsewhere.write_text(WORKING_UCLI + "# from elsewhere\n")
        elsewhere.chmod(0o755)
        set_age(elsewhere, 600)
        set_age(self.main_rs, 5)
        result = self._run("debug", "--from", str(elsewhere))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# from elsewhere", self.dest.read_text())
        self.assertEqual(self._info()["source_git"], "-")

    def test_unknown_argument_is_a_usage_error_and_delivers_nothing(self):
        result = self._run("sideways")
        self.assertEqual(result.returncode, 2)
        self.assertIn("bilinmeyen argüman", result.stderr)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
