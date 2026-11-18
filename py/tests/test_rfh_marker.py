import unittest
from claudeops.needs_ho import rfh_marker_in


class RfhMarkerTests(unittest.TestCase):
    def test_prose_mention_is_not_a_marker(self):
        self.assertFalse(rfh_marker_in("X başlığı `READY FOR HANDOVER` arıyor"))
        self.assertFalse(rfh_marker_in("`## READY FOR HANDOVER` başlığı geçti"))
        self.assertFalse(rfh_marker_in("cevap READY FOR HANDOVER ile biter"))

    def test_heading_and_bare_line_count(self):
        self.assertTrue(rfh_marker_in("iş\n## READY FOR HANDOVER (18 Kas)\n- x"))
        self.assertTrue(rfh_marker_in("**READY FOR HANDOVER**"))
        self.assertTrue(rfh_marker_in("  READY FOR HANDOVER"))

    def test_code_block_and_quote_do_not_count(self):
        self.assertFalse(rfh_marker_in("```\nREADY FOR HANDOVER\n```"))
        self.assertFalse(rfh_marker_in("> READY FOR HANDOVER"))


if __name__ == "__main__":
    unittest.main()
