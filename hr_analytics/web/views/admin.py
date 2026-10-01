"""Master data: employees, departments, shifts, holidays & approved leave, audit log.

Writes are HR-only. Managers get a read-only, scoped employee list.
Changes that alter attendance outcomes (employment dates, shift assignment,
holidays, leave) re-run attendance processing for the affected dates only.
"""
from __future__ import annotations

import re
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...db import repos
from ...db.connection import IntegrityError, transaction
from ...domain.attendance_rules import RuleConfig, ShiftDef, parse_hhmm, parse_workdays, validate_shift
from ...pipeline.processor import process_attendance
from .. import get_db
from ...i18n import _
from ...labels import request_status_label
from ..helpers import audit, department_options, flash_errors, get_department_filter, int_arg, roles_required

bp = Blueprint("admin", __name__)

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LEAVE_TYPES = ("annual", "sick", "unpaid", "other")


def _iso(value: str, label: str, errors: list, required: bool = True) -> str | None:
    value = (value or "").strip()
    if not value:
        if required:
            errors.append(_("{label} is required.", label=label))
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        errors.append(_("{label} must be a valid date.", label=label))
        return None


def reprocess(start: str | date, employee_ids: list[int] | None = None, end: str | date | None = None) -> str | None:
    """Re-evaluate attendance from `start` up to the last processed day (never beyond today)."""
    conn = get_db()
    last = repos.latest_attendance_date(conn)
    if not last:
        return None
    start = date.fromisoformat(str(start))
    stop = min(date.fromisoformat(str(end)) if end else date.fromisoformat(last), date.fromisoformat(last), date.today())
    if start > stop:
        return None
    summ = process_attendance(conn, start, stop, settings=g.settings, employee_ids=employee_ids,
                              user_id=g.user.user_id)
    return _("Attendance recalculated from {start} to {end}.", start=summ.start, end=summ.end)


def _sync_manager_roles(conn, employee_ids: set[int]) -> None:
    """Keep user roles consistent with departments.manager_employee_id (HR accounts are never changed)."""
    for emp_id in employee_ids:
        if emp_id is None:
            continue
        user = conn.execute("SELECT user_id, role FROM users WHERE employee_id = ?", (emp_id,)).fetchone()
        if user is None or user["role"] in ("hr", "gm"):
            continue
        manages = conn.execute("SELECT 1 FROM departments WHERE manager_employee_id = ?", (emp_id,)).fetchone()
        new_role = "manager" if manages else "employee"
        if new_role != user["role"]:
            conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, user["user_id"]))
            audit("role_change", "user", user["user_id"], {"from": user["role"], "to": new_role})


# -------------------------------------------------------------- employees --

@bp.route("/employees")
@roles_required("hr", "manager")
def employees():
    dept = get_department_filter()
    q = (request.args.get("q") or "").strip()[:60]
    active_only = request.args.get("active") == "1"
    rows = repos.list_employees(get_db(), g.user, dept, q or None, include_terminated=not active_only, limit=1000)
    return render_template("employees.html", rows=rows, dept=dept, q=q, active_only=active_only,
                           departments=department_options())


