import os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import front_cmd as f  # noqa: E402

LIVE = "[Service]\nExecStart=/bin/bash -ic '/usr/bin/python3 -m claudeops web'\n"
NEW = "[Service]\nExecStart=/bin/bash -ic 'exec /usr/bin/python3 -m claudeops web'\n"


class T(unittest.TestCase):
    def test_execstart_patch(self):
        es = f.web_execstart(LIVE)
        self.assertEqual(f.with_internal_port(es, "127.0.0.1:28765"), "/bin/bash -ic '/usr/bin/python3 -m claudeops web --host 127.0.0.1 --port 28765'")
        self.assertIn("exec /usr/bin/python3", f.with_internal_port(f.web_execstart(NEW), "127.0.0.1:1"))
        self.assertIsNone(f.with_internal_port("/usr/bin/other", "127.0.0.1:1"))

    def test_dropin_resets_execstart(self):
        d = f.dropin_text("X")
        self.assertTrue(d.index("ExecStart=\n") < d.index("ExecStart=X"))

    def test_plan_blockers(self):
        steps, bl = f.plan_on("127.0.0.1:8765", "127.0.0.1:28765", "/yok/copsd", LIVE)
        self.assertTrue(any("ikili yok" in b for b in bl))
        self.assertGreaterEqual(len(steps), 5)
        _, bl = f.plan_on("127.0.0.1:8765", "127.0.0.1:28765", sys.executable, "[Service]\nExecStart=/x\n")
        self.assertTrue(any("tanınmadı" in b for b in bl))

    def test_unit_template_has_no_secret(self):
        u = f.FRONT_UNIT_TEMPLATE.format(bin="/b/copsd", listen="a:1", internal="b:2", dist="/d", state="/s")
        self.assertIn("--upstream b:2 --dist /d --state-dir /s", u)
        self.assertNotIn("SECRET", u.upper())

    def test_applied_unit_passes_the_secret_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "durum dizini %h $X"
            web = root / "claudeops-web.service"
            web.write_text(LIVE)
            unit = root / "claudeops-front.service"
            args = SimpleNamespace(action="on", apply=True, listen="127.0.0.1:1", internal="127.0.0.1:2", bin=sys.executable)
            with mock.patch.object(f.front_mod.paths, "CLAUDEOPS_DIR", str(state)), \
                    mock.patch.object(f, "WEB_UNIT", web), mock.patch.object(f, "FRONT_UNIT", unit), \
                    mock.patch.object(f, "DROPIN", root / "d" / "front.conf"), \
                    mock.patch.object(f, "port_busy", lambda hp: False), mock.patch.object(f, "_sc", lambda *a: 0), \
                    mock.patch.object(f, "_port_owner", lambda hp: ("holders", [(1, f.FRONT_UNIT_NAME if hp == "127.0.0.1:1"
                                                                                else f.WEB_UNIT_NAME)])), \
                    mock.patch.dict(os.environ, {"CLAUDEOPS_FRONT_SECRET": ""}), mock.patch("builtins.print"):
                self.assertEqual(f.run(args), 0)
                self.assertEqual(os.path.dirname(f.front_mod.secret_path()), str(state))
                self.assertTrue((state / "front.secret").is_file())
            line = [x for x in unit.read_text().splitlines() if x.startswith("ExecStart=")][0]
            self.assertTrue(line.endswith(' --state-dir "%s/durum dizini %%%%h $$X"' % tmp), line)


if __name__ == "__main__":
    unittest.main()
