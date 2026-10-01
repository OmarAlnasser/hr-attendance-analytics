"""The General Manager role sits above HR: it decides about HR staff, holds every HR
power, and its own requests are approved on the spot because nobody sits above it."""
import unittest
from unittest import mock

from werkzeug.security import generate_password_hash

from hr_analytics.db import repos
from hr_analytics.security.scope import can_approve, can_evaluate, load_user_context

from .support import HASH_METHOD, PASSWORD, token
from .test_v2_features import NOW
from .test_web_access import WebTestBase


class GeneralManagerTests(WebTestBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        p = mock.patch("hr_analytics.web.views.selfservice._now", return_value=NOW)
        p.start()
        self.addCleanup(p.stop)
        h = generate_password_hash(PASSWORD, method=HASH_METHOD)
        gm_emp = repos.save_employee(self.conn, {
            "employee_code": "E000", "badge_id": "B000", "full_name": "Person E000", "email": "e000@example.com",
            "job_title": "General Manager", "department_id": self.ids["HR"], "manager_employee_id": None,
            "hire_date": "2024-01-01", "termination_date": None})
        self.conn.execute("INSERT INTO employee_shift_assignments(employee_id, shift_id, effective_from) "
                          "VALUES (?,?,?)", (gm_emp, self.ids["DAY"], "2024-01-01"))
        self.ids["E000"] = gm_emp
        self.ids["user_gm"] = repos.create_user(self.conn, "gm", h, "gm", gm_emp)
        self.ids["user_hr2"] = repos.create_user(self.conn, "hr2", h, "hr", self.ids["E005"])
        self.conn.commit()

    def ctx(self, name):
        return load_user_context(self.conn, self.ids["user_" + name])

    def leave(self, client, start, end):
        return client.post("/requests", data={"csrf_token": token(client), "action": "new_leave",
                                              "leave_type": "annual", "start_date": start, "end_date": end})

    def test_decisions_about_hr_staff_belong_to_the_general_manager(self):
        gm, hr1, hr2 = self.ctx("gm"), self.ctx("hr1"), self.ctx("hr2")
        hr1_emp = self.ids["E009"]
        self.assertFalse(can_evaluate(self.conn, hr2, hr1_emp), "HR does not evaluate HR")
        self.assertFalse(can_approve(self.conn, hr2, hr1_emp))
        self.assertTrue(can_evaluate(self.conn, gm, hr1_emp))
        self.assertTrue(can_approve(self.conn, gm, hr1_emp))
        self.assertTrue(can_evaluate(self.conn, hr1, self.ids["E002"]), "HR still evaluates everyone else")
        self.assertFalse(can_evaluate(self.conn, gm, self.ids["E000"]), "nobody evaluates their own record")
        self.assertFalse(can_evaluate(self.conn, hr1, self.ids["E000"]), "HR does not evaluate the GM")

    def test_hr_leave_request_waits_for_the_general_manager(self):
        self.assertEqual(self.leave(self.client_for("hr1"), "2026-04-05", "2026-04-06").status_code, 302)
        lv = self.conn.execute("SELECT * FROM leave_requests WHERE employee_id = ?", (self.ids["E009"],)).fetchone()
        self.assertEqual(lv["status"], "pending")
        self.assertNotIn("Person E009", self.client_for("hr2").get("/approvals").get_data(as_text=True))
        gm = self.client_for("gm")
        self.assertIn("Person E009", gm.get("/approvals").get_data(as_text=True))
        gm.post("/approvals/decide", data={"csrf_token": token(gm), "kind": "leave", "decision": "approve",
                                           "id": lv["leave_id"]})
        self.assertEqual(repos.get_leave(self.conn, lv["leave_id"])["status"], "approved")

    def test_general_managers_own_leave_is_approved_at_once(self):
        r = self.leave(self.client_for("gm"), "2026-04-12", "2026-04-13")
        self.assertEqual(r.status_code, 302)
        lv = self.conn.execute("SELECT * FROM leave_requests WHERE employee_id = ?", (self.ids["E000"],)).fetchone()
        self.assertEqual(lv["status"], "approved")
        self.assertEqual(lv["approved_by_user_id"], self.ids["user_gm"])
        self.assertTrue(lv["decision_note"].startswith("Approved automatically"))
        actions = [r[0] for r in self.conn.execute("SELECT action FROM audit_log WHERE entity = 'leave_request'")]
        self.assertEqual(actions, ["leave_request", "leave_approve"], "both steps are in the activity log")

    def test_general_manager_has_every_hr_page_and_manages_hr_accounts(self):
        gm = self.client_for("gm")
        for path in ("/today", "/imports/", "/users", "/audit", "/departments", "/reports/"):
            self.assertEqual(gm.get(path).status_code, 200, path)
        r = gm.post(f"/users/{self.ids['user_hr2']}/reset", data={"csrf_token": token(gm)})
        self.assertIn("pw-once", r.get_data(as_text=True), "the GM can reset an HR password")
        hr1 = self.client_for("hr1")
        self.assertEqual(hr1.post(f"/users/{self.ids['user_gm']}/disable", data={"csrf_token": token(hr1)})
                         .status_code, 403, "HR cannot switch off the General Manager")
        users_page = hr1.get("/users").get_data(as_text=True)
        self.assertIn("General Manager only", users_page)

    def test_general_manager_is_not_counted_as_due_an_evaluation(self):
        page = self.client_for("hr1").get("/evaluations/?period=2026-03").get_data(as_text=True)
        row = page[page.index("E000"):page.index("</tr>", page.index("E000"))]
        self.assertIn("Not due", row)


if __name__ == "__main__":
    unittest.main()
