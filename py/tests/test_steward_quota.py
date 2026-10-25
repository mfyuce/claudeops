import datetime
import os
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward_quota as q  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
SAMPLE = """You are currently using your subscription to power your Claude Code usage

Current session: 0% used · resets Oct 25, 3:49pm (Europe/Istanbul)
Current week (all models): 79% used · resets Oct 26, 5:59pm (Europe/Istanbul)
Current week (Fable): 54% used · resets Oct 26, 5:59pm (Europe/Istanbul)
"""


def _ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


class ParseTest(unittest.TestCase):
    def test_parse_real_output(self):
        u = q.parse_usage(SAMPLE, _ts(2026, 10, 25, 11))
        self.assertEqual((u.week_pct, u.fable_pct, u.session_pct), (79.0, 54.0, 0.0))
        self.assertEqual(u.reset_ts, _ts(2026, 10, 26, 17, 59))

    def test_parse_unknown_format_is_none(self):
        self.assertIsNone(q.parse_usage("rate limited, try again", 0))
        self.assertIsNone(q.parse_usage("", 0))

    def test_reset_rolls_into_next_year(self):
        u = q.parse_usage("Current week (all models): 10% used · resets Jan 2, 6:00am (Europe/Istanbul)", _ts(2026, 12, 30, 10))
        self.assertEqual(u.reset_ts, _ts(2027, 1, 2, 6))


class DecideTest(unittest.TestCase):
    def usage(self, pct, reset=_ts(2026, 10, 26, 17, 59)):
        return q.Usage(week_pct=pct, reset_ts=reset)

    def test_off_and_unknown_never_act(self):
        now = _ts(2026, 10, 25, 11)
        self.assertEqual(q.decide({"mode": "off"}, self.usage(99), now, TZ).action, "ok")
        self.assertEqual(q.decide({"mode": "manual", "manual_limit": "50"}, None, now, TZ).action, "ok")
        self.assertEqual(q.decide({"mode": "manual", "manual_limit": "50"}, q.Usage(), now, TZ).action, "ok")

    def test_manual_stops_at_limit(self):
        now = _ts(2026, 10, 25, 11)
        cfg = {"mode": "manual", "manual_limit": "85"}
        self.assertEqual(q.decide(cfg, self.usage(84.9), now, TZ).action, "ok")
        d = q.decide(cfg, self.usage(85), now, TZ)
        self.assertEqual(d.action, "drain")
        self.assertIn("85", d.reason)

    def test_manual_three_tiers(self):
        now = _ts(2026, 10, 25, 11)
        cfg = {"mode": "manual", "manual_limit": "93", "shutdown_limit": "94", "final_limit": "95"}
        for used, want in ((92.9, "ok"), (93, "drain"), (93.9, "drain"), (94, "shutdown"), (94.9, "shutdown"), (95, "stop")):
            self.assertEqual(q.decide(cfg, self.usage(used), now, TZ).action, want, used)

    def test_manual_without_limit_only_final_acts(self):
        now = _ts(2026, 10, 25, 11)
        self.assertEqual(q.decide({"mode": "manual"}, self.usage(80), now, TZ).action, "ok")
        self.assertEqual(q.decide({"mode": "manual"}, self.usage(99), now, TZ).action, "stop")

    def test_auto_daily_cap_pacing(self):
        # sıfırlanma Pzt 17:59; hafta başı geçen Pzt 17:59. Pazar 11:00 = 6. gün: tavan 95*6/7 = 81.4
        sunday = _ts(2026, 10, 25, 11)
        cfg = {"mode": "auto", "final_limit": "95"}
        self.assertEqual(q.decide(cfg, self.usage(79), sunday, TZ).cap, 81.4)
        self.assertEqual(q.decide(cfg, self.usage(79), sunday, TZ).action, "ok")
        self.assertEqual(q.decide(cfg, self.usage(82), sunday, TZ).action, "drain")
        # 7. gün (Pazar 18:00 sonrası): tavan = son limit
        sunday_night = _ts(2026, 10, 25, 19)
        self.assertEqual(q.decide(cfg, self.usage(90), sunday_night, TZ).cap, 95.0)
        self.assertEqual(q.decide(cfg, self.usage(95), sunday_night, TZ).action, "stop")
        # 2. gün (Çarşamba 10:00; hafta Pzt 17:59 başlar): tavan 95*2/7 = 27.1
        wed = _ts(2026, 10, 21, 10)
        d = q.decide(cfg, self.usage(45), wed, TZ)
        self.assertEqual((d.action, d.cap), ("drain", 27.1))

    def test_per_weekday_override(self):
        wed = _ts(2026, 10, 21, 10)
        cfg = {"mode": "auto", "final_limit": "95", "day_wed": "60"}
        self.assertEqual(q.decide(cfg, self.usage(55), wed, TZ).action, "ok")
        self.assertEqual(q.decide(cfg, self.usage(60), wed, TZ).action, "drain")

    def test_day_after_monday_reset_is_tuesday(self):
        # Pzt 18:00 sıfırlanmasından sonraki 24 saat SALI; son dilim (Pazar 18:00-Pzt 18:00) PAZARTESİ
        reset = _ts(2026, 11, 2, 17, 59)       # gelecek Pzt 17:59
        u = self.usage(10, reset)
        self.assertEqual(q.day_label(u, _ts(2026, 10, 26, 20), TZ), "tue")
        self.assertEqual(q.day_label(u, _ts(2026, 10, 27, 20), TZ), "wed")
        self.assertEqual(q.day_label(u, _ts(2026, 11, 1, 20), TZ), "mon")
        cfg = {"mode": "auto", "final_limit": "95", "day_tue": "20"}
        self.assertEqual(q.decide(cfg, u, _ts(2026, 10, 26, 20), TZ).cap, 20.0)
        self.assertEqual(q.day_label(q.Usage(week_pct=1), _ts(2026, 10, 26, 20), TZ), "mon")    # sıfırlanma yok: takvim günü

    def test_auto_without_reset_has_no_cap(self):
        d = q.decide({"mode": "auto"}, q.Usage(week_pct=50), _ts(2026, 10, 21, 10), TZ)
        self.assertEqual((d.action, d.cap), ("ok", None))


if __name__ == "__main__":
    unittest.main()
