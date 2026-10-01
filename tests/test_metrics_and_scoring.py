"""Denominators, zero-division handling, weights and weighted scores."""
import unittest
from datetime import date

import pandas as pd

from hr_analytics.domain.metrics import (attendance_kpis, evaluable_employee_months, grouped_attendance_kpis,
                                         performance_kpis, safe_div)
from hr_analytics.domain.scoring import (DEFAULT_WEIGHTS, parse_period, shift_period, validate_period_for_employee,
                                         validate_scores, validate_weights, weighted_score)


def frame(rows):
    return pd.DataFrame(rows, columns=["employee_id", "status", "is_late", "late_minutes", "span_minutes",
                                       "early_leave_minutes", "department"])


class AttendanceKpiTests(unittest.TestCase):
    def setUp(self):
        self.df = frame([
            (1, "present", 0, 0, 480, 0, "A"), (1, "present", 1, 20, 470, 0, "A"), (1, "absent", 0, 0, None, 0, "A"),
            (1, "leave", 0, 0, None, 0, "A"), (1, "holiday", 0, 0, None, 0, "A"), (1, "day_off", 0, 0, None, 0, "A"),
            (2, "incomplete", 1, 40, None, 0, "A"), (2, "pending", 0, 0, None, 0, "A"),
            (2, "unscheduled_work", 0, 0, 240, 0, "A"),
        ])

    def test_denominators(self):
        k = attendance_kpis(self.df)
        self.assertEqual((k["expected_days"], k["attended_days"], k["absent_days"]), (4, 3, 1))
        self.assertAlmostEqual(k["attendance_rate"], 3 / 4)
        self.assertAlmostEqual(k["absence_rate"], 1 / 4)
        self.assertAlmostEqual(k["late_rate"], 2 / 3, msg="late rate is over attended days")
        self.assertAlmostEqual(k["incomplete_rate"], 1 / 3)
        self.assertAlmostEqual(k["avg_late_minutes"], 30.0)
        self.assertAlmostEqual(k["avg_presence_span_hours"], 475 / 60, msg="span only from present days")
        self.assertEqual((k["leave_days"], k["holiday_days"], k["pending_days"], k["unscheduled_days"]), (1, 1, 1, 1))

    def test_late_flag_on_non_attended_rows_is_ignored(self):
        k = attendance_kpis(frame([(1, "absent", 1, 30, None, 0, "A"), (1, "present", 0, 0, 480, 0, "A")]))
        self.assertEqual((k["late_days"], k["late_rate"]), (0, 0.0))

    def test_zero_denominators_give_blank_not_zero(self):
        k = attendance_kpis(frame([(1, "leave", 0, 0, None, 0, "A"), (1, "holiday", 0, 0, None, 0, "A")]))
        for key in ("attendance_rate", "absence_rate", "late_rate", "incomplete_rate", "avg_late_minutes",
                    "avg_presence_span_hours"):
            self.assertIsNone(k[key], key)
        self.assertIsNone(attendance_kpis(frame([]))["attendance_rate"])
        self.assertIsNone(safe_div(5, 0))

    def test_group_rates_are_pooled_over_days(self):
        df = frame([(1, "present", 0, 0, 480, 0, "Big")] * 99 + [(2, "absent", 0, 0, None, 0, "Big")] +
                   [(3, "absent", 0, 0, None, 0, "Small")])
        g = grouped_attendance_kpis(df, "department").set_index("department")
        self.assertAlmostEqual(g.loc["Big", "attendance_rate"], 0.99)
        self.assertEqual(g.loc["Small", "attendance_rate"], 0.0)
        self.assertEqual(g.loc["Big", "employees"], 2)


