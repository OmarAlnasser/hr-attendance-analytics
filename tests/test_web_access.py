"""Server-side authorisation, CSRF, login behaviour and evaluation entry through the web app."""
import io
import unittest
from datetime import date, datetime

from hr_analytics.db import repos
from hr_analytics.pipeline.importer import import_punch_file
from hr_analytics.pipeline.processor import process_attendance
from hr_analytics.web import create_app
from hr_analytics.web.views import auth as auth_views

from .support import TempDirMixin, build_small_org, csrf_from, login, token, write_csv


class WebTestBase(TempDirMixin):
    def setUp(self):
        super().setUp()
        self.ids = build_small_org(self.conn)
        rows = [("B002", "2026-03-02 08:20:00"), ("B002", "2026-03-02 16:00:00"),
                ("B003", "2026-03-02 07:55:00"), ("B003", "2026-03-02 16:10:00"),
                ("B001", "2026-03-02 07:50:00"), ("B001", "2026-03-02 16:30:00")]
        write_csv(self.tmp / "p.csv", [(b, t, "D1", "") for b, t in rows])
        import_punch_file(self.conn, self.tmp / "p.csv", settings=self.settings, as_of=datetime(2026, 4, 1))
        process_attendance(self.conn, date(2026, 3, 1), date(2026, 3, 31), settings=self.settings,
                           as_of=datetime(2026, 4, 1))
        self.app = create_app(self.settings)
        auth_views._failures.clear()

    def client_for(self, username):
        c = self.app.test_client()
        r = login(c, username)
        self.assertEqual(r.status_code, 302, f"login failed for {username}")
        return c


class AuthenticationTests(WebTestBase, unittest.TestCase):
    def test_pages_require_login(self):
        c = self.app.test_client()
        for path in ("/", "/attendance", "/employees/1", "/evaluations/", "/reports/", "/imports/"):
            r = c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers["Location"])

    def test_wrong_password_is_rejected_without_revealing_which_part(self):
        c = self.app.test_client()
        r1 = login(c, "hr1", "wrong-password-1")
        r2 = login(c, "nobody", "wrong-password-1")
        self.assertEqual((r1.status_code, r2.status_code), (401, 401))
        self.assertIn("Username or password is incorrect", r1.get_data(as_text=True))
        self.assertIn("Username or password is incorrect", r2.get_data(as_text=True))

    def test_throttling_after_repeated_failures(self):
        c = self.app.test_client()
        for _ in range(5):
            login(c, "hr1", "wrong-password-1")
        self.assertEqual(login(c, "hr1").status_code, 429, "even the right password waits during lock-out")

    def test_passwords_are_hashed(self):
        stored = self.conn.execute("SELECT password_hash FROM users WHERE username='hr1'").fetchone()[0]
        self.assertTrue(stored.startswith("pbkdf2:") and "test-password" not in stored)

    def test_post_without_csrf_token_is_rejected(self):
        c = self.client_for("hr1")
        r = c.post("/evaluations/form?employee_id=%d&period=2026-03" % self.ids["E002"],
                   data={"punctuality": 3, "communication": 3, "task_completion": 3, "teamwork": 3})
        self.assertEqual(r.status_code, 400)
        r = c.post("/logout", data={"csrf_token": "forged"})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(repos.get_evaluation(self.conn, self.ids["E002"], "2026-03"))

    def test_login_form_itself_needs_csrf(self):
        r = self.app.test_client().post("/login", data={"username": "hr1", "password": "x"})
        self.assertEqual(r.status_code, 400)

    def test_open_redirect_is_ignored(self):
        c = self.app.test_client()
        tok = csrf_from(c.get("/login").get_data(as_text=True))
        r = c.post("/login?next=//evil.example/steal", data={"username": "hr1", "password": "test-password-123",
                                                              "csrf_token": tok})
        self.assertEqual(r.headers["Location"], "/")

    def test_session_is_renewed_on_login_and_cleared_on_logout(self):
        c = self.app.test_client()
        pre = csrf_from(c.get("/login").get_data(as_text=True))
        login(c, "hr1")
        post = token(c)
        self.assertNotEqual(pre, post, "CSRF token (and session) rotate at login")
        r = c.post("/logout", data={"csrf_token": post})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/").status_code, 302)

    def test_security_headers(self):
        r = self.client_for("hr1").get("/")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Cache-Control"], "no-store")


