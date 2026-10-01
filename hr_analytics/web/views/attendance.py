"""Attendance list, export, and employee profile."""
from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
from flask import Blueprint, abort, g, render_template, request, send_file

from ...db import repos
from ...domain.attendance_rules import ALL_STATUSES, EXPECTED_STATUSES
from ...domain.metrics import attendance_kpis
from ...domain.scoring import CATEGORIES, CATEGORY_LABELS, parse_period, shift_period
from ...i18n import N_, _, current_lang, loc
from ...labels import day_note, status_label, weekday_letter, weekday_name
from ...security.scope import AccessDenied, can_evaluate, can_view_employee
from .. import get_db
from ..helpers import audit, records, department_options, get_department_filter, get_period, line_chart, login_required
from .dashboard import trend_series

bp = Blueprint("attendance", __name__)

# (column in the data, heading in the file)
EXPORT_COLUMNS = [("shift_date", N_("Date")), ("employee_code", N_("Employee code")), ("name", N_("Name")),
                  ("department", N_("Department")), ("shift", N_("Shift")), ("status_text", N_("Status")),
                  ("late_text", N_("Late")), ("first_punch", N_("Clock-in")), ("last_punch", N_("Clock-out")),
                  ("late_minutes", N_("Minutes late")), ("early_leave_minutes", N_("Left early (minutes)")),
                  ("hours_present", N_("Hours present")), ("note", N_("Notes"))]
MAX_ROWS_ON_PAGE = 1000


def _date_arg(name: str, default: date) -> date:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(400, description=_("Please enter a valid date."))


def _filters():
    period = get_period()
    first, last = parse_period(period)
    start, end = _date_arg("start", first), _date_arg("end", last)
    if end < start:
        abort(400, description=_("The end date is before the start date."))
    if (end - start).days > 400:
        abort(400, description=_("Choose a range of at most 400 days."))
    status = (request.args.get("status") or "").strip() or None
    if status and status not in ALL_STATUSES:
        abort(400, description=_("That status is not recognised."))
    q = (request.args.get("q") or "").strip()[:60]
    return {"period": period, "start": start, "end": end, "department_id": get_department_filter(),
            "status": status, "q": q}


def _frame(f) -> pd.DataFrame:
    df = repos.attendance_frame(get_db(), g.user, f["start"].isoformat(), f["end"].isoformat(),
                                f["department_id"], status=f["status"])
    if f["q"] and not df.empty:
        ql = f["q"].lower()
        df = df[df.employee_code.str.lower().str.contains(ql, regex=False)
                | df.full_name.str.lower().str.contains(ql, regex=False)]
    return df


@bp.route("/attendance")
@login_required
def index():
    f = _filters()
    df = _frame(f)
    # KPIs ignore the status filter (a status-filtered denominator would be meaningless)
    kdf = df if not f["status"] else _frame({**f, "status": None})
    return render_template("attendance.html", f=f, rows=records(df, MAX_ROWS_ON_PAGE),
                           total=len(df), max_rows=MAX_ROWS_ON_PAGE, k=attendance_kpis(kdf),
                           statuses=ALL_STATUSES, departments=department_options())


def _csv_safe(v):
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@bp.route("/attendance/export.<fmt>")
@login_required
def export(fmt):
    if fmt not in ("csv", "xlsx"):
        abort(404)
    f = _filters()
    rows = records(_frame(f))
    out = pd.DataFrame([{
        "shift_date": r["shift_date"], "employee_code": r["employee_code"], "name": loc(r, "full_name"),
        "department": loc(r, "department_name"), "shift": loc(r, "shift_name"),
        "status_text": status_label(r["status"]),
        "late_text": _("Yes") if r["is_late"] and r["status"] in ("present", "incomplete") else "",
        "first_punch": (r["first_punch"] or "")[:16], "last_punch": (r["last_punch"] or "")[:16] if r["punch_count"] > 1 else "",
        "late_minutes": r["late_minutes"] if r["is_late"] else None, "early_leave_minutes": r["early_leave_minutes"] or None,
        "hours_present": round(r["span_minutes"] / 60, 2) if r["span_minutes"] is not None else None,
        "note": day_note(r)} for r in rows], columns=[c for c, _h in EXPORT_COLUMNS])
    out = out.map(_csv_safe).rename(columns={c: _(h) for c, h in EXPORT_COLUMNS})
    name = f"attendance_{f['start']}_{f['end']}"
    audit("export", "attendance_daily", None, {"format": fmt, "rows": len(out), "start": f["start"],
                                                "end": f["end"], "department_id": f["department_id"]})
    get_db().commit()
    buf = io.BytesIO()
    if fmt == "csv":
        buf.write(out.to_csv(index=False).encode("utf-8-sig"))
        buf.seek(0)
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=name + ".csv")
    about = pd.DataFrame({
        _("Item"): [_("Dates"), _("Department"), _("Status"), _("Search"), _("Downloaded by"), _("Note")],
        _("Value"): [f"{f['start']} – {f['end']}", f["department_id"] or _("All departments I can see"),
                     status_label(f["status"]) if f["status"] else _("Any"), f["q"] or "–", g.user.username,
                     _("Made-up demonstration data. Hours present run from the first to the last punch and are "
                       "not verified working hours.")]})
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        out.to_excel(xw, sheet_name="attendance", index=False)
        about.to_excel(xw, sheet_name="about", index=False)
        if current_lang() == "ar":
            for ws in xw.book.worksheets:
                ws.sheet_view.rightToLeft = True
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=name + ".xlsx")


