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
                  mock.patch.object(f, "port_busy", self.w.busy), mock.patch.object(f, "_sc", self.w.sc),
                  mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": ""})):
            p.start(); self.addCleanup(p.stop)

    def run_front(self, action, apply=False, listen=L, internal=I, binp=None):
        out = io.StringIO()
        args = SimpleNamespace(action=action, apply=apply, listen=listen, internal=internal, bin=binp or str(self.bin))
        with contextlib.redirect_stdout(out):
            rc = f.run(args)
        return rc, out.getvalue()


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


if __name__ == "__main__":
    unittest.main()