class AuthorisationTests(WebTestBase, unittest.TestCase):
    def test_hr_sees_everything(self):
        c = self.client_for("hr1")
        for path in ("/", f"/employees/{self.ids['E003']}", "/imports/", "/audit", "/departments", "/shifts",
                     "/calendar", "/evaluations/weights", "/review/", "/reports/"):
            self.assertEqual(c.get(path).status_code, 200, path)

    def test_manager_is_limited_to_own_department(self):
        c = self.client_for("mgr_ops")
        self.assertEqual(c.get(f"/employees/{self.ids['E002']}").status_code, 200)
        self.assertEqual(c.get(f"/employees/{self.ids['E003']}").status_code, 403, "IT employee")
        self.assertEqual(c.get(f"/?department_id={self.ids['IT']}").status_code, 403)
        self.assertEqual(c.get(f"/attendance?department_id={self.ids['IT']}").status_code, 403)
        self.assertEqual(c.get(f"/attendance/export.csv?department_id={self.ids['IT']}").status_code, 403)
        for path in ("/imports/", "/audit", "/departments", "/shifts", "/calendar", "/evaluations/weights",
                     f"/employees/{self.ids['E002']}/edit"):
            self.assertEqual(c.get(path).status_code, 403, path)

    def test_manager_export_contains_only_own_department(self):
        c = self.client_for("mgr_ops")
        csv = c.get("/attendance/export.csv?start=2026-03-01&end=2026-03-31").get_data(as_text=True)
        self.assertIn("E002", csv)
        self.assertNotIn("E003", csv)
        self.assertNotIn("E004", csv)

    def test_employee_sees_only_own_data(self):
        c = self.client_for("emp_ops")
        self.assertEqual(c.get(f"/employees/{self.ids['E002']}").status_code, 200)
        self.assertEqual(c.get(f"/employees/{self.ids['E001']}").status_code, 403, "own manager")
        self.assertEqual(c.get(f"/employees/{self.ids['E003']}").status_code, 403)
        for path in ("/employees", "/review/", "/reports/", "/imports/", f"/?department_id={self.ids['OPS']}"):
            self.assertIn(c.get(path).status_code, (302, 403), path)
        csv = c.get("/attendance/export.csv?start=2026-03-01&end=2026-03-31").get_data(as_text=True)
        self.assertIn("E002", csv)
        self.assertNotIn("E001", csv)
        self.assertNotIn("E003", csv)

    def test_manager_cannot_evaluate_other_department_or_self(self):
        c = self.client_for("mgr_ops")
        tok = token(c)
        scores = {"punctuality": 4, "communication": 4, "task_completion": 4, "teamwork": 4, "csrf_token": tok}
        r = c.post(f"/evaluations/form?employee_id={self.ids['E003']}&period=2026-03", data=scores)
        self.assertEqual(r.status_code, 403)
        r = c.post(f"/evaluations/form?employee_id={self.ids['E001']}&period=2026-03", data=scores)
        self.assertEqual(r.status_code, 403, "self-evaluation")
        self.assertIsNone(repos.get_evaluation(self.conn, self.ids["E003"], "2026-03"))
        self.assertIsNone(repos.get_evaluation(self.conn, self.ids["E001"], "2026-03"))

    def test_employee_cannot_post_evaluations(self):
        c = self.client_for("emp_ops")
        r = c.post(f"/evaluations/form?employee_id={self.ids['E002']}&period=2026-03",
                   data={"punctuality": 5, "communication": 5, "task_completion": 5, "teamwork": 5,
                         "csrf_token": token(c)})
        self.assertEqual(r.status_code, 403)

    def test_report_download_scope(self):
        from hr_analytics.reports.runner import run_monthly_report
        org = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                 triggered_by="test")
        it = run_monthly_report(self.conn, period="2026-03", department_id=self.ids["IT"], settings=self.settings,
                                triggered_by="test")
        ops = run_monthly_report(self.conn, period="2026-03", department_id=self.ids["OPS"], settings=self.settings,
                                 triggered_by="test")
        self.assertEqual({org.status, it.status, ops.status}, {"success"})
        c = self.client_for("mgr_ops")
        self.assertEqual(c.get(f"/reports/{org.run_id}/download").status_code, 403)
        self.assertEqual(c.get(f"/reports/{it.run_id}/download").status_code, 403)
        r = c.get(f"/reports/{ops.run_id}/download")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF"))
        r.close()
        r = c.post("/reports/generate", data={"period": "2026-03", "department_id": str(self.ids["IT"]),
                                              "csrf_token": token(c)})
        self.assertEqual(r.status_code, 403)
        r = c.post("/reports/generate", data={"period": "2026-03", "department_id": "", "csrf_token": token(c)})
        self.assertEqual(r.status_code, 403, "managers cannot generate the organisation-wide report")
        r = self.client_for("hr1").get(f"/reports/{it.run_id}/download")
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_deactivated_user_loses_access_immediately(self):
        c = self.client_for("emp_ops")
        self.conn.execute("UPDATE users SET is_active = 0 WHERE username = 'emp_ops'")
        self.conn.commit()
        self.assertEqual(c.get("/attendance").status_code, 302)