@bp.route("/employees/new", methods=["GET", "POST"])
@bp.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@roles_required("hr")
def employee_form(employee_id: int | None = None):
    conn = get_db()
    emp = repos.get_employee(conn, employee_id) if employee_id else None
    if employee_id and emp is None:
        abort(404)
    cur_assign = repos.current_assignment(conn, employee_id) if employee_id else None
    shifts = repos.list_shifts(conn)
    form = dict(emp or {})
    form["shift_id"] = cur_assign["shift_id"] if cur_assign else None
    if request.method == "POST":
        f = request.form
        errors: list[str] = []
        data = {
            "employee_code": f.get("employee_code", "").strip().upper(),
            "badge_id": f.get("badge_id", "").strip(),
            "full_name": f.get("full_name", "").strip(),
            "full_name_ar": f.get("full_name_ar", "").strip() or None,
            "gender": f.get("gender") if f.get("gender") in ("M", "F") else None,
            "email": f.get("email", "").strip().lower() or None,
            "job_title": f.get("job_title", "").strip() or None,
            "job_title_ar": f.get("job_title_ar", "").strip() or None,
        }
        if not CODE_RE.match(data["employee_code"]):
            errors.append(_("The employee code can have 1 to 20 English letters, digits, '-' or '_'."))
        if not CODE_RE.match(data["badge_id"]):
            errors.append(_("The badge number can have 1 to 20 English letters, digits, '-' or '_'."))
        if not (2 <= len(data["full_name"]) <= 120):
            errors.append(_("The name must be 2 to 120 characters long."))
        if data["email"] and not EMAIL_RE.match(data["email"]):
            errors.append(_("That email address does not look right."))
        dept_id = int_arg("department_id")
        dept = repos.get_department(conn, dept_id) if dept_id else None
        if dept is None:
            errors.append(_("Choose a department."))
        data["department_id"] = dept_id
        data["hire_date"] = _iso(f.get("hire_date"), _("The start date"), errors)
        data["termination_date"] = _iso(f.get("termination_date"), _("The last working day"), errors, required=False)
        if data["hire_date"] and data["termination_date"] and data["termination_date"] < data["hire_date"]:
            errors.append(_("The last working day cannot be before the start date."))
        shift_id = int_arg("shift_id")
        if shift_id is None or repos.get_shift(conn, shift_id) is None:
            errors.append(_("Choose a shift."))
        shift_from = _iso(f.get("shift_effective_from") or data.get("hire_date") or "", _("The shift start date"), errors)
        if dept and dept["manager_employee_id"] and dept["manager_employee_id"] != employee_id:
            data["manager_employee_id"] = dept["manager_employee_id"]
        else:
            data["manager_employee_id"] = emp["manager_employee_id"] if emp else None
        if errors:
            flash_errors(errors)
            form.update(data, shift_id=shift_id, shift_effective_from=f.get("shift_effective_from"))
            return render_template("employee_form.html", form=form, emp=emp, shifts=shifts,
                                   departments=repos.list_departments(conn)), 422
        try:
            with transaction(conn):
                new_id = repos.save_employee(conn, data, employee_id)
                shift_changed = cur_assign is None or cur_assign["shift_id"] != shift_id
                if shift_changed:
                    repos.set_shift_assignment(conn, new_id, shift_id, shift_from)
                audit("employee_update" if employee_id else "employee_create", "employee", new_id,
                      {k: data[k] for k in ("employee_code", "department_id", "hire_date", "termination_date")}
                      | ({"shift_id": shift_id, "shift_from": shift_from} if shift_changed else {}))
        except IntegrityError:
            flash(_("Another employee already uses this code, badge number or email."), "error")
            form.update(data, shift_id=shift_id)
            return render_template("employee_form.html", form=form, emp=emp, shifts=shifts,
                                   departments=repos.list_departments(conn)), 422
        # re-evaluate only if something that drives attendance changed
        starts = []
        if emp is None:
            starts.append(data["hire_date"])
        else:
            for k in ("hire_date", "termination_date"):
                if emp[k] != data[k]:
                    starts += [v for v in (emp[k], data[k]) if v]
        if shift_changed and cur_assign is not None:
            starts.append(shift_from)
        msg = reprocess(min(starts), [new_id]) if starts else None
        flash(_("Employee saved.") + (f" {msg}" if msg else ""), "success")
        return redirect(url_for("attendance.employee", employee_id=new_id))
    return render_template("employee_form.html", form=form, emp=emp, shifts=shifts,
                           departments=repos.list_departments(conn))


# ------------------------------------------------------------ departments --

@bp.route("/departments")
@roles_required("hr")
def departments():
    return render_template("departments.html", rows=repos.list_departments(get_db()))


