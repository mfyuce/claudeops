"""rs/prov S4 (sahip kararı (a), 27 Kas): adı `_KEY`/`_TOKEN`/`_SECRET` ile biten açılış ortamı (sağlayıcı + kanca) komut
satırına gömülmez; `CLAUDEOPS_DIR/spawn-env/` (0700) altında 0600 dosyaya yazılır, kabuk onu alt kabukta yükleyip siler.
Dosya güvenle yazılamıyorsa oturum açılmaz. Yalnız geçici dizin; tmux, pencere, kanca ve günlük sahte (gerçek durum
dizinine, tmux sunucusuna ve ağa dokunulmaz)."""
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import authz, spawn  # noqa: E402

SECRETS = {"API_KEY": "s1r-anahtar 'x'", "MY_TOKEN": "t0ken$(id)", "APP_SECRET": "gizli\"deger"}
PLAIN = {"PROVIDER_DIR": "/p d", "COPS_NAME": "kanca"}


class _FakeProvider:
    accepts_cli_opts = False
    mcp_needs_cwd = False

    def __init__(self, env=None):
        self._env = env or {}

    def resolve_effort(self, model, effort):
        return effort

    def resolve_resume_id(self, *a, **k):
        return None

    def build_inner_command(self, *a, **k):
        return "env"

    def env_overrides(self, name):
        return dict(self._env)