class EvaluationEntryTests(WebTestBase, unittest.TestCase):
    def test_manager_enters_and_edits_an_evaluation_with_history_and_audit(self):
        c = self.client_for("mgr_ops")
        url = f"/evaluations/form?employee_id={self.ids['E002']}&period=2026-03"
        self.assertEqual(c.get(url).status_code, 200)
        r = c.post(url, data={"punctuality": 5, "communication": 3, "task_completion": 4, "teamwork": 2,
                              "comments": "Good month", "csrf_token": token(c)})
        self.assertEqual(r.status_code, 302)
        ev = repos.get_evaluation(self.conn, self.ids["E002"], "2026-03")
        self.assertAlmostEqual(ev["weighted_score"], 3.65)
        self.assertIsNotNone(ev["weights_id"])
        c.post(url, data={"punctuality": 5, "communication": 3, "task_completion": 5, "teamwork": 2,
                          "csrf_token": token(c)})
        ev2 = repos.get_evaluation(self.conn, self.ids["E002"], "2026-03")
        self.assertAlmostEqual(ev2["weighted_score"], 4.0)
        hist = repos.evaluation_history(self.conn, ev["evaluation_id"])
        self.assertEqual([h["action"] for h in hist], ["create", "update"])
        actions = [a["action"] for a in repos.list_audit(self.conn)]
        self.assertIn("evaluation_create", actions)
        self.assertIn("evaluation_update", actions)

    def test_invalid_scores_are_rejected_with_messages(self):
        c = self.client_for("hr1")
        r = c.post(f"/evaluations/form?employee_id={self.ids['E002']}&period=2026-03",
                   data={"punctuality": 6, "communication": 0, "task_completion": "x", "teamwork": 3,
                         "csrf_token": token(c)})
        self.assertEqual(r.status_code, 422)
        self.assertIsNone(repos.get_evaluation(self.conn, self.ids["E002"], "2026-03"))

    def test_weights_must_sum_to_100_and_used_weights_are_frozen(self):
        c = self.client_for("hr1")
        bad = c.post("/evaluations/weights", data={"effective_from": "2026-05", "punctuality": 30,
                                                   "communication": 30, "task_completion": 30, "teamwork": 30,
                                                   "csrf_token": token(c)})
        self.assertEqual(bad.status_code, 422)
        c.post(f"/evaluations/form?employee_id={self.ids['E002']}&period=2026-03",
               data={"punctuality": 3, "communication": 3, "task_completion": 3, "teamwork": 3,
                     "csrf_token": token(c)})
        frozen = c.post("/evaluations/weights", data={"effective_from": "2025-01", "punctuality": 40,
                                                      "communication": 20, "task_completion": 20, "teamwork": 20,
                                                      "csrf_token": token(c)})
        self.assertEqual(frozen.status_code, 422, "weights already used by an evaluation cannot be edited")
        ok = c.post("/evaluations/weights", data={"effective_from": "2026-05", "punctuality": 40,
                                                  "communication": 20, "task_completion": 20, "teamwork": 20,
                                                  "csrf_token": token(c)})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(repos.weights_for_period(self.conn, "2026-03")["effective_from"], "2025-01")
        self.assertEqual(repos.weights_for_period(self.conn, "2026-06")["effective_from"], "2026-05")


class UploadTests(WebTestBase, unittest.TestCase):
    def test_hr_uploads_a_file_and_attendance_is_processed(self):
        c = self.client_for("hr1")
        data = b"badge_id,punch_time,device_id\nB002,2026-03-03 07:59:00,D1\nB002,2026-03-03 16:03:00,D1\nBXXX,2026-03-03 08:00:00,D1\n"
        r = c.post("/imports/upload", data={"file": (io.BytesIO(data), "extra.csv"), "timezone": "Asia/Riyadh",
                                            "csrf_token": token(c)}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        b = repos.list_batches(self.conn, 1)[0]
        self.assertEqual((b["status"], b["rows_accepted"], b["rows_rejected"]), ("partial", 2, 1))
        row = self.conn.execute("SELECT status FROM attendance_daily WHERE employee_id=? AND shift_date='2026-03-03'",
                                (self.ids["E002"],)).fetchone()
        self.assertEqual(row[0], "present")
        again = c.post("/imports/upload", data={"file": (io.BytesIO(data), "extra-copy.csv"),
                                                "timezone": "Asia/Riyadh", "csrf_token": token(c)},
                       content_type="multipart/form-data")
        self.assertEqual(again.status_code, 302)
        self.assertEqual(len(repos.list_batches(self.conn)), 2, "identical content is not loaded twice")

    def test_manager_cannot_upload(self):
        c = self.client_for("mgr_ops")
        r = c.post("/imports/upload", data={"file": (io.BytesIO(b"x"), "a.csv"), "csrf_token": token(c)},
                   content_type="multipart/form-data")
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
