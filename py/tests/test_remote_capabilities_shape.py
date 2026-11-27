"""Uzak `/api/session/facts` `capabilities` alanı güvenilmez (TBD#372): dizi değilse boş, metin olmayan öğe atılır.
Gerçek ağ/uzak host YOK; `ws._remote` sahte."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class CapabilitiesShapeTest(unittest.TestCase):
    def probe(self, capabilities):
        reply = {"ok": True, "api": 1, "capabilities": capabilities, "sessions": {}}
        with mock.patch.dict(ws._CAPS, clear=True), \
                mock.patch.object(ws, "_remote", mock.Mock(get=lambda *a, **k: (reply, 200))):
            caps, facts = ws._probe_facts("far", [], 1.0, now=1000.0)
            self.assertEqual(ws._caps_cached("far", 1000.0), caps)
        self.assertEqual((caps["api"], facts), (1, {}))
        return caps["capabilities"]

    def test_text_is_not_split_into_characters(self):
        self.assertEqual(self.probe("exact_target"), [])

    def test_other_non_list_values_are_empty_and_do_not_raise(self):
        for wrong in (5, 1.5, True, {"exact_target": 1}, None):
            self.assertEqual(self.probe(wrong), [], wrong)

    def test_non_text_items_are_dropped(self):
        self.assertEqual(self.probe(["exact_target", 5, None, ["x"], "facts"]), ["exact_target", "facts"])


if __name__ == "__main__":
    unittest.main()