@bp.route("/departments/new", methods=["GET", "POST"])
@bp.route("/departments/<int:department_id>/edit", methods=["GET", "POST"])
@roles_required("hr")
def department_form(department_id: int | None = None):
    conn = get_db()
    dept = repos.get_department(conn, department_id) if department_id else None
    if department_id and dept is None:
        abort(404)
    candidates = conn.execute("""SELECT employee_id, employee_code, full_name, full_name_ar FROM employees
                                 WHERE termination_date IS NULL ORDER BY employee_code""").fetchall()
    if request.method == "POST":
        errors = []
        data = {"code": request.form.get("code", "").strip().upper(),
                "name": request.form.get("name", "").strip(),
                "name_ar": request.form.get("name_ar", "").strip() or None,
                "manager_employee_id": int_arg("manager_employee_id"),
                "is_active": 1 if request.form.get("is_active") else 0}
        if not CODE_RE.match(data["code"]):
            errors.append(_("The code can have 1 to 20 English letters, digits, '-' or '_'."))
        if not (2 <= len(data["name"]) <= 80):
            errors.append(_("The name must be 2 to 80 characters long."))
        if data["manager_employee_id"] and repos.get_employee(conn, data["manager_employee_id"]) is None:
            errors.append(_("That manager was not found."))
        if errors:
            flash_errors(errors)
            return render_template("department_form.html", dept=data | {"department_id": department_id},
                                   candidates=candidates), 422
        try:
            with transaction(conn):
                new_id = repos.save_department(conn, data, department_id)
                _sync_manager_roles(conn, {data["manager_employee_id"], dept["manager_employee_id"] if dept else None})
                audit("department_update" if department_id else "department_create", "department", new_id, data)
        except IntegrityError:
            flash(_("Another department already uses this code."), "error")
            return render_template("department_form.html", dept=data | {"department_id": department_id},
                                   candidates=candidates), 422
        flash(_("Department saved. The manager's access changes straight away."), "success")
        return redirect(url_for("admin.departments"))
    return render_template("department_form.html", dept=dept or {"is_active": 1}, candidates=candidates)


# ----------------------------------------------------------------- shifts --

@bp.route("/shifts")
@roles_required("hr")
def shifts():
    return render_template("shifts.html", rows=repos.list_shifts(get_db()))


@bp.route("/shifts/new", methods=["GET", "POST"])
@bp.route("/shifts/<int:shift_id>/edit", methods=["GET", "POST"])
@roles_required("hr")
def shift_form(shift_id: int | None = None):
    conn = get_db()
    shift = repos.get_shift(conn, shift_id) if shift_id else None
    if shift_id and shift is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        errors = []
        data = {"code": f.get("code", "").strip().upper(), "name": f.get("name", "").strip(),
                "name_ar": f.get("name_ar", "").strip() or None,
                "start_time": f.get("start_time", "").strip()[:5], "end_time": f.get("end_time", "").strip()[:5],
                "workdays": ",".join(d for d in ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
                                     if f.get(f"wd_{d}")),
                "is_active": 1 if f.get("is_active") else 0}
        for k, label in (("grace_minutes", _("The grace for lateness")),
                         ("early_leave_grace_minutes", _("The grace for leaving early"))):
            try:
                data[k] = int(f.get(k, ""))
                if not 0 <= data[k] <= 120:
                    raise ValueError
            except ValueError:
                errors.append(_("{label} must be a whole number of minutes from 0 to 120.", label=label))
        if not CODE_RE.match(data["code"]):
            errors.append(_("The code can have 1 to 20 English letters, digits, '-' or '_'."))
        if not data["name"]:
            errors.append(_("The name is required."))
        try:
            sd = ShiftDef(shift_id or 0, data["code"], parse_hhmm(data["start_time"]), parse_hhmm(data["end_time"]),
                          data.get("grace_minutes", 0), data.get("early_leave_grace_minutes", 0),
                          parse_workdays(data["workdays"]))
            if not errors:
                errors += validate_shift(sd, RuleConfig.from_settings(g.settings))
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            flash_errors(errors)
            return render_template("shift_form.html", shift=data | {"shift_id": shift_id}), 422
        try:
            with transaction(conn):
                new_id = repos.save_shift(conn, data, shift_id)
                audit("shift_update" if shift_id else "shift_create", "shift", new_id, data)
        except IntegrityError:
            flash(_("Another shift already uses this code."), "error")
            return render_template("shift_form.html", shift=data | {"shift_id": shift_id}), 422
        flash(_("Shift saved. Days already calculated keep their results until they are recalculated "
                "(Import punches, then Recalculate)."), "success")
        return redirect(url_for("admin.shifts"))
    return render_template("shift_form.html", shift=shift or {"grace_minutes": 15, "early_leave_grace_minutes": 5,
                                                             "workdays": "SUN,MON,TUE,WED,THU", "is_active": 1})


