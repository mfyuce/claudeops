import os, sys, unittest
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
        u = f.FRONT_UNIT_TEMPLATE.format(bin="/b/copsd", listen="a:1", internal="b:2")
        self.assertIn("--upstream b:2", u)
        self.assertNotIn("SECRET", u.upper())


if __name__ == "__main__":
    unittest.main()
