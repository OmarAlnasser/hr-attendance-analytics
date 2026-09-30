"""Hosting features: health check, public demo mode, and generated files surviving a wiped disk."""
import json
import re
import unittest
from pathlib import Path

from hr_analytics.db import repos
from hr_analytics.reports.runner import run_monthly_report
from hr_analytics.web import create_app
from hr_analytics.web.views.review import model_summary

from .support import csrf_from, login, token
from .test_web_access import WebTestBase


class HealthTests(WebTestBase, unittest.TestCase):
    def test_healthz_needs_no_login_and_reveals_nothing(self):
        r = self.app.test_client().get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")
        self.assertNotIn("password", r.get_data(as_text=True).lower())

    def test_demo_login_is_off_by_default(self):
        c = self.app.test_client()
        self.assertNotIn("Explore the live demo", c.get("/login").get_data(as_text=True))
        tok = csrf_from(c.get("/login").get_data(as_text=True))
        self.assertEqual(c.post("/demo-login", data={"csrf_token": tok, "username": "hr1"}).status_code, 404)


class DemoModeTests(WebTestBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.settings.DEMO_MODE = True
        self.settings.DEMO_ACCOUNTS = "hr1,mgr_ops,emp_ops"
        self.conn.execute("UPDATE employees SET is_synthetic = 1 WHERE employee_code IN ('E009', 'E001', 'E002')")
        self.conn.commit()
        self.app = create_app(self.settings)

    def demo_client(self, username):
        c = self.app.test_client()
        tok = csrf_from(c.get("/login").get_data(as_text=True))
        r = c.post("/demo-login", data={"csrf_token": tok, "username": username})
        return c, r

    def test_one_click_login_for_each_showcase_role(self):
        page = self.app.test_client().get("/login").get_data(as_text=True)
        self.assertIn("Explore the live demo", page)
        self.assertEqual(len(re.findall(r'action="/demo-login"', page)), 3)
        for username, landing in (("hr1", "Overview"), ("mgr_ops", "Overview"), ("emp_ops", "My requests")):
            c, r = self.demo_client(username)
            self.assertEqual(r.status_code, 302, username)
            self.assertIn(landing, c.get("/", follow_redirects=True).get_data(as_text=True))
        self.assertIn("Public demo", c.get("/requests").get_data(as_text=True))

    def test_only_listed_synthetic_accounts_can_be_used(self):
        self.assertEqual(self.demo_client("emp_it")[1].status_code, 404, "not a showcase account")
        self.conn.execute("UPDATE employees SET is_synthetic = 0 WHERE employee_code = 'E002'")
        self.conn.commit()
        self.assertEqual(self.demo_client("emp_ops")[1].status_code, 404, "a real person's account never opens")
        c = self.app.test_client()
        self.assertEqual(c.post("/demo-login", data={"username": "hr1"}).status_code, 400, "CSRF still applies")

    def test_visitors_cannot_lock_the_showcase_accounts(self):
        c, _ = self.demo_client("emp_ops")
        new = "someone-elses-password-1"
        c.post("/account", data={"csrf_token": token(c), "current_password": "test-password-123",
                                 "new_password": new, "repeat_password": new})
        self.assertEqual(login(self.app.test_client(), "emp_ops").status_code, 302, "password unchanged")
        hr, _ = self.demo_client("hr1")
        for action in ("disable", "reset", "grant_hr"):
            hr.post(f"/users/{self.ids['user_mgr_ops']}/{action}", data={"csrf_token": token(hr)})
        u = repos.get_user(self.conn, self.ids["user_mgr_ops"])
        self.assertEqual((u["is_active"], u["role"], u["must_change_password"]), (1, "manager", 0))
        hr.post(f"/users/{self.ids['user_emp_it']}/disable", data={"csrf_token": token(hr)})
        self.assertEqual(repos.get_user(self.conn, self.ids["user_emp_it"])["is_active"], 0,
                         "other accounts can still be managed, so the feature can be tried")


class StoredFilesTests(WebTestBase, unittest.TestCase):
    def test_report_downloads_after_the_disk_is_wiped(self):
        out = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                 triggered_by="test")
        self.assertEqual(out.status, "success")
        pdf = Path(out.output_path).read_bytes()
        Path(out.output_path).unlink()                     # what a free host does on restart
        hr = self.client_for("hr1")
        self.assertIn(f"/reports/{out.run_id}/download", hr.get("/reports/").get_data(as_text=True))
        r = hr.get(f"/reports/{out.run_id}/download")
        self.assertEqual((r.status_code, r.data), (200, pdf))
        again = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                   triggered_by="test")
        self.assertEqual(again.status, "skipped", "the stored copy counts, so it is not regenerated")

    def test_model_summary_falls_back_to_the_database(self):
        repos.save_file(self.conn, "models/model_evaluation.json", json.dumps({"status": "model"}).encode(),
                        "application/json")
        self.conn.commit()
        empty_dir = self.tmp / "no-models-here"
        self.assertIsNone(model_summary(str(empty_dir)))
        self.assertEqual(model_summary(str(empty_dir), self.conn), {"status": "model"})


if __name__ == "__main__":
    unittest.main()
