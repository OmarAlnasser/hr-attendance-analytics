"""v2 features: schema migration, leave and missed-punch requests with approvals,
the live Today board, HR account management, and bulk employee import."""
import io
import sqlite3
import unittest
from datetime import date, datetime
from unittest import mock

from hr_analytics.db import repos
from hr_analytics.db.connection import SCHEMA_VERSION, connect, migrate, schema_version
from hr_analytics.pipeline.processor import process_attendance
from hr_analytics.web.views import auth as auth_views

from .support import PASSWORD, csrf_from, login, token
from .test_web_access import WebTestBase

NOW = datetime(2026, 3, 20, 12, 0)          # the clock the self-service views see in these tests
patch_now = mock.patch("hr_analytics.web.views.selfservice._now", return_value=NOW)


def day(conn, emp_id, d):
    r = conn.execute("SELECT * FROM attendance_daily WHERE employee_id = ? AND shift_date = ?", (emp_id, d)).fetchone()
    return dict(r) if r else None


def flashes(resp, cat="error"):
    import re
    return re.findall(rf'class="flash {cat}"[^>]*>([^<]+)', resp.get_data(as_text=True))


# ================================================================ migration ==

V1_SCHEMA = __import__("pathlib").Path(__file__).with_name("fixtures") / "schema_v1.sql"   # schema as shipped in v1


class MigrationTests(unittest.TestCase):
    def test_v1_database_is_upgraded_in_place_and_keeps_its_data(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "v1.sqlite3")
            c = sqlite3.connect(db)
            c.executescript(V1_SCHEMA.read_text(encoding="utf-8"))
            c.executescript("""
                INSERT INTO departments(department_id, code, name) VALUES (1, 'OPS', 'Operations');
                INSERT INTO employees(employee_id, employee_code, badge_id, full_name, department_id, hire_date)
                    VALUES (1, 'E1', 'B1', 'Someone', 1, '2025-01-01');
                INSERT INTO users(user_id, username, password_hash, role, employee_id) VALUES (1, 'a', 'h', 'hr', 1);
                INSERT INTO leave_requests VALUES (7, 1, 'sick', '2026-01-01', '2026-01-02', 'approved', 1);""")
            self.assertEqual(c.execute("SELECT value FROM schema_meta").fetchone()[0], "1")
            c.close()
            conn = connect(db)
            applied = migrate(conn)
            self.assertEqual(len(applied), 9, applied)
            self.assertIn("users: 'gm' (General Manager) role", applied)
            self.assertEqual(schema_version(conn), SCHEMA_VERSION)
            row = dict(conn.execute("SELECT * FROM leave_requests WHERE leave_id = 7").fetchone())
            self.assertEqual((row["leave_type"], row["status"], row["approved_by_user_id"]), ("sick", "approved", 1))
            self.assertIsNone(row["requested_by_user_id"])
            conn.execute("UPDATE leave_requests SET status = 'cancelled' WHERE leave_id = 7")   # new status allowed
            self.assertEqual(conn.execute("SELECT must_change_password FROM users").fetchone()[0], 0)
            self.assertEqual(migrate(conn), [], "second run is a no-op")
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.close()


# ==================================================================== leave ==

