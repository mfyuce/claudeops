"""`layout` pencere sıralaması: `host:ad` başlığında sıralamayı yalnız `ad` belirler (stdlib unittest).

Çalıştırma:  python3 py/tests/test_layout_order.py -v

Kullanıcı notu (2026-10-13): "pencere sıralaması isme göre, remote ismi varsa `yuhem:ae2026..` gibi iki
noktadan sonrası için sıralama olsun. `yuhem` sıralama için kullanılmasın. Böylece aynı isimler aynı yere
toplanır." Eskiden `sorted()` başlığın TAMAMINA bakıyordu: önce tüm yerel adlar, sonra tüm `ulak_31:*`,
sonra tüm `yuhem:*`; yerelde `hittite…` ile `yuhem:hittite…` ayrı desktop'lara düşüyordu.

Gerçek pencere taşımaz, `wmctrl`/`xdotool` çağırmaz: `build_layout_plan` saf bir hesap.
"""
import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.layout import ScreenGeometry, _layout_sort_key, build_layout_plan  # noqa: E402

SCREEN = ScreenGeometry(0, 0, 1920, 1080, cols=2, rows=2)  # desktop başına 4 pencere


def placed(titles, pinned=None, groups=None):
    """Planı [(ad, desktop)] olarak, ekranda okunan sırayla (desktop, satır, sütun) döndür."""
    windows = {f"0x{i:x}": t for i, t in enumerate(titles, 1)}
    plan, name_to_wid = build_layout_plan(
        windows, SCREEN, pinned_names=pinned, groups=groups, claude_only=True, known_names=set(titles))
    wid_to_name = {w: n for n, w in name_to_wid.items()}
    rows = sorted(plan.assignments, key=lambda a: (a[1], a[3], a[2]))
    return [(wid_to_name[wid], ws) for wid, ws, _x, _y in rows]


def names(titles, **kw):
    return [n for n, _ws in placed(titles, **kw)]


class SortKeyTests(unittest.TestCase):
    def test_bare_name_sorts_by_itself_with_an_empty_host(self):
        self.assertEqual(_layout_sort_key("hittite20260917"), ("hittite20260917", ""))

    def test_mirror_title_sorts_by_the_part_after_the_colon(self):
        self.assertEqual(_layout_sort_key("yuhem:hittite20260924"), ("hittite20260924", "yuhem"))

    def test_underscores_in_host_and_name_are_kept(self):
        self.assertEqual(_layout_sort_key("ulak_31:shell_ulak20261002_1"), ("shell_ulak20261002_1", "ulak_31"))


class SingleWindowOrderTests(unittest.TestCase):
    def test_host_prefix_does_not_cluster_windows_by_host(self):
        # eski davranış: c, f, ulak_31:b, ulak_31:d, yuhem:a, yuhem:e
        self.assertEqual(
            names(["ulak_31:b", "yuhem:a", "c", "ulak_31:d", "yuhem:e", "f"]),
            ["yuhem:a", "ulak_31:b", "c", "ulak_31:d", "yuhem:e", "f"])

    def test_same_name_on_different_hosts_lands_side_by_side(self):
        got = placed(["hittite20260917", "yuhem:hittite20260924", "ulak_31:japigw",
                      "japigw20260924", "luwian20260923", "yuhem:luwian20260924"])
        self.assertEqual(got, [
            ("hittite20260917", 1), ("yuhem:hittite20260924", 1),
            ("ulak_31:japigw", 1), ("japigw20260924", 1),
            ("luwian20260923", 2), ("yuhem:luwian20260924", 2)])

    def test_equal_names_put_the_local_window_first_then_hosts_alphabetically(self):
        self.assertEqual(
            names(["yuhem:mgw", "ulak_31:mgw", "mgw", "local:mgw"]),
            ["mgw", "local:mgw", "ulak_31:mgw", "yuhem:mgw"])

    def test_a_longer_name_still_follows_its_own_prefix(self):
        # `shell` < `shell20261006` < `shell_yuhem` (rakam, `_`'den önce); host sıralamayı değiştirmez
        self.assertEqual(
            names(["yuhem:shell_yuhem", "shell20261006", "shell"]),
            ["shell", "shell20261006", "yuhem:shell_yuhem"])

    def test_result_does_not_depend_on_the_window_enumeration_order(self):
        titles = ["yuhem:mgw", "mgw", "ulak_31:mgw", "ulak_31:abc", "zed"]
        want = names(titles)
        for perm in itertools.permutations(titles):
            self.assertEqual(names(list(perm)), want, perm)


class PinsAndGroupsAreUntouchedTests(unittest.TestCase):
    def test_pinned_windows_still_take_desktop_zero_before_the_sorted_rest(self):
        got = placed(["aaa", "yuhem:shell_yuhem", "ulak_31:bbb"], pinned=["yuhem:shell_yuhem"])
        self.assertEqual(got, [("yuhem:shell_yuhem", 0), ("aaa", 1), ("ulak_31:bbb", 1)])

    def test_group_members_still_come_before_the_sorted_singles(self):
        got = names(["zzz", "hc20261001", "aaa", "yuhem:bbb"], groups=[["hc"]])
        self.assertEqual(got, ["hc20261001", "aaa", "yuhem:bbb", "zzz"])


if __name__ == "__main__":
    unittest.main()
