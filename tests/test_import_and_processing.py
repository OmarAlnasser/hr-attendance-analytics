"""Import validation, provenance, re-import without duplication, time zones, and daily processing."""
import unittest
from datetime import date, datetime

import pandas as pd

from hr_analytics.db import repos
from hr_analytics.pipeline.importer import import_punch_file
from hr_analytics.pipeline.processor import TRAILING_HOURS, process_attendance, range_for_batch
from hr_analytics.security.scope import UserContext

from .support import TempDirMixin, build_small_org, write_csv

AS_OF = datetime(2026, 4, 15, 12, 0)
HR = UserContext(0, "system", "hr", None)


class ImportTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ids = build_small_org(self.conn)

    def _import(self, path, **kw):
        return import_punch_file(self.conn, path, settings=self.settings, as_of=AS_OF, **kw)

    def punches(self):
        return self.conn.execute("SELECT COUNT(*) FROM raw_punches").fetchone()[0]

    def test_invalid_rows_are_quarantined_with_reasons(self):
        f = write_csv(self.tmp / "mixed.csv", [
            ("B002", "2026-03-02 07:58:00", "D1", "IN"),
            ("B002", "2026-03-02 16:04:00", "D1", "OUT"),
            ("B002", "2026-03-02 16:04:00", "D1", "OUT"),       # exact duplicate inside the file
            ("B999", "2026-03-02 08:00:00", "D1", "IN"),         # unknown badge
            ("", "2026-03-02 08:00:00", "D1", "IN"),             # missing badge
            ("B003", "02/03/2026 08:00", "D1", "IN"),            # not ISO
            ("B003", "2026-03-02", "D1", "IN"),                  # date only
            ("B003", "2027-01-01 08:00:00", "D1", "IN"),         # future relative to import time
            ("B003", "", "D1", "IN"),                            # missing time
        ])
        r = self._import(f)
        self.assertEqual(r.status, "partial")
        self.assertEqual((r.rows_total, r.rows_accepted, r.rows_duplicate, r.rows_rejected), (9, 2, 1, 6))
        self.assertEqual(r.reject_reasons, {"UNKNOWN_BADGE": 1, "MISSING_BADGE": 1, "INVALID_TIMESTAMP": 2,
                                            "FUTURE_TIMESTAMP": 1, "MISSING_TIMESTAMP": 1})
        rej = repos.batch_rejects(self.conn, r.batch_id)
        self.assertEqual(len(rej), 6)
        self.assertTrue(all(x["raw_data"] and x["reason_detail"] for x in rej), "original row and reason kept")
        b = repos.get_batch(self.conn, r.batch_id)
        self.assertTrue(b["stored_path"] and b["file_sha256"], "provenance: stored copy and file hash")
        raw = self.conn.execute("SELECT punch_time_raw, source_row, batch_id FROM raw_punches ORDER BY punch_id").fetchall()
        self.assertEqual([tuple(x) for x in raw], [("2026-03-02 07:58:00", 1, r.batch_id),
                                                   ("2026-03-02 16:04:00", 2, r.batch_id)])

    def test_same_file_twice_is_refused(self):
        f = write_csv(self.tmp / "a.csv", [("B002", "2026-03-02 07:58:00", "D1", "IN")])
        self.assertEqual(self._import(f).status, "success")
        again = self._import(f)
        self.assertEqual(again.status, "duplicate_file")
        self.assertEqual(self.punches(), 1)

    def test_overlapping_file_does_not_duplicate_punches(self):
        write_csv(self.tmp / "a.csv", [("B002", "2026-03-02 07:58:00", "D1", "IN"),
                                       ("B002", "2026-03-02 16:04:00", "D1", "OUT")])
        write_csv(self.tmp / "b.csv", [("B002", "2026-03-02 07:58:00", "D1", "IN"),     # already stored
                                       ("B002", "2026-03-02 16:04:00", "D1", "OUT"),    # already stored
                                       ("B002", "2026-03-03 07:55:00", "D1", "IN")])    # new
        self._import(self.tmp / "a.csv")
        r = self._import(self.tmp / "b.csv")
        self.assertEqual((r.status, r.rows_accepted, r.rows_duplicate), ("success", 1, 2))
        self.assertEqual(self.punches(), 3)

    def test_timezones(self):
        f = write_csv(self.tmp / "tz.csv", [("B002", "2026-03-02T05:05:00Z", "D1", "IN"),          # UTC -> 08:05
                                            ("B002", "2026-03-02T16:00:00+03:00", "D1", "OUT"),     # already local
                                            ("B003", "2026-03-02 05:10:00", "D2", "IN")])           # naive, file tz UTC
        r = self._import(f, source_timezone="UTC")
        self.assertEqual(r.status, "success")
        local = [x[0] for x in self.conn.execute("SELECT punch_time_local FROM raw_punches ORDER BY punch_id")]
        self.assertEqual(local, ["2026-03-02 08:05:00", "2026-03-02 16:00:00", "2026-03-02 08:10:00"])

    def test_unknown_timezone_fails_cleanly(self):
        f = write_csv(self.tmp / "x.csv", [("B002", "2026-03-02 07:58:00", "D1", "IN")])
        r = self._import(f, source_timezone="Mars/Olympus")
        self.assertEqual((r.status, r.batch_id), ("failed", None))

    def test_excel_with_alternative_headers(self):
        df = pd.DataFrame({"Badge No": ["B002", "B002"], "Date Time": ["2026-03-02 07:58:00", "2026-03-02 16:01:00"],
                           "Terminal": ["GATE", "GATE"], "State": ["C/In", "C/Out"]})
        path = self.tmp / "device.xlsx"
        df.to_excel(path, index=False)
        r = self._import(path)
        self.assertEqual((r.status, r.rows_accepted), ("success", 2))
        self.assertEqual(self.conn.execute("SELECT DISTINCT device_id FROM raw_punches").fetchone()[0], "GATE")

    def test_missing_required_column_fails(self):
        path = write_csv(self.tmp / "bad.csv", [("B002", "x")], header=("badge_id", "comment"))
        r = self._import(path)
        self.assertEqual(r.status, "failed")
        self.assertEqual(self.punches(), 0)


class ProcessingTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ids = build_small_org(self.conn)
        rows = [
            ("B002", "2026-03-02 08:10:00"), ("B002", "2026-03-02 16:02:00"),   # Mon on time
            ("B002", "2026-03-03 08:31:00"),                                   # Tue single punch, late
            # Wed 03-04: absent
            ("B005", "2026-03-01 21:57:00"), ("B005", "2026-03-02 06:04:00"),   # Sun night shift across midnight
            ("B006", "2026-03-09 08:00:00"), ("B006", "2026-03-09 16:00:00"),   # before hire (hired 03-10)
            ("B007", "2026-03-08 08:00:00"), ("B007", "2026-03-08 16:00:00"),   # after termination (03-05)
        ]
        write_csv(self.tmp / "march.csv", [(b, t, "D1", "") for b, t in rows])
        self.batch = import_punch_file(self.conn, self.tmp / "march.csv", settings=self.settings, as_of=AS_OF)

    def process(self, start="2026-03-01", end="2026-03-12", **kw):
        return process_attendance(self.conn, date.fromisoformat(start), date.fromisoformat(end),
                                  settings=self.settings, as_of=AS_OF, **kw)

    def row(self, code, d):
        r = self.conn.execute("SELECT a.* FROM attendance_daily a JOIN employees e USING(employee_id) "
                              "WHERE e.employee_code = ? AND a.shift_date = ?", (code, d)).fetchone()
        return dict(r) if r else None

    def test_daily_statuses(self):
        self.process()
        self.assertEqual(self.row("E002", "2026-03-02")["status"], "present")
        tue = self.row("E002", "2026-03-03")
        self.assertEqual((tue["status"], tue["is_late"], tue["late_minutes"]), ("incomplete", 1, 31))
        self.assertEqual(self.row("E002", "2026-03-04")["status"], "absent")
        self.assertEqual(self.row("E002", "2026-03-06")["status"], "day_off")

    def test_night_shift_assigned_to_start_date(self):
        self.process()
        sun = self.row("E005", "2026-03-01")
        self.assertEqual((sun["status"], sun["punch_count"]), ("present", 2))
        self.assertEqual(self.row("E005", "2026-03-02")["status"], "absent", "Monday night has no punches")

    def test_days_outside_employment_have_no_rows_and_punches_are_reported(self):
        self.process()
        self.assertIsNone(self.row("E006", "2026-03-09"))
        self.assertEqual(self.row("E006", "2026-03-10")["status"], "absent")
        self.assertIsNone(self.row("E007", "2026-03-08"))
        self.assertIsNotNone(self.row("E007", "2026-03-05"))
        reasons = [r[0] for r in self.conn.execute("SELECT reason FROM punch_exceptions")]
        self.assertEqual(reasons.count("outside_employment"), 4)

    def test_holiday_and_leave_are_excluded_from_expected_days(self):
        self.conn.execute("INSERT INTO holidays(holiday_date, name) VALUES ('2026-03-04', 'Test holiday')")
        repos.insert_leave(self.conn, self.ids["E003"], "annual", "2026-03-02", "2026-03-03", "approved", None)
        repos.insert_leave(self.conn, self.ids["E003"], "annual", "2026-03-05", "2026-03-05", "pending", None)
        self.conn.commit()
        self.process()
        self.assertEqual(self.row("E002", "2026-03-04")["status"], "holiday")
        self.assertEqual(self.row("E003", "2026-03-02")["status"], "leave")
        self.assertEqual(self.row("E003", "2026-03-05")["status"], "absent", "pending leave is not approved leave")

    def test_reprocessing_is_idempotent(self):
        self.process()
        first = self.conn.execute("SELECT employee_id, shift_date, status, late_minutes FROM attendance_daily "
                                  "ORDER BY 1, 2").fetchall()
        self.process()
        self.process("2026-03-02", "2026-03-04")
        second = self.conn.execute("SELECT employee_id, shift_date, status, late_minutes FROM attendance_daily "
                                   "ORDER BY 1, 2").fetchall()
        self.assertEqual([tuple(r) for r in first], [tuple(r) for r in second])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM punch_exceptions").fetchone()[0], 4)

    def test_absence_waits_for_shift_end(self):
        process_attendance(self.conn, date(2026, 3, 11), date(2026, 3, 11), settings=self.settings,
                           as_of=datetime(2026, 3, 11, 12, 0))
        self.assertEqual(self.row("E002", "2026-03-11")["status"], "pending")

    def test_batch_range_ignores_trailing_night_clock_outs(self):
        self.assertEqual(TRAILING_HOURS, 8)
        self.assertEqual(range_for_batch("2026-03-01 07:50:00", "2026-04-01 06:05:00"),
                         (date(2026, 3, 1), date(2026, 3, 31)))
        self.assertEqual(range_for_batch("2026-03-01 07:50:00", "2026-03-31 22:05:00"),
                         (date(2026, 3, 1), date(2026, 3, 31)))
        # the previous day is included only when an earlier batch already holds its punches
        self.assertEqual(range_for_batch("2026-03-02 05:00:00", "2026-03-05 16:00:00", self.conn, None)[0],
                         date(2026, 3, 1))
        self.assertEqual(range_for_batch("2026-03-02 05:00:00", "2026-03-05 16:00:00", self.conn,
                                         self.batch.batch_id)[0], date(2026, 3, 2))

    def test_scoped_frames_respect_roles(self):
        self.process()
        from hr_analytics.security.scope import load_user_context
        mgr = load_user_context(self.conn, self.ids["user_mgr_ops"])
        emp = load_user_context(self.conn, self.ids["user_emp_it"])
        ops = {self.ids[c] for c in ("E001", "E002", "E005", "E006", "E007")}
        self.assertEqual(set(repos.attendance_frame(self.conn, mgr, "2026-03-01", "2026-03-12").employee_id), ops)
        self.assertEqual(set(repos.attendance_frame(self.conn, emp, "2026-03-01", "2026-03-12").employee_id),
                         {self.ids["E003"]})
        # asking for another department through the filter still returns nothing
        self.assertTrue(repos.attendance_frame(self.conn, mgr, "2026-03-01", "2026-03-12",
                                               department_id=self.ids["IT"]).empty)


if __name__ == "__main__":
    unittest.main()
