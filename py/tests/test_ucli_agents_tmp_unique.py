"""ucli_agents: eşzamanlı _save/_write_token_file çağrıları sabit .tmp adında çarpışmaz."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_agents as ua  # noqa: E402


class TmpUnique(unittest.TestCase):
    def test_concurrent_saves_do_not_collide(self):
        d = tempfile.mkdtemp()
        errs = []
        with mock.patch.object(ua, "STATE_FILE", os.path.join(d, "st", "agents.json")), mock.patch.object(ua, "TOKEN_DIR", os.path.join(d, "tok")):
            def work(i):
                try:
                    for n in range(30):
                        ua._save({"parents": {}, "children": {str(i): n}})
                        ua._write_token_file("sess", f"t{i}-{n}")
                except Exception as e:      # noqa: BLE001
                    errs.append(repr(e))
            ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(errs, [])
            self.assertEqual(sorted(os.listdir(os.path.join(d, "st"))), ["agents.json"])      # artık .tmp kalmadı
            self.assertEqual(sorted(os.listdir(os.path.join(d, "tok"))), ["sess"])

    def test_stale_fixed_tmp_symlink_is_irrelevant(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "st"))
        os.symlink("/nonexistent/x", os.path.join(d, "st", "agents.json.tmp"))
        with mock.patch.object(ua, "STATE_FILE", os.path.join(d, "st", "agents.json")):
            ua._save({"parents": {}, "children": {}})
        self.assertTrue(os.path.isfile(os.path.join(d, "st", "agents.json")))


if __name__ == "__main__":
    unittest.main()
