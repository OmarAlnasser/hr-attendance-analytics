"""Cases for human review: transparent rules first, experimental model second."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, g, render_template

from ...db import repos
from ...domain.scoring import shift_period
from ...services.review import review_cases, rules_for_display
from .. import get_db
from ..helpers import records, department_options, get_department_filter, get_period, roles_required

bp = Blueprint("review", __name__, url_prefix="/review")


def model_summary(models_dir: str, conn=None) -> dict | None:
    """From the models folder, or from the database copy when the disk is empty (cloud hosts)."""
    p = Path(models_dir) / "model_evaluation.json"
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        raw = repos.load_file(conn, "models/model_evaluation.json") if conn is not None else None
        return json.loads(raw.decode("utf-8")) if raw else None
    except (OSError, ValueError):
        return None


@bp.route("/")
@roles_required("hr", "manager")
def index():
    conn, s = get_db(), g.settings
    period = get_period()
    dept = get_department_filter()
    cases = review_cases(conn, g.user, period, threshold=s.LOW_SCORE_THRESHOLD, department_id=dept)
    grouped = []
    if len(cases):
        for emp_id, part in cases.groupby("employee_id", sort=False):
            first = part.iloc[0]
            grouped.append({"employee_id": int(emp_id), "employee_code": first.employee_code,
                            "full_name": first.full_name, "full_name_ar": first.full_name_ar,
                            "department_name": first.department_name, "department_name_ar": first.department_name_ar,
                            "flags": records(part[["rule_code", "rule", "value"]])})
        grouped.sort(key=lambda r: (-len(r["flags"]), r["employee_code"]))
    rule_counts = cases.groupby("rule_code")["employee_id"].nunique().to_dict() if len(cases) else {}

    summary = model_summary(s.MODELS_DIR, conn)
    risk_rows, risk_period = [], None
    if summary and summary.get("status") == "model":
        risk_period = repos.latest_risk_period(conn)
        if risk_period:
            rf = repos.risk_frame(conn, g.user, risk_period)
            if dept is not None and not rf.empty:
                ids = {e["employee_id"] for e in repos.list_employees(conn, g.user, dept, limit=5000)}
                rf = rf[rf.employee_id.isin(ids)]
            risk_rows = records(rf, 25)
    return render_template("review.html", period=period, dept=dept, departments=department_options(),
                           grouped=grouped, rules=rules_for_display(), rule_counts=rule_counts, summary=summary,
                           risk_rows=risk_rows, risk_period=risk_period, prev_period=shift_period(period, -1),
                           next_period=shift_period(period, 1), threshold=s.LOW_SCORE_THRESHOLD)