class LeaveRequestTests(WebTestBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        patch_now.start()
        self.addCleanup(patch_now.stop)

    def _request_leave(self, client, start="2026-03-03", end="2026-03-04", ltype="annual", reason=""):
        return client.post("/requests", data={"csrf_token": token(client), "action": "new_leave",
                                              "leave_type": ltype, "start_date": start, "end_date": end,
                                              "reason": reason})

    def _decide(self, client, kind, rid, decision, note=""):
        return client.post("/approvals/decide", data={"csrf_token": token(client), "kind": kind, "id": rid,
                                                      "decision": decision, "note": note})

    def _last_leave(self):
        return dict(self.conn.execute("SELECT * FROM leave_requests ORDER BY leave_id DESC LIMIT 1").fetchone())

    def test_request_is_pending_until_the_manager_approves_then_days_become_leave(self):
        emp = self.client_for("emp_ops")
        self.assertEqual(self._request_leave(emp).status_code, 302)
        lv = self._last_leave()
        self.assertEqual((lv["status"], lv["requested_by_user_id"]), ("pending", self.ids["user_emp_ops"]))
        self.assertEqual(day(self.conn, self.ids["E002"], "2026-03-03")["status"], "absent", "pending leave never counts")

        mgr = self.client_for("mgr_ops")
        self.assertIn(">1<", mgr.get("/approvals").get_data(as_text=True), "sidebar badge shows one waiting")
        r = self._decide(mgr, "leave", lv["leave_id"], "approve")
        self.assertEqual(r.status_code, 302)
        lv = self._last_leave()
        self.assertEqual((lv["status"], lv["approved_by_user_id"]), ("approved", self.ids["user_mgr_ops"]))
        self.assertIsNotNone(lv["decided_at"])
        for d in ("2026-03-03", "2026-03-04"):
            rec = day(self.conn, self.ids["E002"], d)
            self.assertEqual((rec["status"], rec["leave_type"]), ("leave", "annual"), d)
        self.assertEqual(day(self.conn, self.ids["E002"], "2026-03-05")["status"], "absent", "only the leave days change")
        actions = {r[0] for r in self.conn.execute("SELECT action FROM audit_log")}
        self.assertTrue({"leave_request", "leave_approve"} <= actions)

    def test_scope_other_department_manager_and_self_approval_are_refused(self):
        self._request_leave(self.client_for("emp_ops"))
        lv = self._last_leave()
        self.assertEqual(self._decide(self.client_for("mgr_it"), "leave", lv["leave_id"], "approve").status_code, 403)
        self.assertNotIn(f'value="{lv["leave_id"]}"', self.client_for("mgr_it").get("/approvals").get_data(as_text=True))
        # a manager's own request goes to HR, never to themselves
        mgr = self.client_for("mgr_ops")
        self._request_leave(mgr, "2026-03-10", "2026-03-10")
        own = self._last_leave()
        self.assertEqual(self._decide(mgr, "leave", own["leave_id"], "approve").status_code, 403)
        self.assertEqual(self._decide(self.client_for("hr1"), "leave", own["leave_id"], "approve").status_code, 302)
        self.assertEqual(self._last_leave()["status"], "approved")
        # employees cannot reach the approval endpoints at all
        self.assertEqual(self._decide(self.client_for("emp_it"), "leave", lv["leave_id"], "approve").status_code, 403)
        self.assertEqual(self.client_for("emp_it").get("/approvals").status_code, 403)

    def test_rejection_needs_a_note_and_a_request_is_decided_only_once(self):
        self._request_leave(self.client_for("emp_ops"))
        lv = self._last_leave()
        mgr = self.client_for("mgr_ops")
        self._decide(mgr, "leave", lv["leave_id"], "reject")
        self.assertEqual(self._last_leave()["status"], "pending", "reject without a note is refused")
        self._decide(mgr, "leave", lv["leave_id"], "reject", "Peak week, please pick other dates")
        self.assertEqual(self._last_leave()["status"], "rejected")
        self._decide(self.client_for("hr1"), "leave", lv["leave_id"], "approve")
        lv = self._last_leave()
        self.assertEqual((lv["status"], lv["approved_by_user_id"]), ("rejected", self.ids["user_mgr_ops"]),
                         "a second decision does not overwrite the first")

    def test_validation_overlap_dates_and_employment(self):
        emp = self.client_for("emp_ops")
        self._request_leave(emp, "2026-03-03", "2026-03-05")
        r = self._request_leave(emp, "2026-03-05", "2026-03-06")
        self.assertEqual(r.status_code, 422)
        self.assertTrue(any("overlap" in m for m in flashes(r)))
        self.assertEqual(self._request_leave(emp, "2026-03-06", "2026-03-02").status_code, 422)
        r = self._request_leave(emp, "2026-03-06", "2026-03-06", ltype="other")
        self.assertTrue(any("reason" in m for m in flashes(r)))
        self.assertEqual(self._request_leave(emp, "2023-12-20", "2023-12-21").status_code, 422, "too far back")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0], 1)

    def test_employee_cancels_pending_but_not_leave_that_already_started(self):
        emp = self.client_for("emp_ops")
        self._request_leave(emp, "2026-03-03", "2026-03-03")
        lv = self._last_leave()
        emp.post("/requests", data={"csrf_token": token(emp), "action": "cancel_leave", "leave_id": lv["leave_id"]})
        self.assertEqual(self._last_leave()["status"], "cancelled")
        self._request_leave(emp, "2026-03-09", "2026-03-09")
        started = self._last_leave()
        self._decide(self.client_for("mgr_ops"), "leave", started["leave_id"], "approve")
        emp.post("/requests", data={"csrf_token": token(emp), "action": "cancel_leave", "leave_id": started["leave_id"]})
        self.assertEqual(self._last_leave()["status"], "approved", "started leave is cancelled through HR only")
        other = self.client_for("emp_it")      # cannot touch someone else's request
        r = other.post("/requests", data={"csrf_token": token(other), "action": "cancel_leave",
                                          "leave_id": started["leave_id"]})
        self.assertEqual(r.status_code, 404)