@bp.route("/employees/<int:employee_id>")
@login_required
def employee(employee_id: int):
    conn = get_db()
    emp = repos.get_employee(conn, employee_id)
    if emp is None:
        abort(404)
    if not can_view_employee(conn, g.user, employee_id):
        raise AccessDenied(_("You can only see people within your area."))
    period = get_period()
    first, last = parse_period(period)
    att = repos.attendance_frame(conn, g.user, first.isoformat(), last.isoformat(), employee_id=employee_id)
    att_rows = records(att)
    by_day = {r["shift_date"]: r for r in att_rows}
    hire = date.fromisoformat(emp["hire_date"])
    term = date.fromisoformat(emp["termination_date"]) if emp["termination_date"] else None
    ribbon = []
    d = first
    while d <= last:
        r = by_day.get(d.isoformat())
        if r is not None:
            status = status_label(r["status"])
            cls = "late" if r["status"] in ("present", "incomplete") and r["is_late"] else r["status"]
        elif d < hire or (term and d > term):
            status, cls = _("Not employed"), "none"
        else:
            status, cls = _("Not calculated yet"), "none"
        tip = f"{weekday_name(d.weekday())} {d.isoformat()}: {status}"
        if r is not None and r.get("first_punch"):
            tip += f" · {r['first_punch'][11:16]}" + (f"–{r['last_punch'][11:16]}" if r["punch_count"] > 1 else "")
        if r is not None and r["is_late"]:
            tip += " · " + _("{n} min late", n=r["late_minutes"])
        ribbon.append({"date": d, "cls": cls, "tip": tip, "weekday": weekday_letter(d.weekday())})
        d += timedelta(days=1)

    detail = [r for r in att_rows
              if r["status"] in ("absent", "incomplete", "unscheduled_work", "leave", "holiday", "pending")
              or (r["status"] == "present" and (r["is_late"] or r["early_leave_minutes"]))]

    trend = trend_series(conn, g.user, period, 12, employee_id=employee_id)
    labels = [t["period"][2:] for t in trend]
    att_chart = line_chart(labels, [
        {"name": _("Attendance rate"), "values": [t["attendance_rate"] for t in trend], "cls": "c-present"},
        {"name": _("Late rate"), "values": [t["late_rate"] for t in trend], "cls": "c-late"}])
    score_chart = line_chart(labels, [{"name": _("Weighted score"), "values": [t["avg_score"] for t in trend],
                                       "cls": "c-score"}], y_min=1, y_max=5, y_fmt=lambda v: f"{v:.1f}")
    evals = repos.evaluations_frame(conn, g.user, shift_period(period, -11), period, employee_id=employee_id)
    shift = repos.current_assignment(conn, employee_id)
    corrections = repos.list_corrections(conn, g.user, employee_id=employee_id, start=first.isoformat(),
                                         end=last.isoformat())
    shift_row = repos.get_shift(conn, shift["shift_id"]) if shift else None
    return render_template("employee.html", emp=emp, period=period, prev_period=shift_period(period, -1),
                           next_period=shift_period(period, 1), ribbon=ribbon, k=attendance_kpis(att),
                           detail=detail, att_chart=att_chart, score_chart=score_chart,
                           evals=records(evals.sort_values("period", ascending=False)),
                           categories=CATEGORIES, labels=CATEGORY_LABELS, shift=shift_row,
                           can_evaluate=can_evaluate(conn, g.user, employee_id),
                           leaves=repos.list_leaves(conn, g.user, 12, employee_id=employee_id),
                           corrections=corrections,
                           pending_dates={c["shift_date"] for c in corrections if c["status"] == "pending"},
                           is_self=(g.user.employee_id == employee_id), expected_statuses=EXPECTED_STATUSES)
