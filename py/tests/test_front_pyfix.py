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
                  mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": ""})):
            p.start(); self.addCleanup(p.stop)

    def run_front(self, action, apply=False, listen=L, internal=I, binp=None):
        out = io.StringIO()
        args = SimpleNamespace(action=action, apply=apply, listen=listen, internal=internal, bin=binp or str(self.bin))
        with contextlib.redirect_stdout(out):
            rc = f.run(args)
        return rc, out.getvalue()


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


if __name__ == "__main__":
    unittest.main()
