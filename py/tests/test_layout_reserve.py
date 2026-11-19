"""`layout --reserve N`: her desktop'ta SON N yuva boş kalır (2x2'de 1 = sağ alt köşe). Saf hesap, pencere taşımaz."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.layout import ScreenGeometry, build_layout_plan  # noqa: E402

SCREEN = ScreenGeometry(0, 0, 1920, 1080, cols=2, rows=2)
TITLES = [f"s{i}" for i in range(1, 8)]          # 7 pencere


def plan(reserve=0, pinned=None):
    windows = {f"0x{i:x}": t for i, t in enumerate(TITLES, 1)}
    p, _ = build_layout_plan(windows, SCREEN, pinned_names=pinned, claude_only=True, known_names=set(TITLES), reserve=reserve)
    return p.assignments


class Reserve(unittest.TestCase):
    def test_default_unchanged_fills_all_four_slots(self):
        a = plan()
        self.assertEqual([ws for _w, ws, _x, _y in a], [1, 1, 1, 1, 2, 2, 2])
        self.assertIn((SCREEN.quad_w, SCREEN.quad_h), {(x, y) for _w, _s, x, y in a})   # sağ alt yuva kullanılıyor

    def test_reserve_one_never_uses_bottom_right(self):
        a = plan(reserve=1)
        self.assertEqual([ws for _w, ws, _x, _y in a], [1, 1, 1, 2, 2, 2, 3])            # 3 pencere/desktop
        self.assertNotIn((SCREEN.quad_w, SCREEN.quad_h), {(x, y) for _w, _s, x, y in a})

    def test_reserve_never_leaves_zero_slots(self):
        a = plan(reserve=9)
        self.assertEqual(len({ws for _w, ws, _x, _y in a}), 7)                           # en az 1 yuva: desktop başına 1

    def test_pinned_respects_reserve(self):
        a = plan(reserve=1, pinned=["s1", "s2", "s3", "s4"])
        self.assertEqual(sum(1 for _w, ws, _x, _y in a if ws == 0), 3)                  # ws0'a en çok 3 sabit


if __name__ == "__main__":
    unittest.main()
