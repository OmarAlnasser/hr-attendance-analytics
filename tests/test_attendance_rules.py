"""Core attendance rules: grace boundaries, holidays, leave, night shifts, missing punches, absence timing."""
import unittest
from datetime import date, datetime, time

from hr_analytics.domain.attendance_rules import RuleConfig, ShiftDef, collapse_punches, evaluate_day, validate_shift

SUN_THU = frozenset({6, 0, 1, 2, 3})           # date.weekday(): Mon=0 ... Sun=6
DAY = ShiftDef(1, "DAY", time(8, 0), time(16, 0), 15, 5, SUN_THU)
NIGHT = ShiftDef(2, "NIGHT", time(22, 0), time(6, 0), 15, 5, SUN_THU)
CFG = RuleConfig()
MON = date(2026, 3, 2)                          # a Monday (working day)
FRI = date(2026, 3, 6)                          # a Friday (day off)
LATER = datetime(2026, 4, 1)                    # "now" well after the shifts


def dt(d: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, ss)


def day(punches, d=MON, shift=DAY, as_of=LATER, cfg=CFG, **kw):
    return evaluate_day(d, shift, punches, as_of=as_of, cfg=cfg, **kw)


class GraceBoundaryTests(unittest.TestCase):
    def test_exactly_at_grace_end_is_on_time(self):
        r = day([dt(MON, 8, 15), dt(MON, 16, 5)])
        self.assertEqual((r["status"], r["is_late"], r["late_minutes"]), ("present", 0, 0))

    def test_seconds_within_the_grace_minute_are_on_time(self):
        r = day([dt(MON, 8, 15, 59), dt(MON, 16, 5)])
        self.assertEqual(r["is_late"], 0, "minute resolution: 08:15:59 counts as 08:15")

    def test_one_minute_after_grace_is_late_counted_from_start(self):
        r = day([dt(MON, 8, 16), dt(MON, 16, 5)])
        self.assertEqual((r["is_late"], r["late_minutes"]), (1, 16))

    def test_late_minutes_can_be_counted_from_grace_end(self):
        cfg = RuleConfig(late_minutes_from="grace_end")
        r = day([dt(MON, 8, 16), dt(MON, 16, 5)], cfg=cfg)
        self.assertEqual((r["is_late"], r["late_minutes"]), (1, 1))

    def test_zero_grace(self):
        strict = ShiftDef(3, "STRICT", time(8), time(16), 0, 0, SUN_THU)
        self.assertEqual(day([dt(MON, 8, 0, 59), dt(MON, 16, 0)], shift=strict)["is_late"], 0)
        self.assertEqual(day([dt(MON, 8, 1), dt(MON, 16, 0)], shift=strict)["late_minutes"], 1)

    def test_early_leave_uses_its_own_grace(self):
        self.assertEqual(day([dt(MON, 7, 55), dt(MON, 15, 55)])["early_leave_minutes"], 0)   # within 5 min
        self.assertEqual(day([dt(MON, 7, 55), dt(MON, 15, 50)])["early_leave_minutes"], 10)


class CalendarTests(unittest.TestCase):
    def test_holiday_without_punches_is_holiday(self):
        self.assertEqual(day([], holiday_name="National Day")["status"], "holiday")

    def test_work_on_a_holiday_is_unscheduled_work(self):
        self.assertEqual(day([dt(MON, 8), dt(MON, 16)], holiday_name="National Day")["status"], "unscheduled_work")

    def test_approved_leave_wins_even_with_punches(self):
        r = day([dt(MON, 8), dt(MON, 16)], leave_type="annual")
        self.assertEqual((r["status"], r["leave_type"], r["is_late"]), ("leave", "annual", 0))
        self.assertIn("punches_on_approved_leave", r["notes"])

    def test_leave_without_punches(self):
        self.assertEqual(day([], leave_type="sick")["status"], "leave")

    def test_weekend(self):
        self.assertEqual(day([], d=FRI)["status"], "day_off")
        self.assertEqual(day([dt(FRI, 9), dt(FRI, 13)], d=FRI)["status"], "unscheduled_work")


