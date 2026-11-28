"""`spawn_session(dry_run=True)` kendini önizleme kipinde yeniden çağırır: her parametre aynen iletilmeli (TODO rs-prov
"kuru çalıştırma kenarları"; eskiden konumsal liste elle yazılıydı, yeni parametre unutulursa kuru koşuda düşerdi)."""
import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from claudeops import preview, spawn  # noqa: E402


class SpawnDryRunForwardsEveryArgument(unittest.TestCase):
    def test_spawn_dry_run_forwards_every_argument(self):
        original = spawn.spawn_session
        params = inspect.signature(original).parameters
        given = {}
        for n, p in params.items():
            # varsayılandan farklı, ayırt edilebilir değerler
            given[n] = True if n == "dry_run" else object() if p.default is not True else False
        seen = []

        def record(*args, **kwargs):
            seen.append((args, kwargs, preview.active()))
            return "kayit"

        with mock.patch.object(spawn, "spawn_session", record):
            self.assertEqual(original(**given), "kayit")
        self.assertEqual(len(seen), 1)
        args, kwargs, active = seen[0]
        self.assertEqual(args, ())
        self.assertTrue(active)
        self.assertEqual(set(kwargs), set(params))
        for n in params:
            self.assertIs(kwargs[n], given[n], n)


if __name__ == "__main__":
    unittest.main()
