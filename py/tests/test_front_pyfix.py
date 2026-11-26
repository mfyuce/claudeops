"""`front` Python hataları (docs/rs-cli.md "Python hatası?" 1-8): Rust `cops-cli` ile aynı davranış (sahip: kapalı yön).

Gerçek systemctl, gerçek birim dizini ve gerçek durum dizini HİÇ kullanılmaz: yollar geçici dizinde, `_sc`, `port_busy`,
`_port_owner` sahte (Rust `src/front/tests.rs` `World` karşılığı)."""
import contextlib, io, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import front_cmd as f  # noqa: E402

LIVE = "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web'\n"
L, I = "127.0.0.1:8765", "127.0.0.1:28765"
REAL_OWNER = f._port_owner      # Env sahtesiyle değiştirir; gerçek /proc taraması testleri bunu çağırır


class World:
    """Sahte dünya: port sahipleri (kanonik `ip:port` -> sahip), systemctl çağrıları, başarısız komutlar, etkiler."""

    def __init__(self):
        self.owners = {}
        self.calls = []
        self.fail = {}
        self.fail_always = {}
        self.effects = []
        self.front_active = False
        self.front_enabled = False
        self.query_err = False

    def busy(self, hp):
        return self.owners.get(hp, ("none",)) != ("none",)

    def owner(self, hp):
        return self.owners.get(hp, ("none",))

    def sc(self, *a):
        cmd = " ".join(a)
        if a[:2] in (("is-active", "--quiet"), ("is-enabled", "--quiet")):
            if self.query_err:
                raise f._ScError("systemctl başlatılamadı")
            return 0 if (self.front_active if a[0] == "is-active" else self.front_enabled) else 3
        self.calls.append(cmd)
        if cmd in self.fail:
            return self.fail.pop(cmd)
        if cmd in self.fail_always:
            return self.fail_always[cmd]
        for c, hp, o in list(self.effects):
            if c == cmd:
                self.owners[hp] = o
        return 0


def unit(name):
    return ("holders", [(10, name)])


