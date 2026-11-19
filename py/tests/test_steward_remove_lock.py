"""D11: `steward remove` kimliği ayardan silmeyi ownership_lock İÇİNDE yapar (dizin taşıma ile kayıt silme arasında pencere yok)."""
import contextlib
import io
import os
import tempfile
import types
import unittest
from unittest import mock

from claudeops.commands import steward as cs


class RemoveLock(unittest.TestCase):
    def test_settings_delete_happens_while_lock_held(self):
        held = {"n": 0}
        events = []

        @contextlib.contextmanager
        def fake_lock(timeout=None):
            held["n"] += 1
            events.append("lock+")
            try:
                yield
            finally:
                held["n"] -= 1
                events.append("lock-")

        def fake_save(patch):
            events.append(("save", held["n"], patch))
            return {}
        root = tempfile.mkdtemp()
        paths = types.SimpleNamespace(root=root)
        with mock.patch.object(cs, "steward_ids", lambda: ["default", "x"]), \
                mock.patch.object(cs.sw, "brain_name_for", lambda sid: "brain_x"), \
                mock.patch.object(cs, "_project_running", lambda n: False), \
                mock.patch.object(cs.sw, "ownership_lock", fake_lock), \
                mock.patch.object(cs.sw, "load_projects", lambda sid: {}), \
                mock.patch.object(cs.sw, "paths_for", lambda sid: paths), \
                mock.patch.object(cs, "save_settings", fake_save), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cs.cmd_remove(types.SimpleNamespace(target_sid="x"))
        self.assertEqual(rc, 0)
        save = [e for e in events if isinstance(e, tuple)][0]
        self.assertEqual((save[1], save[2]), (1, {"stewards": {"x": None}}))      # kilit tutulurken
        self.assertFalse(os.path.isdir(root))                                     # dizin taşındı


if __name__ == "__main__":
    unittest.main()
