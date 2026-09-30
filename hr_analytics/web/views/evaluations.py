"""Monthly performance evaluations and weight settings."""
from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...db import repos
from ...db.connection import transaction
from ...domain.metrics import EVALUABLE_MIN_DAYS
from ...domain.scoring import (CATEGORIES, CATEGORY_LABELS, DEFAULT_WEIGHTS, parse_period, shift_period,
                               validate_weights)
from ...security.scope import AccessDenied, can_evaluate, can_view_employee
from ...services.evaluations import save_evaluation, weights_dict
from .. import get_db
from ..helpers import records, audit, department_options, flash_errors, get_department_filter, get_period, int_arg, login_required, roles_required

bp = Blueprint("evaluations", __name__, url_prefix="/evaluations")


@bp.route("/")
@login_required
def index():
    conn = get_db()
    period = get_period()
    first, last = parse_period(period)
    if g.user.role == "employee":
        ev = repos.evaluations_frame(conn, g.user, "2000-01", "2999-12")
        return render_template("evaluations_own.html",
                               evals=records(ev.sort_values("period", ascending=False)),
                               categories=CATEGORIES, labels=CATEGORY_LABELS)
    dept = get_department_filter()
    emps = repos.employees_frame(conn, g.user, dept)
    ev = repos.evaluations_frame(conn, g.user, period, period, dept)
    by_emp = {r["employee_id"]: r for r in records(ev)}
    rows = []
    for r in records(emps.sort_values(["department_name", "employee_code"])):
        start = max(first, date.fromisoformat(r["hire_date"]))
        term = r["termination_date"] if isinstance(r["termination_date"], str) and r["termination_date"] else None
        end = min(last, date.fromisoformat(term)) if term else last
        days = (end - start).days + 1
        if days <= 0:
            continue
        rows.append({**r, "days_employed": days, "evaluable": days >= EVALUABLE_MIN_DAYS,
                     "evaluation": by_emp.get(r["employee_id"]),
                     "can_evaluate": can_evaluate(conn, g.user, r["employee_id"])})
    done = sum(1 for r in rows if r["evaluation"] and r["evaluable"])
    evaluable = sum(1 for r in rows if r["evaluable"])
    return render_template("evaluations.html", rows=rows, period=period, dept=dept, done=done, evaluable=evaluable,
                           departments=department_options(), prev_period=shift_period(period, -1),
                           next_period=shift_period(period, 1), threshold=g.settings.LOW_SCORE_THRESHOLD,
                           min_days=EVALUABLE_MIN_DAYS)


@bp.route("/form", methods=["GET", "POST"])
@roles_required("hr", "manager")
def form():
    conn = get_db()
    employee_id = int_arg("employee_id")
    period = (request.values.get("period") or "").strip()
    emp = repos.get_employee(conn, employee_id) if employee_id else None
    if emp is None:
        abort(404)
    # Server-side permission check on both GET and POST (the UI hides the link too, but that is not the control).
    if not can_evaluate(conn, g.user, employee_id):
        raise AccessDenied("You cannot evaluate this employee (outside your department, or your own record).")
    try:
        parse_period(period)
    except ValueError:
        abort(400, description="Period must look like YYYY-MM.")
    existing = repos.get_evaluation(conn, employee_id, period)
    weights = repos.weights_for_period(conn, period)
    values = {c: (existing or {}).get(f"score_{c}") for c in CATEGORIES}
    comments = (existing or {}).get("comments") or ""
    if request.method == "POST":
        values = {c: request.form.get(c, "") for c in CATEGORIES}
        comments = request.form.get("comments", "")
        res = save_evaluation(conn, g.user, employee_id, period, values, comments, remote_addr=request.remote_addr)
        if res.ok:
            flash(f"Evaluation {'updated' if res.action == 'update' else 'saved'}: weighted score "
                  f"{res.weighted_score:.2f}.", "success")
            return redirect(url_for("evaluations.index", period=period))
        flash_errors(res.errors)
        return render_template("evaluation_form.html", emp=emp, period=period, values=values, comments=comments,
                               existing=existing, weights=weights, categories=CATEGORIES,
                               labels=CATEGORY_LABELS), 422
    return render_template("evaluation_form.html", emp=emp, period=period, values=values, comments=comments,
                           existing=existing, weights=weights, categories=CATEGORIES, labels=CATEGORY_LABELS)


@bp.route("/<int:evaluation_id>/history")
@login_required
def history(evaluation_id: int):
    conn = get_db()
    ev = repos.evaluation_by_id(conn, evaluation_id)
    if ev is None:
        abort(404)
    if not can_view_employee(conn, g.user, ev["employee_id"]):
        raise AccessDenied("You can only view evaluations within your scope.")
    hist = repos.evaluation_history(conn, evaluation_id)
    for h in hist:
        h["old"] = json.loads(h["old_values"]) if h.get("old_values") else None
        h["new"] = json.loads(h["new_values"]) if h.get("new_values") else None
    return render_template("evaluation_history.html", ev=ev, history=hist, categories=CATEGORIES,
                           labels=CATEGORY_LABELS)


@bp.route("/weights", methods=["GET", "POST"])
@roles_required("hr")
def weights():
    conn = get_db()
    if request.method == "POST":
        eff = (request.form.get("effective_from") or "").strip()
        w = {c: request.form.get(c, "").strip() for c in CATEGORIES}
        errors = []
        try:
            parse_period(eff)
        except ValueError as exc:
            errors.append(str(exc))
        errors += validate_weights(w)
        if not errors:
            try:
                with transaction(conn):
                    wid = repos.upsert_weights(conn, eff, {c: float(w[c]) for c in CATEGORIES}, g.user.user_id)
                    audit("weights_save", "evaluation_weights", wid, {"effective_from": eff, **w})
                flash(f"Weights saved; they apply to evaluations from {eff} onwards. Existing evaluations keep "
                      f"the weights they were scored with.", "success")
                return redirect(url_for("evaluations.weights"))
            except ValueError as exc:
                errors.append(str(exc))
        flash_errors(errors)
        return render_template("weights.html", rows=repos.list_weights(conn), form=w, eff=eff,
                               categories=CATEGORIES, labels=CATEGORY_LABELS), 422
    rows = repos.list_weights(conn)
    current = weights_dict(rows[0]) if rows else DEFAULT_WEIGHTS
    return render_template("weights.html", rows=rows, form={c: f"{current[c]:g}" for c in CATEGORIES}, eff="",
                           categories=CATEGORIES, labels=CATEGORY_LABELS)
