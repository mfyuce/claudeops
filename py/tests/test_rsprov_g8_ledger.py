"""rs/prov G8: ucli ajan defteri (`ucli_agents`) kilidi, bozuk kayıt ve bozuk defter. Yalnız geçici dizin."""
import fcntl
import glob
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_agents as ua  # noqa: E402


class _Registry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = os.path.join(tmp.name, "ucli_agents.json")
        for p in (mock.patch.object(ua, "STATE_FILE", self.state), mock.patch.object(ua, "TOKEN_DIR", os.path.join(tmp.name, "tok"))):
            p.start()
            self.addCleanup(p.stop)

    def put(self, body):
        with open(self.state, "w") as f:
            f.write(body)

    def text(self, path):
        with open(path) as f:
            return f.read()


class CrossProcessLock(_Registry):
    def test_every_writer_waits_for_the_file_lock(self):
        self.put(json.dumps({"parents": {"p": {"sha256": "x"}}, "children": {"p_aj1": {"parent": "p"}}}))
        for write in (lambda: ua.issue_token("p"), lambda: ua.revoke_parent("p"),
                      lambda: ua.reserve_child("p", set(), lambda n: False, {}), lambda: ua.update_child("p_aj1", status="stopped")):
            fd = os.open(self.state + ".lock", os.O_RDWR | os.O_CREAT, 0o600)      # başka süreç kilidi tutuyor
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                t = threading.Thread(target=write, daemon=True)
                t.start()
                t.join(0.3)
                self.assertTrue(t.is_alive())
            finally:
                os.close(fd)
            t.join(10)
            self.assertFalse(t.is_alive())


class BadParentRecord(_Registry):
    def test_the_spawn_still_fails_and_no_token_is_written(self):
        body = json.dumps({"parents": {"p": 5}, "children": {}})
        self.put(body)
        with self.assertRaises(TypeError):
            ua.issue_token("p")
        self.assertFalse(os.path.exists(ua.token_file("p")))
        self.assertEqual(self.text(self.state), body)


if __name__ == "__main__":
    unittest.main()