# ------------------------------------------------------- holidays & leave --

@bp.route("/calendar", methods=["GET", "POST"])
@roles_required("hr")
def calendar_view():
    conn = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        errors: list[str] = []
        if action == "add_holiday":
            d = _iso(request.form.get("holiday_date"), _("The date"), errors)
            name = (request.form.get("name") or "").strip()
            name_ar = (request.form.get("name_ar") or "").strip()[:80] or None
            if not (2 <= len(name) <= 80):
                errors.append(_("The holiday name must be 2 to 80 characters long."))
            if not errors:
                with transaction(conn):
                    repos.save_holiday(conn, d, name, name_ar)
                    audit("holiday_save", "holiday", d, {"name": name, "name_ar": name_ar})
                msg = reprocess(d, end=d)
                flash(_("Public holiday saved.") + (f" {msg}" if msg else ""), "success")
        elif action == "delete_holiday":
            d = _iso(request.form.get("holiday_date"), _("The date"), errors)
            if not errors:
                with transaction(conn):
                    repos.delete_holiday(conn, d)
                    audit("holiday_delete", "holiday", d)
                msg = reprocess(d, end=d)
                flash(_("Public holiday removed.") + (f" {msg}" if msg else ""), "success")
        elif action == "add_leave":
            emp = repos.get_employee_by_code(conn, (request.form.get("employee_code") or "").strip().upper())
            if emp is None:
                errors.append(_("No employee has that code."))
            ltype = request.form.get("leave_type")
            if ltype not in LEAVE_TYPES:
                errors.append(_("Choose a type of leave."))
            s = _iso(request.form.get("start_date"), _("The first day"), errors)
            e = _iso(request.form.get("end_date"), _("The last day"), errors)
            if s and e and e < s:
                errors.append(_("The last day is before the first day."))
            if s and e and (date.fromisoformat(e) - date.fromisoformat(s)).days > 180:
                errors.append(_("One leave record can cover at most 180 days."))
            if not errors:
                clash = repos.overlapping_leave(conn, emp["employee_id"], s, e)
                if clash:
                    errors.append(_("These dates overlap leave from {a} to {b} for {code} that is {status}. Decide or "
                                    "cancel that request first (Approvals).", a=clash["start_date"], b=clash["end_date"],
                                    code=emp["employee_code"], status=request_status_label(clash["status"]).lower()))
            if not errors:
                with transaction(conn):
                    lid = repos.insert_leave(conn, emp["employee_id"], ltype, s, e, "approved", g.user.user_id,
                                             "Recorded directly by HR")
                    audit("leave_approve", "leave_request", lid, {"employee_id": emp["employee_id"], "type": ltype,
                                                                  "start": s, "end": e})
                msg = reprocess(s, [emp["employee_id"]], end=e)
                flash(_("Approved leave recorded for {code}.", code=emp["employee_code"]) + (f" {msg}" if msg else ""),
                      "success")
        else:
            abort(400)
        flash_errors(errors)
        return redirect(url_for("admin.calendar_view"))
    return render_template("calendar.html", holidays=repos.list_holidays(conn),
                           leaves=repos.list_leaves(conn, g.user, 150), leave_types=LEAVE_TYPES)


# ------------------------------------------------------------------ audit --

@bp.route("/audit")
@roles_required("hr")
def audit_log():
    return render_template("audit.html", rows=repos.list_audit(get_db(), 400))
