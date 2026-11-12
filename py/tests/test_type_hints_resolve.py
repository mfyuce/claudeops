"""ruff F821 turu (12 Kas): `get_type_hints` ile tanımsız ad patlamasın (settings.Config, steward.Sequence)."""
import typing
import unittest

from claudeops import settings, steward


class TypeHintsResolveTest(unittest.TestCase):
    def test_steward_config_return(self):
        h = typing.get_type_hints(settings.steward_config, globalns={**vars(settings), "Config": steward.Config})
        self.assertIs(h["return"], steward.Config)

    def test_done_conflict_answer(self):
        self.assertIn("questions", typing.get_type_hints(steward.done_conflict_answer))


if __name__ == "__main__":
    unittest.main()
