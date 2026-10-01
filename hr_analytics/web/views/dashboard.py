"""Organisation / department dashboard."""
from __future__ import annotations

import pandas as pd
from flask import Blueprint, g, redirect, render_template, url_for

from ...db import repos
from ...domain.metrics import (attendance_kpis, evaluable_employee_months, grouped_attendance_kpis,
                               performance_kpis, weekday_week_heatmap)
from ...domain.scoring import parse_period, shift_period
from ...i18n import _
from ...services.review import review_cases
from .. import get_db
from ..helpers import department_options, get_department_filter, get_period, heat_class, line_chart, login_required

bp = Blueprint("dashboard", __name__)


def trend_series(conn, user, period: str, months: int = 12, department_id=None, employee_id=None):
    start_p = shift_period(period, -(months - 1))
    first, _ = parse_period(start_p)
    _, last = parse_period(period)
    att = {r["period"]: r for r in repos.monthly_attendance_summary(conn, user, first.isoformat(), last.isoformat(),
                                                                     department_id, employee_id)}
    sc = {r["period"]: r for r in repos.monthly_score_summary(conn, user, start_p, period, department_id, employee_id)}
    labels = [shift_period(start_p, i) for i in range(months)]
    rows = []
    for p in labels:
        a, s = att.get(p), sc.get(p)
        exp = a["expected_days"] if a else 0
        attd = a["attended_days"] if a else 0
        rows.append({
            "period": p,
            "expected_days": exp,
            "attendance_rate": (attd / exp) if exp else None,
            "absence_rate": (a["absent_days"] / exp) if exp else None,
            "late_rate": (a["late_days"] / attd) if attd else None,
            "evaluations": s["evaluations"] if s else 0,
            "avg_score": s["avg_score"] if s else None,
        })
    return rows


@bp.route("/")
@login_required
def index():
    if not g.user.has_team:
        if g.user.employee_id is None:
            return render_template("error.html", code=200, title=_("No employee record"),
                                   message=_("This account is not linked to an employee record."))
        return redirect(url_for("attendance.employee", employee_id=g.user.employee_id))

    conn, s = get_db(), g.settings
    period = get_period()
    dept = get_department_filter()
    first, last = parse_period(period)

    att = repos.attendance_frame(conn, g.user, first.isoformat(), last.isoformat(), dept)
    ev = repos.evaluations_frame(conn, g.user, period, period, dept)
    emps = repos.employees_frame(conn, g.user, dept)
    ak = attendance_kpis(att)
    pk = performance_kpis(ev, evaluable_employee_months(emps, first, last), s.LOW_SCORE_THRESHOLD)

    by_dept = []
    if not att.empty:
        gd = grouped_attendance_kpis(att, ["department_id", "department_name", "department_name_ar"])
        scores = ev.groupby("department_id")["weighted_score"].agg(["mean", "count"]) if not ev.empty else pd.DataFrame()
        for r in gd.sort_values("department_name").to_dict("records"):
            sc = scores.loc[r["department_id"]] if not scores.empty and r["department_id"] in scores.index else None
            r["avg_score"] = float(sc["mean"]) if sc is not None else None
            r["evaluations"] = int(sc["count"]) if sc is not None else 0
            r["small_sample"] = r["employees"] < s.SMALL_SAMPLE_EMPLOYEES
            by_dept.append(r)

    heat = weekday_week_heatmap(att)
    heat_rows = []
    if not heat.empty:
        for wk, row in heat.iterrows():
            heat_rows.append({"week": wk, "cells": [
                {"day": d, "rate": (None if pd.isna(row.get(d)) else float(row.get(d))),
                 "cls": heat_class(None if pd.isna(row.get(d)) else float(row.get(d)))}
                for d in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]]})

    trend = trend_series(conn, g.user, period, 12, dept)
    labels = [t["period"][2:] for t in trend]
    att_chart = line_chart(labels, [
        {"name": _("Attendance rate"), "values": [t["attendance_rate"] for t in trend], "cls": "c-present"},
        {"name": _("Late rate (of days attended)"), "values": [t["late_rate"] for t in trend], "cls": "c-late"},
        {"name": _("Absence rate"), "values": [t["absence_rate"] for t in trend], "cls": "c-absent"},
    ])
    score_chart = line_chart(labels, [
        {"name": _("Average weighted score"), "values": [t["avg_score"] for t in trend], "cls": "c-score"},
    ], y_min=1, y_max=5, y_fmt=lambda v: f"{v:.1f}", ticks=4)

    cases = review_cases(conn, g.user, period, threshold=s.LOW_SCORE_THRESHOLD, department_id=dept)
    return render_template("dashboard.html", period=period, prev_period=shift_period(period, -1),
                           next_period=shift_period(period, 1), dept=dept, departments=department_options(),
                           ak=ak, pk=pk, by_dept=by_dept, heat_rows=heat_rows, att_chart=att_chart,
                           score_chart=score_chart, trend=trend, case_count=len(cases),
                           case_employees=cases["employee_id"].nunique() if len(cases) else 0)