# ============================================================== corrections ==

class CorrectionTests(WebTestBase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        patch_now.start()
        self.addCleanup(patch_now.stop)

    def _report(self, client, when, kind="in", reason="Badge reader at gate 2 was down"):
        return client.post("/requests", data={"csrf_token": token(client), "action": "new_correction",
                                              "punch_kind": kind, "punch_time": when, "reason": reason})

    def _last(self):
        return dict(self.conn.execute("SELECT * FROM attendance_corrections ORDER BY correction_id DESC").fetchone())

    def test_approved_corrections_become_manual_punches_and_fix_the_day(self):
        emp_id = self.ids["E002"]
        self.assertEqual(day(self.conn, emp_id, "2026-03-03")["status"], "absent")
        emp, mgr = self.client_for("emp_ops"), self.client_for("mgr_ops")
        for when, kind in (("2026-03-03T08:05", "in"), ("2026-03-03T16:01", "out")):
            before = day(self.conn, emp_id, "2026-03-03")
            self.assertEqual(self._report(emp, when, kind).status_code, 302)
            c = self._last()
            self.assertEqual((c["status"], c["shift_date"]), ("pending", "2026-03-03"))
            self.assertEqual(day(self.conn, emp_id, "2026-03-03"), before, "nothing changes before approval")
            r = mgr.post("/approvals/decide", data={"csrf_token": token(mgr), "kind": "correction",
                                                    "id": c["correction_id"], "decision": "approve"})
            self.assertEqual(r.status_code, 302)
        rec = day(self.conn, emp_id, "2026-03-03")
        self.assertEqual((rec["status"], rec["is_late"], rec["first_punch"][11:16], rec["last_punch"][11:16]),
                         ("present", 0, "08:05", "16:01"))
        punches = self.conn.execute("""SELECT p.device_id, p.punch_type, b.source_type, b.imported_by_user_id
                                       FROM raw_punches p JOIN import_batches b ON b.batch_id = p.batch_id
                                       WHERE p.employee_id = ? AND p.punch_time_local LIKE '2026-03-03%'""",
                                    (emp_id,)).fetchall()
        self.assertEqual({tuple(p) for p in punches},
                         {("MANUAL", "IN", "manual", self.ids["user_mgr_ops"]),
                          ("MANUAL", "OUT", "manual", self.ids["user_mgr_ops"])})
        self.assertIsNotNone(self._last()["punch_id"])
        # re-processing from scratch reproduces the same result (manual punches are ordinary punches)
        process_attendance(self.conn, date(2026, 3, 1), date(2026, 3, 31), settings=self.settings,
                           as_of=datetime(2026, 4, 1))
        self.assertEqual(day(self.conn, emp_id, "2026-03-03")["status"], "present")

    def test_invalid_corrections_are_refused_with_a_reason(self):
        emp = self.client_for("emp_ops")
        cases = {
            "2026-03-25T08:00": "future",
            "2026-03-02T08:21": "already recorded",      # device punch at 08:20 exists
            "2026-03-06T02:00": "not close to any of your shifts",
            "2026-01-05T08:00": "last 60 days",
        }
        for when, expect in cases.items():
            r = self._report(emp, when)
            self.assertEqual(r.status_code, 422, when)
            self.assertTrue(any(expect in m for m in flashes(r)), (when, flashes(r)))
        self.assertEqual(self._report(emp, "2026-03-03T08:00", reason="x").status_code, 422, "reason too short")
        self.assertEqual(self._report(emp, "2026-03-03T08:00").status_code, 302)
        r = self._report(emp, "2026-03-03T08:03")
        self.assertTrue(any("already reported this missed punch" in m for m in flashes(r)))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance_corrections").fetchone()[0], 1)

    def test_night_shift_clock_out_maps_to_the_previous_shift_date(self):
        # E005 works 22:00-06:00; a 06:02 clock-out on the 4th belongs to the shift of the 3rd
        h = __import__("werkzeug.security", fromlist=["x"]).generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
        repos.create_user(self.conn, "night", h, "employee", self.ids["E005"])
        self.conn.commit()
        c = self.client_for("night")
        self.assertEqual(self._report(c, "2026-03-04T06:02", "out").status_code, 302)
        self.assertEqual(self._last()["shift_date"], "2026-03-03")

    def test_other_department_manager_cannot_approve_and_withdrawn_cannot_be_approved(self):
        emp = self.client_for("emp_ops")
        self._report(emp, "2026-03-03T08:05")
        c = self._last()
        it = self.client_for("mgr_it")
        r = it.post("/approvals/decide", data={"csrf_token": token(it), "kind": "correction",
                                              "id": c["correction_id"], "decision": "approve"})
        self.assertEqual(r.status_code, 403)
        emp.post("/requests", data={"csrf_token": token(emp), "action": "cancel_correction",
                                    "correction_id": c["correction_id"]})
        self.assertEqual(self._last()["status"], "cancelled")
        mgr = self.client_for("mgr_ops")
        mgr.post("/approvals/decide", data={"csrf_token": token(mgr), "kind": "correction",
                                            "id": c["correction_id"], "decision": "approve"})
        self.assertEqual(self._last()["status"], "cancelled")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM raw_punches WHERE device_id = 'MANUAL'").fetchone()[0], 0)

    def test_profile_offers_report_link_on_own_problem_days_only(self):
        own = self.client_for("emp_ops").get(f"/employees/{self.ids['E002']}?period=2026-03").get_data(as_text=True)
        self.assertIn("Report a missed punch", own)
        mgr_view = self.client_for("mgr_ops").get(f"/employees/{self.ids['E002']}?period=2026-03").get_data(as_text=True)
        self.assertNotIn("Report a missed punch", mgr_view)


# ==================================================================== today ==

class TodayBoardTests(WebTestBase, unittest.TestCase):
    def board(self, client, when_date, when_time):
        html = client.get(f"/today?date={when_date}&time={when_time}").get_data(as_text=True)
        import re
        cols = {}
        for sec in re.findall(r'<section class="col[^"]*" aria-label="([^"]+)">(.*?)</section>', html, re.S):
            cols[sec[0]] = set(re.findall(r'>(E\d{3})</a>', sec[1]))
        return cols, html

    def test_replay_puts_each_person_in_the_right_column(self):
        hr = self.client_for("hr1")
        cols, html = self.board(hr, "2026-03-02", "09:00")
        self.assertEqual(cols["Arrived late"], {"E002"})          # 08:20 > 08:00 + 15 min grace
        self.assertEqual(cols["In, on time"], {"E001", "E003"})
        self.assertIn("E005", cols["Expected later"])              # night shift starts 22:00
        self.assertTrue({"E004", "E009"} <= cols["Not in yet"])
        self.assertIn("E007", cols["Not in yet"], "leaves on the 5th, so still expected on the 2nd")
        self.assertNotIn("E006", set().union(*cols.values()), "hired on the 10th: not on the board yet")
        self.assertNotIn('http-equiv="refresh"', html, "replay does not auto-refresh")

    def test_punches_after_the_replay_moment_are_ignored(self):
        cols, _ = self.board(self.client_for("hr1"), "2026-03-02", "08:10")
        self.assertIn("E002", cols["Expected later"], "at 08:10 E002 is not due until 08:15 and has not punched")
        cols, _ = self.board(self.client_for("hr1"), "2026-03-02", "17:00")
        self.assertEqual(cols["Clocked out"], {"E001", "E002", "E003"})

    def test_board_is_scoped_and_live_mode_refreshes(self):
        cols, _ = self.board(self.client_for("mgr_it"), "2026-03-02", "09:00")
        everyone = set().union(*cols.values())
        self.assertTrue(everyone and everyone <= {"E003", "E004"}, everyone)
        self.assertEqual(self.client_for("emp_ops").get("/today").status_code, 403)
        live = self.client_for("hr1").get("/today").get_data(as_text=True)
        self.assertIn('http-equiv="refresh"', live)
        self.assertIn("most recent punch received", live, "a stale feed is announced, not shown as mass absence")
        self.assertEqual(self.client_for("hr1").get("/today?date=2999-01-01").status_code, 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='process_attendance'").fetchone()[0],
                         1, "the board writes nothing")


# ============================================================ user accounts ==

class UserAdminTests(WebTestBase, unittest.TestCase):
    def _post(self, client, path, **data):
        return client.post(path, data={"csrf_token": token(client), **data})

    @staticmethod
    def _temp_pw(resp):
        import re
        m = re.search(r'class="pw-once"[^>]*>([^<]+)<', resp.get_data(as_text=True))
        assert m, "temporary password not shown"
        return m.group(1)

    def test_create_account_forces_a_password_change_at_first_sign_in(self):
        hr = self.client_for("hr1")
        r = self._post(hr, "/users/create", employee_id=self.ids["E005"])
        pw = self._temp_pw(r)
        u = repos.get_user_by_username(self.conn, "e005")
        self.assertEqual((u["role"], u["must_change_password"]), ("employee", 1))
        self.assertNotIn(pw, u["password_hash"])
        c = self.app.test_client()
        self.assertEqual(login(c, "e005", pw).status_code, 302)
        r = c.get("/attendance")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/account"), "everything leads to /account")
        new = "a-brand-new-password-9"
        c.post("/account", data={"csrf_token": csrf_from(c.get("/account").get_data(as_text=True)),
                                 "current_password": pw, "new_password": new, "repeat_password": new})
        self.assertEqual(c.get("/attendance").status_code, 200)
        self.assertEqual(repos.get_user_by_username(self.conn, "e005")["must_change_password"], 0)

    def test_reset_disable_and_role_changes(self):
        hr = self.client_for("hr1")
        uid = self.ids["user_emp_ops"]
        pw = self._temp_pw(self._post(hr, f"/users/{uid}/reset"))
        auth_views._failures.clear()
        self.assertEqual(login(self.app.test_client(), "emp_ops").status_code, 401, "old password stops working")
        self.assertEqual(login(self.app.test_client(), "emp_ops", pw).status_code, 302)

        self._post(hr, f"/users/{uid}/disable")
        auth_views._failures.clear()
        self.assertEqual(login(self.app.test_client(), "emp_ops", pw).status_code, 401)
        self._post(hr, f"/users/{uid}/enable")
        self.assertEqual(repos.get_user(self.conn, uid)["is_active"], 1)

        # only the General Manager gives or removes HR access
        self.assertEqual(self._post(hr, f"/users/{self.ids['user_mgr_ops']}/grant_hr").status_code, 403)
        self.assertEqual(repos.get_user(self.conn, self.ids["user_mgr_ops"])["role"], "manager")
        h = __import__("werkzeug.security", fromlist=["x"]).generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
        repos.create_user(self.conn, "gm1", h, "gm", None)
        self.conn.commit()
        gm = self.client_for("gm1")
        self._post(gm, f"/users/{self.ids['user_mgr_ops']}/grant_hr")
        self.assertEqual(repos.get_user(self.conn, self.ids["user_mgr_ops"])["role"], "hr")
        self.assertEqual(self._post(hr, f"/users/{self.ids['user_mgr_ops']}/reset").status_code, 403,
                         "HR cannot reset another HR account")
        self._post(gm, f"/users/{self.ids['user_mgr_ops']}/revoke_hr")
        self.assertEqual(repos.get_user(self.conn, self.ids["user_mgr_ops"])["role"], "manager",
                         "removing HR falls back to the role the org chart implies")
        # HR cannot lock themselves out here
        self._post(hr, f"/users/{self.ids['user_hr1']}/disable")
        self.assertEqual(repos.get_user(self.conn, self.ids["user_hr1"])["is_active"], 1)
        actions = [r[0] for r in self.conn.execute("SELECT action FROM audit_log WHERE entity='user'")]
        self.assertTrue({"password_reset", "user_disable", "user_enable", "role_change"} <= set(actions))

    def test_disable_leavers_and_access_control(self):
        h = __import__("werkzeug.security", fromlist=["x"]).generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
        repos.create_user(self.conn, "leaver", h, "employee", self.ids["E007"])     # terminated 2026-03-05
        self.conn.commit()
        hr = self.client_for("hr1")
        self.assertIn("Switch off leavers", hr.get("/users").get_data(as_text=True))
        self._post(hr, "/users/disable-leavers")
        self.assertEqual(repos.get_user_by_username(self.conn, "leaver")["is_active"], 0)
        self.assertEqual(repos.get_user_by_username(self.conn, "emp_ops")["is_active"], 1)
        for who in ("mgr_ops", "emp_ops"):
            c = self.client_for(who)
            self.assertEqual(c.get("/users").status_code, 403)
            self.assertEqual(self._post(c, f"/users/{self.ids['user_emp_it']}/reset").status_code, 403)


# ============================================================== bulk import ==

class BulkImportTests(WebTestBase, unittest.TestCase):
    HEADER = "employee_code,badge_id,full_name,email,job_title,department_code,shift_code,hire_date\n"

    def _upload(self, client, text, mode="import", accounts=False):
        data = {"csrf_token": token(client), "mode": mode,
                "file": (io.BytesIO(text.encode("utf-8")), "people.csv")}
        if accounts:
            data["create_accounts"] = "1"
        return client.post("/employees/import", data=data, content_type="multipart/form-data")

    def test_check_only_saves_nothing_then_import_saves_all(self):
        hr = self.client_for("hr1")
        csv = self.HEADER + ("E101,B101,New One,one@example.com,Analyst,it,day,2026-03-15\n"
                             "E102,B102,New Two,,,OPS,NIGHT,2026-03-16\n")
        before = self.conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        r = self._upload(hr, csv, mode="check")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Ready to import: 2", r.get_data(as_text=True))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0], before)
        r = self._upload(hr, csv, accounts=True)
        self.assertEqual(r.status_code, 200)
        e = repos.get_employee_by_code(self.conn, "E102")
        self.assertEqual(repos.current_assignment(self.conn, e["employee_id"])["effective_from"], "2026-03-16")
        self.assertEqual(repos.get_user_by_username(self.conn, "e101")["must_change_password"], 1)
        self.assertEqual(r.get_data(as_text=True).count('class="pw-once"'), 2)
        self.assertIsNotNone(day(self.conn, e["employee_id"], "2026-03-16"), "new people are processed from hire")

    def test_any_bad_row_blocks_the_whole_file(self):
        hr = self.client_for("hr1")
        csv = self.HEADER + ("E201,B201,Fine Person,,,OPS,DAY,2026-03-01\n"
                             "E002,B777,Existing Code,,,OPS,DAY,2026-03-01\n"
                             "E203,B002,Badge Taken,,,OPS,DAY,2026-03-01\n"
                             "E204,B204,Bad Dept,,,NOPE,DAY,01/03/2026\n"
                             "E201,B205,Twice,,,OPS,DAY,2026-03-01\n")
        r = self._upload(hr, csv)
        self.assertEqual(r.status_code, 422)
        body = r.get_data(as_text=True)
        for expect in ("Row 3", "already exists", "Row 4", "badge B002 is already in use",
                       "there is no department with the code", "joining date must look like", "appears twice"):
            self.assertIn(expect, body)
        self.assertIsNone(repos.get_employee_by_code(self.conn, "E201"), "all or nothing")
        self.assertEqual(self._upload(hr, "code,name\nX,Y\n").status_code, 422)
        self.assertEqual(self._upload(self.client_for("mgr_ops"), csv).status_code, 403)


if __name__ == "__main__":
    unittest.main()