class Env(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "durum dizini %h $X"
        ud = self.root / "home" / ".config" / "systemd" / "user"
        ud.mkdir(parents=True)
        self.web, self.front, self.dropin = ud / "claudeops-web.service", ud / "claudeops-front.service", \
            ud / "claudeops-web.service.d" / "front.conf"
        self.web.write_text(LIVE)
        self.bin = self.root / "copsd"
        self.bin.write_text("#!/bin/sh\n"); self.bin.chmod(0o755)
        self.w = World()
        for p in (mock.patch.object(f.front_mod.paths, "CLAUDEOPS_DIR", str(self.state)),
                  mock.patch.object(f, "WEB_UNIT", self.web), mock.patch.object(f, "FRONT_UNIT", self.front),
                  mock.patch.object(f, "DROPIN", self.dropin), mock.patch.object(f, "DIST_DIR", "/repo/py/webui/dist"),
                  mock.patch.object(f, "port_busy", self.w.busy), mock.patch.object(f, "_port_owner", self.w.owner),
                  mock.patch.object(f, "_sc", self.w.sc),
                  mock.patch.dict(f._TIMING, {"front_up": 0.05, "port_free": 0.05, "web_up": 0.05, "poll": 0.005}),
                  mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": ""})):
            p.start(); self.addCleanup(p.stop)

    def run_front(self, action, apply=False, listen=L, internal=I, binp=None):
        out = io.StringIO()
        args = SimpleNamespace(action=action, apply=apply, listen=listen, internal=internal, bin=binp or str(self.bin))
        with contextlib.redirect_stdout(out):
            rc = f.run(args)
        return rc, out.getvalue()


    def web_outside(self):
        """Canlıdaki "kapalı" durum: web dış portta, ön kapı yok (Rust `Env::web_outside`)."""
        self.w.owners[L] = unit(f.WEB_UNIT_NAME)
        self.w.effects = [("restart claudeops-web.service", L, ("none",)),
                          ("restart claudeops-web.service", I, unit(f.WEB_UNIT_NAME)),
                          ("enable --now claudeops-front.service", L, unit(f.FRONT_UNIT_NAME))]

    def front_on(self):
        """"Açık" durum: ön kapı dışta, web içte, drop-in yazılı (Rust `Env::front_on`)."""
        self.dropin.parent.mkdir(parents=True, exist_ok=True)
        self.dropin.write_text("eski drop-in\n")
        self.front.write_text("eski birim\nExecStart=/x/copsd --listen 127.0.0.1:8765 --upstream y\n")
        w = self.w
        w.front_active = w.front_enabled = True
        w.owners[L], w.owners[I] = unit(f.FRONT_UNIT_NAME), unit(f.WEB_UNIT_NAME)
        w.effects = [("disable --now claudeops-front.service", L, ("none",)),
                     ("restart claudeops-web.service", I, ("none",)),
                     ("restart claudeops-web.service", L, unit(f.WEB_UNIT_NAME)),
                     ("enable --now claudeops-front.service", L, unit(f.FRONT_UNIT_NAME))]


class P1Addresses(Env):
    """1: `--internal 28765` bozuk birim, sayı olmayan port döküm, `[::1]` hata -> geçersiz adres ENGEL / `status` rc 1."""

    def test_bad_internal_addresses_are_blockers_not_crashes(self):
        for bad in ("28765", "127.0.0.1:abc", "127.0.0.1:0", "127.0.0.1:70000", "[::1]:28765", "localhost:28765", ""):
            rc, out = self.run_front("on", True, L, bad)
            self.assertEqual(rc, 1, f"{bad}: {out}")
            self.assertIn("geçersiz --internal", out, bad)
            self.assertEqual(self.w.calls, [], bad)
            self.assertFalse(self.front.exists(), bad)
            self.assertFalse((self.state / "front.secret").exists(), bad)

    def test_bad_listen_is_a_blocker_and_ipv6_listen_is_fine(self):
        rc, out = self.run_front("on", False, "8765", I)
        self.assertEqual(rc, 1)
        self.assertIn('geçersiz --listen: "8765": IP:port biçiminde değil (iki nokta yok)', out)
        rc, out = self.run_front("on", False, "[::1]:8765", I)
        self.assertEqual(rc, 0, out)
        rc, out = self.run_front("on", False, I, I)
        self.assertEqual(rc, 1)
        self.assertIn("dış ve iç adres çakışıyor: 127.0.0.1:28765 / 127.0.0.1:28765", out)

    def test_status_reports_bad_address_without_crashing(self):
        rc, out = self.run_front("status", False, "[::1]:8765", "28765")
        self.assertEqual(rc, 1)
        self.assertIn("port [::1]:8765: boş\n", out)
        self.assertIn('port 28765: geçersiz adres ("28765": IP:port biçiminde değil (iki nokta yok))\n', out)

    def test_parse_rules_match_rust(self):
        self.assertEqual(f._fmt(f._parse_listen("127.0.0.1:08765")), "127.0.0.1:8765")
        self.assertEqual(f._fmt(f._parse_listen("[::1]:8765")), "[::1]:8765")
        for bad in ("28765", "127.0.0.1:", "127.0.0.1:abc", "127.0.0.1:+80", "127.0.0.1:0", "127.0.0.1:65536",
                    "127.0.0.1:999999", "localhost:8765", ":8765", "[::1:8765", "::1:8765", "127.0.0.1:８７",
                    "[::1%lo]:8765", "01.2.3.4:80"):
            with self.assertRaises(ValueError, msg=bad):
                f._parse_listen(bad)
        with self.assertRaises(ValueError) as c:
            f._parse_internal("[::1]:28765")
        self.assertIn("IPv6", str(c.exception))
        self.assertEqual(str(c.exception),
                         '"[::1]:28765": iç adres IPv6 olamaz (Python web yalnız IPv4 dinler: ThreadingHTTPServer AF_INET)')
        self.assertEqual(f._rdbg('a"b\\c\n\x1b'), '"a\\"b\\\\c\\n\\u{1b}"')


class P2ForeignInternalPort(Env):
    """2: drop-in varken iç portu yabancı süreç tutuyorsa ön kapı ona vekil olmasın (ENGEL)."""

    def test_foreign_process_on_internal_port_blocks_even_with_dropin(self):
        self.front_on()
        self.w.owners["127.0.0.1:29999"] = ("holders", [(99, None)])
        rc, out = self.run_front("on", True, L, "127.0.0.1:29999")
        self.assertEqual(rc, 1, out)
        self.assertIn("iç port başka bir süreçte: 127.0.0.1:29999 (pid 99 (birimsiz)); drop-in var ama dinleyen "
                      "claudeops-web.service değil", out)
        self.assertEqual(self.w.calls, [])
        self.assertEqual(self.dropin.read_text(), "eski drop-in\n")
        for o in (("other_user", 5), ("unknown",), unit("other.service"), ("holders", [(1, f.WEB_UNIT_NAME), (2, None)])):
            self.w.owners[I] = o
            rc, out = self.run_front("on", True, L, I)
            self.assertEqual(rc, 1, o)
            self.assertIn("başka bir süreçte", out)
        self.assertEqual(self.w.calls, [])

    def test_our_web_on_internal_port_is_a_reapply(self):
        self.front_on()
        self.w.effects = []
        rc, out = self.run_front("on", True, L, I)
        self.assertEqual(self.w.calls[:3], ["daemon-reload", "enable --now claudeops-front.service",
                                            "restart claudeops-front.service"], out)

    def test_real_listener_is_found_with_our_pid(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); s.listen()
            hp = "127.0.0.1:%d" % s.getsockname()[1]
            o = REAL_OWNER(hp)
            self.assertEqual(o[0], "holders", o)
            self.assertIn(os.getpid(), [p for p, _ in o[1]])
            self.assertFalse(f._is_unit(o, f.WEB_UNIT_NAME))
        self.assertEqual(REAL_OWNER(hp), ("none",))

    def test_fake_proc_tree_unit_detection(self):
        p = self.root / "proc"
        (p / "net").mkdir(parents=True)
        head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        uid = os.getuid()
        addr = "0100007F" if sys.byteorder == "little" else "7F000001"
        (p / "net" / "tcp").write_text(f"{head}   0: {addr}:6FDD 00000000:0000 0A 00000000:00000000 00:00000000 "
                                       f"00000000  {uid}        0 4242 1 0 100 0 0 10 0\n")
        (p / "77" / "fd").mkdir(parents=True)
        os.symlink("socket:[4242]", p / "77" / "fd" / "3")
        (p / "77" / "cgroup").write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/claudeops-web.service\n")
        with mock.patch.object(f, "_PROC", str(p)):
            self.assertTrue(f._is_unit(REAL_OWNER("127.0.0.1:28637"), f.WEB_UNIT_NAME))
            (p / "78" / "fd").mkdir(parents=True)
            os.symlink("socket:[4242]", p / "78" / "fd" / "9")
            (p / "78" / "cgroup").write_text("0::/user.slice/x.scope/\n")
            self.assertFalse(f._is_unit(REAL_OWNER("127.0.0.1:28637"), f.WEB_UNIT_NAME))
            hybrid = ("12:pids:/user.slice/user-1000.slice/user@1000.service\n"
                      "1:name=systemd:/user.slice/user-1000.slice/user@1000.service/app.slice/claudeops-web.service\n"
                      "0::/user.slice/user-1000.slice/user@1000.service/app.slice/claudeops-web.service\n")
            (p / "78" / "cgroup").write_text(hybrid)
            self.assertEqual(f._unit_of(str(p), 78), f.WEB_UNIT_NAME)
            self.assertTrue(f._is_unit(REAL_OWNER("127.0.0.1:28637"), f.WEB_UNIT_NAME))
            (p / "78" / "cgroup").write_text("12:pids:/user.slice/user-1000.slice/user@1000.service\n"
                                             "1:name=systemd:/u/app.slice/claudeops-front.service\n")
            self.assertEqual(f._unit_of(str(p), 78), f.FRONT_UNIT_NAME)
            (p / "78" / "cgroup").write_text("12:pids:/user.slice/u@1.service\n")
            self.assertIsNone(f._unit_of(str(p), 78))
            with mock.patch.object(f.os, "getuid", lambda: uid + 1):
                self.assertEqual(REAL_OWNER("127.0.0.1:28637"), ("other_user", uid))
            self.assertEqual(f._describe(("holders", [(1, None), (2, "a.service")])), "pid 1 (birimsiz), pid 2 (a.service)")


class P5RelativeBin(Env):
    """5: göreli `--bin` birime göreli yazılıyordu (systemd reddeder); çalıştırılamaz ikili de engel."""

    def test_relative_bin_is_a_blocker(self):
        rel = self.root / "rel-copsd"
        rel.write_text("#!/bin/sh\n"); rel.chmod(0o755)
        cwd = os.getcwd()
        os.chdir(self.root); self.addCleanup(os.chdir, cwd)
        rc, out = self.run_front("on", True, L, I, binp="rel-copsd")
        self.assertEqual(rc, 1, out)
        self.assertIn("ENGEL:\n  ikili yolu mutlak değil: rel-copsd (systemd ExecStart mutlak yol ister)\n", out)
        self.assertEqual(self.w.calls, [])
        self.assertFalse(self.front.exists())

    def test_non_executable_bin_is_a_blocker(self):
        self.bin.chmod(0o644)
        rc, out = self.run_front("on", False)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"ikili çalıştırılabilir dosya değil: {self.bin}\n", out)
        rc, out = self.run_front("on", False, binp=str(self.root))
        self.assertIn(f"ikili çalıştırılabilir dosya değil: {self.root}\n", out)


class P6Quoting(Env):
    """6: `bin`/`dist` tırnaksızdı, boşluklu yol ExecStart'ı bölüyordu; denetim karakterli yol birimi bozuyordu."""

    def test_bin_and_dist_with_spaces_are_quoted(self):
        with mock.patch.object(f, "DIST_DIR", Path("/a b/dist")):
            u = f._unit_text("/x y/copsd", "a:1", "b:2")
        self.assertIn('ExecStart="/x y/copsd" --listen a:1 --upstream b:2 --dist "/a b/dist" --state-dir', u)
        u = f._unit_text("/b/copsd", "a:1", "b:2")
        self.assertIn("ExecStart=/b/copsd --listen a:1 --upstream b:2 --dist /repo/py/webui/dist --state-dir", u)
        with mock.patch.object(f, "DIST_DIR", "/d%i$X"):
            self.assertIn('ExecStart="/b\\"q" --listen a:1 --upstream b:2 --dist "/d%%i$$X"', f._unit_text('/b"q', "a:1", "b:2"))

    def test_applied_unit_with_spaced_bin_has_one_execstart_word(self):
        b = self.root / "ikili dizini" / "copsd"
        b.parent.mkdir(); b.write_text("#!/bin/sh\n"); b.chmod(0o755)
        self.web_outside()
        rc, out = self.run_front("on", True, binp=str(b))
        self.assertEqual(rc, 0, out)
        line = [x for x in self.front.read_text().splitlines() if x.startswith("ExecStart=")][0]
        self.assertTrue(line.startswith(f'ExecStart="{b}" --listen '), line)

    def test_control_characters_in_paths_block(self):
        b = self.root / "a\nExecStartPre=evil"
        b.write_text(""); b.chmod(0o755)
        rc, out = self.run_front("on", True, binp=str(b))
        self.assertEqual(rc, 1, out)
        self.assertIn('ikili yolu denetim karakteri içeriyor (birim dosyasını bozar): "%s/a\\nExecStartPre=evil"' % self.root, out)
        self.assertEqual(self.w.calls, [])
        self.assertFalse(self.front.exists())
        with mock.patch.object(f.front_mod.paths, "CLAUDEOPS_DIR", str(self.root / "s\tx")):
            rc, out = self.run_front("on", False)
        self.assertIn("durum dizini yolu denetim karakteri içeriyor", out)


class P7SecretEnv(Env):
    """7: `CLAUDEOPS_FRONT_SECRET` doluyken `ensure_secret` dosya üretmiyordu; ortam yalnız CLI kabuğunda olduğundan copsd ve
    web birimleri gizlisiz kalıyordu. Dosya ortamdan bağımsız üretilir; okumada ortam yine önce gelir."""

    def test_env_does_not_prevent_the_file(self):
        with mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": "ortam"}):
            v = f.front_mod.ensure_secret()
            self.assertEqual(len(v), 64)
            p = self.state / "front.secret"
            self.assertEqual(p.read_text(), v + "\n")
            self.assertEqual(f.front_mod.ensure_secret(), v)
            self.assertEqual(f.front_mod.read_secret(), "ortam")
        self.assertEqual(f.front_mod.read_secret(), v)

    def test_front_on_writes_the_file_even_with_env(self):
        self.w.owners[L] = unit(f.WEB_UNIT_NAME)
        with mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": "ortam"}):
            self.run_front("on", True)
        self.assertTrue((self.state / "front.secret").is_file())


class P8RelativeStateDir(unittest.TestCase):
    """8: göreli `CLAUDEOPS_DIR` `py/cops`un `cd py/` adımı yüzünden `py/` altına çözülüyordu (gizli, birim `--state-dir`
    oraya gidiyordu). Artık açık hata, hiçbir şey yazılmaz (Rust `Roots::check_absolute` ile aynı)."""

    PY = Path(__file__).resolve().parents[1]

    def _env(self, d):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDEOPS_DIR"}
        env.update(CLAUDEOPS_DIR=d, CLAUDEOPS_EXTENSIONS="off")
        return env

    def test_relative_state_dir_is_refused_before_anything_is_written(self):
        import subprocess
        rel = "cops-goreli-durum-testi"
        self.assertFalse((self.PY / rel).exists())
        with tempfile.TemporaryDirectory() as cwd:
            for argv in (["python3", "-c", "import claudeops.paths"], [str(self.PY / "cops"), "front", "status"]):
                r = subprocess.run(argv, cwd=self.PY if argv[0] == "python3" else cwd, env=self._env(rel),
                                   capture_output=True, text=True, timeout=120)
                self.assertEqual(r.returncode, 1, (argv, r.stdout, r.stderr))
                self.assertEqual(r.stderr, f"CLAUDEOPS_DIR göreli ({rel}): mutlak yol verin\n", argv)
                self.assertEqual(r.stdout, "")
                self.assertFalse((self.PY / rel).exists())
                self.assertEqual(os.listdir(cwd), [])

    def test_absolute_state_dir_still_works(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(["python3", "-c", "from claudeops import paths; print(paths.CLAUDEOPS_DIR)"], cwd=self.PY,
                               env=self._env(d), capture_output=True, text=True, timeout=120)
            self.assertEqual((r.returncode, r.stdout), (0, d + "\n"), r.stderr)


class P3Rollback(Env):
    """3: `on`/`off` yarıda kalınca geri alma yoktu, `off` `disable --now` sonucunu yok sayıyordu, birim dosyaları yerinde
    kesilip yazılıyordu, ön kapının dinlediği / web'in döndüğü doğrulanmıyordu. Rust `front::on/off` ile aynı."""

    def test_applied_on_succeeds_and_verifies(self):
        self.web_outside()
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.endswith("açıldı: dış 127.0.0.1:8765 -> iç 127.0.0.1:28765\n"), out)
        self.assertEqual(self.dropin.read_text(), "[Service]\nExecStart=\nExecStart=/bin/bash -ic '/usr/bin/python3 -m "
                                                  "claudeops web --host 127.0.0.1 --port 28765'\n")
        self.assertEqual(self.w.calls, ["daemon-reload", "restart claudeops-web.service",
                                        "enable --now claudeops-front.service"])
        self.assertEqual([x for x in os.listdir(self.front.parent) if x.startswith(".")], [])

    def test_on_rolls_back_at_every_systemctl_step(self):
        steps = ["daemon-reload", "restart claudeops-web.service", "enable --now claudeops-front.service"]
        undo = [["daemon-reload"], ["daemon-reload", "restart claudeops-web.service"],
                ["disable --now claudeops-front.service", "daemon-reload", "restart claudeops-web.service"]]
        for i, step in enumerate(steps):
            with self.subTest(step=step):
                self.setUp()
                self.web_outside()
                self.w.fail[step] = 5
                rc, out = self.run_front("on", True)
                self.assertEqual(rc, 1, out)
                self.assertIn(f"HATA: systemctl --user {step}\n  neden: çıkış 5\nGERİ ALMA:\n", out)
                self.assertIn("geri alındı: birim dosyaları ve servisler önceki durumda\n", out)
                self.assertFalse(self.front.exists())
                self.assertFalse(self.dropin.exists())
                self.assertEqual(self.w.calls[i + 1:], undo[i])

    def test_front_not_listening_is_rolled_back(self):
        self.web_outside()
        self.w.effects = [e for e in self.w.effects if e[0] != "enable --now claudeops-front.service"
                          and not (e[0] == "restart claudeops-web.service" and e[1] == L)]
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1)
        self.assertIn("HATA: ön kapı 127.0.0.1:8765 üzerinde dinlemiyor (0 sn içinde claudeops-front.service görülmedi: "
                      "pid 10 (claudeops-web.service))", out)
        self.assertIn("geri alındı", out)
        self.assertEqual(self.w.calls[3:], ["disable --now claudeops-front.service", "daemon-reload",
                                            "restart claudeops-web.service"])

    def test_on_web_not_on_internal_is_rolled_back(self):
        self.web_outside()
        self.w.effects = [e for e in self.w.effects if not (e[0] == "restart claudeops-web.service" and e[1] == I)]
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1, out)
        self.assertIn("HATA: web iç adreste 127.0.0.1:28765 doğrulanamadı", out)
        self.assertIn("geri alındı", out)
        self.assertFalse(self.dropin.exists())

    def test_reapply_failure_restores_previous_unit_and_restarts_old_front(self):
        self.front_on()
        self.w.fail_always["restart claudeops-front.service"] = 1
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1, out)
        self.assertTrue(self.front.read_text().startswith("eski birim"))
        self.assertEqual(self.dropin.read_text(), "eski drop-in\n")
        self.assertIn("  systemctl --user restart claudeops-front.service: HATA (çıkış 1)\n", out)
        self.assertIn("GERİ ALMA BAŞARISIZ: yukarıda HATA yazan adımları elle tamamlayın", out)

    def test_write_failure_restores_files_without_systemctl(self):
        self.dropin.parent.mkdir(parents=True)
        self.dropin.parent.chmod(0o500)
        self.addCleanup(self.dropin.parent.chmod, 0o700)
        self.front.write_text("onceki")
        self.front.chmod(0o640)
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1)
        self.assertIn(f"HATA: yazılamadı: {self.dropin}: ", out)
        self.assertEqual(self.front.read_text(), "onceki")
        self.assertEqual(self.front.stat().st_mode & 0o777, 0o640)
        self.assertIn(f"  geri yaz: {self.front} (önceki içerik): tamam\n  sil: {self.dropin} (önceden yoktu): tamam\n", out)
        self.assertIn("geri alındı", out)
        self.assertEqual(self.w.calls, [])

    def test_on_listen_change_failure_restarts_old_front_instead_of_stopping_it(self):
        self.front_on()
        self.w.effects = []
        rc, out = self.run_front("on", True, "127.0.0.1:9000", I)
        self.assertEqual(rc, 1, out)
        self.assertIn("ön kapı 127.0.0.1:9000 üzerinde dinlemiyor", out)
        self.assertIn("geri alındı", out)
        self.assertEqual(self.w.calls, ["daemon-reload", "enable --now claudeops-front.service",
                                        "restart claudeops-front.service", "daemon-reload",
                                        "restart claudeops-front.service"])
        self.assertTrue(self.front.read_text().startswith("eski birim"))

    def test_on_rollback_keeps_previous_enablement(self):
        self.front_on()
        self.w.front_enabled = False
        self.w.fail["restart claudeops-front.service"] = 1
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.w.calls[3:], ["daemon-reload", "restart claudeops-front.service",
                                            "disable claudeops-front.service"])
        self.setUp()
        self.web_outside()
        self.w.front_enabled = True
        self.w.fail["enable --now claudeops-front.service"] = 1
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.w.calls[3:], ["stop claudeops-front.service", "daemon-reload", "restart claudeops-web.service"])

    def test_unknown_front_state_changes_nothing(self):
        for action in ("on", "off"):
            with self.subTest(action=action):
                self.setUp()
                self.front_on()
                self.w.query_err = True
                rc, out = self.run_front(action, True)
                self.assertEqual(rc, 1, out)
                self.assertIn("HATA: claudeops-front.service durumu okunamadı: systemctl başlatılamadı (hiçbir şey değişmedi)", out)
                self.assertEqual(self.w.calls, [])
                self.assertEqual(self.dropin.read_text(), "eski drop-in\n")
                self.assertFalse((self.state / "front.secret").exists())

    def test_unreadable_web_unit_is_a_blocker(self):
        self.web.write_bytes(b"[Service]\nExecStart=\xff web\n")
        rc, out = self.run_front("on", True)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"ENGEL:\n  claudeops-web.service okunamadı: {self.web}: UTF-8 değil\n", out)
        self.assertEqual(self.w.calls, [])

    def test_off_success_sequence_and_verifies_web(self):
        self.front_on()
        rc, out = self.run_front("off", True, "9.9.9.9:1", I)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.endswith("kapandı\n"))
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.w.calls, ["disable --now claudeops-front.service", "daemon-reload",
                                        "restart claudeops-web.service"])

    def test_off_disable_failure_changes_nothing(self):
        self.front_on()
        self.w.fail["disable --now claudeops-front.service"] = 1
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 1)
        self.assertIn("HATA: systemctl --user disable --now claudeops-front.service\n  neden: çıkış 1\n", out)
        self.assertEqual(self.dropin.read_text(), "eski drop-in\n")
        self.assertEqual(self.w.calls, ["disable --now claudeops-front.service", "enable --now claudeops-front.service"])

    def test_off_disable_failure_keeps_stopped_front_stopped(self):
        self.front_on()
        self.w.front_active = self.w.front_enabled = False
        self.w.fail["disable --now claudeops-front.service"] = 1
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.w.calls, ["disable --now claudeops-front.service"])
        self.assertIn("geri alındı", out)

    def test_off_web_restart_failure_returns_to_front(self):
        self.front_on()
        self.w.fail_always["restart claudeops-web.service"] = 3
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 3, "Python'un eski davranışı gibi restart'ın kodu")
        self.assertIn("HATA: web restart\n", out)
        self.assertEqual(self.dropin.read_text(), "eski drop-in\n")
        self.assertEqual(self.w.calls[3:], ["daemon-reload", "restart claudeops-web.service",
                                            "enable --now claudeops-front.service"])
        self.assertIn("GERİ ALMA BAŞARISIZ", out)

    def test_off_web_not_back_outside_is_rolled_back(self):
        self.front_on()
        self.w.effects = [e for e in self.w.effects if not (e[0] == "restart claudeops-web.service" and e[1] == L)]
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 1)
        self.assertIn("HATA: web 127.0.0.1:8765 üzerinde doğrulanamadı (0 sn: dinleyen soket bulunamadı)", out)
        self.assertIn("geri alındı", out)
        self.assertEqual(self.dropin.read_text(), "eski drop-in\n")

    def test_off_port_not_released_stops_before_touching_web(self):
        self.front_on()
        self.w.effects = []
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 1)
        self.assertIn("HATA: dış port 127.0.0.1:8765 boşalmadı (pid 10 (claudeops-front.service)); web oraya dönemez", out)
        self.assertTrue(self.dropin.exists())
        self.assertEqual(self.w.calls, ["disable --now claudeops-front.service", "enable --now claudeops-front.service"])

    def test_off_without_front_unit_ignores_disable_error(self):
        self.w.owners[L] = unit(f.WEB_UNIT_NAME)
        self.w.fail["disable --now claudeops-front.service"] = 5
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 0, out)
        self.assertIn("(not: claudeops-front.service birimi yok; durdurma hatası yok sayıldı)\n", out)

    def test_off_verifies_web_on_its_own_port_when_front_listen_differs(self):
        self.front_on()
        alt = "127.0.0.1:9000"
        self.front.write_text("ExecStart=/x/copsd --listen 127.0.0.1:9000 --upstream y\n")
        del self.w.owners[L]
        self.w.owners[alt] = unit(f.FRONT_UNIT_NAME)
        self.w.effects = [("disable --now claudeops-front.service", alt, ("none",)),
                          ("restart claudeops-web.service", L, unit(f.WEB_UNIT_NAME))]
        rc, out = self.run_front("off", True)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.endswith("kapandı\n"), out)

    def test_web_addr_follows_web_unit_flags(self):
        a = lambda t: (lambda r: f._fmt(r) if r else None)(f._web_addr(t))      # noqa: E731
        self.assertEqual(a(LIVE), "127.0.0.1:8765")
        self.assertEqual(a("ExecStart=/x -m claudeops web --port 9001 --host 0.0.0.0"), "127.0.0.1:9001")
        self.assertEqual(a("ExecStart=/bin/bash -ic 'python3 -m claudeops web --host=127.0.0.2 --port=9002'"), "127.0.0.2:9002")
        self.assertIsNone(a("ExecStart=/x web --port abc"))
        self.assertIsNone(a("[Service]\n"))

    def test_atomic_write_snapshot_restore_roundtrip(self):
        p = self.root / "u.service"
        self.assertIsNone(f._snapshot(p))
        f._atomic_write(p, b"a")
        p.chmod(0o640)
        snap = f._snapshot(p)
        self.assertEqual(snap, (b"a", 0o640))
        f._atomic_write(p, b"b")
        f._restore(p, snap)
        self.assertEqual((p.read_bytes(), p.stat().st_mode & 0o777), (b"a", 0o640))
        f._restore(p, None)
        self.assertFalse(p.exists())
        f._restore(p, None)
        d = self.root / "d"; d.mkdir(); (d / "x").write_text("1")
        with self.assertRaises(OSError):
            f._atomic_write(d, b"z")
        self.assertEqual(sorted(x for x in os.listdir(self.root) if x.startswith(".")), [])


if __name__ == "__main__":
    unittest.main()