class _Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = os.path.realpath(d.name)
        self.state = os.path.join(self.root, "durum")
        os.mkdir(self.state, 0o700)
        self.cwd = os.path.join(self.root, "is")
        os.mkdir(self.cwd)
        self.envdir = os.path.join(self.state, "spawn-env")
        self.logs, self.direct, self.windows = [], [], []
        self.hook_env = {}
        self.provider = _FakeProvider()

        def direct(name, cwd, inner, env):
            self.direct.append(inner)
            return True

        patches = [
            mock.patch.object(spawn, "CLAUDEOPS_DIR", self.state),
            mock.patch.object(spawn, "get_provider", lambda cli: self.provider),
            mock.patch.object(spawn, "spawn_priority_prefix", lambda name: ""),
            mock.patch.object(spawn, "diag_log", lambda ev, **k: self.logs.append((ev, k))),
            mock.patch.object(spawn, "_reclaim_ghost_session", lambda *a: None),
            mock.patch.object(spawn, "tmux_available", lambda: True),
            mock.patch.object(spawn, "tmux_spawn_direct", direct),
            mock.patch.object(authz, "spawn_env", lambda cli, name, cwd: dict(self.hook_env)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def spawn(self, **kw):
        kw.setdefault("hidden", True)
        return spawn.spawn_session("s1", self.cwd, "m", display=":9", force_new=True, cli="sahte", **kw)

    def env_files(self):
        if not os.path.isdir(self.envdir):
            return []
        return sorted(os.listdir(self.envdir))

    def assert_no_secret_in(self, text):
        for v in SECRETS.values():
            self.assertNotIn(v, text)
            self.assertNotIn(v.split()[0][:6], text)


class SecretEnvGoesToAFileTest(_Base):
    def test_secret_names_leave_the_command_line_and_reach_the_child(self):
        self.hook_env = {**PLAIN, **SECRETS}
        self.spawn()
        self.assertEqual(len(self.direct), 1)
        inner = self.direct[0]
        self.assert_no_secret_in(inner)
        self.assertIn("PROVIDER_DIR='/p d' ", inner)
        self.assertIn("COPS_NAME=kanca ", inner)
        files = self.env_files()
        self.assertEqual(len(files), 1, files)
        path = os.path.join(self.envdir, files[0])
        self.assertEqual(stat.S_IMODE(os.stat(self.envdir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)
        self.assertIn(path, inner)
        # Gerçek kabukta: değerler çocuğa ulaşır, dosya yüklenince silinir, değer kalan kabuğa sızmaz.
        r = subprocess.run(["sh", "-c", inner + "; echo KALAN=${API_KEY-yok}"], capture_output=True, text=True,
                           timeout=10, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        self.assertEqual(r.returncode, 0, r.stderr)
        for k, v in {**PLAIN, **SECRETS}.items():
            self.assertIn(f"{k}={v}\n", r.stdout)
        self.assertIn("KALAN=yok", r.stdout)
        self.assertFalse(os.path.exists(path))

    def test_provider_env_is_split_the_same_way(self):
        self.provider = _FakeProvider({"COPS_NAME": "s1", "SERVICE_TOKEN": "prov-gizli"})
        self.spawn()
        self.assertNotIn("prov-gizli", self.direct[0])
        self.assertIn("COPS_NAME=s1 ", self.direct[0])
        with open(os.path.join(self.envdir, self.env_files()[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), "export SERVICE_TOKEN=prov-gizli\n")

    def test_only_secret_suffixes_and_bare_names_count(self):
        self.hook_env = {"KEYRING_DIR": "/k", "TOKENS": "2", "SECRETARY": "a", "PASSWORDS": "p",
                         "X_KEY": "gizli1"}
        self.spawn()
        inner = self.direct[0]
        for k in ("KEYRING_DIR=/k", "TOKENS=2", "SECRETARY=a", "PASSWORDS=p"):
            self.assertIn(k, inner)
        self.assertNotIn("gizli1", inner)

    def test_password_and_credential_names_leave_the_command_line(self):
        # TBD#443: üç son ek dışında kalan parola/kimlik bilgisi adları da komut satırına girmez.
        self.hook_env = {"PASSWORD": "gizli-a", "DB_PASSWORD": "gizli-b", "X_PASSWD": "gizli-c",
                         "GH_CREDENTIALS": "gizli-d", "AWS_CREDENTIAL": "gizli-e", "TOKEN": "gizli-f"}
        self.spawn()
        inner = self.direct[0]
        for v in self.hook_env.values():
            self.assertNotIn(v, inner)
        with open(os.path.join(self.envdir, self.env_files()[0]), encoding="utf-8") as f:
            body = f.read()
        for k, v in self.hook_env.items():
            self.assertIn(f"export {k}={v}\n", body)

    def test_auth_pat_dsn_names_leave_the_command_line(self):
        # 28 Kas (TODO rs-prov S4 kalanı): erişim jetonu, parolalı adres ve anahtar parolası adları da dosyaya gider.
        self.hook_env = {"GITHUB_PAT": "gizli-g", "DATABASE_DSN": "pg://u:gizli-d@h", "NPM_AUTH": "gizli-n",
                         "GPG_PASSPHRASE": "gizli-p", "X_APIKEY": "gizli-k", "PAT": "gizli-b",
                         "PATH_EXTRA": "/kalir", "XPAT": "kalir2"}
        self.spawn()
        inner = self.direct[0]
        for k, v in self.hook_env.items():
            if v.startswith("/kalir") or v == "kalir2":
                self.assertIn(f"{k}={v}", inner)
            else:
                self.assertNotIn(v, inner)

    def test_dry_run_masks_the_new_secret_names(self):
        self.hook_env = {"GITHUB_PAT": "gizli-g", "DATABASE_DSN": "pg://u:gizli-d@h", "GPG_PASSPHRASE": "gizli-p"}
        out = self.spawn(dry_run=True)
        for v in self.hook_env.values():
            self.assertNotIn(v, out)
        self.assertIn("GITHUB_PAT=***", out)

    def test_without_secret_names_the_command_is_unchanged_and_nothing_is_written(self):
        self.hook_env = dict(PLAIN)
        self.spawn()
        self.assertEqual(self.direct[0], f"cd {self.cwd} && PROVIDER_DIR='/p d' COPS_NAME=kanca env")
        self.assertFalse(os.path.exists(self.envdir))

    def test_dry_run_writes_nothing_and_masks(self):
        self.hook_env = {**PLAIN, **SECRETS}
        out = self.spawn(dry_run=True)
        self.assertTrue(out.startswith("[dry-run] "), out)
        self.assert_no_secret_in(out)
        self.assertIn("API_KEY=***", out)
        self.assertFalse(os.path.exists(self.envdir))
        self.assertEqual(self.direct, [])

    def test_concurrent_spawns_get_separate_files(self):
        self.hook_env = dict(SECRETS)
        self.spawn()
        self.spawn()
        self.assertEqual(len(self.env_files()), 2)
        self.assertNotEqual(self.direct[0], self.direct[1])

    def test_window_and_watchdog_paths_carry_no_secret(self):
        self.hook_env = dict(SECRETS)
        launched = []
        with mock.patch.object(spawn, "shutil", SimpleNamespace(which=lambda n: "/usr/bin/" + n)), \
                mock.patch.object(spawn, "_launch_gnome_terminal",
                                  lambda name, cwd, cmd, env: launched.append((cmd, env)) or True), \
                mock.patch.object(spawn, "tmux_new_session_shell_fragment", lambda n, c, i: f"FRAG<{i}>"), \
                mock.patch.object(spawn, "threading", SimpleNamespace(Thread=lambda target, args, daemon: SimpleNamespace(
                    start=lambda: launched.append(("bekci", args))))):
            self.spawn(hidden=False)
        self.assertEqual(len(launched), 2)
        self.assert_no_secret_in(repr(launched))

    def test_logs_carry_no_secret(self):
        self.hook_env = {**PLAIN, **SECRETS}
        self.spawn()
        self.assert_no_secret_in(repr(self.logs))

    def test_stale_files_are_pruned_fresh_ones_kept(self):
        os.mkdir(self.envdir, 0o700)
        old = os.path.join(self.envdir, "eski.env")
        fresh = os.path.join(self.envdir, "taze.env")
        for p in (old, fresh):
            with open(p, "w") as f:
                f.write("export A_KEY=1\n")
        past = time.time() - spawn._SPAWN_ENV_STALE_SECONDS - 60
        os.utime(old, (past, past))
        self.hook_env = dict(SECRETS)
        self.spawn()
        files = self.env_files()
        self.assertNotIn("eski.env", files)
        self.assertIn("taze.env", files)
        self.assertEqual(len(files), 2)

    def test_a_wide_own_directory_is_narrowed(self):
        os.mkdir(self.envdir)
        os.chmod(self.envdir, 0o755)
        self.hook_env = dict(SECRETS)
        self.spawn()
        self.assertEqual(stat.S_IMODE(os.stat(self.envdir).st_mode), 0o700)
        self.assertEqual(len(self.direct), 1)


class FailClosedTest(_Base):
    def refused(self):
        self.hook_env = {**PLAIN, **SECRETS}
        with self.assertRaises(authz.SpawnRefused) as cm:
            self.spawn()
        self.assertEqual(self.direct, [])
        self.assertEqual(cm.exception.reason, "secret_env_file")
        self.assert_no_secret_in(str(cm.exception))
        self.assert_no_secret_in(repr(self.logs))
        self.assertIn("spawn_env_file_refused", [e for e, _ in self.logs])
        return cm.exception

    def test_symlinked_directory_is_refused(self):
        target = os.path.join(self.root, "baska")
        os.mkdir(target, 0o700)
        os.symlink(target, self.envdir)
        self.refused()
        self.assertEqual(os.listdir(target), [])

    def test_directory_owned_by_someone_else_is_refused(self):
        os.mkdir(self.envdir, 0o700)
        with mock.patch.object(spawn.os, "geteuid", lambda: os.getuid() + 1):
            self.refused()
        self.assertEqual(os.listdir(self.envdir), [])

    def test_a_regular_file_in_its_place_is_refused(self):
        with open(self.envdir, "w") as f:
            f.write("")
        self.refused()

    def test_unwritable_directory_is_refused(self):
        if os.geteuid() == 0:
            self.skipTest("root izin denetimine takılmaz")
        os.mkdir(self.envdir, 0o500)
        self.addCleanup(os.chmod, self.envdir, 0o700)
        e = self.refused()
        self.assertEqual(e.detail, "PermissionError")

    def test_dry_run_is_not_refused_and_still_writes_nothing(self):
        os.symlink(os.path.join(self.root, "yok"), self.envdir)
        self.hook_env = dict(SECRETS)
        self.assertTrue(self.spawn(dry_run=True).startswith("[dry-run] "))
        self.assertFalse(os.path.exists(os.path.join(self.root, "yok")))


class WatchdogRestoresTheEnvFileTest(_Base):
    """TODO 248 (S4 kalanı): dosya yüklenip silindikten sonra bekçi yeniden açarsa (oturum düşmüş) CLI yine başlamalı:
    bekçi her yeniden açılıştan hemen önce dosyayı aynı içerikle geri yazar; var olanı ezmez; yazamazsa açmaz."""

    def run_watchdog(self, consume_first=True):
        self.hook_env = dict(SECRETS)
        captured, launched = [], []
        with mock.patch.object(spawn, "shutil", SimpleNamespace(which=lambda n: "/usr/bin/" + n)), \
                mock.patch.object(spawn, "_launch_gnome_terminal", lambda name, cwd, cmd, env: True), \
                mock.patch.object(spawn, "tmux_new_session_shell_fragment", lambda n, c, i: f"FRAG<{i}>"), \
                mock.patch.object(spawn, "threading", SimpleNamespace(Thread=lambda target, args, daemon: SimpleNamespace(
                    start=lambda: captured.append(args)))):
            self.spawn(hidden=False)
        args = captured[0]
        self.assert_no_secret_in(repr(args))
        if consume_first:     # ilk kabuk dosyayı yükleyip sildi, oturum sonra düştü
            for f in self.env_files():
                os.unlink(os.path.join(self.envdir, f))
        seen = []

        def direct(name, cwd, inner, env):
            seen.append((inner, self.env_files()))
            return True
        with mock.patch.object(spawn, "FALLBACK_ATTEMPT_WAIT_SECONDS", 0.01), \
                mock.patch.object(spawn.time, "sleep"), \
                mock.patch.object(spawn, "tmux_has_session", return_value=False), \
                mock.patch.object(spawn, "_window_titled", return_value=False), \
                mock.patch.object(spawn, "_launch_gnome_terminal",
                                  lambda name, cwd, cmd, env: launched.append(self.env_files()) or True), \
                mock.patch.object(spawn, "tmux_spawn_direct", direct):
            spawn._fallback_watchdog(*args)
        return args, launched, seen

    def test_relaunch_finds_the_file_again(self):
        args, launched, seen = self.run_watchdog()
        self.assertEqual(len(launched), spawn.FALLBACK_RETRY_COUNT)
        self.assertTrue(all(len(x) == 1 for x in launched), launched)
        self.assertEqual(len(seen), 1)
        inner, files = seen[0]
        self.assertEqual(len(files), 1)
        self.assertIn(files[0], inner)
        path = os.path.join(self.envdir, files[0])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        out = subprocess.run(["bash", "-c", f". {path} && env"], capture_output=True, text=True).stdout
        for k, v in SECRETS.items():
            self.assertIn(f"{k}={v}", out)
        self.assert_no_secret_in(repr(self.logs))

    def test_an_unconsumed_file_is_left_untouched(self):
        self.hook_env = dict(SECRETS)
        args, launched, seen = self.run_watchdog(consume_first=False)
        self.assertEqual(len(seen[0][1]), 1)

    def test_unwritable_directory_stops_the_relaunch(self):
        if os.geteuid() == 0:
            self.skipTest("root izin denetimine takılmaz")
        self.hook_env = dict(SECRETS)
        orig = spawn._write_spawn_env_file
        calls = {"n": 0}

        def write_once(*a):
            calls["n"] += 1
            if calls["n"] > 1:
                raise PermissionError(13, "izin yok")
            return orig(*a)
        with mock.patch.object(spawn, "_write_spawn_env_file", write_once):
            args, launched, seen = self.run_watchdog()
        self.assertEqual((launched, seen), ([], []))
        ev = [k for e, k in self.logs if e == "spawn_env_file_refused"]
        self.assertEqual(ev[-1].get("error"), "PermissionError")
        self.assert_no_secret_in(repr(self.logs))


if __name__ == "__main__":
    unittest.main()
