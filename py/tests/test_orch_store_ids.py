"""orch_store: eksik/geçersiz run id ValueError verir (KeyError değil); NUL/traversal reddedilir (review cliops|uzops 2 Kas)."""
import unittest

from claudeops import orch_store


class Ids(unittest.TestCase):
    def test_save_run_bad_ids(self):
        for bad in ({}, {"id": None}, {"id": 5}, {"id": ""}, {"id": "../x"}, {"id": "a\0b"}):
            with self.assertRaises(ValueError):
                orch_store.save_run(bad)

    def test_paths(self):
        self.assertIsNone(orch_store._run_path("a\0b"))
        self.assertIsNone(orch_store.load_run("../x"))
        with self.assertRaises(ValueError):
            orch_store.run_dir("../x")


if __name__ == "__main__":
    unittest.main()