class ScoringTests(unittest.TestCase):
    def test_default_weights_sum_to_100(self):
        self.assertEqual(validate_weights(DEFAULT_WEIGHTS), [])
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 100)

    def test_weights_must_sum_to_100(self):
        w = dict(DEFAULT_WEIGHTS, teamwork=25)
        self.assertTrue(any("100" in e for e in validate_weights(w)))
        self.assertTrue(validate_weights(dict(DEFAULT_WEIGHTS, teamwork=-5, task_completion=60)))
        self.assertTrue(validate_weights(dict(DEFAULT_WEIGHTS, teamwork="x")))
        self.assertTrue(validate_weights({"punctuality": 100}))

    def test_weighted_score(self):
        scores = {"punctuality": 5, "communication": 3, "task_completion": 4, "teamwork": 2}
        # 5*25 + 3*20 + 4*35 + 2*20 = 365 -> 3.65
        self.assertAlmostEqual(weighted_score(scores, DEFAULT_WEIGHTS), 3.65)
        self.assertAlmostEqual(weighted_score({k: 1 for k in scores}, DEFAULT_WEIGHTS), 1.0)
        self.assertAlmostEqual(weighted_score({k: 5 for k in scores}, DEFAULT_WEIGHTS), 5.0)

    def test_score_validation(self):
        ok = {"punctuality": "3", "communication": 4, "task_completion": "5", "teamwork": 1}
        self.assertEqual(validate_scores(ok), [])
        for bad in (0, 6, "3.5", "", None, "a"):
            self.assertTrue(validate_scores(dict(ok, teamwork=bad)), bad)

    def test_periods(self):
        self.assertEqual(parse_period("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(shift_period("2026-01", -1), "2025-12")
        for bad in ("2026-13", "2026-1", "26-01", "2026/01"):
            with self.assertRaises(ValueError):
                parse_period(bad)

    def test_evaluation_period_must_fit_employment(self):
        today = date(2026, 4, 15)
        self.assertEqual(validate_period_for_employee("2026-03", "2024-01-01", None, today), [])
        self.assertTrue(validate_period_for_employee("2026-05", "2024-01-01", None, today))          # future
        self.assertTrue(validate_period_for_employee("2026-03", "2026-04-01", None, today))          # not joined
        self.assertTrue(validate_period_for_employee("2026-03", "2024-01-01", "2026-02-27", today))  # already left


class PerformanceKpiTests(unittest.TestCase):
    def test_coverage_and_low_score_rate(self):
        ev = pd.DataFrame({"weighted_score": [2.5, 3.0, 4.2, 3.9]})
        k = performance_kpis(ev, 5, threshold=3.0)
        self.assertAlmostEqual(k["coverage"], 0.8)
        self.assertEqual(k["low_score_count"], 1, "3.0 is not below a threshold of 3.0")
        self.assertAlmostEqual(k["low_score_rate"], 0.25)

    def test_no_evaluations(self):
        k = performance_kpis(pd.DataFrame({"weighted_score": []}), 0, 3.0)
        self.assertIsNone(k["coverage"])
        self.assertIsNone(k["avg_weighted_score"])

    def test_evaluable_employee_months(self):
        emps = pd.DataFrame({"hire_date": ["2024-01-01", "2026-03-25", "2026-03-20", "2024-01-01", "2026-04-02"],
                             "termination_date": [None, None, None, "2026-03-05", None]})
        # full month; 7 days (no); 12 days (yes); 5 days (no); not yet hired (no)
        self.assertEqual(evaluable_employee_months(emps, date(2026, 3, 1), date(2026, 3, 31)), 2)


if __name__ == "__main__":
    unittest.main()


class GroupedKpiEquivalenceTests(unittest.TestCase):
    """The vectorised grouped_attendance_kpis must agree with attendance_kpis() run per group."""

    def test_matches_per_group_computation(self):
        import numpy as np
        import pandas as pd
        from hr_analytics.domain.metrics import attendance_kpis, grouped_attendance_kpis
        rng = np.random.default_rng(7)
        n = 600
        statuses = ["present", "incomplete", "absent", "leave", "holiday", "day_off", "pending", "unscheduled_work"]
        df = pd.DataFrame({
            "employee_id": rng.integers(1, 25, n),
            "department_id": rng.integers(1, 4, n),
            "status": rng.choice(statuses, n),
            "is_late": rng.integers(0, 2, n),
            "late_minutes": rng.integers(0, 90, n),
            "early_leave_minutes": rng.choice([0, 0, 0, 12, 40], n),
            "span_minutes": rng.choice([np.nan, 300, 480, 510], n),
        })
        df.loc[df.status.isin(["absent", "leave", "holiday", "day_off"]), ["is_late", "late_minutes"]] = 0
        for by in ("employee_id", ["department_id"], ["department_id", "employee_id"]):
            fast = grouped_attendance_kpis(df, by).to_dict("records")
            keys = [by] if isinstance(by, str) else by
            slow = []
            for key, part in df.groupby(keys, sort=True):
                k = attendance_kpis(part)
                k.update(dict(zip(keys, key if isinstance(key, tuple) else (key,))))
                slow.append(k)
            self.assertEqual(len(fast), len(slow))
            for a, b in zip(fast, slow):
                self.assertEqual(set(a), set(b))
                for col in a:
                    na = a[col] is None or (isinstance(a[col], float) and a[col] != a[col])   # NaN in a DataFrame
                    nb = b[col] is None
                    if na or nb:
                        self.assertEqual(na, nb, (by, col))
                    else:
                        self.assertAlmostEqual(float(a[col]), float(b[col]), places=9, msg=(by, col))