class MissingPunchAndTimingTests(unittest.TestCase):
    def test_absence_only_after_shift_end(self):
        self.assertEqual(day([], as_of=dt(MON, 15, 59))["status"], "pending")
        self.assertEqual(day([], as_of=dt(MON, 16, 0))["status"], "absent")

    def test_single_punch_near_start_is_incomplete_missing_out_and_can_be_late(self):
        r = day([dt(MON, 8, 30)])
        self.assertEqual((r["status"], r["is_late"], r["late_minutes"]), ("incomplete", 1, 30))
        self.assertIn("missing_out_punch", r["notes"])
        self.assertIsNone(r["span_minutes"])

    def test_single_punch_near_end_is_missing_in_and_never_late(self):
        r = day([dt(MON, 16, 2)])
        self.assertEqual((r["status"], r["is_late"]), ("incomplete", 0))
        self.assertIn("missing_in_punch", r["notes"])

    def test_single_punch_while_shift_running_is_pending(self):
        self.assertEqual(day([dt(MON, 7, 58)], as_of=dt(MON, 12, 0))["status"], "pending")

    def test_near_duplicate_punches_collapse(self):
        r = day([dt(MON, 7, 58), dt(MON, 7, 59)])
        self.assertEqual((r["raw_punch_count"], r["punch_count"], r["status"]), (2, 1, "incomplete"))
        self.assertEqual(len(collapse_punches([dt(MON, 8), dt(MON, 8, 1, 59), dt(MON, 8, 2)], 2)), 2)

    def test_span_is_first_to_last_punch(self):
        r = day([dt(MON, 7, 50), dt(MON, 12, 0), dt(MON, 16, 20)])
        self.assertEqual((r["status"], r["span_minutes"], r["first_punch"][11:16], r["last_punch"][11:16]),
                         ("present", 510, "07:50", "16:20"))


class NightShiftTests(unittest.TestCase):
    def test_night_shift_belongs_to_start_date(self):
        r = day([dt(MON, 21, 55), dt(date(2026, 3, 3), 6, 3)], shift=NIGHT)
        self.assertEqual((r["shift_date"], r["status"], r["is_late"]), ("2026-03-02", "present", 0))
        self.assertEqual(r["scheduled_end"], "2026-03-03 06:00:00")
        self.assertEqual(r["span_minutes"], 8 * 60 + 8)

    def test_night_shift_late_after_midnight_start_offset(self):
        r = day([dt(MON, 22, 20), dt(date(2026, 3, 3), 6, 0)], shift=NIGHT)
        self.assertEqual((r["is_late"], r["late_minutes"]), (1, 20))

    def test_night_shift_is_pending_until_next_morning(self):
        self.assertEqual(day([], shift=NIGHT, as_of=dt(date(2026, 3, 3), 5, 59))["status"], "pending")
        self.assertEqual(day([], shift=NIGHT, as_of=dt(date(2026, 3, 3), 6, 0))["status"], "absent")

    def test_thursday_night_shift_is_a_working_day(self):
        thu = date(2026, 3, 5)
        self.assertEqual(day([dt(thu, 22), dt(date(2026, 3, 6), 6)], d=thu, shift=NIGHT)["status"], "present")


class ShiftValidationTests(unittest.TestCase):
    def test_default_shifts_are_valid(self):
        self.assertEqual(validate_shift(DAY, CFG), [])
        self.assertEqual(validate_shift(NIGHT, CFG), [])

    def test_windows_that_would_overlap_are_rejected(self):
        long = ShiftDef(9, "LONG", time(6), time(21), 15, 5, SUN_THU)   # 15 h + 4 h + 6 h >= 24 h
        self.assertTrue(any("overlap" in e for e in validate_shift(long, CFG)))

    def test_grace_longer_than_shift_is_rejected(self):
        short = ShiftDef(9, "S", time(8), time(8, 30), 45, 0, SUN_THU)
        self.assertTrue(validate_shift(short, CFG))


if __name__ == "__main__":
    unittest.main()
