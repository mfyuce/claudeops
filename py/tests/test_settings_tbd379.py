"""TBD#379 (S12): sonsuz `history_warn_at` değnekçi ayarı okumasını düşürmesin."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claudeops import settings
from claudeops.steward import Config


class InfiniteHistoryWarnAt(unittest.TestCase):
    def test_infinite_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with mock.patch.object(settings, "SETTINGS_JSON", path):
                for raw in ("Infinity", "-Infinity", "1e400"):
                    path.write_text('{"history_warn_at": %s}' % raw, encoding="utf-8")
                    cfg = settings.steward_config()
                    self.assertEqual(cfg.history_warn_at, Config.history_warn_at, raw)
                    self.assertEqual(cfg.history_warn_at, 1900, raw)


if __name__ == "__main__":
    unittest.main()
