"""Full path with the documented commands: generate -> seed -> import -> process -> evaluate in the web app
-> monthly PDF (duplicate protection) -> Power BI export reconciled with the app's KPI functions."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from hr_analytics.cli import cli
from hr_analytics.config import Settings
from hr_analytics.db import repos
from hr_analytics.db.connection import connect
from hr_analytics.domain.metrics import attendance_kpis
from hr_analytics.domain.scoring import parse_period
from hr_analytics.security.scope import UserContext
from hr_analytics.web import create_app

from .support import HASH_METHOD, PG_URL, login, pg_create_schema, pg_drop_schema, pg_schema_url, token

PW = "e2e-demo-password"


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        t = Path(cls._tmp.name)
        cls.env = {
            "HR_SECRET_KEY": "e2e-secret", "HR_TESTING": "1", "HR_DATABASE_PATH": str(t / "e2e.sqlite3"),
            "HR_INSTANCE_DIR": str(t / "instance"), "HR_DATA_DIR": str(t / "data"),
            "HR_REPORTS_DIR": str(t / "reports"), "HR_EXPORTS_DIR": str(t / "powerbi"),
            "HR_MODELS_DIR": str(t / "models"), "HR_UPLOAD_DIR": str(t / "uploads"),
            "HR_PASSWORD_HASH_METHOD": HASH_METHOD, "HR_DEMO_PASSWORD": PW,
            "HR_SYNTHETIC_START": "2026-02-01", "HR_SYNTHETIC_MONTHS": "4",
            "HR_SYNTHETIC_EMPLOYEES": "24", "HR_SYNTHETIC_NEW_HIRES": "2",
        }
        cls._pg_schema = pg_create_schema() if PG_URL else None
        if cls._pg_schema:
            cls.env["HR_DATABASE_URL"] = pg_schema_url(cls._pg_schema)
        cls.runner = CliRunner(env=cls.env)
        cls.outputs = {}
        for name, args in (("init", ["init-db", "--reset"]), ("gen", ["generate-data"]), ("seed", ["seed"]),
                           ("import", ["import-punches", str(t / "data" / "synthetic" / "punches")]),
                           ("train", ["train-model"]), ("export", ["export-powerbi"])):
            res = cls.runner.invoke(cli, args, catch_exceptions=False)
            assert res.exit_code == 0, (name, res.output)
            cls.outputs[name] = res.output
        cls.settings = Settings(**{k[3:]: v for k, v in cls.env.items()
                                   if k[3:] in Settings.__dataclass_fields__ and k[3:] not in
                                   ("TESTING", "SYNTHETIC_MONTHS", "SYNTHETIC_EMPLOYEES", "SYNTHETIC_NEW_HIRES")})
        cls.settings.TESTING = True
        cls.conn = connect(cls.settings.db_target)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        if cls._pg_schema:
            pg_drop_schema(cls._pg_schema)
        cls._tmp.cleanup()

    def test_01_pipeline_outputs(self):
        self.assertIn("27 employees", self.outputs["gen"])   # 24 + 2 new hires + the General Manager
        self.assertIn("Processed", self.outputs["import"])
        self.assertIn("UNKNOWN_BADGE", self.outputs["import"], "planted bad rows are quarantined")
        n = self.conn.execute("SELECT COUNT(*) FROM attendance_daily").fetchone()[0]
        self.assertGreater(n, 2000)
        last = self.conn.execute("SELECT MAX(shift_date), MIN(shift_date) FROM attendance_daily").fetchone()
        self.assertEqual((last[1], last[0]), ("2026-02-01", "2026-05-31"),
                         "no rows outside the imported data range")
        self.assertIn("insufficient_data", self.outputs["train"], "4 months are too few for the model")

    def test_02_reimporting_the_folder_changes_nothing(self):
        before = self.conn.execute("SELECT COUNT(*) FROM raw_punches").fetchone()[0]
        res = self.runner.invoke(cli, ["import-punches", str(Path(self.env["HR_DATA_DIR"]) / "synthetic" / "punches")])
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.output.count("duplicate_file"), 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM raw_punches").fetchone()[0], before)

    def test_03_evaluation_through_the_web_app(self):
        app = create_app(self.settings)
        c = app.test_client()
        self.assertEqual(login(c, "e0001", PW).status_code, 302)     # OPS department manager
        emp = self.conn.execute("SELECT e.employee_id FROM employees e JOIN departments d USING(department_id) "
                                "WHERE d.code='OPS' AND e.employee_code <> 'E0001' AND e.termination_date IS NULL "
                                "ORDER BY e.employee_code LIMIT 1").fetchone()[0]
        self.conn.execute("DELETE FROM evaluation_history WHERE evaluation_id IN (SELECT evaluation_id FROM "
                          "performance_evaluations WHERE employee_id=? AND period='2026-05')", (emp,))
        self.conn.execute("DELETE FROM performance_evaluations WHERE employee_id=? AND period='2026-05'", (emp,))
        self.conn.commit()
        r = c.post(f"/evaluations/form?employee_id={emp}&period=2026-05",
                   data={"punctuality": 4, "communication": 4, "task_completion": 4, "teamwork": 4,
                         "comments": "e2e", "csrf_token": token(c)})
        self.assertEqual(r.status_code, 302)
        ev = repos.get_evaluation(self.conn, emp, "2026-05")
        self.assertEqual((ev["weighted_score"], ev["comments"]), (4.0, "e2e"))
        page = c.get("/?period=2026-05").get_data(as_text=True)
        self.assertIn("Attendance rate", page)

    def test_04_monthly_report_once_per_period(self):
        first = self.runner.invoke(cli, ["run-monthly", "--period", "2026-05", "--all-departments"])
        self.assertEqual(first.exit_code, 0, first.output)
        # organisation + 7 departments (incl. executive), each in English and in Arabic
        self.assertEqual(first.output.count("[success]"), 16)
        second = self.runner.invoke(cli, ["run-monthly", "--period", "2026-05", "--all-departments"])
        self.assertEqual(second.output.count("[skipped]"), 16)
        runs = self.conn.execute("SELECT status, output_path, report_type FROM report_runs "
                                 "WHERE period='2026-05'").fetchall()
        self.assertEqual(len(runs), 16)
        self.assertEqual(sum(1 for r in runs if r[2] == "monthly_hr_ar"), 8)
        for status, path, _type in runs:
            self.assertEqual(status, "success")
            self.assertTrue(Path(path).read_bytes().startswith(b"%PDF"))
        forced = self.runner.invoke(cli, ["report", "--period", "2026-05", "--force"])
        self.assertIn("[success]", forced.output)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM report_runs WHERE period='2026-05' AND "
                                           "status='superseded'").fetchone()[0], 1)

    def test_05_power_bi_export_reconciles_with_app_kpis(self):
        out = Path(self.env["HR_EXPORTS_DIR"])
        fact = pd.read_csv(out / "FactAttendanceDaily.csv")
        dim = pd.read_csv(out / "DimEmployee.csv")
        expected = pd.read_csv(out / "validation" / "expected_kpis.csv")
        hr = UserContext(0, "system", "hr", None)
        for period in ("2026-03", "2026-04"):
            first, last = parse_period(period)
            k = attendance_kpis(repos.attendance_frame(self.conn, hr, first.isoformat(), last.isoformat()))
            f = fact[(fact.DateKey >= int(first.strftime("%Y%m%d"))) & (fact.DateKey <= int(last.strftime("%Y%m%d")))]
            # the same arithmetic the DAX measures perform
            dax_rate = f.IsAttended.sum() / f.IsExpected.sum()
            dax_late = (f.IsLate * f.IsAttended).sum() / f.IsAttended.sum()
            self.assertAlmostEqual(dax_rate, k["attendance_rate"], places=9)
            self.assertAlmostEqual(dax_late, k["late_rate"], places=9)
            row = expected[(expected.Period == period) & (expected.department_name == "(All)")].iloc[0]
            self.assertEqual(int(row.expected_days), k["expected_days"])
            self.assertAlmostEqual(row.attendance_rate, k["attendance_rate"], places=5)
        self.assertEqual(dim.EmployeeKey.is_unique, True, "dimension key must be unique (no double counting)")
        self.assertTrue(set(fact.EmployeeKey) <= set(dim.EmployeeKey))
        self.assertTrue(fact.duplicated(["EmployeeKey", "DateKey"]).sum() == 0, "grain: employee x shift date")
        sec = pd.read_csv(out / "SecurityManagerDepartment.csv")
        self.assertTrue(sec.UserPrincipalName.str.contains("@").all())


if __name__ == "__main__":
    unittest.main()
